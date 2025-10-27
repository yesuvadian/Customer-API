import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==============================
# DATABASE CONFIGURATION
# ==============================
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "mydatabase")

# Construct SQLAlchemy database URL
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False

# ==============================
# SECURITY / JWT CONFIGURATION
# ==============================
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")

JWT_SECRET = os.getenv("JWT_SECRET", "your-jwt-secret")
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", 1440))

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
SESSION_EXPIRY_DAYS = int(os.getenv("SESSION_EXPIRY_DAYS", 20))

# ==============================
# ACCOUNT LOCKOUT POLICY
# ==============================
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 5))
LOCK_DURATION_MINUTES = int(os.getenv("LOCK_DURATION_MINUTES", 15))

# ==============================
# PASSWORD POLICY / HISTORY
# ==============================
RESET_TOKEN_EXPIRY_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRY_MINUTES", 30))
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
# APPLICATION SETTINGS
# ==============================
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")

MAX_FILE_SIZE_KB = os.getenv("MAX_FILE_SIZE_KB", "500")

