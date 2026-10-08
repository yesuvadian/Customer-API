"""
Router: /integration-settings

Admin-configurable SMTP + SMS gateway credentials, org-overridable —
closes the SRS gap "SMTP/SMS credentials are .env-only" (changing a mail
server or SMS provider previously meant editing .env and restarting).

Singleton-per-org GET/PUT/DELETE(reset), same shape as
/threshold-config/failure-cohort-thresholds: every org starts on the
inherited platform default (the one organization_id IS NULL row, seeded
from the existing .env values by alter_integration_settings.py) and only
diverges once an admin here actually changes something. See
services/integration_settings_service.py for the resolution/encryption
details. Menu-level visibility is gated by the "Integration Settings"
module (seed_integration_settings_module.py); this router itself only
requires an authenticated user, same as the other admin-config routers.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from services.integration_settings_service import (
    MASKED_SECRET,
    get_settings_for_ui,
    upsert_org_settings,
)

router = APIRouter(
    prefix="/integration-settings",
    tags=["integration-settings"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class IntegrationSettingsResponse(BaseModel):
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None  # MASKED_SECRET or None, never the real value
    smtp_from_email: Optional[str] = None

    sms_provider: Optional[str] = None
    sms_from_number: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None  # MASKED_SECRET or None
    msg91_auth_key: Optional[str] = None  # MASKED_SECRET or None
    msg91_template_id: Optional[str] = None
    msg91_sender_id: Optional[str] = None
    sms_http_url: Optional[str] = None
    sms_http_auth_header: Optional[str] = None
    sms_http_auth_value: Optional[str] = None  # MASKED_SECRET or None

    has_override: bool
    updated_at: Optional[str] = None


class IntegrationSettingsUpdate(BaseModel):
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: Optional[str] = None

    sms_provider: Optional[str] = None
    sms_from_number: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    msg91_auth_key: Optional[str] = None
    msg91_template_id: Optional[str] = None
    msg91_sender_id: Optional[str] = None
    sms_http_url: Optional[str] = None
    sms_http_auth_header: Optional[str] = None
    sms_http_auth_value: Optional[str] = None


@router.get("", response_model=IntegrationSettingsResponse)
def get_integration_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_settings_for_ui(db, current_user.organization_id)


@router.put("", response_model=IntegrationSettingsResponse)
def update_integration_settings(
    payload: IntegrationSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates this org's own override row on first edit (get-or-create) --
    every org starts on the inherited platform default and only diverges
    once an admin here actually changes something. Any field left out of
    the payload, or a secret field sent back as MASKED_SECRET (i.e.
    untouched by the admin), is left unchanged."""
    data = payload.model_dump(exclude_unset=True)
    upsert_org_settings(db, current_user.organization_id, data, current_user.id)
    db.commit()
    return get_settings_for_ui(db, current_user.organization_id)


@router.delete("", status_code=204)
def reset_integration_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Removes this org's override row so it falls back to the platform
    default again -- a no-op (not a 404) if there was no override."""
    from models import IntegrationSettings
    row = (
        db.query(IntegrationSettings)
        .filter(IntegrationSettings.organization_id == current_user.organization_id)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
