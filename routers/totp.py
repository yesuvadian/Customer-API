from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from pydantic import BaseModel,EmailStr
from pytest import Session

#from auth import decode_access_token
from auth_utils import decode_access_token,get_current_user
from database import get_db
#from services import user_service,user_security_service

from services.user_security_service import UserSecurityService
from services.user_service import UserService
# Correct import
from services.totp_service import TOTPService
#from services.user_service import UserService,
#from routes.auth_routes import decode_access_token

load_dotenv()

totp_router = APIRouter(prefix="/totp", tags=["totp"],dependencies=[Depends(get_current_user)])
user_service = UserService()
user_security_service=UserSecurityService()
# Create an instance
totp_service = TOTPService()
# Configs
OTP_MAX_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", 5))
OTP_LOCK_MINUTES = int(os.getenv("OTP_LOCK_DURATION_MIN", 15))
OTP_VALIDITY_MINUTES = int(os.getenv("OTP_VALIDITY_MIN", 5))
TOTP_INTERVAL = int(os.getenv("TOTP_INTERVAL", 30))

class TOTPSetupRequest(BaseModel):
    email_id: EmailStr
# -------------------------------
# Helpers
# -------------------------------
from pydantic import BaseModel, EmailStr

# Define request body model
class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

def to_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid authorization header")

    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")
    return payload.get("sub")

# ✅ Define a body model

# -------------------------------
# Setup TOTP
# -------------------------------
@totp_router.post("/setup")
async def setup_totp(
    body: TOTPSetupRequest,
    db: Session = Depends(get_db),  
    current_user=Depends(get_current_user)
):
    email = body.email_id

    # Fetch user by email
    user = user_service.get_user_by_email(db,email)
    if not user:
        return JSONResponse({"detail": "User not found"}, status_code=404)

    now = datetime.now(timezone.utc)

    try:
        # --- Check login and OTP locks ---
        if user_security_service.is_login_locked(db,user.id):
            remaining = user_security_service.login_lock_remaining_minutes(db,user.id, now)
            return JSONResponse({
                "detail": f"Account locked due to failed login attempts. Try again in {remaining} minutes."
            }, status_code=403)

        if user_security_service.is_otp_locked(db,user.id):
            remaining = user_security_service.otp_lock_remaining_minutes(db,user.id)
            return JSONResponse({
                "detail": f"Account locked due to failed OTP attempts. Try again in {remaining} minutes."
            }, status_code=403)

        # --- Check OTP resend limit ---
        if user_security_service.has_exceeded_otp_resend(db,user.id):
            locked_until = user_security_service.lock_user_otp(db,user.id,now)
            return JSONResponse({
                "detail": f"OTP attempts exceeded without verification. Account locked until {locked_until}"
            }, status_code=403)

        # --- Ensure TOTP secret ---
     # Ensure TOTP secret
        if not user_security_service.has_totp_secret(db, user.id):
            secret = TOTPService.generate_totp_secret()
            user_security_service.update_user_totp_secret(db, user.id, secret)
        else:
            # fetch the existing secret
            user_sec = user_security_service.get_user_security(db, user.id)
            secret = user_sec.totp_secret
            

        # --- Send OTP and mark pending ---
        otp_code = user_security_service.resend_otp_for_user(db,user.id)

        # --- Generate TOTP URI for QR code ---
        uri = totp_service.get_totp_uri(user.email, secret)

        return JSONResponse({
            "uri": uri,
            "otp_sent": otp_code,
            "otp_attempts": user_security_service.get_otp_attempts(db,user.id),
            "pending_verification": True
        })

    except Exception as e:
        return JSONResponse({"detail": f"Error setting up TOTP: {str(e)}"}, status_code=500)


