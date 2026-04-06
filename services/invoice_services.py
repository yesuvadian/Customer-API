import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache

_INVOICE_CACHE_TTL = 120   # single invoice
_LIST_CACHE_TTL = 120      # invoice list
_ITEM_CACHE_TTL = 3600     # items almost never change


class InvoiceService:
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

    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    def _invalidate_invoice_caches(
        self, contact_id: str | None = None, invoice_id: str | None = None
    ):
        if contact_id:
            cache.delete(f"zoho:invoices:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")
        if invoice_id:
            cache.delete(f"zoho:invoice:{invoice_id}")

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

    # -------------------------------------------------
    # Create Invoice
    # -------------------------------------------------
    def create_invoice(self, access_token: str, payload):
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
                "tax_id": "",
                "tax_exemption_code": "NON",
            })

        response = requests.post(
            f"{self.base_url}/invoices",
            headers=headers,
            json={
                "customer_id": contact_id,
                "line_items": line_items,
                "notes": payload.notes or "Invoice created from customer portal",
            },
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create invoice", "zoho_response": response.json()},
            )

        invoice = response.json()["invoice"]
        self._invalidate_invoice_caches(contact_id, invoice["invoice_id"])
        return invoice

    # -------------------------------------------------
    # List Invoices
    # -------------------------------------------------
    def list_invoices_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:invoices:{contact_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        response = requests.get(
            f"{self.base_url}/invoices",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch invoices", "zoho_response": response.json()},
            )

        invoices = response.json().get("invoices", [])

        for inv in invoices:
            inv["salesorder_number"] = inv.get("reference_number")

        cache.set(cache_key, invoices, ttl=_LIST_CACHE_TTL)
        return invoices

    # -------------------------------------------------
    # Get Invoice (cached) — attachments embedded to save a round-trip
    # -------------------------------------------------
    def get_invoice(self, access_token: str, invoice_id: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:invoice:{invoice_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        response = requests.get(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Failed to fetch invoice {invoice_id}", "zoho_response": response.json()},
            )

        invoice = response.json().get("invoice", {})

        # Embed attachments so the Flutter client skips a separate /attachments call
        invoice["attachments"] = [
            {
                "attachment_id": doc.get("document_id"),
                "file_name": doc.get("file_name"),
                "file_type": doc.get("file_type"),
                "file_size": doc.get("file_size"),
            }
            for doc in invoice.get("documents", [])
        ]

        cache.set(cache_key, invoice, ttl=_INVOICE_CACHE_TTL)
        return invoice

    # -------------------------------------------------
    # Get Attachments — reuses get_invoice cache (no extra GET)
    # -------------------------------------------------
    def get_invoice_attachments(self, access_token: str, invoice_id: str, contact_id: str = ""):
        """
        Returns attachment list from the already-cached invoice.
        Pass contact_id if available so the cache can be populated correctly;
        the empty-string fallback still works because get_invoice resolves it.
        """
        invoice = self.get_invoice(access_token, invoice_id, contact_id)
        # attachments are embedded by get_invoice above
        return invoice.get("attachments", [])

    # -------------------------------------------------
    # ERP Review Invoice
    # -------------------------------------------------
    def review_invoice(
        self,
        access_token: str,
        invoice_id: str,
        payload,
        reviewer_id: str,
        contact_id: str,
    ):
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.put(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=self._auth_headers(access_token),
            json={
                "status": payload.status,
                "notes": payload.notes or f"Reviewed by ERP user {reviewer_id}",
            },
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to review invoice", "zoho_response": response.json()},
            )

        invoice = response.json()["invoice"]
        self._invalidate_invoice_caches(contact_id, invoice["invoice_id"])
        return invoice

    # -------------------------------------------------
    # Customer Approve Invoice
    # -------------------------------------------------
    def customer_approve_invoice(
        self, access_token: str, invoice_id: str, payload, contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.put(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=self._auth_headers(access_token),
            json={
                "status": payload.status,
                "notes": payload.notes or f"Response from customer {contact_id}",
            },
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to update invoice status", "zoho_response": response.json()},
            )

        invoice = response.json().get("invoice", {})
        self._invalidate_invoice_caches(contact_id, invoice_id)
        return invoice

    # -------------------------------------------------
    # PDF
    # -------------------------------------------------
    def get_invoice_pdf(self, access_token: str, invoice_id: str):
        response = requests.get(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "print": "true", "accept": "pdf"},
            timeout=30,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch PDF for invoice {invoice_id}",
                    "zoho_response": (
                        response.json()
                        if "application/json" in response.headers.get("Content-Type", "")
                        else None
                    ),
                },
            )

        return response.content

    # -------------------------------------------------
    # Download Attachment
    # -------------------------------------------------
    def download_invoice_attachment(
        self, access_token: str, invoice_id: str, attachment_id: str
    ):
        resp = requests.get(
            f"{self.base_url}/invoices/{invoice_id}/documents/{attachment_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to download attachment")

        return resp.content

    # -------------------------------------------------
    # Comments
    # -------------------------------------------------
    def get_invoice_comments(self, access_token: str, invoice_id: str):
        resp = requests.get(
            f"{self.base_url}/invoices/{invoice_id}/comments",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch invoice comments", "zoho_response": resp.json()},
            )

        result = []
        for c in resp.json().get("comments", []):
            description = c.get("description", "")
            if "[CUSTOM_META]" not in description:
                continue
            meta = extract_comment_meta(description)
            result.append({
                "comment_id": c.get("comment_id", ""),
                "invoice_id": invoice_id,
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

    def add_invoice_comment(
        self,
        access_token: str,
        invoice_id: str,
        description: str,
        email: str | None = None,
    ):
        meta_block = build_comment_meta(email=email)

        resp = requests.post(
            f"{self.base_url}/invoices/{invoice_id}/comments",
            headers=self._json_headers(access_token),
            params={"organization_id": self.org_id},
            json={"description": meta_block + description},
            timeout=15,
        )

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to add invoice comment", "zoho_response": resp.json()},
            )

        return resp.json()

    def update_invoice_comment(
        self,
        access_token: str,
        invoice_id: str,
        comment_id: str,
        payload: dict,
        email: str | None = None,
    ):
        description = payload.get("description", "")
        meta_block = build_comment_meta(email=email)
        updated_payload = {**payload, "description": meta_block + description}

        resp = requests.put(
            f"{self.base_url}/invoices/{invoice_id}/comments/{comment_id}",
            headers=self._json_headers(access_token),
            params={"organization_id": self.org_id},
            json=updated_payload,
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to update invoice comment", "zoho_response": resp.json()},
            )

        return resp.json()

    def delete_invoice_comment(self, access_token: str, invoice_id: str, comment_id: str):
        resp = requests.delete(
            f"{self.base_url}/invoices/{invoice_id}/comments/{comment_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to delete invoice comment", "zoho_response": resp.json()},
            )