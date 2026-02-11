import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache


class RetainerInvoiceService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -------------------------------------------------
    # Cache helpers
    # -------------------------------------------------
    def _invalidate_retainer_caches(
        self,
        contact_id: str | None = None,
        retainerinvoice_id: str | None = None
    ):
        if contact_id:
            cache.delete(f"zoho:retainers:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")

        if retainerinvoice_id:
            cache.delete(f"zoho:retainer:{retainerinvoice_id}")

    # -------------------------------------------------
    # Utility
    # -------------------------------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -------------------------------------------------
    # Create Retainer Invoice
    # -------------------------------------------------
    def create_retainer_invoice(self, access_token: str, payload):
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
            f"{self.base_url}/retainerinvoices",
            headers=headers,
            json={
                "customer_id": contact_id,
                "line_items": line_items,
                "notes": payload.notes or "Retainer invoice created from customer portal"
            },
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

        retainer = response.json()["retainer_invoice"]
        self._invalidate_retainer_caches(contact_id, retainer["retainerinvoice_id"])
        return retainer

    # -------------------------------------------------
    # List Retainer Invoices
    # -------------------------------------------------
    def list_retainer_invoices_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:retainers:{contact_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
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

        retainers = response.json().get("retainerinvoices", [])
        cache.set(cache_key, retainers)
        return retainers

    # -------------------------------------------------
    # Get Retainer Invoice
    # -------------------------------------------------
    def get_retainer_invoice(
        self,
        access_token: str,
        retainerinvoice_id: str,
        contact_id: str
    ):
        cache_key = f"zoho:retainer:{retainerinvoice_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

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

        retainer = response.json().get("retainerinvoice")
        if retainer:
            cache.set(cache_key, retainer)
        return retainer or {}

    # -------------------------------------------------
    # Review / Approve
    # -------------------------------------------------
    def review_retainer_invoice(
        self,
        access_token: str,
        retainerinvoice_id: str,
        payload,
        reviewer_id: str,
        contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.put(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}",
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
                    "message": "Failed to review retainer invoice",
                    "zoho_response": response.json()
                }
            )

        retainer = response.json().get("retainer_invoice", {})
        self._invalidate_retainer_caches(contact_id, retainerinvoice_id)
        return retainer

    def customer_approve_retainer_invoice(
        self,
        access_token: str,
        retainerinvoice_id: str,
        payload,
        contact_id: str
    ):
        return self.review_retainer_invoice(
            access_token,
            retainerinvoice_id,
            payload,
            reviewer_id=contact_id,
            contact_id=contact_id
        )

    # -------------------------------------------------
    # PDF (NO CACHE)
    # -------------------------------------------------
    def get_retainer_invoice_pdf(self, access_token: str, retainerinvoice_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        params = {"organization_id": self.org_id, "print": "true", "accept": "pdf"}

        response = requests.get(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch retainer invoice PDF",
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
    def list_comments(self, access_token: str, retainerinvoice_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.get(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}/comments",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to get comments for retainer invoice {retainerinvoice_id}",
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
                "retainerinvoice_id": retainerinvoice_id,
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
        retainerinvoice_id: str,
        description: str,
        email: str | None = None
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}/comments",
            headers=headers,
            json={"description": build_comment_meta(email) + description},
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

        self._invalidate_retainer_caches(retainerinvoice_id=retainerinvoice_id)
        return response.json()

    def update_comment(
        self,
        access_token: str,
        retainerinvoice_id: str,
        comment_id: str,
        payload: dict
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.put(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}/comments/{comment_id}",
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

        self._invalidate_retainer_caches(retainerinvoice_id=retainerinvoice_id)
        return response.json()

    def delete_comment(
        self,
        access_token: str,
        retainerinvoice_id: str,
        comment_id: str
    ):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.delete(
            f"{self.base_url}/retainerinvoices/{retainerinvoice_id}/comments/{comment_id}",
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

        self._invalidate_retainer_caches(retainerinvoice_id=retainerinvoice_id)
        return {"message": "Comment deleted successfully"}
