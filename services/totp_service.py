import os
from dotenv import load_dotenv
import pyotp
from schemas import User
from utils.email_service import EmailService

# Load environment variables
load_dotenv()

class TOTPService:
    # Default interval is 90 seconds if not set in .env
    TOTP_INTERVAL = int(os.getenv("TOTP_INTERVAL", 90))
    email_service= EmailService()


    @staticmethod
    def generate_totp_secret() -> str:
        """Generate a new TOTP secret for a user"""
        return pyotp.random_base32()

    @classmethod
    def get_totp_uri(cls, email: str, secret: str, issuer: str = "AstuteDev") -> str:
        """Return the provisioning URI for TOTP setup (used for QR codes)"""
        totp = pyotp.TOTP(secret, interval=cls.TOTP_INTERVAL)
        return totp.provisioning_uri(name=email, issuer_name=issuer)

    @classmethod
    def verify_totp_code(cls, user: dict, otp_input: str) -> bool:
        """Verify a user-provided OTP against their TOTP secret"""
        if not user.get("totp_secret"):
            raise ValueError("User does not have a TOTP secret configured")
        totp = pyotp.TOTP(user["totp_secret"], interval=cls.TOTP_INTERVAL)
        # valid_window=1 allows 1-step leeway
        return totp.verify(otp_input, valid_window=1)
    @classmethod
    def send_totp_to_user(self, email_id: str,totp_secret:str) -> str:
        """Generate and send a TOTP via email (and optionally SMS)"""
        if not email_id:
            raise ValueError("User must have an email address")
        if not totp_secret:
            raise ValueError("User does not have a TOTP secret configured")

        otp = pyotp.TOTP(totp_secret, interval=self.TOTP_INTERVAL).now()
        self.email_service.send_totp(email_id, otp)

        # Optional SMS sending
        # phone = user.get("phone_number")
        # if phone and phone.strip():
        #     send_totp_sms(phone, otp)

        return otp
