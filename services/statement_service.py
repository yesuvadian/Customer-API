import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from services.redis_cache import RedisCacheService as cache


class StatementService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -------------------------------------------------
    # Utility
    # -------------------------------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    def _invalidate_statement_caches(self, contact_id: str):
        # Statements impact balances → dashboard only
        cache.delete(f"zoho:dashboard:{contact_id}")

    # -------------------------------------------------
    # Email Customer Statement
    # -------------------------------------------------
    def email_customer_statement(
        self,
        access_token: str,
        contact_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        email_body: str | None = None
    ):
        contact_id = self._resolve_contact_id(contact_id)

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        body = {
            "body": email_body or "Please find attached your account statement."
        }

        params = {"organization_id": self.org_id}

        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        response = requests.post(
            f"{self.base_url}/contacts/{contact_id}/statements/email",
            headers=headers,
            json=body,
            params=params,
            timeout=15
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to email customer statement",
                    "zoho_response": response.json()
                }
            )

        self._invalidate_statement_caches(contact_id)
        return response.json()

    # -------------------------------------------------
    # Statement Email History
    # -------------------------------------------------
    def get_statement_email_history(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        response = requests.get(
            f"{self.base_url}/contacts/{contact_id}/statements/email",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch statement email history",
                    "zoho_response": response.json()
                }
            )

        return response.json().get("statement_emails", [])

    # -------------------------------------------------
    # Get Statement PDF
    # -------------------------------------------------
    def get_statement_pdf(
        self,
        access_token: str,
        contact_id: str,
        start_date: str | None = None,
        end_date: str | None = None
    ):
        contact_id = self._resolve_contact_id(contact_id)

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Accept": "application/pdf"
        }

        params = {"organization_id": self.org_id}

        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        response = requests.get(
            f"{self.base_url}/contacts/{contact_id}/statements",
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch statement PDF",
                    "zoho_response": (
                        response.json()
                        if "application/json" in response.headers.get("Content-Type", "")
                        else None
                    )
                }
            )

        return response.content  # raw PDF bytes
