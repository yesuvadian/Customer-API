from typing import Dict, Optional
from urllib.request import Request
import uuid
import os
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from database import get_db
from models import Module, PasswordHistory, PasswordResetToken, Plan, Role, RoleModulePrivilege, User, UserRole, UserSecurity, UserSession
from security_utils import get_password_hash, verify_password
from services import user_service
from utils.common_service import UTCDateTimeMixin
from utils.email_service import EmailService


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
#BASE_URL=os.getenv("BASE_URL", "http://localhost:59685")

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
def get_registration_user(token: str = Depends(oauth2_scheme)) -> str:
    """
    Validate registration token issued in Step 1.
    - Ensures token exists
    - Ensures token contains a "sub" and type "register"
    """

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration token missing",
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_or_session_id = payload.get("sub")
        token_type = payload.get("type")
        exp = payload.get("exp")

        if not user_or_session_id or token_type != "register":
            raise HTTPException(status_code=401, detail="Invalid registration token")

        # Optional: enforce expiration
        if exp and UTCDateTimeMixin._utc_now().timestamp() > exp:
            raise HTTPException(status_code=401, detail="Registration token expired")

        return user_or_session_id  # This identifies the pending user/session

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired registration token",
        )
def login_user(db: Session, email: str, password: str):
    try:
        # Always use UTC-aware time
        now = UTCDateTimeMixin._utc_now()
 
        # Step 1: Fetch user
        user = db.query(User).filter_by(email=email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
 
        # Step 2: Check if user is active
        if not user.isactive:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive. Please contact administrator."
            )
 
        # Step 3: Security record
        security = db.query(UserSecurity).filter_by(user_id=user.id).first()
        if not security:
            security = UserSecurity(
                user_id=user.id,
                failed_login_attempts=0,
                login_locked_until=None
            )
            db.add(security)
            db.flush()
 
        # Step 4: Account locked? Show remaining time
        if security.login_locked_until and security.login_locked_until > now:
            remaining = security.login_locked_until - now
            remaining_minutes = int(remaining.total_seconds() // 60)
 
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account locked. Try again in {remaining_minutes} minute(s)."
            )
 
        # Step 5: Password verification
        if verify_password(password, user.password_hash):
 
            # Reset attempts
            security.failed_login_attempts = 0
 
            # Clear lock ONLY if expired
            if security.login_locked_until and security.login_locked_until <= now:
                security.login_locked_until = None
 
            db.commit()
 
        else:
            # FAILED LOGIN
            security.failed_login_attempts += 1
 
            # Lock account
            if security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                security.login_locked_until = now + timedelta(minutes=LOGIN_LOCK_DURATION_MIN)
                db.commit()
 
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Too many failed attempts. Account locked for {LOGIN_LOCK_DURATION_MIN} minute(s)."
                )
 
            # Not locked yet → generic error
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
 
        # Step 6: Load roles
        role_ids = [r.role_id for r in db.query(UserRole).filter_by(user_id=user.id).all()]
        if not role_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no roles assigned. Contact administrator."
            )
 
        roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
        role_names = [r.name for r in roles]
 
        # -------------------------------------------------------
        # Step 7: Privileges (DO NOT filter by is_active)
        # -------------------------------------------------------

        modules_map = {
            m.id: {
                "name": m.name,
                "is_active": m.is_active  # UI visibility ONLY
            }
            for m in db.query(Module).all()
        }

        filtered_privileges = {}

        raw_privs = db.query(RoleModulePrivilege).filter(
            RoleModulePrivilege.role_id.in_(
                [r.role_id for r in db.query(UserRole).filter_by(user_id=user.id)]
            )
        ).all()

        for priv in raw_privs:
            module_info = modules_map.get(priv.module_id)
            if not module_info:
                continue

            mod_name = module_info["name"]

            if mod_name not in filtered_privileges:
                filtered_privileges[mod_name] = {
                    "can_view": False,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_search": False,
                    "can_import": False,
                    "can_export": False,
                    "is_active": module_info["is_active"],  # 🔥 IMPORTANT
                }

            for key in [
                "can_view",
                "can_add",
                "can_edit",
                "can_delete",
                "can_search",
                "can_import",
                "can_export",
            ]:
                filtered_privileges[mod_name][key] |= getattr(priv, key)



        
        # Step 8: Plan info
        plan = None
        if user.plan_id:
            plan_obj = db.query(Plan).filter_by(id=user.plan_id).first()
            if plan_obj:
                plan = {
                    "id": str(plan_obj.id),
                    "planname": plan_obj.planname,
                    "plan_description": plan_obj.plan_description,
                    "plan_limit": plan_obj.plan_limit,
                }
 
        # Step 9: Login success
        return {
            "access_token": create_access_token({"sub": str(user.id)}),
            "refresh_token": create_refresh_token(str(user.id)),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "firstname": user.firstname,
                "lastname": user.lastname,
                "phone_number": user.phone_number,
                "is_active": user.isactive,
                "email_confirmed": user.email_confirmed,
                "phone_confirmed": user.phone_confirmed,
                "cts": UTCDateTimeMixin._make_aware(user.cts),
                "mts": UTCDateTimeMixin._make_aware(user.mts),
                "roles": role_names,
                "plan": plan
            },
            "privileges": filtered_privileges

        }
 
    except HTTPException:
        raise
 
    except Exception as e:
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
        cts=now,
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
from fastapi import Depends, HTTPException, Request, status

