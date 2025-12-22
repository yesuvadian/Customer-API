import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService

class StatementService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:  # treat as email
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -----------------------------
    # Email Customer Statement
    # -----------------------------
    def email_customer_statement(self, access_token: str, contact_id: str, email_body: str = None):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}
        body = {"body": email_body or "Please find attached your account statement."}
        contact_id = self._resolve_contact_id(contact_id)
        response = requests.post(
            f"{self.base_url}/contacts/{contact_id}/statements/email",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to email customer statement", "zoho_response": response.json()}
            )
        return response.json()

    # -----------------------------
    # Get Statement Email History
    # -----------------------------
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
                detail={"message": "Failed to fetch statement email history", "zoho_response": response.json()}
            )
        return response.json().get("statement_emails", [])
    
    def email_customer_statement(
    self,
    access_token: str,
    contact_id: str,
    #organization_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    email_body: str | None = None
):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        body = {
            "body": email_body or "Please find attached your account statement."
        }

        params = {"organization_id": self.org_id}

        # Add date window only if provided
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

        return response.json()

    def get_statement_pdf(
        self,
        access_token: str,
        contact_id: str,
        #organization_id: str,
        start_date: str | None = None,
        end_date: str | None = None
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Accept": "application/pdf"
        }
        contact_id = self._resolve_contact_id(contact_id)
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
            raise Exception(response.json())

        return response.content  # <-- binary PDF
