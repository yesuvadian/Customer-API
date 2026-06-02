import os
import smtplib
import mimetypes
from email.message import EmailMessage
from typing import List, Dict, Optional
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
        
        # No default system CC — per-template cc_emails are passed explicitly
        self.cc_email = None
        # Use BASE_URL from .env with a fallback
        self.base_url = os.getenv("BASE_URL", "http://localhost:8000")

        # Read TOTP interval from .env and store as instance variable
        self.totp_interval = int(os.getenv("TOTP_INTERVAL", 30))  # default 30 seconds

        # Optional: Password reset expiry from .env
        self.reset_token_expiry = int(os.getenv("RESETPASSWORD_TOKEN_EXPIRE", 3600))  # default 1 hour
    def _add_cc(self, msg: EmailMessage, extra_cc: Optional[List[str]] = None):
        """Build a single Cc: header from the default system CC and any extra addresses."""
        parts: List[str] = []
        if self.cc_email:
            parts.append(self.cc_email)
        if extra_cc:
            parts.extend(addr for addr in extra_cc if addr)
        if parts:
            msg["Cc"] = ", ".join(parts)
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
        self.send_email_starttls(to_email, "Congniwatt-Action Required: Password Reset", body)

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
        self.send_email_starttls(to_email, "Congniwatt: Your OTP Code", body)
    def send_email_starttls(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ):
        """
        Send email using STARTTLS (Office 365 compatible).
        cc / bcc accept lists of individual email address strings.
        """
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to_email
        self._add_cc(msg, cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg.set_content(body_html, subtype="html")

        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.username, self.password)
            server.send_message(msg)
        finally:
            server.quit()

    def send_email_starttls_bcc(
        self,
        bcc_emails: List[str],
        subject: str,
        body_html: str,
        cc: Optional[List[str]] = None,
        extra_bcc: Optional[List[str]] = None,
    ) -> None:
        """
        Send one HTML email to multiple recipients via BCC (STARTTLS / Office 365).

        The 'To' header is set to 'undisclosed-recipients:;' so no recipient
        can see the other addresses.  All addresses are placed in the Bcc field.

        bcc_emails  : primary recipient list (resolved from recipient roles)
        cc          : per-template CC addresses
        extra_bcc   : per-template BCC addresses (merged with bcc_emails)
        """
        all_bcc = list(bcc_emails or []) + list(extra_bcc or [])
        if not all_bcc:
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = self.from_email
        msg["To"]      = "undisclosed-recipients:;"
        msg["Bcc"]     = ", ".join(all_bcc)
        self._add_cc(msg, cc)
        msg.set_content(body_html, subtype="html")

        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.username, self.password)
            server.send_message(msg)
        finally:
            server.quit()
    def send_attachment_email_starttls(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        attachment_content: bytes,
        filename: str,
        mime_type: str = "application/octet-stream"
    ):
        """Send email with a single attachment (STARTTLS / Office 365)."""
        self.send_multi_attachment_email_starttls(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            attachments=[
                {"content": attachment_content, "filename": filename, "mime_type": mime_type}
            ],
        )

    def send_multi_attachment_email_starttls(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        attachments: Optional[List[Dict]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ):
        """
        Send HTML email with zero or more file attachments via STARTTLS (Office 365).

        Each entry in `attachments` is a dict with:
          - "content"   : bytes  — raw file bytes
          - "filename"  : str    — attachment filename shown in email client
          - "mime_type" : str    — e.g. "application/pdf" or "application/vnd.ms-excel"
                                   defaults to "application/octet-stream"

        cc / bcc accept lists of individual email address strings from the template.
        """
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = self.from_email
        msg["To"]      = to_email
        self._add_cc(msg, cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg.set_content(body_html, subtype="html")

        for att in (attachments or []):
            content   = att.get("content")
            filename  = att.get("filename", "attachment")
            mime_type = att.get("mime_type", "application/octet-stream")

            if not content:
                continue

            maintype, subtype = mime_type.split("/", 1)
            msg.add_attachment(
                content,
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.username, self.password)
            server.send_message(msg)
        finally:
            server.quit()

    def send_multi_attachment_email_starttls_bcc(
        self,
        bcc_emails: List[str],
        subject: str,
        body_html: str,
        attachments: Optional[List[Dict]] = None,
        cc: Optional[List[str]] = None,
        extra_bcc: Optional[List[str]] = None,
    ) -> None:
        """
        BCC variant of send_multi_attachment_email_starttls.
        Sends one email with optional attachments to all addresses in BCC.

        bcc_emails  : primary recipient list (resolved from recipient roles)
        cc          : per-template CC addresses
        extra_bcc   : per-template BCC addresses (merged with bcc_emails)
        """
        all_bcc = list(bcc_emails or []) + list(extra_bcc or [])
        if not all_bcc:
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = self.from_email
        msg["To"]      = "undisclosed-recipients:;"
        msg["Bcc"]     = ", ".join(all_bcc)
        self._add_cc(msg, cc)
        msg.set_content(body_html, subtype="html")

        for att in (attachments or []):
            content   = att.get("content")
            filename  = att.get("filename", "attachment")
            mime_type = att.get("mime_type", "application/octet-stream")
            if not content:
                continue
            maintype, subtype = mime_type.split("/", 1)
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.username, self.password)
            server.send_message(msg)
        finally:
            server.quit()

    @staticmethod
    def _fetch_attachment(url: str) -> Optional[bytes]:
        """
        Download a file from `url` and return its raw bytes.
        Returns None on any failure (caller skips attachment gracefully).
        Supports:
          • http(s)://  — fetches via requests
          • /local/path — reads from filesystem (for internal storage)
        """
        if not url:
            return None
        try:
            if url.startswith(("http://", "https://")):
                import requests as _req
                resp = _req.get(url, timeout=30)
                resp.raise_for_status()
                return resp.content
            else:
                # Treat as local filesystem path
                with open(url, "rb") as fh:
                    return fh.read()
        except Exception:
            return None

    @staticmethod
    def _guess_filename(url: str, var_key: str) -> tuple:
        """
        Derive a (filename, mime_type) pair from a URL or var_key.
        Falls back to a safe default.
        """
        # Extract filename from URL path
        from urllib.parse import urlparse
        path = urlparse(url).path if url.startswith("http") else url
        basename = os.path.basename(path) or "attachment"

        mime_type, _ = mimetypes.guess_type(basename)
        if not mime_type:
            # Guess from var_key convention
            if "pdf" in var_key.lower():
                mime_type = "application/pdf"
                if not basename.endswith(".pdf"):
                    basename += ".pdf"
            elif "xls" in var_key.lower():
                mime_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                if not basename.endswith(".xlsx"):
                    basename += ".xlsx"
            else:
                mime_type = "application/octet-stream"

        return basename, mime_type
