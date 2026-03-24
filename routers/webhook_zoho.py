from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from services.websocket_service import send_to_user
import os, json, hmac, hashlib

from services.redis_cache import RedisCacheService as cache
from services.zoho_cache_map import ZOHO_MODULE_CACHE_KEYS
from services.zoho_contact_service import ZohoContactService

contact_service = ZohoContactService()

router = APIRouter()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET")


# -------------------------------------------------
# 🔐 Verify Zoho Signature
# -------------------------------------------------
def verify_zoho_signature(raw_body: bytes, signature: str) -> bool:
    calculated = hmac.new(
        ZOHO_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(calculated, signature)

def get_zoho_erp_id(zoho_contact_id: str):
    try:
        contact = contact_service.get_contact_by_id(zoho_contact_id)
        return contact.get("zoho_erp_id")
    except Exception as e:
        print(" Failed to get zoho_erp_id:", e)
        return None
    

# -------------------------------------------------
# 🚀 Webhook Endpoint
# -------------------------------------------------
@router.post("/webhooks/zoho/{module}", response_class=JSONResponse)
async def zoho_webhook(module: str, request: Request):
    module = module.lower()
    headers = request.headers
    raw_body = await request.body()

    print("🚀 ZOHO WEBHOOK HIT:", module)
    print("Content-Type:", headers.get("content-type"))
    print("RAW BODY:", raw_body[:500])

    # -------------------------------------------------
    # 1. Zoho validation ping
    # -------------------------------------------------
    if headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        print("ℹ️ Zoho validation ping received")
        return {"status": "ok"}

    # -------------------------------------------------
    # 2. Verify signature
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

    # 👉 NEW: extract event type
    event_type = payload.get("event_type", "")

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

    zoho_contact_id = (
        root_obj.get("customer_id")
        or root_obj.get("contact_id")
    )

    if not zoho_contact_id:
        print("⚠️ contact_id missing")
        return {"status": "ignored"}

    try:
        contact = contact_service.get_contact_by_id(zoho_contact_id)
        email = contact.get("email")
        zoho_erp_id = contact.get("zoho_erp_id")

        # ✅ unified key
        user_key = zoho_erp_id or email

        if not user_key:
            print("⚠️ No valid user identifier")
            return {"status": "ignored"}

        if not zoho_erp_id:
            print("⚠️ zoho_erp_id missing")
        else:
            print("✅ ERP ID:", zoho_erp_id)

    except Exception as e:
        print("❌ Failed to resolve contact email:", e)
        return {"status": "ignored"}

    # -------------------------------------------------
    # 🔔 7. Notification Logic (NEW)
    # -------------------------------------------------
    if module == "quotes":
        estimate_id = root_obj.get("estimate_id")

        if event_type == "estimate.created":
            print(f"🟢 New Quote Created: {estimate_id}")

            notification = {
                "type": "quote_created",
                "estimate_id": estimate_id,
                "message": f"New quote {estimate_id} created"
            }

            # ✅ store in Redis
            cache_key = f"notifications:{user_key}"
            existing = cache.get(cache_key) or []

            if not isinstance(existing, list):
                existing = []

            existing.append(notification)
            cache.set(cache_key, existing)

            # 🚀 NEW: send real-time via WebSocket
            await send_to_user(user_key, notification)

    # -------------------------------------------------
    # 8. Invalidate cache
    # -------------------------------------------------
    for ns in cache_namespaces:
        key = f"zoho:{ns}:{user_key}"
        cache.delete(key)
        deleted_keys.append(key)

    print("✅ Cache invalidated:", deleted_keys)

    return {
        "code": 0,
        "message": "cache invalidated",
        "module": module,
        "contact_id": user_key,
        "event_type": event_type,
        "keys": deleted_keys,
    }