import os
import smtplib
from email.message import EmailMessage
#from config import EMAIL_CONFIG
from dotenv import load_dotenv

from config import EMAIL_PASS, EMAIL_USER, FROM_EMAIL, SMTP_PORT, SMTP_SERVER

# Load environment variables from .env
load_dotenv()

class EmailService:
   
    def __init__(self):
        self.smtp_server = SMTP_SERVER
        self.smtp_port = SMTP_PORT
        self.username = EMAIL_USER
        self.password = EMAIL_PASS
        self.from_email =FROM_EMAIL

        # Use BASE_URL from .env with a fallback
        self.base_url = os.getenv("BASE_URL", "http://localhost:8000")

        # Read TOTP interval from .env and store as instance variable
        self.totp_interval = int(os.getenv("TOTP_INTERVAL", 30))  # default 30 seconds

        # Optional: Password reset expiry from .env
        self.reset_token_expiry = int(os.getenv("RESETPASSWORD_TOKEN_EXPIRE", 3600))  # default 1 hour
    def send_attachment_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        attachment_content: bytes,
        filename: str,
        mime_type: str = "application/octet-stream"
):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to_email
        msg.set_content(body_html, subtype="html")
        msg.add_attachment(attachment_content, maintype=mime_type.split("/")[0], subtype=mime_type.split("/")[1], filename=filename)

        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
            server.login(self.username, self.password)
            server.send_message(msg)

    def send_email(self, to_email: str, subject: str, body: str):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to_email
        msg.set_content(body, subtype="html")

        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
            server.login(self.username, self.password)
            server.send_message(msg)

    def send_password_reset(self, to_email: str, token: str):
        universal_link = f"{self.base_url}/reset-password?token={token}&email={to_email}"
        body = f"""
            <h3>Password Reset / Contact Request</h3>
            <p>Click the link below to continue:</p>
            <a href="{universal_link}" style="color:#004080; text-decoration:none; font-weight:bold;">
                Reset Password
            </a>
            <p>This link will expire in {self.reset_token_expiry} seconds.</p>
        """
        self.send_email(to_email, "VAP-Action Required: Password Reset", body)

    def send_totp(self, to_email: str, otp: str):
        body = f"""
        <h3>Your One-Time Password (OTP)</h3>
        <p>Use the code below to complete your login or verification:</p>
        <div style="font-size: 24px; font-weight: bold; color: #004080; margin: 10px 0;">
            {otp}
        </div>
        <p>This code will expire in {self.totp_interval} seconds. Do not share it with anyone.</p>
        <p>If you did not request this, please ignore this message.</p>
        """
        self.send_email(to_email, "VAP: Your OTP Code", body)
