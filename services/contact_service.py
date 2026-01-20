import requests
from fastapi import HTTPException, status
import config
from zohoschemas import ContactPerson

class ContactService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID

    def _get_headers(self, access_token: str):
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }
    def get_all_customers(self, access_token: str):
        all_contacts = []
        page = 1

        while True:
            data = self.fetch_customers(access_token, page=page)
            all_contacts.extend(data.get("contacts", []))

            page_context = data.get("page_context", {})
            if not page_context.get("has_more_page"):
                break

            page += 1

        return all_contacts

    def fetch_customers(self, access_token: str, page: int = 1, per_page: int = 200):
        response = requests.get(
            f"{self.base_url}/contacts",
            headers=self._get_headers(access_token),
            params={
                "organization_id": self.org_id,
                "contact_type": "customer",
                "page": page,
                "per_page": per_page
            },
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch Zoho customers",
                    "zoho_response": response.json()
                }
            )

        return response.json()
   
    def create_contact(self, access_token: str, payload):
        # 1. Validation Logic
     
            

        # 2. API Request
        response = requests.post(
            f"{self.base_url}/contacts",
            headers=self._get_headers(access_token),
            json=payload.dict(),
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create contact", "zoho_response": response.json()}
            )

        return response.json()["contact"]
