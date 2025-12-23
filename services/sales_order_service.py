import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta

class SalesOrderService:
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
    # Create Draft Sales Order
    # -----------------------------
    def create_draft_order(self, access_token: str, payload):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}
        contact_id = self._resolve_contact_id(payload.contact_id)

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
                    detail={"message": f"Failed to fetch item {item.item_id}", "zoho_response": item_response.json()}
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
            "notes": payload.notes or "Sales order requested from customer portal"
        }

        response = requests.post(
            f"{self.base_url}/salesorders",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create draft sales order", "zoho_response": response.json()}
            )

        return response.json()["salesorder"]

    # -----------------------------
    # List Sales Orders for Customer
    # -----------------------------
    def list_orders_for_customer(self, access_token: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/salesorders",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch sales orders", "zoho_response": response.json()}
            )

        return response.json().get("salesorders", [])

    # -----------------------------
    # Get Sales Order Details
    # -----------------------------
    def get_order(self, access_token: str, salesorder_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch sales order {salesorder_id}",
                    "zoho_response": response.json()
                }
            )

        return response.json().get("salesorder", {})

    # -----------------------------
    # ERP Review Sales Order
    # -----------------------------
    def review_order(self, access_token: str, salesorder_id: str, payload, reviewer_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Reviewed by ERP user {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to review sales order",
                    "zoho_response": response.json()
                }
            )

        return response.json().get("salesorder", {})

    # -----------------------------
    # Customer Approval Sales Order
    # -----------------------------
    def customer_approve_order(self, access_token: str, salesorder_id: str, payload, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Response from customer {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to update sales order status",
                    "zoho_response": response.json()
                }
            )

        return response.json().get("salesorder", {})

    # -----------------------------
    # Get Comments
    # -----------------------------
    def get_comments(self, access_token: str, salesorder_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/comments",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch comments",
                    "zoho_response": response.json()
                }
            )

        comments = response.json().get("comments", [])
        result = []

        for c in comments:
            meta = extract_comment_meta(c.get("description", ""))

            result.append({
                "comment_id": c.get("comment_id", ""),
                "salesorder_id": salesorder_id,
                "description": strip_comment_meta(c.get("description", "")),
                "commented_by": meta.get("customer_name", c.get("commented_by", "")),
                "commented_by_id": meta.get("customer_id", c.get("commented_by_id", "")),
                "comment_type": meta.get("comment_type", c.get("comment_type", "")),
                "date": c.get("date", ""),
                "date_description": c.get("date_description", ""),
                "time": c.get("time", ""),
                "comments_html_format": c.get("comments_html_format", "")
            })

        return result


    # -----------------------------
    # Add Comment (POST)
    # -----------------------------
    def add_comment(
    self,
    access_token: str,
    salesorder_id: str,
    description: str,
    email: str | None = None,
    show_to_client: bool = True
):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # Centralized meta handling
        meta_block = build_comment_meta(email=email)

        body = {
            "description": meta_block + description,
            "show_comment_to_clients": show_to_client
        }

        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/comments",
            headers=headers,
            json=body,
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
    # Update Comment (PUT)
    # -----------------------------
    def update_comment(self, access_token: str, salesorder_id: str, comment_id: str, description: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}

        body = {"description": description}

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}/comments/{comment_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to update comment", "zoho_response": response.json()}
            )

        return response.json()

    # -----------------------------
    # Delete Comment (DELETE)
    # -----------------------------
    def delete_comment(self, access_token: str, salesorder_id: str, comment_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.delete(
            f"{self.base_url}/salesorders/{salesorder_id}/comments/{comment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to delete comment",
                    "zoho_response": response.json()
                }
            )

        return {"message": "Comment deleted"}
    def get_order_pdf(self, access_token: str, salesorder_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        params = {
            "organization_id": self.org_id,
            "print": "true",
            "accept": "pdf"
        }

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch PDF for sales order {salesorder_id}",
                    "zoho_response": response.json()
                    if "application/json" in response.headers.get("Content-Type", "")
                    else None
                }
            )

        return response.content
