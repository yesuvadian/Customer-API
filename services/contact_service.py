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
