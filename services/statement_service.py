import requests
from fastapi import HTTPException, status
import config

class StatementService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID

    # -----------------------------
    # Email Customer Statement
    # -----------------------------
    def email_customer_statement(self, access_token: str, contact_id: str, email_body: str = None):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}
        body = {"body": email_body or "Please find attached your account statement."}

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
    
    def email_customer_statement(self, access_token: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}
        body = {"body": "Please find attached your account statement."}
        response = requests.post(f"{self.base_url}/contacts/{contact_id}/statements/email",
                                headers=headers, json=body,
                                params={"organization_id": self.org_id}, timeout=30)
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail={"message": "Failed to email statement PDF",
                                        "zoho_response": response.json()})
        return response.json()