# -------------------------------
# Send existing OTP
# -------------------------------
@totp_router.post("/send-totp")
async def send_existing_otp(
    body: TOTPSetupRequest,
    db: Session = Depends(get_db),  
    current_user=Depends(get_current_user)
    ):
   # payload = await request.json()
    email = body.email_id
    if not email:
        return JSONResponse({"detail": "email is required"}, status_code=400)

    # --- Fetch user ---
    user = user_service.get_user_by_email(db,email)
    if not user:
        return JSONResponse({"detail": "User not found"}, status_code=404)

    #now = datetime.now(timezone.utc)

    # --- Check login lock ---
    if user_security_service.is_login_locked(db,user.id):
        remaining = user_security_service.login_lock_remaining_minutes(user.id)
        return JSONResponse({
            "detail": f"Account locked due to failed login attempts. Try again in {remaining} minutes."
        }, status_code=403)

    # --- Check OTP lock ---
    if user_security_service.is_otp_locked(db,user.id):
        remaining = user_security_service.otp_lock_remaining_minutes(db,user.id)
        return JSONResponse({
            "detail": f"Account locked due to failed OTP attempts. Try again in {remaining} minutes."
        }, status_code=403)
      # --- Validate OTP ---
    user_sec = user_security_service.get_user_security(db, user.id)
    otp_expiry = UserSecurityService._make_aware(user_sec.otp_expiry)

    if  (otp_expiry and otp_expiry < UserSecurityService._utc_now()):
        user_security_service.increment_otp_attempts(db, user.id)
        return JSONResponse({"valid": False, "detail": "Invalid or expired OTP"}, status_code=401)
    # --- Ensure TOTP secret ---
    if not user_security_service.is_totp_enabled(db,user.id):
        secret = totp_service.generate_totp_secret()
        user_security_service.update_user_totp_secret(db,user.id, secret)
    else:
            # fetch the existing secret
        user_sec = user_security_service.get_user_security(db, user.id)
        secret = user_sec.totp_secret
    # --- Check OTP resend limit ---
    if user_security_service.has_exceeded_otp_resend(db,user.id):
        locked_until = user_security_service.lock_user_otp(db,user.id)
        return JSONResponse({
                "detail": f"OTP attempts exceeded without verification. Account locked until {locked_until}"
            }, status_code=403)
    # --- Resend OTP ---
    otp_data = user_security_service.resend_otp_for_user(db,user.id)

    # --- Mark OTP pending ---
    user_security_service.mark_otp_pending(db,user.id)

    return JSONResponse({
        "message": "OTP resent successfully",
        "otp_sent": otp_data.get("otp"),
        "resend_count": otp_data.get("otp_resend_count", 0)
    })



# -------------------------------
# Verify OTP route
# -------------------------------
@totp_router.post("/verify")
async def verify_otp_route(
    body: OTPVerifyRequest,  # Pydantic model
    db: Session = Depends(get_db), 
    current_user: str = Depends(get_current_user)
):
    email = body.email
    otp = body.otp

    # --- Fetch user ---
    user = user_service.get_user_by_email(db, email)
    if not user:
        return JSONResponse({"detail": "User not found"}, status_code=404)

    now = UserSecurityService._utc_now()

    # --- Check OTP lock ---
    if not user_security_service.can_attempt_otp(db, user.id):
        user_sec = user_security_service.get_user_security(db, user.id)
        locked_until = UserSecurityService._make_aware(user_sec.otp_locked_until)
        return JSONResponse({
            "detail": f"Account locked due to failed OTP attempts. Try again after {locked_until}"
        }, status_code=403)
    
    # --- Check OTP resend limit ---
    if user_security_service.has_exceeded_otp_resend(db, user.id):
        locked_until = user_security_service.lock_user_otp(db, user.id)
        return JSONResponse({
            "detail": f"OTP attempts exceeded without verification. Account locked until {locked_until}"
        }, status_code=403)

    # --- Check login lock ---
    if user_security_service.is_login_locked(db, user.id):
        remaining = user_security_service.login_lock_remaining_minutes(db, user.id)
        return JSONResponse({
            "detail": f"Account locked due to failed password attempts. Try again in {remaining} minutes."
        }, status_code=403)

    # --- Validate OTP ---
    user_sec = user_security_service.get_user_security(db, user.id)
    otp_expiry = UserSecurityService._make_aware(user_sec.otp_expiry)

    if otp != user_sec.otp_code or (otp_expiry and otp_expiry < now):
        user_security_service.increment_otp_attempts(db, user.id)
        return JSONResponse({"valid": False, "detail": "Invalid or expired OTP"}, status_code=401)

    # --- Optionally verify TOTP ---
    if user_sec.totp_secret and not totp_service.verify_totp_code(user_sec, otp):
        user_security_service.increment_otp_attempts(db, user.id)
        return JSONResponse({"valid": False, "detail": "Invalid OTP"}, status_code=401)

    # --- OTP correct: reset attempts ---
    user_security_service.reset_otp_attempts(db, user.id)

    return JSONResponse({"valid": True, "detail": "OTP verified successfully"}, status_code=200)



# -------------------------------
# Get OTP config
# -------------------------------
@totp_router.get("/config")
async def get_otp_config(current_user: str = Depends(get_current_user)):
    try:
        max_attempts = int(os.getenv("MAX_OTP_ATTEMPTS", 5))
        lock_duration_min = int(os.getenv("OTP_LOCK_DURATION_MIN", 15))
        validity_min = int(os.getenv("OTP_VALIDITY_MIN", 5))
        totp_interval = int(os.getenv("TOTP_INTERVAL", 30))

        return JSONResponse({
            "max_attempts": max_attempts,
            "lock_duration_minutes": lock_duration_min,
            "otp_validity_minutes": validity_min,
            "otp_validity_seconds": validity_min * 60,
            "totp_interval_seconds": totp_interval
        })
    except Exception as e:
        return JSONResponse({"detail": f"Error reading OTP config: {str(e)}"}, status_code=500)
