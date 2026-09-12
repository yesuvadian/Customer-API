"""
Exposes a small set of SAFE, non-secret runtime settings to the frontend so
values like MAX_UPLOAD_MB don't have to be hand-duplicated into web/config.json
and assets/env/.env and kept in sync by hand.

No authentication required (registered in AUTH_PUBLIC_ENDPOINTS) — the UI
fetches this at startup, before login, so a missing/invalid token must never
401 here. A valid token IS still resolved onto request.state.user if one is
present, so this could be personalized for a logged-in caller later without
another middleware change. Only add settings here that are safe to expose to
an unauthenticated caller; this is not the place for secrets, connection
strings, or anything from the SECURITY & AUTHENTICATION / EMAIL / SMS blocks
of .env.
"""
import os

from fastapi import APIRouter

from config import MAX_DOCUMENT_UPLOAD_MB, ALLOWED_UPLOAD_TYPES

router = APIRouter(tags=["Public Config"])


@router.get("/public-config")
def get_public_config():
    return {
        "max_upload_mb": int(os.getenv("MAX_UPLOAD_MB", 5)),
        "max_document_upload_mb": MAX_DOCUMENT_UPLOAD_MB,
        "allowed_upload_types": {
            category: sorted({ext for exts in mime_map.values() for ext in exts})
            for category, mime_map in ALLOWED_UPLOAD_TYPES.items()
        },
    }
