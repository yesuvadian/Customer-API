from fastapi import HTTPException, status
import config
from services.zoho_client import zoho_request
from services.redis_cache import RedisCacheService as cache


class ZohoItemService:

    # -----------------------------
    # Get Items (CACHED)
    # -----------------------------
    def get_items(
        self,
        page: int = 1,
        per_page: int = 200,
        search_text: str | None = None,
    ):
        search_key = search_text or "all"
        cache_key = f"zoho:items:{page}:{per_page}:{search_key}"

        # 🔹 1. Try cache
        cached = cache.get(cache_key)
        if cached:
            return cached

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
                    "message": "Failed to fetch items from Zoho Books",
                    "zoho_response": response.json()
                }
            )

        data = response.json()

        # 🔹 2. Store in cache (no TTL)
        cache.set(cache_key, data)

        return data

    # -----------------------------
    # Get Taxes (CACHED)
    # -----------------------------
    def get_taxes(self):
        cache_key = "zoho:taxes"

        # 🔹 1. Try cache
        cached = cache.get(cache_key)
        if cached:
            return cached

        params = {
            "organization_id": config.ZOHO_ORG_ID
        }

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
