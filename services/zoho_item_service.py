from fastapi import HTTPException, status, Response
import config
from services.zoho_client import zoho_request


class ZohoItemService:

    def get_items(
        self,
        page: int = 1,
        per_page: int = 200,
        search_text: str | None = None,
    ):
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

        # Attach backend image URL for items with attachments
        for item in items:
            if item.get("has_attachment") and item.get("item_id"):
                # This is your own backend route, not Zoho’s direct API
                item["image_url"] = f"/zohoitems/{item['item_id']}/image"

        # ✅ Wrap in dict so client sees { "items": [...] }
        return {"items": items}

    def get_item_image(self, item_id: str):
        """Proxy Zoho item image so frontend doesn’t need Zoho auth."""
        #zoho_url = f"{config.ZOHO_API_BASE}/{item_id}/image"
      
        params = {"organization_id": config.ZOHO_ORG_ID}

        resp = zoho_request(
            method="GET",
            path=f"/items/{item_id}/image",
            params=params
           # headers=headers
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

    def get_taxes(self):
        """
        Fetch all taxes configured in Zoho Books.
        Useful for retrieving tax_id values that must be used in quotes/invoices.
        """
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

        return response.json()