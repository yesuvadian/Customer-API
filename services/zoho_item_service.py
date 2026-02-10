from fastapi import HTTPException, status, Response
import config
from services.zoho_client import zoho_request
from services.redis_cache import RedisCacheService as cache
from services.divisionservice import DivisionService
from database import SessionLocal


class ZohoItemService:

    # -----------------------------
    # Get Items (CACHED + DIVISION-AWARE)
    # -----------------------------
    def get_items(
        self,
        page: int = 1,
        per_page: int = 200,
        search_text: str | None = None,
        division: str | None = None,   # 👈 OPTIONAL FILTER
    ):
        search_key = search_text or "all"
        division_key = division or "all"

        cache_key = f"zoho:items:{page}:{per_page}:{search_key}:{division_key}"

        # 🔹 1. Try cache
        cached = cache.get(cache_key)
        if cached:
            return cached

        # 🔹 2. Fetch valid divisions from DB
        db = SessionLocal()
        try:
            division_service = DivisionService(db)
            valid_divisions = {
                d.division_name
                for d in division_service.list_divisions()
                if d.is_active
            }
        finally:
            db.close()

        params = {
            "organization_id": config.ZOHO_ORG_ID,
            "page": page,
            "per_page": per_page,
            "filter_by": "Status.Active",
        }

        if search_text:
            params["search_text"] = search_text

        response = zoho_request(
            method="GET",
            path="/items",
            params=params
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch items from Zoho Inventory",
                    "zoho_response": response.json()
                }
            )

        items = response.json().get("items", [])

        enriched_items = []

        for item in items:
            # -----------------------------
            # Attach backend image URL
            # -----------------------------
            if item.get("has_attachment") and item.get("item_id"):
                item["image_url"] = f"/zohoitems/{item['item_id']}/image"

            # -----------------------------
            # Division normalization (DB-backed)
            # -----------------------------
            zoho_division = item.get("cf_division")

            if zoho_division in valid_divisions:
                item["division"] = zoho_division
            else:
                item["division"] = None  # invalid or missing division

            # -----------------------------
            # Optional division filter
            # -----------------------------
            if division and item["division"] != division:
                continue

            enriched_items.append(item)

        result = {"items": enriched_items}

        # 🔹 3. Store in cache (no TTL)
        cache.set(cache_key, result)

        return result

    # -----------------------------
    # Item Image Proxy
    # -----------------------------
    def get_item_image(self, item_id: str):
        """Proxy Zoho item image so frontend doesn’t need Zoho auth."""

        params = {"organization_id": config.ZOHO_ORG_ID}

        resp = zoho_request(
            method="GET",
            path=f"/items/{item_id}/image",
            params=params
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail={
                    "message": "Failed to fetch image from Zoho",
                    "zoho_response": resp.json()
                }
            )

        return Response(content=resp.content, media_type="image/jpeg")

    # -----------------------------
    # Get Taxes (CACHED)
    # -----------------------------
    def get_taxes(self):
        cache_key = "zoho:taxes"

        # 🔹 1. Try cache
        cached = cache.get(cache_key)
        if cached:
            return cached

        params = {"organization_id": config.ZOHO_ORG_ID}

        response = zoho_request(
            method="GET",
            path="/settings/taxes",
            params=params
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch taxes from Zoho Books",
                    "zoho_response": response.json()
                }
            )

        data = response.json()

        # 🔹 2. Store in cache
        cache.set(cache_key, data)

        return data
