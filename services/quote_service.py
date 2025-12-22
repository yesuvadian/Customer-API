import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService

class QuoteService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -----------------------------
    # Utility: resolve contact_id
    # -----------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:  # treat as email
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -----------------------------
    # Create Draft Quote
    # -----------------------------
    def create_draft_quote(self, access_token: str, payload):
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
            "notes": payload.notes or "Quote requested from customer portal"
        }

        response = requests.post(
            f"{self.base_url}/estimates",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create draft quote",
                    "zoho_response": response.json()
                }
            )

        return response.json()["estimate"]

    # -----------------------------
    # List Quotes for Customer
    # -----------------------------
    def list_quotes_for_customer(self, access_token: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/estimates",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch quotes", "zoho_response": response.json()}
            )
        estimates = response.json().get("estimates", {})

         # ❌ EXCLUDE draft quotes
        quotes = [
            q for q in estimates 
            if q.get("status", "").lower() != "draft"
        ]

        return quotes

    # -----------------------------
    # Get Quote Details
    # -----------------------------
    def get_quote(self, access_token: str, estimate_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Failed to fetch quote {estimate_id}", "zoho_response": response.json()}
            )

        estimate = response.json().get("estimate", {})

        

        return estimate


    # -----------------------------
    # ERP Review Quote
    # -----------------------------
    def review_quote(self, access_token: str, estimate_id: str, payload, reviewer_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Reviewed by ERP user {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to review quote", "zoho_response": response.json()}
            )
        return response.json().get("estimate", {})

    # -----------------------------
    # Customer Approval
    # -----------------------------
    def customer_approve_quote(self, access_token: str, estimate_id: str, payload, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Response from customer {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to update quote status", "zoho_response": response.json()}
            )
        return response.json().get("estimate", {})
    
    def update_quote_status(self, access_token: str, estimate_id: str, action: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/status/{action}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        data = response.json()

        if response.status_code != 200 or data.get("code") != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to mark quote as {action}",
                    "zoho_response": data
                }
            )

        return {
            "message": data.get("message", "Status updated"),
            "estimate_number": data.get("estimate", {}).get("estimate_number", ""),
            "estimate_id": estimate_id,
            "status": action
        }

    def get_quote_pdf(self, access_token: str, estimate_id: str):
            headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
            params = {
                "organization_id": self.org_id,
                "print": "true",
                "accept": "pdf"
            }

            response = requests.get(
                f"{self.base_url}/estimates/{estimate_id}",
                headers=headers,
                params=params,
                timeout=30
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": f"Failed to fetch PDF for estimate {estimate_id}",
                        "zoho_response": response.json() if "application/json" in response.headers.get("Content-Type","") else None
                    }
                )

            return response.content  # raw PDF bytes
    # -----------------------------
    # Add Comment
    # -----------------------------
    def add_comment(self, access_token: str, estimate_id: str, description: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        payload = {"description": description}

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=headers,
            json=payload,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to add comment",
                    "zoho_response": response.json()
                }
            )

        return response.json()
    # -----------------------------
    # Update Comment
    # -----------------------------
    def update_comment(self, access_token: str, estimate_id: str, comment_id: str, description: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        payload = {"description": description}

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
            headers=headers,
            json=payload,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to update comment {comment_id}",
                    "zoho_response": response.json()
                }
            )

        return response.json()
    # -----------------------------
    # Delete Comment
    # -----------------------------
    def delete_comment(self, access_token: str, estimate_id: str, comment_id: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.delete(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to delete comment {comment_id}",
                    "zoho_response": response.json()
                }
            )

        return {"message": "Comment deleted successfully"}
    # -----------------------------
    # List Comments
    # -----------------------------
    def get_comments(self, access_token: str, estimate_id: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch comments for estimate {estimate_id}",
                    "zoho_response": response.json()
                }
            )

        return response.json().get("comments", [])
