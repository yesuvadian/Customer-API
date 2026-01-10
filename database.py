import os
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

        print("✅ ERP PostgreSQL connected successfully.")

    except Exception as e:
        ERP_AVAILABLE = False
        print(f"⚠️ ERP PostgreSQL unavailable, skipping: {e}")
else:
    ERP_AVAILABLE = False
    print("⚠️ ERP PostgreSQL environment variables missing — skipping ERP DB.")
        

# ======================================================
# VENDOR DATABASE (Main Application DB)
# ======================================================

VENDOR_DB_HOST = os.getenv("DB_HOST")
VENDOR_DB_PORT = os.getenv("DB_PORT")
VENDOR_DB_NAME = os.getenv("DB_NAME")
VENDOR_DB_USER = os.getenv("DB_USER")
VENDOR_DB_PASSWORD = os.getenv("DB_PASSWORD")

if not all([VENDOR_DB_HOST, VENDOR_DB_PORT, VENDOR_DB_NAME, VENDOR_DB_USER, VENDOR_DB_PASSWORD]):
    raise RuntimeError("❌ Missing required Vendor PostgreSQL environment variables!")

VENDOR_DATABASE_URL = (
    f"postgresql+psycopg2://{VENDOR_DB_USER}:{VENDOR_DB_PASSWORD}"
    f"@{VENDOR_DB_HOST}:{VENDOR_DB_PORT}/{VENDOR_DB_NAME}"
    "?options=-csearch_path=public"
)

vendor_engine = create_engine(
    VENDOR_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

VendorSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=vendor_engine,
    future=True,
)

print("✅ Vendor PostgreSQL connected successfully.")


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

        print("✅ MongoDB connected successfully.")

    except Exception as e:
        MONGO_AVAILABLE = False
        print(f"⚠️ MongoDB unavailable, skipping: {e}")
else:
    MONGO_AVAILABLE = False
    print("⚠️ MongoDB environment variables missing — skipping MongoDB.")
