from typing import Optional
import uuid
import os
from datetime import timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import get_db
from models import User, UserSecurity
from security_utils import verify_password
from services import user_service
from utils.common_service import UTCDateTimeMixin
#from mixins.time_utils import UTCDateTimeMixin  # ✅ import mixin

# ==============================
# Configuration
# ==============================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", 5))
LOGIN_LOCK_DURATION_MIN = int(os.getenv("LOGIN_LOCK_DURATION_MIN", 15))

SECRET_KEY = os.getenv("SECRET_KEY", "your_super_secret_key_here")
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ==============================
# Token Utilities
# ==============================
def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    expire = UTCDateTimeMixin._utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    expire = UTCDateTimeMixin._utc_now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = data.copy()
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """Decode JWT access token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ==============================
# Authentication Logic
# ==============================
def authenticate_user(db: Session, username: str, password: str):
    """
    Authenticate a user using the user_security table for tracking
    failed logins and lockouts. Uses UTCDateTimeMixin for all datetime operations.
    """
    if not username or not password:
        return {"error": "Username and password required", "status": 400}

    # 🔍 Find user
    user = db.query(User).filter(User.email == username).first()
    if not user:
        return {"error": "Invalid credentials", "status": 401}

    # 🔐 Ensure user_security record exists
    security = db.query(UserSecurity).filter_by(user_id=user.id).first()
    if not security:
        security = UserSecurity(user_id=user.id)
        db.add(security)
        db.commit()
        db.refresh(security)

    now = UTCDateTimeMixin._utc_now()  # ✅ always aware UTC datetime

    # 🚫 Check if account is locked
    locked_until = UTCDateTimeMixin._make_aware(security.login_locked_until)

    if locked_until:
        if locked_until <= now:
            # 🔓 Lock expired — clear it automatically
            security.login_locked_until = None
            db.commit()
        else:
            # 🚷 Still locked
            seconds_left = (locked_until - now).total_seconds()
            remaining_minutes = int(seconds_left // 60)
            if remaining_minutes == 0 and seconds_left > 0:
                remaining_minutes = 1
            return {
                "error": f"Account locked. Try again in {remaining_minutes} minutes.",
                "status": 403,
            }

    # 🔑 Verify password
    if not verify_password(password, user.password_hash):
        security.failed_login_attempts = (security.failed_login_attempts or 0) + 1

        if security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            security.login_locked_until = now + timedelta(minutes=LOGIN_LOCK_DURATION_MIN)
            security.failed_login_attempts = 0  # reset after lockout

        db.commit()
        return {"error": "Invalid credentials", "status": 401}

    # ✅ Successful login
    security.failed_login_attempts = 0
    security.login_locked_until = None
    db.commit()

    return {"user": user}


# ==============================
# Get Current User
# ==============================
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Extract user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise credentials_exception

    return user
