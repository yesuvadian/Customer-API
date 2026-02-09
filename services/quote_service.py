import requests
from fastapi import HTTPException, UploadFile, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache


class QuoteService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -------------------------------------------------
    # Cache helpers
    # -------------------------------------------------
    def _invalidate_quote_caches(
        self,
        contact_id: str | None = None,
        estimate_id: str | None = None
    ):
        if contact_id:
            cache.delete(f"zoho:quotes:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")

        if estimate_id:
            cache.delete(f"zoho:quote:{estimate_id}")

    # -------------------------------------------------
    # Utility
    # -------------------------------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -------------------------------------------------
    # Upload Attachment
    # -------------------------------------------------
    def upload_attachment(
        self,
        access_token: str,
        estimate_id: str,
        file: UploadFile,
        uploaded_by: str | None = None
    ):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        files = {
            "attachment": (
                file.filename,
                file.file,
                file.content_type or "application/octet-stream"
            )
        }

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/attachment",
            headers=headers,
            files=files,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to upload attachment", "zoho_response": response.json()}
            )

        # Optional audit comment
        if uploaded_by:
            try:
                self.add_comment(
                    access_token,
                    estimate_id,
                    f"Attachment uploaded: {file.filename}",
                    uploaded_by
                )
            except Exception:
                pass

        # Attachment affects quote detail only
        self._invalidate_quote_caches(estimate_id=estimate_id)
        return response.json()

    # -------------------------------------------------
    # Create Draft Quote (Enquiry)
    # -------------------------------------------------
    def create_draft_quote_enquiry(self, access_token: str, payload):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        contact_id = self._resolve_contact_id(payload.contact_id)

        body = {
            "customer_id": contact_id,
            "line_items": [{
                "name": "Enquiry Request",
                "quantity": 1,
                "rate": 0,
                "description": getattr(
                    payload,
                    "enquiry_description",
                    "Customer enquiry submitted from portal"
                ),
                "tax_exemption_code": "NON"
            }],
            "notes": payload.notes or "Quote enquiry submitted from customer portal",
            "status": "draft"
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
                detail={"message": "Failed to create enquiry draft quote", "zoho_response": response.json()}
            )

        estimate = response.json()["estimate"]
        self._invalidate_quote_caches(contact_id, estimate["estimate_id"])
        return estimate

    # -------------------------------------------------
    # Create Draft Quote
    # -------------------------------------------------
    def create_draft_quote(self, access_token: str, payload):
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
                    detail={"message": f"Failed to fetch item {item.item_id}", "zoho_response": item_resp.json()}
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
            f"{self.base_url}/estimates",
            headers=headers,
            json={"customer_id": contact_id, "line_items": line_items, "notes": payload.notes},
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create draft quote", "zoho_response": response.json()}
            )

        estimate = response.json()["estimate"]
        self._invalidate_quote_caches(contact_id, estimate["estimate_id"])
        return estimate

    # -------------------------------------------------
    # List Quotes
    # -------------------------------------------------
    def list_quotes_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:quotes:{contact_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        response = requests.get(
            f"{self.base_url}/estimates",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to fetch quotes")

        quotes = [
            q for q in response.json().get("estimates", [])
            if q.get("status", "").lower() != "draft"
        ]

        cache.set(cache_key, quotes)
        return quotes

    # -------------------------------------------------
    # Get Quote
    # -------------------------------------------------
    def get_quote(self, access_token: str, estimate_id: str, contact_id: str):
        cache_key = f"zoho:quote:{estimate_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to fetch quote")

        estimate = response.json().get("estimate")
        if estimate:
            cache.set(cache_key, estimate)
        return estimate or {}

    # -------------------------------------------------
    # Review / Approve
    # -------------------------------------------------
    def review_quote(self, access_token: str, estimate_id: str, payload, reviewer_id: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            json={"status": payload.status, "notes": payload.notes},
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to review quote")

        estimate = response.json()["estimate"]
        self._invalidate_quote_caches(contact_id, estimate_id)
        return estimate

    def customer_approve_quote(self, access_token: str, estimate_id: str, payload, contact_id: str):
        return self.review_quote(access_token, estimate_id, payload, contact_id, contact_id)

    # -------------------------------------------------
    # Status Change
    # -------------------------------------------------
    def update_quote_status(self, access_token: str, estimate_id: str, action: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/status/{action}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        data = response.json()
        self._invalidate_quote_caches(estimate_id=estimate_id)

        if response.status_code != 200 or data.get("code") != 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, data)

        return {
            "message": data.get("message"),
            "estimate_id": estimate_id,
            "status": action
        }

    # -------------------------------------------------
    # Comments
    # -------------------------------------------------
    def add_comment(self, access_token: str, estimate_id: str, description: str, email: str | None = None):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}
        payload = {"description": build_comment_meta(email) + description}

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=headers,
            json=payload,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code not in (200, 201):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to add comment")

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return response.json()

    def update_comment(self, access_token: str, estimate_id: str, comment_id: str, description: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
            headers=headers,
            json={"description": description},
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to update comment")

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return response.json()

    def delete_comment(self, access_token: str, estimate_id: str, comment_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.delete(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to delete comment")

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return {"message": "Comment deleted successfully"}
