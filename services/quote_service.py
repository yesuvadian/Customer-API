import os
import requests
from fastapi import HTTPException, UploadFile, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache

_QUOTE_CACHE_TTL = 120
_ITEM_CACHE_TTL = 3600


class QuoteService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------
    def _auth_headers(self, access_token: str) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {access_token}"}

    def _json_headers(self, access_token: str) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def _invalidate_quote_caches(
        self,
        contact_id: str | None = None,
        estimate_id: str | None = None,
    ):
        if contact_id:
            cache.delete(f"zoho:quotes:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")
        if estimate_id:
            cache.delete(f"zoho:quote:{estimate_id}")

    def _get_item_cached(self, headers: dict, item_id: str) -> dict:
        cache_key = f"zoho:item:{item_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        resp = requests.get(
            f"{self.base_url}/items/{item_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Failed to fetch item {item_id}", "zoho_response": resp.json()},
            )

        item = resp.json().get("item", {})
        cache.set(cache_key, item, ttl=_ITEM_CACHE_TTL)
        return item

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
        uploaded_by: str | None = None,
    ):
        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/attachment",
            headers=self._auth_headers(access_token),
            files={"attachment": (file.filename, file.file, file.content_type or "application/octet-stream")},
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to upload attachment", "zoho_response": response.json()},
            )

        if uploaded_by:
            try:
                self.add_comment(
                    access_token, estimate_id,
                    f"Attachment uploaded: {file.filename}",
                    uploaded_by,
                )
            except Exception:
                pass

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return response.json()

    # -------------------------------------------------
    # Create Draft Quote (Enquiry)
    # -------------------------------------------------
    def create_draft_quote_enquiry(self, access_token: str, payload):
        headers = self._json_headers(access_token)
        contact_id = self._resolve_contact_id(payload.contact_id)

        body = {
            "customer_id": contact_id,
            "line_items": [{
                "name": "Enquiry Request",
                "quantity": 1,
                "rate": 0,
                "description": getattr(payload, "enquiry_description", "Customer enquiry submitted from portal"),
                "tax_exemption_code": "NON",
            }],
            "notes": payload.notes or "Quote enquiry submitted from customer portal",
            "status": "draft",
            "custom_fields": self._build_rfq_field(access_token),
        }

        response = requests.post(
            f"{self.base_url}/estimates",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create enquiry draft quote", "zoho_response": response.json()},
            )

        estimate = response.json()["estimate"]
        self._invalidate_quote_caches(contact_id, estimate["estimate_id"])
        return estimate

    # -------------------------------------------------
    # Create Draft Quote
    # -------------------------------------------------
    def create_draft_quote(self, access_token: str, payload):
        headers = self._json_headers(access_token)
        contact_id = self._resolve_contact_id(payload.contact_id)

        line_items = []
        for item in payload.items:
            item_data = self._get_item_cached(headers, item.item_id)
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
            })

        response = requests.post(
            f"{self.base_url}/estimates",
            headers=headers,
            json={
                "customer_id": contact_id,
                "line_items": line_items,
                "notes": payload.notes,
                "custom_fields": self._build_rfq_field(access_token),
            },
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create draft quote", "zoho_response": response.json()},
            )

        estimate = response.json()["estimate"]
        self._invalidate_quote_caches(contact_id, estimate["estimate_id"])
        return estimate

    # -------------------------------------------------
    # Vendor helpers
    # -------------------------------------------------
    def find_vendors_for_items(self, item_ids: list[str], auth_header: str) -> list:
        vendor_url = f"{config.VENDOR_APP_URL}/company_products/find_vendors_by_ids"
        try:
            response = requests.get(
                vendor_url,
                params={"ids": item_ids},
                headers={"x-internal-secret": config.INTERNAL_SERVICE_SECRET},
                timeout=10,
            )
            if response.status_code == 200:
                return response.json().get("vendors", [])
            print(f"Vendor app returned status {response.status_code}: {response.text}")
            return []
        except requests.exceptions.RequestException as e:
            print(f"Failed to reach Vendor App: {str(e)}")
            return []

    def create_vendor_if_not_exists(self, access_token: str, vendor_name: str):
        headers = self._json_headers(access_token)

        search_resp = requests.get(
            f"{self.base_url}/contacts",
            headers=headers,
            params={"organization_id": self.org_id, "contact_name": vendor_name},
            timeout=15,
        )

        if search_resp.status_code == 200:
            contacts = search_resp.json().get("contacts", [])
            if contacts:
                return contacts[0]["contact_id"]

        create_resp = requests.post(
            f"{self.base_url}/contacts",
            headers=headers,
            params={"organization_id": self.org_id},
            json={"contact_name": vendor_name, "contact_type": "vendor"},
            timeout=15,
        )

        if create_resp.status_code not in (200, 201):
            raise HTTPException(400, "Failed to create vendor")

        return create_resp.json()["contact"]["contact_id"]

    def assign_vendors_to_quote(self, access_token: str, estimate_id: str, vendors: list[dict]):
        headers = self._json_headers(access_token)
        zoho_vendor_ids = []

        for vendor in vendors:
            contact_id = (
                vendor["zoho_erp_id"]
                if vendor.get("zoho_erp_id")
                else self.create_vendor_if_not_exists(access_token, vendor["name"])
            )
            zoho_vendor_ids.append(contact_id)

        if not zoho_vendor_ids:
            raise HTTPException(400, "No valid vendors found")

        resp = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            json={"custom_fields": [{"api_name": "cf_supplier", "value": zoho_vendor_ids[0]}]},
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(400, resp.text)

        return resp.json()

    # -------------------------------------------------
    # RFQ field
    # -------------------------------------------------
    def _build_rfq_field(self, access_token: str):
        rfq = self.generate_next_rfq(access_token)
        return [{"customfield_id": config.ZOHO_ESTIMATE_RFQ_FIELD_ID, "value": rfq}]

    def generate_next_rfq(self, access_token: str) -> str:
        response = requests.get(
            f"{self.base_url}/estimates",
            headers=self._auth_headers(access_token),
            params={
                "organization_id": self.org_id,
                "sort_column": "created_time",
                "sort_order": "D",
                "per_page": 1,
            },
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Failed to fetch estimates for RFQ generation",
            )

        estimates = response.json().get("estimates", [])

        if not estimates:
            return "RFQ-0001"

        rfq = estimates[0].get("cf_rfq") or estimates[0].get("custom_field_hash", {}).get("cf_rfq")

        if rfq and rfq.startswith("RFQ-"):
            try:
                return f"RFQ-{int(rfq.split('-')[1]) + 1:04d}"
            except Exception as e:
                print("RFQ parse error:", e)

        return "RFQ-0001"

    # -------------------------------------------------
    # List Quotes
    # -------------------------------------------------
    def list_quotes_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:quotes:{contact_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        response = requests.get(
            f"{self.base_url}/estimates",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to fetch quotes")

        quotes = [
            q for q in response.json().get("estimates", [])
            if q.get("status", "").lower() != "draft"
        ]

        cache.set(cache_key, quotes, ttl=_QUOTE_CACHE_TTL)
        return quotes

    # -------------------------------------------------
    # Get Quote (cached)
    # -------------------------------------------------
    def get_quote(self, access_token: str, estimate_id: str, contact_id: str):
        cache_key = f"zoho:quote:{estimate_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to fetch quote")

        estimate = response.json().get("estimate")
        if estimate:
            cache.set(cache_key, estimate, ttl=_QUOTE_CACHE_TTL)
        return estimate or {}

    # -------------------------------------------------
    # Review
    # -------------------------------------------------
    def review_quote(
        self,
        access_token: str,
        estimate_id: str,
        payload,
        reviewer_id: str,
        contact_id: str,
    ):
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=self._auth_headers(access_token),
            json={"status": payload.status, "notes": payload.notes},
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to review quote")

        estimate = response.json()["estimate"]
        self._invalidate_quote_caches(contact_id, estimate_id)
        return estimate

    # -------------------------------------------------
    # Mark Estimate as Sent with Supplier
    # -------------------------------------------------
    def mark_estimate_as_sent_with_supplier(
        self, access_token: str, estimate_id: str, supplier_id: str
    ):
        headers = self._json_headers(access_token)

        # Step 1: Update supplier custom field
        update_response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            json={"custom_fields": [{"api_name": "cf_supplier", "value": supplier_id}]},
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if update_response.status_code != 200:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                {"message": "Failed to update supplier field", "zoho_response": update_response.json()},
            )

        # Step 2: Mark as sent
        send_response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/status/sent",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        data = send_response.json()
        self._invalidate_quote_caches(estimate_id=estimate_id)

        if send_response.status_code != 200 or data.get("code") != 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                {"message": "Failed to mark estimate as sent", "zoho_response": data},
            )

        # Get estimate_number from cache (already populated above by get_quote callers)
        # or do a lightweight fetch
        try:
            quote = self.get_quote(access_token, estimate_id, contact_id="")
            estimate_number = quote.get("estimate_number", "")
        except Exception:
            estimate_number = ""

        return {
            "message": data.get("message", "Estimate marked as sent"),
            "estimate_id": estimate_id,
            "estimate_number": estimate_number,
            "status": "sent",
            "supplier_id": supplier_id,
        }

    def customer_approve_quote(self, access_token: str, estimate_id: str, payload, customer_id: str):
        return self.review_quote(access_token, estimate_id, payload, customer_id, customer_id)

    # -------------------------------------------------
    # Status Change — returns estimate_number from cache when possible
    # -------------------------------------------------
    def update_quote_status(self, access_token: str, estimate_id: str, action: str):
        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/status/{action}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        data = response.json()
        self._invalidate_quote_caches(estimate_id=estimate_id)

        if response.status_code != 200 or data.get("code") != 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, data)

        # Pull estimate_number from cache if available; one GET otherwise
        try:
            quote = self.get_quote(access_token, estimate_id, contact_id="")
            estimate_number = quote.get("estimate_number", "")
        except Exception:
            estimate_number = ""

        return {
            "message": data.get("message"),
            "estimate_id": estimate_id,
            "estimate_number": estimate_number,
            "status": action,
        }

    # -------------------------------------------------
    # PDF
    # -------------------------------------------------
    def get_quote_pdf(self, access_token: str, estimate_id: str):
        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "print": "true", "accept": "pdf"},
            timeout=30,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch PDF for estimate {estimate_id}",
                    "zoho_response": (
                        response.json()
                        if "application/json" in response.headers.get("Content-Type", "")
                        else None
                    ),
                },
            )

        return response.content

    # -------------------------------------------------
    # Comments
    # -------------------------------------------------
    def add_comment(
        self,
        access_token: str,
        estimate_id: str,
        description: str,
        email: str | None = None,
    ):
        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=self._json_headers(access_token),
            json={"description": build_comment_meta(email=email) + description},
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code not in (200, 201):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to add comment")

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return response.json()

    def update_comment(
        self,
        access_token: str,
        estimate_id: str,
        comment_id: str,
        description: str,
        email: str | None = None,
    ):
        # Re-attach meta block so get_comments() keeps showing this comment
        meta_block = build_comment_meta(email=email)

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
            headers=self._json_headers(access_token),
            json={"description": meta_block + description},
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to update comment")

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return response.json()

    def delete_comment(self, access_token: str, estimate_id: str, comment_id: str):
        response = requests.delete(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to delete comment")

        self._invalidate_quote_caches(estimate_id=estimate_id)
        return {"message": "Comment deleted successfully"}

    def get_comments(self, access_token: str, estimate_id: str):
        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch comments for estimate {estimate_id}",
                    "zoho_response": response.json(),
                },
            )

        result = []
        for c in response.json().get("comments", []):
            description = c.get("description", "")
            if "[CUSTOM_META]" not in description:
                continue
            meta = extract_comment_meta(description)
            result.append({
                "comment_id": c.get("comment_id", ""),
                "estimate_id": c.get("estimate_id", ""),
                "description": strip_comment_meta(description),
                "commented_by": meta.get("customer_name", c.get("commented_by", "")),
                "commented_by_id": meta.get("customer_id", c.get("commented_by_id", "")),
                "comment_type": "client",
                "date": c.get("date", ""),
                "date_description": c.get("date_description", ""),
                "time": c.get("time", ""),
                "comments_html_format": c.get("comments_html_format", ""),
            })

        return result