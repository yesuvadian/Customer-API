import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache


class SalesOrderService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -------------------------------------------------
    # Cache helpers
    # -------------------------------------------------
    def _invalidate_salesorder_caches(
        self,
        contact_id: str | None = None,
        salesorder_id: str | None = None
    ):
        if contact_id:
            cache.delete(f"zoho:salesorders:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")

        if salesorder_id:
            cache.delete(f"zoho:salesorder:{salesorder_id}")

    # -------------------------------------------------
    # Utility
    # -------------------------------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -------------------------------------------------
    # Create Draft Sales Order
    # -------------------------------------------------
    def create_draft_order(self, access_token: str, payload):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        contact_id = self._resolve_contact_id(payload.contact_id)
        line_items = []

        for item in payload.items:
            item_resp = requests.get(
                f"{self.base_url}/items/{item.item_id}",
                headers=headers,
                params={"organization_id": self.org_id},
                timeout=15
            )

            if item_resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": f"Failed to fetch item {item.item_id}",
                        "zoho_response": item_resp.json()
                    }
                )

            item_data = item_resp.json()["item"]
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
                "tax_exemption_code": "NON"
            })

        response = requests.post(
            f"{self.base_url}/salesorders",
            headers=headers,
            json={
                "customer_id": contact_id,
                "line_items": line_items,
                "notes": payload.notes or "Sales order requested from customer portal"
            },
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create draft sales order",
                    "zoho_response": response.json()
                }
            )

        salesorder = response.json()["salesorder"]
        self._invalidate_salesorder_caches(contact_id, salesorder["salesorder_id"])
        return salesorder

    # -------------------------------------------------
    # List Sales Orders
    # -------------------------------------------------
    def list_orders_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:salesorders:{contact_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        response = requests.get(
            f"{self.base_url}/salesorders",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch sales orders",
                    "zoho_response": response.json()
                }
            )

        orders = response.json().get("salesorders", [])
        cache.set(cache_key, orders)
        return orders

    # -------------------------------------------------
    # Get Sales Order
    # -------------------------------------------------
    def get_order(self, access_token: str, salesorder_id: str, contact_id: str):
        cache_key = f"zoho:salesorder:{salesorder_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

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

        order = response.json().get("salesorder")
        if order:
            cache.set(cache_key, order)
        return order or {}

    # -------------------------------------------------
    # Review / Approve
    # -------------------------------------------------
    def review_order(
        self,
        access_token: str,
        salesorder_id: str,
        payload,
        reviewer_id: str,
        contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            json={
                "status": payload.status,
                "notes": payload.notes or f"Reviewed by ERP user {reviewer_id}"
            },
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

        order = response.json().get("salesorder", {})
        self._invalidate_salesorder_caches(contact_id, salesorder_id)
        return order

    def customer_approve_order(
        self,
        access_token: str,
        salesorder_id: str,
        payload,
        contact_id: str
    ):
        return self.review_order(
            access_token,
            salesorder_id,
            payload,
            reviewer_id=contact_id,
            contact_id=contact_id
        )

    # -------------------------------------------------
    # PDF (NO CACHE)
    # -------------------------------------------------
    def get_order_pdf(self, access_token: str, salesorder_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        params = {"organization_id": self.org_id, "print": "true", "accept": "pdf"}

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
                    "zoho_response": (
                        response.json()
                        if "application/json" in response.headers.get("Content-Type", "")
                        else None
                    )
                }
            )

        return response.content

    # -------------------------------------------------
    # Comments
    # -------------------------------------------------
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

        result = []
        for c in response.json().get("comments", []):
            desc = c.get("description", "")
            if "[CUSTOM_META]" not in desc:
                continue

            meta = extract_comment_meta(desc)
            result.append({
                "comment_id": c.get("comment_id"),
                "salesorder_id": salesorder_id,
                "description": strip_comment_meta(desc),
                "commented_by": meta.get("customer_name", c.get("commented_by")),
                "commented_by_id": meta.get("customer_id", c.get("commented_by_id")),
                "comment_type": "client",
                "date": c.get("date"),
                "time": c.get("time"),
                "comments_html_format": c.get("comments_html_format")
            })

        return result

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

        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/comments",
            headers=headers,
            json={
                "description": build_comment_meta(email) + description,
                "show_comment_to_clients": show_to_client
            },
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

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return response.json()

    def update_comment(
        self,
        access_token: str,
        salesorder_id: str,
        comment_id: str,
        description: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}/comments/{comment_id}",
            headers=headers,
            json={"description": description},
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to update comment",
                    "zoho_response": response.json()
                }
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return response.json()

    def delete_comment(
        self,
        access_token: str,
        salesorder_id: str,
        comment_id: str
    ):
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

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return {"message": "Comment deleted successfully"}
