from fastapi import APIRouter, Request, HTTPException
import os
from services.redis_cache import RedisCacheService as cache
from services.zoho_cache_map import ZOHO_MODULE_CACHE_KEYS

router = APIRouter()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET")


@router.post("/webhooks/zoho/{module}")
async def zoho_webhook(module: str, request: Request):
    # -------------------------------------------------
    # 1. Validate Zoho secret token
    # -------------------------------------------------
    secret = request.headers.get("X-Zoho-Webhook-Secret")
    if not secret or secret != ZOHO_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid Zoho webhook secret")

    payload = await request.json()
    module = module.lower()

    # -------------------------------------------------
    # 2. Resolve cache namespaces
    # -------------------------------------------------
    cache_namespaces = ZOHO_MODULE_CACHE_KEYS.get(module)
    if not cache_namespaces:
        return {"status": "ignored", "reason": "unknown module"}

    deleted_keys = []

    # -------------------------------------------------
    # 3. GLOBAL modules (items / taxes)
    # -------------------------------------------------
    if module in ("items", "item", "taxes"):
        for ns in cache_namespaces:
            if ns == "items":
                cache.delete_pattern("zoho:items:*")
                deleted_keys.append("zoho:items:*")
            elif ns == "taxes":
                cache.delete("zoho:taxes")
                deleted_keys.append("zoho:taxes")

        return {
            "code": 0,
            "message": "global cache invalidated",
            "module": module,
            "keys": deleted_keys
        }

    # -------------------------------------------------
    # 4. CUSTOMER-scoped modules
    # -------------------------------------------------
    contact_id = (
        payload.get("customer_id")
        or payload.get("contact_id")
        or payload.get("customer", {}).get("customer_id")
        or payload.get("contact", {}).get("contact_id")
    )

    if not contact_id:
        return {"status": "ignored", "reason": "contact_id missing"}

    for ns in cache_namespaces:
        key = f"zoho:{ns}:{contact_id}"
        cache.delete(key)
        deleted_keys.append(key)

    return {
        "code": 0,
        "message": "cache invalidated",
        "module": module,
        "contact_id": contact_id,
        "keys": deleted_keys
    }
