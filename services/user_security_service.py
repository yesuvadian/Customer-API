from datetime import datetime, timedelta, timezone
import uuid
from dotenv import load_dotenv
import os
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
import models, schemas
from services.totp_service import TOTPService
from utils.common_service import UTCDateTimeMixin


class UserSecurityService(UTCDateTimeMixin):
    load_dotenv()
    totp_service = TOTPService()
# Configs
    # Load configuration from .env with fallback defaults
    OTP_VALIDITY_MINUTES = int(os.getenv("OTP_VALIDITY_MIN", 5))
    OTP_MAX_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", 3))
    OTP_LOCK_MINUTES = int(os.getenv("OTP_LOCK_DURATION_MIN", 30))
    OTP_MAX_RESEND = 3

    
     # -------------------
    # Login lock checks
    # -------------------
    @classmethod
    def is_login_locked(cls, db: Session, user_id: str) -> bool:
        user_sec = cls.get_user_security(db, user_id)
        locked_until = cls._make_aware(user_sec.login_locked_until)
        return locked_until is not None and locked_until > cls._utc_now()
    

    @classmethod
    def login_lock_remaining_minutes(cls, db: Session, user_id: str) -> int:
        user_sec = cls.get_user_security(db, user_id)
        locked_until = cls._make_aware(user_sec.login_locked_until)
        if locked_until and locked_until > cls._utc_now():
            remaining = locked_until - cls._utc_now()
            return int(remaining.total_seconds() // 60)
        return 0


  

  
  

   
     # -------------------
    # OTP lock checks
    # -------------------
    @classmethod
    def is_otp_locked(cls, db: Session, user_id: str) -> bool:
        user_sec = cls.get_user_security(db, user_id)
        otp_locked_until = cls._make_aware(user_sec.otp_locked_until)
        return otp_locked_until is not None and otp_locked_until > cls._utc_now()



    @classmethod
    def otp_lock_remaining_minutes(cls, db: Session, user_id: str) -> int:
        user_sec = cls.get_user_security(db, user_id)
        otp_locked_until = cls._make_aware(user_sec.otp_locked_until)
        if otp_locked_until and otp_locked_until > cls._utc_now():
            remaining = otp_locked_until - cls._utc_now()
            return int(remaining.total_seconds() // 60)
        return 0
    @classmethod
    def can_attempt_otp(cls, db: Session, user_id: str) -> bool:
        try:
            user_sec = cls.get_user_security(db, user_id)
        except HTTPException:
            return False

        otp_locked_until = cls._make_aware(user_sec.otp_locked_until)
        return not (otp_locked_until and otp_locked_until > cls._utc_now())
    # -------------------
    # Check if OTP resend attempts exceeded
    # -------------------
    @classmethod
    def has_exceeded_otp_resend(cls, db: Session, user_id: str) -> bool:
        user_sec = cls.get_user_security(db, user_id)
        otp_resend_count = user_sec.otp_resend_count or 0
        otp_pending = getattr(user_sec, "otp_pending_verification", False)
        return otp_resend_count >= cls.OTP_MAX_RESEND and otp_pending
    # -------------------
    # Create a new user_security entry
    # -------------------
    @classmethod  
    def create_user_security(cls,db: Session, user_id: str, totp_secret: str = None):
        db_user_security = models.UserSecurity(
            user_id=user_id,
            totp_secret=totp_secret
        )
        db.add(db_user_security)
        db.commit()
        db.refresh(db_user_security)
        return db_user_security
    
    # -------------------
    # Lock OTP
    # -------------------
    @classmethod
    def lock_user_otp(cls, db: Session, user_id: str, now: datetime = None):
        user_sec = cls.get_user_security(db, user_id)
        now = cls._utc_now() if now is None else cls._make_aware(now)
        locked_until = now + timedelta(minutes=cls.OTP_LOCK_MINUTES)

        user_sec.otp_locked_until = locked_until
        user_sec.otp_attempts = 0
        user_sec.otp_resend_count = 0
        user_sec.otp_pending_verification = False

        db.commit()
        db.refresh(user_sec)
        return locked_until
    
    # -------------------
    # Mark OTP pending
    # -------------------
    @classmethod
    def mark_otp_pending(cls, db: Session, user_id: uuid.UUID):
        user_security = cls.get_user_security(db, user_id)
        user_security.otp_pending_verification = True
        user_security.last_otp_sent_at = cls._utc_now()
        db.commit()
        db.refresh(user_security)
        return user_security

    # -------------------
    # Get user_security by user_id
    # -------------------
    @staticmethod
    def get_user_security(db: Session, user_id: str):
        db_user_security = db.query(models.UserSecurity).filter(models.UserSecurity.user_id == user_id).first()
        if not db_user_security:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User security not found")
        return db_user_security
        # -------------------
    # Get current OTP attempts for a user
    # -------------------
    @classmethod
    def get_otp_attempts(cls, db: Session, user_id: str) -> int:
        """
        Returns the number of OTP verification attempts a user has made.
        """
        user_sec = cls.get_user_security(db, user_id)
        return user_sec.otp_attempts or 0
    # -------------------
    # Update OTP details
    # -------------------
    # -------------------
    # Update OTP
    # -------------------
    @classmethod
    def update_otp(cls, db: Session, user_id: str, otp_code: str):
        user_sec = cls.get_user_security(db, user_id)
        otp_expiry = cls._make_aware(otp_expiry)
        user_sec.otp_code = otp_code
        user_sec.otp_expiry = otp_expiry
        user_sec.otp_attempts = 0
        user_sec.otp_pending_verification = True
        user_sec.last_otp_sent_at = cls._utc_now()
        db.commit()
        db.refresh(user_sec)
        return user_sec
    
    def resend_otp_for_user(cls, db: Session, user_id: uuid.UUID):
        """
        Resend OTP for a user by regenerating it, marking it pending, 
        and incrementing the resend count. Forces login if OTP expired.
        """
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        user_security = db.query(models.UserSecurity).filter(models.UserSecurity.user_id == user_id).first()
        if not user_security:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User security record not found"
            )

        # Ensure OTP is still valid
        otp_expiry = cls._make_aware(user_security.otp_expiry)
        if otp_expiry is None or otp_expiry <= cls._utc_now():
            # OTP expired → force user to login again
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="OTP expired. Please login again."
            )

        # Generate new OTP
        new_otp = cls.totp_service.send_totp_to_user(user.email, user_security.totp_secret)
        user_security.otp_code = new_otp
        user_security.otp_pending_verification = True
        user_security.last_otp_sent_at = cls._utc_now()

        # Update otp_expiry for new OTP
        user_security.otp_expiry = cls._utc_now() + timedelta(minutes=cls.OTP_VALIDITY_MINUTES)

        # Increment otp_resend_count safely
        user_security.otp_resend_count = (user_security.otp_resend_count or 0) + 1

        db.commit()
        db.refresh(user_security)

        # TODO: send OTP via SMS/email
        # send_otp(user.phone_number, new_otp)

        return {
            "message": "OTP resent successfully",
            "otp_resend_count": user_security.otp_resend_count
        }
    # Increment OTP attempts
    # -------------------
    # -------------------
    # Increment OTP attempts
    # -------------------
    @classmethod
    def increment_otp_attempts(cls, db: Session, user_id: str, lock_duration_minutes: int = 15):
        user_sec = cls.get_user_security(db, user_id)
        user_sec.otp_attempts += 1

        if user_sec.otp_attempts >= cls.OTP_MAX_ATTEMPTS:
            user_sec.otp_locked_until = cls._utc_now() + timedelta(minutes=lock_duration_minutes)
            user_sec.otp_attempts = 0

        db.commit()
        db.refresh(user_sec)
        return user_sec

    # -------------------
    # Reset OTP / unlock
    # -------------------
    # -------------------
    # Reset OTP / unlock
    # -------------------
    @classmethod
    def reset_otp_attempts(cls, db: Session, user_id: str):
        user_sec = cls.get_user_security(db, user_id)
        user_sec.otp_code = None
        user_sec.otp_expiry = None
        user_sec.otp_attempts = 0
        user_sec.otp_locked_until = None
        user_sec.otp_pending_verification = False
        user_sec.otp_resend_count = 0
        db.commit()
        db.refresh(user_sec)
        return user_sec

    # -------------------
    # Update failed login attempts
    # -------------------
    # -------------------
    # Increment failed login
    # -------------------
    @classmethod
    def increment_failed_login(cls, db: Session, user_id: str, lock_duration_minutes: int = 15):
        user_sec = cls.get_user_security(db, user_id)
        user_sec.failed_login_attempts += 1

        if user_sec.failed_login_attempts >= 5:
            user_sec.login_locked_until = cls._utc_now() + timedelta(minutes=lock_duration_minutes)
            user_sec.failed_login_attempts = 0

        db.commit()
        db.refresh(user_sec)
        return user_sec


    # -------------------
    # Delete user_security entry
    # -------------------
    @classmethod
    def delete_user_security(cls,db: Session, user_id: str):
        user_sec = UserSecurityService.get_user_security(db, user_id)
        db.delete(user_sec)
        db.commit()
        return {"detail": "User security deleted successfully"}
    @classmethod
    def can_attempt_otp(cls, db: Session, user_id: str) -> bool:
        """
        Check if user can attempt OTP.
        Returns False if user does not exist or OTP is currently locked.
        """
        try:
            user_sec = cls.get_user_security(db, user_id)
        except HTTPException:
            return False  # User security not found

        locked_until = getattr(user_sec, "otp_locked_until", None)
        if locked_until and locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
            return False

        return True
    # -------------------
    # Check if TOTP is enabled for a user
    # -------------------
    @classmethod
    def is_totp_enabled(cls,db: Session, user_id: str) -> bool:
        user_sec = UserSecurityService.get_user_security(db, user_id)
        return bool(user_sec.totp_secret)

    # -------------------
    # Update or set TOTP secret for a user
    # -------------------
    @classmethod
    def update_user_totp_secret(cls,db: Session, user_id: str, totp_secret: str):
        user_sec = UserSecurityService.get_user_security(db, user_id)
        user_sec.totp_secret = totp_secret
        db.commit()
        db.refresh(user_sec)
        return user_sec
    # -------------------
    # Get TOTP secret for a user
    # -------------------
      # -------------------
    # Check if TOTP is set for a user
    # -------------------
    @classmethod
    def has_totp_secret(cls, db: Session, user_id: str) -> bool:
        """
        Returns True if the user has a TOTP secret set, False otherwise.
        """
        try:
            user_sec = cls.get_user_security(db, user_id)
            return bool(user_sec.totp_secret)
        except HTTPException:
            # If user_security record not found, consider TOTP not set
            return False
