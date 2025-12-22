import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService


class RetainerInvoiceService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -----------------------------
    # Utility: resolve contact_id from email
    # -----------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:  # treat as email
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -----------------------------
    # Create Retainer Invoice
    # -----------------------------
    def create_retainer_invoice(self, access_token: str, payload):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }
        contact_id = self._resolve_contact_id(payload.contact_id)

        # Build line items
        line_items = []
        for item in payload.items:
            item_response = requests.get(
                f"{self.base_url}/items/{item.item_id}",
                headers=headers,
                params={"organization_id": self.org_id},
                timeout=15
            )
            if item_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": f"Failed to fetch item {item.item_id}",
                        "zoho_response": item_response.json()
                    }
                )
            item_data = item_response.json().get("item", {})
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
                "tax_id": "",
                "tax_exemption_code": "NON"
            })

        body = {
            "customer_id": contact_id,
            "line_items": line_items,
            "notes": payload.notes or "Retainer invoice created from customer portal"
        }

        response = requests.post(
            f"{self.base_url}/retainerinvoices",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15
        )
        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create retainer invoice",
                    "zoho_response": response.json()
                }
            )
        return response.json()["retainer_invoice"]

    # -----------------------------
    # List Retainer Invoices for Customer
    # -----------------------------
    def list_retainer_invoices_for_customer(self, access_token: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/retainerinvoices",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch retainer invoices",
                    "zoho_response": response.json()
                }
            )
        return response.json().get("retainer_invoices", [])

    # -----------------------------
    # Get Retainer Invoice Details
    # -----------------------------
    def get_retainer_invoice(self, access_token: str, retainerinvoice_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch retainer invoice {retainerinvoice_id}",
                    "zoho_response": response.json()
                }
            )
        return response.json().get("retainer_invoice", {})

    # -----------------------------
    # ERP Review Retainer Invoice
    # -----------------------------
    def review_retainer_invoice(self, access_token: str, retainerinvoice_id: str, payload, reviewer_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Reviewed by ERP user {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to review retainer invoice",
                    "zoho_response": response.json()
                }
            )
        return response.json().get("retainer_invoice", {})

    # -----------------------------
    # Customer Approval Retainer Invoice
    # -----------------------------
    def customer_approve_retainer_invoice(self, access_token: str, retainerinvoice_id: str, payload, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Response from customer {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to update retainer invoice status",
                    "zoho_response": response.json()
                }
            )
        return response.json().get("retainer_invoice", {})
    
    def get_retainer_invoice_pdf(self, access_token: str, retainerinvoice_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        params = {"organization_id": self.org_id, "print": "true", "accept": "pdf"}
        response = requests.get(f"{self.base_url}/retainerinvoices/{retainerinvoice_id}",
                                headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail={"message": "Failed to fetch retainer invoice PDF",
                                        "zoho_response": response.json()})
        return response.content
