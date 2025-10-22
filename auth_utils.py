from typing import Dict, Optional
from urllib.request import Request
import uuid
import os
from datetime import timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import get_db
from models import Module, PasswordHistory, Role, RoleModulePrivilege, User, UserRole, UserSecurity, UserSession
from security_utils import get_password_hash, verify_password
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
PASSWORD_HISTORY_LIMIT=int(os.getenv("PASSWORD_HISTORY_LIMIT", 5))
SECRET_KEY = os.getenv("SECRET_KEY", "your_super_secret_key_here")
ALGORITHM = "HS256"
RESET_TOKEN_EXPIRE_MINUTES=int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", 300))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ==============================
# Token Utilities
# ==============================
def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    expire = UTCDateTimeMixin._utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
# ----------------------------------------------------------------
# 🔍 Verify and decode password reset token
# ----------------------------------------------------------------
def verify_reset_token(token: str) -> Optional[str]:
    """
    Verify a password reset token and return the user_id if valid.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type"
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token payload"
            )
        return user_id

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token"
        )
def generate_reset_token(user_id: str) -> str:
    """
    Create a short-lived JWT token for password reset.
    """
    expire = UTCDateTimeMixin._utc_now() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "password_reset",
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token

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

def login_user(db: Session, email: str, password: str):
    try:
        # Step 1: Fetch user
        user = db.query(User).filter_by(email=email).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Step 2: Check if user is active
        if not user.isactive:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive. Please contact administrator."
            )

        # Step 3: Fetch UserSecurity record
        security = db.query(UserSecurity).filter_by(user_id=user.id).first()
        if not security:
            # Optionally, create a default security record if missing
            security = UserSecurity(
                user_id=user.id,
                failed_login_attempts=0,
                login_locked_until=None
            )
            db.add(security)
            db.flush()  # Make sure security record is saved and has an ID

        # Step 4: Check if the account is locked
        if security.login_locked_until and security.login_locked_until > UTCDateTimeMixin._utc_now():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account locked. Try again later."
            )

        # Step 5: Verify password
        if verify_password(password, user.password_hash):
            # Reset failed attempts and lockout time if password is correct
            security.failed_login_attempts = 0
            security.login_locked_until = None
        else:
            # Increment failed login attempts and lockout if necessary
            security.failed_login_attempts += 1
            if security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                security.login_locked_until = UTCDateTimeMixin._utc_now() + timedelta(minutes=LOGIN_LOCK_DURATION_MIN)
            db.commit() # Ensure the changes are written to the DB
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Step 6: Fetch roles
        role_ids = [r.role_id for r in db.query(UserRole).filter_by(user_id=user.id).all()]
        if not role_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no roles assigned. Contact administrator."
            )

        roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
        role_names = [r.name for r in roles]

        # Step 7: Fetch privileges
        privileges: Dict[str, Dict[str, bool]] = {}
        module_map = {m.id: m.name for m in db.query(Module).all()}
        raw_privs = db.query(RoleModulePrivilege).filter(RoleModulePrivilege.role_id.in_(role_ids)).all()

        for priv in raw_privs:
            mod_name = module_map.get(priv.module_id)
            if not mod_name:
                continue

            if mod_name not in privileges:
                privileges[mod_name] = {key: False for key in ["can_add", "can_view", "can_edit",
                                                           "can_delete", "can_search", "can_import",
                                                           "can_export"]}

            for key in privileges[mod_name]:
                privileges[mod_name][key] |= getattr(priv, key)

        # Step 8: Generate access token
        return {
            "access_token": create_access_token({"sub": str(user.id)}),  # Make sure `user.id` is a string here
            "user": {
                "id": str(user.id),  # Explicitly convert UUID to string
                "email": user.email,
                "first_name": user.firstname,
                "last_name": user.lastname,
                "roles": role_names,
            },
            "privileges": privileges,
        }

    except HTTPException:
        raise  # Re-raise HTTP exceptions directly
    except Exception as e:
        # Log unexpected exceptions
        print(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during login."
        )

# ==============================
# Authentication Logic
# ==============================
def authenticate_user(db: Session, username: str, password: str, request=None):
    """
    Authenticate a user using the user_security table for tracking
    failed logins and lockouts. Uses UTCDateTimeMixin for all datetime operations.
    Creates a UserSession on successful login.
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

    now = UTCDateTimeMixin._utc_now()

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
            security.failed_login_attempts = 0
        db.commit()
        return {"error": "Invalid credentials", "status": 401}

    # ✅ Successful login
    security.failed_login_attempts = 0
    security.login_locked_until = None
    db.commit()

    # -----------------------------
    # Create a user session (JWT tracking)
    # -----------------------------
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token(str(user.id))

    session = UserSession(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        created_at=now,
        expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=request.client.host if request else None,
        user_agent=request.headers.get("User-Agent") if request else None
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "user": user,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "session_id": session.id
    }


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
def requestpasswordreset( db: Session, email: str, request: Request) -> str:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        reset_token = generate_reset_token(user.id)
        reset_link = f"{request.base_url}auth/reset-password?token={reset_token}"
        # Normally, you'd email this link to the user
        return reset_link

def resetpassword(db: Session, token: str, new_password: str):
    if not token or not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token and new password are required"
        )

    user_id = verify_reset_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Step 1: Check against current password
    if verify_password(new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="New password cannot be the same as the current password."
        )

    # Step 2: Check against recent password history
    history = (
        db.query(PasswordHistory)
        .filter_by(user_id=user_id)
        .order_by(PasswordHistory.cts.desc())
        .limit(PASSWORD_HISTORY_LIMIT)
        .all()
    )

    for old_pw in history:
        if verify_password(new_password, old_pw.password_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"New password cannot be one of your last {PASSWORD_HISTORY_LIMIT} passwords."
            )

    # Step 3: Update password
    new_hash = get_password_hash(new_password)
    user.password_hash = new_hash

    # 🔐 Ensure UserSecurity record exists
    security = db.query(UserSecurity).filter_by(user_id=user.id).first()
    if not security:
        security = UserSecurity(user_id=user.id)
        db.add(security)
        db.flush()  # ensure security.id exists

    security.failed_login_attempts = 0
    security.login_locked_until = None

    # Step 4: Save to PasswordHistory
    pw_entry = PasswordHistory(
        user_id=user.id,
        password_hash=new_hash,
        cts=UTCDateTimeMixin._utc_now(),
        created_by=user.id,
        modified_by=user.id,
    )
    db.add(pw_entry)

    # Step 5: Prune old history entries
    total_history = (
        db.query(PasswordHistory)
        .filter_by(user_id=user.id)
        .order_by(PasswordHistory.cts.desc())
        .all()
    )

    if len(total_history) > PASSWORD_HISTORY_LIMIT:
        for old_entry in total_history[PASSWORD_HISTORY_LIMIT:]:
            db.delete(old_entry)

    db.commit()
    return {"message": "Password reset successful"}