# database.py

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from pymongo import MongoClient
load_dotenv()

# ======================================================
# ERP DATABASE (external ERP server)
# ======================================================

ERP_DB_HOST = os.getenv("POSTGRES_HOST")
ERP_DB_PORT = os.getenv("POSTGRES_PORT")
ERP_DB_NAME = os.getenv("POSTGRES_DB")
ERP_DB_USER = os.getenv("POSTGRES_USER")
ERP_DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")

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


# ======================================================
# VENDOR DATABASE (MAIN App DB)
# ======================================================

VENDOR_DB_HOST = os.getenv("DB_HOST")
VENDOR_DB_PORT = os.getenv("DB_PORT")
VENDOR_DB_NAME = os.getenv("DB_NAME")
VENDOR_DB_USER = os.getenv("DB_USER")
VENDOR_DB_PASSWORD = os.getenv("DB_PASSWORD")

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

# ======================================================
# BACKWARD COMPATIBILITY ALIASES
# ======================================================

# ✅ This preserves your existing imports:
engine = vendor_engine
SessionLocal = VendorSessionLocal
get_db = lambda: (db for db in [VendorSessionLocal()] if True)

# ======================================================
# BASE
# ======================================================

Base = declarative_base()


# ======================================================
# DEPENDENCIES
# ======================================================

def get_vendor_db():
    db = VendorSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_erp_db():
    db = ErpSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ✅ make legacy get_db() call vendor DB
get_db = get_vendor_db
# ======================================================
# MONGODB (Backward compatibility)
# ======================================================



MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")

if not all([MONGO_URI, MONGO_DB, MONGO_COLLECTION]):
    raise RuntimeError("Missing required MongoDB environment variables")

mongo_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=int(os.getenv("MONGO_SERVER_TIMEOUT_MS", 3000))
)

mongo_db = mongo_client[MONGO_DB]
mongo_collection = mongo_db[MONGO_COLLECTION]
