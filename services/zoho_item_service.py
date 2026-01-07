from fastapi import HTTPException, status
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
            "filter_by": "Status.Active",  # applied directly
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

        return response.json()


    def get_taxes(self):
        """
        Fetch all taxes configured in Zoho Books.
        Useful for retrieving tax_id values that must be used in quotes/invoices.
        """
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

        return response.json()