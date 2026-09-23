import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# ======================================================
# FLAGS
# ======================================================

ERP_AVAILABLE = True
MONGO_AVAILABLE = True

# ======================================================
# ERP DATABASE (Optional External ERP Server)
# ======================================================



ERP_DB_HOST = os.getenv("POSTGRES_HOST")
ERP_DB_PORT = os.getenv("POSTGRES_PORT")
ERP_DB_NAME = os.getenv("POSTGRES_DB")
ERP_DB_USER = os.getenv("POSTGRES_USER")
ERP_DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")

erp_engine = None
ErpSessionLocal = None

if all([ERP_DB_HOST, ERP_DB_PORT, ERP_DB_NAME, ERP_DB_USER, ERP_DB_PASSWORD]):
    try:
        ERP_DATABASE_URL = (
            f"postgresql+psycopg2://{ERP_DB_USER}:{ERP_DB_PASSWORD}"
            f"@{ERP_DB_HOST}:{ERP_DB_PORT}/{ERP_DB_NAME}"
            "?options=-csearch_path=public"
        )

        erp_engine = create_engine(
            ERP_DATABASE_URL,
            pool_pre_ping=True,
            pool_size=int(os.getenv("POSTGRES_MIN_SIZE", 1)),
            max_overflow=int(os.getenv("POSTGRES_MAX_SIZE", 10)),
            future=True,
        )

        ErpSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=erp_engine,
            future=True,
        )

        print("[OK] ERP PostgreSQL connected successfully.")

    except Exception as e:
        ERP_AVAILABLE = False
        print(f"[WARN] ERP PostgreSQL unavailable, skipping: {e}")
else:
    ERP_AVAILABLE = False
    print("[WARN] ERP PostgreSQL environment variables missing -- skipping ERP DB.")
        

# ======================================================
# VENDOR DATABASE (Main Application DB)
# ======================================================

VENDOR_DB_HOST = os.getenv("DB_HOST")
VENDOR_DB_PORT = os.getenv("DB_PORT")
VENDOR_DB_NAME = os.getenv("DB_NAME")
VENDOR_DB_USER = os.getenv("DB_USER")
VENDOR_DB_PASSWORD = os.getenv("DB_PASSWORD")

if not all([VENDOR_DB_HOST, VENDOR_DB_PORT, VENDOR_DB_NAME, VENDOR_DB_USER, VENDOR_DB_PASSWORD]):
    raise RuntimeError("[ERROR] Missing required Vendor PostgreSQL environment variables!")

# A real 50-concurrent-thread load test showed ALL threads simultaneously
# stall for ~44 of a 58-minute run then recover together - too long to be
# SQLAlchemy's own 30s pool-checkout timeout (that fails fast with a
# QueuePool error), so it's a query stuck on the Postgres side with no
# timeout to bound it. `statement_timeout` (ms) caps how long any single
# query may run before Postgres kills it - trades a silent multi-minute
# freeze for a fast, visible failure instead.
VENDOR_DB_STATEMENT_TIMEOUT_MS = os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000")

# `statement_timeout` only bounds an ACTIVELY EXECUTING query - it does
# nothing for a session that finished its query and then never committed,
# rolled back, or closed (Postgres shows this as state='idle in
# transaction', wait_event='ClientRead' - waiting for the CLIENT to speak
# next). A real 100-concurrent-thread load test found 75 of 79 total
# connections stuck exactly like this, some for 39+ minutes, spread across
# many unrelated endpoints - almost certainly a Session cleanup (db.close())
# that gets skipped when a request is cancelled mid-flight under load (a
# known class of bug with Starlette's BaseHTTPMiddleware, which
# auth_privilege.py uses - see the separate middleware fix). Each stuck
# session permanently occupies a pool slot until the process restarts, so
# under sustained load the pool doesn't just get busy, it leaks away to
# nothing. idle_in_transaction_session_timeout (ms) is the DB-side safety
# net: Postgres kills any such session on its own, freeing the pool slot,
# regardless of whether the app-level leak is ever fixed.
VENDOR_DB_IDLE_IN_TXN_TIMEOUT_MS = os.getenv("DB_IDLE_IN_TXN_TIMEOUT_MS", "60000")

