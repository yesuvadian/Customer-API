"""
SMTP / SMS integration settings — org-overridable, DB-backed replacement
for the previous .env-only configuration.

Resolution order (same shape as NotificationTemplate's override query):
    org-specific row (organization_id = <org>)  wins over
    platform-default row (organization_id IS NULL)  wins over
    the original .env / config.py values (only if no DB row exists at all —
    covers a fresh install before the platform-default row is seeded).

Secret fields are Fernet-encrypted at rest (utils/crypto.py) and are never
returned to the API layer in plaintext — get_settings_for_ui() returns a
masked placeholder (MASKED_SECRET) for any secret that has a stored value.
upsert_org_settings() treats an incoming field equal to MASKED_SECRET, or
simply absent from the payload, as "leave unchanged" rather than blanking
or re-encrypting it.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import IntegrationSettings
from utils.crypto import encrypt_secret, decrypt_secret

MASKED_SECRET = "••••••••"

_SECRET_FIELDS = (
    "smtp_password",
    "twilio_auth_token",
    "msg91_auth_key",
    "sms_http_auth_value",
)

# UI-facing field -> DB column storing its encrypted value
_SECRET_COLUMN = {
    "smtp_password": "smtp_password_encrypted",
    "twilio_auth_token": "twilio_auth_token_encrypted",
    "msg91_auth_key": "msg91_auth_key_encrypted",
    "sms_http_auth_value": "sms_http_auth_value_encrypted",
}

_PLAIN_FIELDS = (
    "smtp_server", "smtp_port", "smtp_username", "smtp_from_email",
    "sms_provider", "sms_from_number", "twilio_account_sid",
    "msg91_template_id", "msg91_sender_id",
    "sms_http_url", "sms_http_auth_header",
)


def _effective_row(db: Session, org_id: Optional[UUID]) -> Optional[IntegrationSettings]:
    return (
        db.query(IntegrationSettings)
        .filter(
            IntegrationSettings.is_active.is_(True),
            or_(
                IntegrationSettings.organization_id == org_id,
                IntegrationSettings.organization_id.is_(None),
            ),
        )
        .order_by(IntegrationSettings.organization_id.desc().nulls_last())
        .first()
    )


def get_effective_smtp_config(db: Session, org_id: Optional[UUID]) -> dict:
    """Decrypted SMTP config for internal use (EmailService). Falls back to
    .env-derived config.py values field-by-field if no DB row/value exists."""
    from config import SMTP_SERVER, SMTP_PORT, EMAIL_USER, EMAIL_PASS, FROM_EMAIL

    row = _effective_row(db, org_id)
    return {
        "smtp_server": (row.smtp_server if row and row.smtp_server else SMTP_SERVER),
        "smtp_port": (row.smtp_port if row and row.smtp_port else SMTP_PORT),
        "smtp_username": (row.smtp_username if row and row.smtp_username else EMAIL_USER),
        "smtp_password": (decrypt_secret(row.smtp_password_encrypted) if row and row.smtp_password_encrypted else EMAIL_PASS),
        "smtp_from_email": (row.smtp_from_email if row and row.smtp_from_email else FROM_EMAIL),
    }


def get_effective_sms_config(db: Session, org_id: Optional[UUID]) -> dict:
    """Decrypted SMS config for internal use (SmsDispatcher). Falls back to
    .env-derived values field-by-field if no DB row/value exists."""
    import os

    row = _effective_row(db, org_id)

    def _f(col: str, env: str, default: str = "") -> str:
        val = getattr(row, col, None) if row else None
        return val if val else os.getenv(env, default)

    return {
        "provider": _f("sms_provider", "SMS_PROVIDER", "none").lower().strip(),
        "from_number": _f("sms_from_number", "SMS_FROM_NUMBER", ""),
        "twilio_sid": _f("twilio_account_sid", "TWILIO_ACCOUNT_SID", ""),
        "twilio_token": (decrypt_secret(row.twilio_auth_token_encrypted) if row and row.twilio_auth_token_encrypted else os.getenv("TWILIO_AUTH_TOKEN", "")),
        "msg91_key": (decrypt_secret(row.msg91_auth_key_encrypted) if row and row.msg91_auth_key_encrypted else os.getenv("MSG91_AUTH_KEY", "")),
        "msg91_template": _f("msg91_template_id", "MSG91_TEMPLATE_ID", ""),
        "msg91_sender": _f("msg91_sender_id", "MSG91_SENDER_ID", "SEACMS"),
        "http_url": _f("sms_http_url", "SMS_HTTP_URL", ""),
        "http_header": _f("sms_http_auth_header", "SMS_HTTP_AUTH_HEADER", "Authorization"),
        "http_value": (decrypt_secret(row.sms_http_auth_value_encrypted) if row and row.sms_http_auth_value_encrypted else os.getenv("SMS_HTTP_AUTH_VALUE", "")),
    }


def get_settings_for_ui(db: Session, org_id: Optional[UUID]) -> dict:
    """Org-specific row only (not merged with platform default) — the admin
    screen edits this org's own overrides; unset fields display as empty so
    the admin can see exactly what this org has vs. is inheriting. Secret
    fields that have a stored value come back as MASKED_SECRET, never the
    real value."""
    row = (
        db.query(IntegrationSettings)
        .filter(IntegrationSettings.organization_id == org_id)
        .first()
    ) if org_id else (
        db.query(IntegrationSettings)
        .filter(IntegrationSettings.organization_id.is_(None))
        .first()
    )

    out: dict = {f: (getattr(row, f, None) if row else None) for f in _PLAIN_FIELDS}
    for ui_field, col in _SECRET_COLUMN.items():
        has_value = bool(row and getattr(row, col, None))
        out[ui_field] = MASKED_SECRET if has_value else None
    out["has_override"] = row is not None
    out["updated_at"] = row.mts.isoformat() if row and row.mts else None
    return out


def upsert_org_settings(db: Session, org_id: Optional[UUID], data: dict, user_id: Optional[UUID]) -> IntegrationSettings:
    """Create-or-update this org's (or the platform default's, if org_id is
    None) override row. A field absent from `data`, or equal to
    MASKED_SECRET for a secret field, is left unchanged."""
    row = (
        db.query(IntegrationSettings)
        .filter(
            IntegrationSettings.organization_id == org_id
            if org_id else IntegrationSettings.organization_id.is_(None)
        )
        .first()
    )
    if row is None:
        row = IntegrationSettings(organization_id=org_id)
        db.add(row)

    for field in _PLAIN_FIELDS:
        if field in data:
            setattr(row, field, data[field])

    for ui_field, col in _SECRET_COLUMN.items():
        if ui_field in data:
            value = data[ui_field]
            if value == MASKED_SECRET:
                continue  # unchanged sentinel — don't touch the stored ciphertext
            if value in (None, ""):
                setattr(row, col, None)  # explicit clear
            else:
                setattr(row, col, encrypt_secret(value))

    row.updated_by = user_id
    db.flush()
    return row