def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    # Standard credentials exception used on decode/lookup failures
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode JWT
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except Exception:
        raise credentials_exception

    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise credentials_exception

    # Allow everything else
    return user



def requestpasswordreset(db: Session, email: str, request: Request) -> str:
    # 🔍 1. Find the user
    user = db.query(User).filter_by(email=email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # 🔒 2. Invalidate any previous unused tokens
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False
    ).update({"used": True})
    db.commit()

    # 🧩 3. Generate a new token
    reset_token = generate_reset_token(user.id)

    # 💾 4. Store the token in DB
    token_entry = PasswordResetToken(
        user_id=user.id,
        token=reset_token,
        cts=UTCDateTimeMixin._utc_now(),
        expires_at=UTCDateTimeMixin._utc_now() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        used=False
    )
    db.add(token_entry)
    db.commit()

    # 📧 5. Send email via your existing EmailService
    email_service = EmailService()
    email_service.send_password_reset(to_email=user.email, token=reset_token)

    # 🔗 6. Return link for debugging or frontend testing
    reset_link = f"{email_service.base_url}/reset-password?token={reset_token}&email={user.email}"

    return reset_link


def resetpassword(db: Session, token: str, new_password: str):
    if not token or not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token and new password are required"
        )

    # 1️⃣ Verify JWT and extract user_id
    user_id = verify_reset_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    # 2️⃣ Check if token is already used
    from models import PasswordResetToken
    token_entry = db.query(PasswordResetToken).filter_by(token=token).first()
    if not token_entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token not found or already invalidated"
        )

    if token_entry.used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has already been used"
        )

    if UTCDateTimeMixin._make_aware(token_entry.expires_at) < UTCDateTimeMixin._utc_now():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )

    # 3️⃣ Fetch user
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # 4️⃣ Check if new password matches old ones
    if verify_password(new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="New password cannot be the same as the current password."
        )

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

    # 5️⃣ Update password
    new_hash = get_password_hash(new_password)
    user.password_hash = new_hash

    # Ensure UserSecurity record exists
    security = db.query(UserSecurity).filter_by(user_id=user.id).first()
    if not security:
        security = UserSecurity(user_id=user.id)
        db.add(security)
        db.flush()

    security.failed_login_attempts = 0
    security.login_locked_until = None

    # 6️⃣ Save to PasswordHistory
    pw_entry = PasswordHistory(
        user_id=user.id,
        password_hash=new_hash,
        cts=UTCDateTimeMixin._utc_now(),
        created_by=user.id,
        modified_by=user.id,
    )
    db.add(pw_entry)

    # 7️⃣ Mark token as used
    token_entry.used = True

    # 8️⃣ Prune old password history
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
