# utils/comment_meta_util.py

import re
from typing import Optional, Dict
from services.zoho_contact_service import ZohoContactService

_contact_service = ZohoContactService()

def build_comment_meta(
    *,
    email: Optional[str],
    comment_type_if_found: str = "client",
    comment_type_if_missing: str = "system",
    extra: Optional[Dict[str, str]] = None
) -> str:
    """
    Resolve contact from email (if provided) and build comment metadata.

    - contact_service is created here (global/shared)
    - handles all IF logic
    - reusable across the system
    """

    meta = {}
    contact = None

    # -----------------------------
    # IF email exists → resolve contact
    # -----------------------------
    if email:
        try:
            contact = _contact_service.get_contact_id_by_email(email)
        except Exception:
            contact = None  # fail safe

    # -----------------------------
    # IF contact resolved → build customer meta
    # -----------------------------
    if contact:
        meta["customer_id"] = contact.get("contact_id")
        meta["customer_name"] = contact.get("contact_name")
        meta["customer_email"] = contact.get("email")
        meta["comment_type"] = comment_type_if_found
    else:
        meta["comment_type"] = comment_type_if_missing

    # -----------------------------
    # IF extra metadata provided
    # -----------------------------
    if extra:
        for k, v in extra.items():
            if v is not None:
                meta[k] = str(v)

    # -----------------------------
    # IF nothing to store → return empty
    # -----------------------------
    if not meta:
        return ""

    lines = "\n".join(f"{k}={v}" for k, v in meta.items())
    return f"[CUSTOM_META]\n{lines}\n[/CUSTOM_META]\n\n"
# utils/comment_meta_util.py (same file)




def extract_comment_meta(description: str) -> dict:
    if not description:
        return {}

    match = re.search(r"\[CUSTOM_META\](.*?)\[/CUSTOM_META\]", description, re.S)
    if not match:
        return {}

    lines = match.group(1).strip().split("\n")
    return {
        k.strip(): v.strip()
        for line in lines
        if "=" in line
        for k, v in [line.split("=", 1)]
    }


def strip_comment_meta(description: str) -> str:
    return re.sub(
        r"\[CUSTOM_META\].*?\[/CUSTOM_META\]\s*",
        "",
        description or "",
        flags=re.S
    ).strip()
