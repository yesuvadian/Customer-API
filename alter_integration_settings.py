#!/usr/bin/env python3
"""
One-time setup: create integration_settings and seed the platform-default
row (organization_id=NULL) from the current .env values, so existing
behavior is unchanged until an org explicitly overrides it via the
Organisation -> Integration Settings screen.

Same "org can override, default always exists" pattern as
NotificationTemplate / FailureCohortThresholdConfig --
get_effective_smtp_config()/get_effective_sms_config()
(services/integration_settings_service.py) look up an org-specific row
first, then this NULL default row, then the raw .env values as a last
resort (covers a fresh install before this script has ever run).

Secrets (SMTP password, Twilio auth token, MSG91 auth key, generic HTTP
auth value) are encrypted before being stored -- see utils/crypto.py.
Requires INTEGRATION_SECRET_KEY to be set in .env; generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Re-running this script is safe: it only inserts the default row if one
doesn't already exist, so an admin's already-edited value is never
overwritten.

Usage:
    python alter_integration_settings.py
"""
import os

from database import VendorSessionLocal
from models import Base, IntegrationSettings
from utils.crypto import encrypt_secret
import config as _config


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[IntegrationSettings.__table__],
    )
    print("Ensured integration_settings table exists.")

    db = VendorSessionLocal()
    try:
        existing = (
            db.query(IntegrationSettings)
            .filter(IntegrationSettings.organization_id.is_(None))
            .first()
        )
        if existing:
            print(
                f"Platform-default row already exists (smtp_server={existing.smtp_server}, "
                f"sms_provider={existing.sms_provider}) -- left untouched."
            )
            return

        db.add(IntegrationSettings(
            organization_id=None,
            smtp_server=_config.SMTP_SERVER,
            smtp_port=_config.SMTP_PORT,
            smtp_username=_config.EMAIL_USER,
            smtp_password_encrypted=encrypt_secret(_config.EMAIL_PASS),
            smtp_from_email=_config.FROM_EMAIL,
            sms_provider=os.getenv("SMS_PROVIDER", "none"),
            sms_from_number=os.getenv("SMS_FROM_NUMBER", ""),
            twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token_encrypted=encrypt_secret(os.getenv("TWILIO_AUTH_TOKEN")),
            msg91_auth_key_encrypted=encrypt_secret(os.getenv("MSG91_AUTH_KEY")),
            msg91_template_id=os.getenv("MSG91_TEMPLATE_ID", ""),
            msg91_sender_id=os.getenv("MSG91_SENDER_ID", "SEACMS"),
            sms_http_url=os.getenv("SMS_HTTP_URL", ""),
            sms_http_auth_header=os.getenv("SMS_HTTP_AUTH_HEADER", "Authorization"),
            sms_http_auth_value_encrypted=encrypt_secret(os.getenv("SMS_HTTP_AUTH_VALUE")),
        ))
        db.commit()
        print(
            f"Seeded platform-default row from .env: smtp_server={_config.SMTP_SERVER}, "
            f"sms_provider={os.getenv('SMS_PROVIDER', 'none')}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
