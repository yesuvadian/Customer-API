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

    def is_email_exists(self, access_token: str, email: str) -> bool:
        """Checks Zoho for an existing contact by email."""
        params = {
            "organization_id": self.org_id,
            "email": email
        }
        response = requests.get(
            f"{self.base_url}/contacts",
            headers=self._get_headers(access_token),
            params=params,
            timeout=15
        )
        if response.status_code == 200:
            contacts = response.json().get("contacts", [])
            return len(contacts) > 0
        return False

    def is_Mobile_exists(self, access_token: str, mobile: str) -> bool:
        """Checks Zoho for an existing contact by mobile number."""
        # Try searching using 'phone' as Zoho often maps mobile to this search key
        params = {
            "organization_id": self.org_id,
            "phone": mobile  
        }
        response = requests.get(
            f"{self.base_url}/contacts",
            headers=self._get_headers(access_token),
            params=params,
            timeout=15
        )
        if response.status_code == 200:
            contacts = response.json().get("contacts", [])
            return len(contacts) > 0
        return False
    def create_contact(self, access_token: str, payload):
        # 1. Validation Logic
        if self.is_email_exists(access_token, payload.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contact with this email already exists in Zoho"
            )
        if self.is_Mobile_exists(access_token, payload.mobile):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contact with this mobile number already exists in Zoho"
            )

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
