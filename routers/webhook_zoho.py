from fastapi import APIRouter, Request, HTTPException
import os
from services.redis_cache import RedisCacheService as cache
from services.zoho_cache_map import ZOHO_MODULE_CACHE_KEYS

router = APIRouter()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET")


@router.post("/webhooks/zoho/{module}")
async def zoho_webhook(module: str, request: Request):
    # -------------------------------------------------
    # 1. Verify webhook secret
    # -------------------------------------------------
    secret = request.headers.get("X-Zoho-Webhook-Secret")
    if not secret or secret != ZOHO_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload = await request.json()

    # -------------------------------------------------
    # 2. Extract contact_id safely
    # -------------------------------------------------
    contact_id = (
        payload.get("customer_id")
        or payload.get("contact_id")
        or payload.get("customer", {}).get("customer_id")
        or payload.get("contact", {}).get("contact_id")
    )

    if not contact_id:
        return {"status": "ignored", "reason": "contact_id missing"}

    module = module.lower()

    # -------------------------------------------------
    # 3. Resolve cache namespaces
    # -------------------------------------------------
    cache_namespaces = ZOHO_MODULE_CACHE_KEYS.get(
        module,
        ["dashboard"]  # fallback safety
    )

    deleted_keys = []

    for namespace in cache_namespaces:
        key = f"zoho:{namespace}:{contact_id}"
        cache.delete(key)
        deleted_keys.append(key)

    return {
        "status": "cache_invalidated",
        "module": module,
        "contact_id": contact_id,
        "keys": deleted_keys
    }
