from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os, json, hmac, hashlib

from services.redis_cache import RedisCacheService as cache
from services.zoho_cache_map import ZOHO_MODULE_CACHE_KEYS

router = APIRouter()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET")


def verify_zoho_signature(raw_body: bytes, signature: str) -> bool:
    calculated = hmac.new(
        ZOHO_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(calculated, signature)


@router.post("/webhooks/zoho/{module}", response_class=JSONResponse)
async def zoho_webhook(module: str, request: Request):
    module = module.lower()
    headers = request.headers
    raw_body = await request.body()

    print("🚀 ZOHO WEBHOOK HIT:", module)
    print("Content-Type:", headers.get("content-type"))
    print("RAW BODY:", raw_body[:500])  # limit log size

    # -------------------------------------------------
    # 1. Handle Zoho ping / validation calls
    # -------------------------------------------------
    if headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        print("ℹ️ Zoho validation ping received")
        return {"status": "ok"}

    # -------------------------------------------------
    # 2. Verify signature (OFFICIAL & CORRECT)
    # -------------------------------------------------
    signature = headers.get("x-zoho-webhook-signature")
    if not signature:
        print("⚠️ Missing Zoho signature")
        return {"status": "ignored"}

    if not verify_zoho_signature(raw_body, signature):
        print("❌ Zoho webhook signature mismatch")
        return {"status": "ignored"}

    # -------------------------------------------------
    # 3. Parse JSON
    # -------------------------------------------------
    try:
        payload = json.loads(raw_body.decode())
    except Exception:
        print("⚠️ Invalid JSON payload")
        return {"status": "ignored"}

    # -------------------------------------------------
    # 4. Resolve cache namespaces
    # -------------------------------------------------
    cache_namespaces = ZOHO_MODULE_CACHE_KEYS.get(module)
    if not cache_namespaces:
        return {"status": "ignored"}

    deleted_keys = []

    # -------------------------------------------------
    # 5. Global modules
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
            "keys": deleted_keys,
        }

    # -------------------------------------------------
    # 6. Resolve contact_id
    # -------------------------------------------------
    ROOT_KEYS = {
        "quotes": "estimate",
        "invoices": "invoice",
        "salesorders": "salesorder",
        "payments": "payment",
    }

    root_key = ROOT_KEYS.get(module)
    root_obj = payload.get(root_key, {})

    contact_id = (
        root_obj.get("customer_id")
        or root_obj.get("contact_id")
    )

    if not contact_id:
        print("⚠️ contact_id missing")
        return {"status": "ignored"}

    # -------------------------------------------------
    # 7. Invalidate cache
    # -------------------------------------------------
    for ns in cache_namespaces:
        key = f"zoho:{ns}:{contact_id}"
        cache.delete(key)
        deleted_keys.append(key)

    print("✅ Cache invalidated:", deleted_keys)

    return {
        "code": 0,
        "message": "cache invalidated",
        "module": module,
        "contact_id": contact_id,
        "keys": deleted_keys,
    }
