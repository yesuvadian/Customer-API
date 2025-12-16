import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==============================
# APP ENVIRONMENT
# ==============================
APP_NAME = os.getenv("APP_NAME", "Relu-Vendor-API")
APP_ENV = os.getenv("APP_ENV", os.getenv("ENV", "development"))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")

# ==============================
# DATABASE CONFIGURATION
# ==============================

# ERP / EXTERNAL SERVICES
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

# asyncpg compatibility dict
POSTGRES_CONFIG = {
    "host": POSTGRES_HOST,
    "port": int(POSTGRES_PORT),
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
    "database": POSTGRES_DB,
}


POSTGRES_MIN_SIZE = int(os.getenv("POSTGRES_MIN_SIZE", 1))
POSTGRES_MAX_SIZE = int(os.getenv("POSTGRES_MAX_SIZE", 10))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@"
    f"{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False


# ---- MongoDB ----
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB = os.getenv("MONGO_DB", "testdb")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "default_collection")

MONGO_URI = os.getenv(
    "MONGO_URI",
    f"mongodb://{MONGO_HOST}:{MONGO_PORT}/"
)

MONGO_SERVER_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_TIMEOUT_MS", 3000))


# ==============================
# ERP / EXTERNAL SERVICES
# ==============================
ERP_URL = os.getenv("ERP_URL", "https://erp.example.com/api/vendors")
ERP_API_KEY = os.getenv("ERP_API_KEY", "")
ERP_TIMEOUT = int(os.getenv("ERP_TIMEOUT", "30"))
ERP_RETRY_COUNT = int(os.getenv("ERP_RETRY_COUNT", "3"))
ERP_RETRY_DELAY = int(os.getenv("ERP_RETRY_DELAY", "2"))

NOMINATIM_URL = os.getenv(
    "NOMINATIM_URL",
    "https://nominatim.openstreetmap.org/reverse"
)


# ==============================
# SECURITY / JWT SETTINGS
# ==============================
SECRET_KEY = os.getenv("SECRET_KEY", "change_this_secret")
JWT_SECRET = os.getenv("JWT_SECRET", SECRET_KEY)

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
SESSION_EXPIRY_DAYS = int(os.getenv("SESSION_EXPIRY_DAYS", 20))

# OTP / MFA
TOTP_INTERVAL = int(os.getenv("TOTP_INTERVAL", 180))
OTP_VALIDITY_MIN = int(os.getenv("OTP_VALIDITY_MIN", 5))
MAX_OTP_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", 3))
OTP_LOCK_DURATION_MIN = int(os.getenv("OTP_LOCK_DURATION_MIN", 15))

# Login Lockout
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", 5))
LOGIN_LOCK_DURATION_MIN = int(os.getenv("LOGIN_LOCK_DURATION_MIN", 15))


# ==============================
# PASSWORD & RESET POLICY
# ==============================
RESETPASSWORD_TOKEN_EXPIRE = int(os.getenv("RESETPASSWORD_TOKEN_EXPIRE", 300))
PASSWORD_HISTORY_LIMIT = int(os.getenv("PASSWORD_HISTORY_LIMIT", 5))


# ==============================
# EMAIL SETTINGS
# ==============================
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", EMAIL_USER or "noreply@example.com")


# ==============================
# FILE UPLOAD LIMITS
# ==============================
MAX_FILE_SIZE_KB = int(os.getenv("MAX_FILE_SIZE_KB", 500))
# ==============================
# ZOHO BOOKS CONFIGURATION
# ==============================

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_ORG_ID = os.getenv("ZOHO_ORG_ID")

# India DC (books.zohosecure.in → zohoapis.in)
ZOHO_API_BASE = os.getenv("ZOHO_API_BASE", "https://www.zohoapis.in")
ZOHO_ACCOUNTS_BASE = os.getenv("ZOHO_ACCOUNTS_BASE", "https://accounts.zoho.in")

# Safety check (fail fast in startup)
if not all([ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID]):
    raise RuntimeError("Zoho Books environment variables are not fully configured")