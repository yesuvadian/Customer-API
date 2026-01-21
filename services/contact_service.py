import requests
from fastapi import HTTPException, status
import config


class ContactService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID

    # -------------------------------------------------
    # Headers
    # -------------------------------------------------
    def _get_headers(self, access_token: str) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    # -------------------------------------------------
    # Fetch ALL active customer contacts (paginated)
    # -------------------------------------------------
    def get_all_customers(self, access_token: str) -> list[dict]:
        all_contacts: list[dict] = []
        page = 1

        while True:
            data = self.fetch_customers(access_token, page=page)
            contacts = data.get("contacts", [])

            # ✅ Defensive filter: only ACTIVE customers
            for contact in contacts:
                if contact.get("status") == "active":
                    all_contacts.append(contact)

            page_context = data.get("page_context", {})
            if not page_context.get("has_more_page"):
                break

            page += 1

        return all_contacts

    # -------------------------------------------------
    # Fetch customer contacts (single page)
    # -------------------------------------------------
    def fetch_customers(
        self,
        access_token: str,
        page: int = 1,
        per_page: int = 200,
    ) -> dict:
        response = requests.get(
            f"{self.base_url}/contacts",
            headers=self._get_headers(access_token),
            params={
                "organization_id": self.org_id,
                "contact_type": "customer",
                "page": page,
                "per_page": per_page,
            },
            timeout=15,
        )

        if response.status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch Zoho customers",
                    "zoho_response": response.json(),
                },
            )

        return response.json()

    # -------------------------------------------------
    # Create contact in Zoho
    # -------------------------------------------------
    def create_contact(self, access_token: str, payload):
        response = requests.post(
            f"{self.base_url}/contacts",
            headers=self._get_headers(access_token),
            params={"organization_id": self.org_id},
            json=payload.dict(),
            timeout=15,
        )

        if response.status_code != status.HTTP_201_CREATED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create contact",
                    "zoho_response": response.json(),
                },
            )

        return response.json()["contact"]