VENDOR_DATABASE_URL = (
    f"postgresql+psycopg2://{VENDOR_DB_USER}:{VENDOR_DB_PASSWORD}"
    f"@{VENDOR_DB_HOST}:{VENDOR_DB_PORT}/{VENDOR_DB_NAME}"
    f"?options=-csearch_path=public"
    f"%20-cstatement_timeout={VENDOR_DB_STATEMENT_TIMEOUT_MS}"
    f"%20-cidle_in_transaction_session_timeout={VENDOR_DB_IDLE_IN_TXN_TIMEOUT_MS}"
)

vendor_engine = create_engine(
    VENDOR_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", 5)),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", 10)),
    future=True,
)

VendorSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=vendor_engine,
    future=True,
)

# Scheduled background jobs (main.py's APScheduler jobs - notification
# dispatch/retry, etc.) previously shared vendor_engine's pool with live web
# requests. Under real concurrent load, that pool fills up with request
# traffic and the background job's own checkout attempt times out
# ("QueuePool limit ... connection timed out") - confirmed via a real
# 100-concurrent-thread load test. A separate, small, dedicated pool means
# a scheduled job always gets a connection immediately regardless of how
# busy request traffic is, at the cost of a handful of extra idle Postgres
# connections (default 5+5=10) on top of the main pool - comfortably within
# this DB's max_connections headroom.
BG_DATABASE_URL = (
    f"postgresql+psycopg2://{VENDOR_DB_USER}:{VENDOR_DB_PASSWORD}"
    f"@{VENDOR_DB_HOST}:{VENDOR_DB_PORT}/{VENDOR_DB_NAME}"
    f"?options=-csearch_path=public"
    f"%20-cstatement_timeout={VENDOR_DB_STATEMENT_TIMEOUT_MS}"
    f"%20-cidle_in_transaction_session_timeout={VENDOR_DB_IDLE_IN_TXN_TIMEOUT_MS}"
)

bg_engine = create_engine(
    BG_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_BACKGROUND_POOL_SIZE", 5)),
    max_overflow=int(os.getenv("DB_BACKGROUND_MAX_OVERFLOW", 5)),
    future=True,
)

BackgroundSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=bg_engine,
    future=True,
)

print("[OK] Vendor PostgreSQL connected successfully.")


# ======================================================
# BASE
# ======================================================

Base = declarative_base()


# ======================================================
# DEPENDENCIES (Vendor DB)
# ======================================================

def get_vendor_db():
    db = VendorSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ------------------------------------------------------
# Helper for service-layer usage (non-FastAPI dependency)
# ------------------------------------------------------
@contextmanager
def get_vendor_session():
    db = VendorSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ======================================================
# DEPENDENCIES (ERP DB Optional)
# ======================================================

def get_erp_db():
    if not ERP_AVAILABLE:
        yield None
        return

    db = ErpSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ======================================================
# COMPATIBILITY FOR OLD IMPORTS
# ======================================================

# Old code imports "engine" → vendor engine
engine = vendor_engine
SessionLocal = VendorSessionLocal
get_db = get_vendor_db


# ======================================================
# OPTIONAL MONGODB
# ======================================================

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")

mongo_client = None
mongo_db = None
mongo_collection = None

if all([MONGO_URI, MONGO_DB, MONGO_COLLECTION]):
    try:
        mongo_client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=int(os.getenv("MONGO_SERVER_TIMEOUT_MS", 3000))
        )

        mongo_db = mongo_client[MONGO_DB]
        mongo_collection = mongo_db[MONGO_COLLECTION]

        # test ping
        mongo_client.admin.command("ping")

        print("[OK] MongoDB connected successfully.")

    except Exception as e:
        MONGO_AVAILABLE = False
        print(f"[WARN] MongoDB unavailable, skipping: {e}")
else:
    MONGO_AVAILABLE = False
    print("[WARN] MongoDB environment variables missing -- skipping MongoDB.")
