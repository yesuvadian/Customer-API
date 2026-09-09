"""
Exposes a small set of SAFE, non-secret runtime settings to the frontend so
values like MAX_UPLOAD_MB don't have to be hand-duplicated into web/config.json
and assets/env/.env and kept in sync by hand.

No authentication required (registered in PUBLIC_ENDPOINTS) — the UI fetches
this at startup, before login. Only add settings here that are safe to expose
to an unauthenticated caller; this is not the place for secrets, connection
strings, or anything from the SECURITY & AUTHENTICATION / EMAIL / SMS blocks
of .env.
"""
import os

from fastapi import APIRouter

router = APIRouter(tags=["Public Config"])


@router.get("/public-config")
def get_public_config():
    return {
        "max_upload_mb": int(os.getenv("MAX_UPLOAD_MB", 5)),
    }
