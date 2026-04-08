import requests
from fastapi import HTTPException, status
import config
import base64
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache
from fastapi import UploadFile
from datetime import datetime

# TTL constants — keep in one place so they're easy to tune
_SO_CACHE_TTL = 60          # single salesorder: short-lived, status changes frequently
_SO_LIST_CACHE_TTL = 120    # list: a bit more tolerant
_ITEM_CACHE_TTL = 3600      # items almost never change


class SalesOrderService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------
    def _build_filename(self, salesorder: dict, file: UploadFile, doc_type: str) -> str:
        salesorder_number = salesorder.get("salesorder_number", "")
        clean_number = salesorder_number.lower().replace("-", "_")
        extension = file.filename.split(".")[-1] if "." in file.filename else "pdf"
        return f"{clean_number}_{doc_type}.{extension}"

    def _auth_headers(self, access_token: str) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {access_token}"}

    def _json_headers(self, access_token: str) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def _invalidate_salesorder_caches(
        self,
        contact_id: str | None = None,
        salesorder_id: str | None = None,
    ):
        if contact_id:
            cache.delete(f"zoho:salesorders:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")
        if salesorder_id:
            cache.delete(f"zoho:salesorder:{salesorder_id}")

    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -------------------------------------------------
    # Fetch Sales Order (cached)
    # -------------------------------------------------
    def _get_order_status(self, access_token: str, salesorder_id: str) -> dict:
        """
        Fetch a single sales order with a short TTL cache.
        All internal helpers share this call — avoids duplicate GETs within
        a single request lifecycle.
        """
        cache_key = f"zoho:salesorder:{salesorder_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to fetch sales order status",
            )

        salesorder = response.json().get("salesorder", {})
        cache.set(cache_key, salesorder, ttl=_SO_CACHE_TTL)
        return salesorder

    # -------------------------------------------------
    # Validation guards
    # -------------------------------------------------
    def _validate_status_for_po(self, order_status: str | None):
        if order_status and order_status.lower() in ("packed", "shipped"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PO cannot be updated when order status is '{order_status}'",
            )

    def _validate_status_for_grn(self, salesorder: dict):
        # Currently no restriction — kept as hook for future rules
        return

    # -------------------------------------------------
    # Upload PO Attachment
    # -------------------------------------------------
    def upload_po_attachment(
        self,
        access_token: str,
        salesorder_id: str,
        file: UploadFile,
        po_number: str,
        uploaded_by: str | None = None,
    ):
        # Single fetch — reused by both validation and filename generation
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_po(salesorder.get("status"))

        # Update PO custom field first
        self.update_po_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            po_number=po_number,
        )

        file.file.seek(0)
        new_filename = self._build_filename(salesorder=salesorder, file=file, doc_type="po")

        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment",
            headers=self._auth_headers(access_token),
            files={"attachment": (new_filename, file.file, file.content_type or "application/pdf")},
            params={"organization_id": self.org_id},
            timeout=30,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code not in (200, 201) or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=400,
                detail={"message": "Failed to upload PO attachment", "zoho_response": data},
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return data

    # -------------------------------------------------
    # Upload GRN Attachment
    # -------------------------------------------------
    def upload_grn_attachment(
        self,
        access_token: str,
        salesorder_id: str,
        cf_grn_number: str,
        file: UploadFile,
        uploaded_by: str | None = None,
    ):
        # Fetch once — used for validation + filename
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_grn(salesorder)

        self.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=cf_grn_number,
        )

        file.file.seek(0)
        new_filename = self._build_filename(salesorder=salesorder, file=file, doc_type="grn")
        file_bytes = file.file.read()

        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment",
            headers=self._auth_headers(access_token),
            files={"attachment": (new_filename, file_bytes, file.content_type or "application/pdf")},
            params={"organization_id": self.org_id},
            timeout=30,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code not in (200, 201) or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to upload GRN attachment", "zoho_response": data},
            )

        # Add comment (non-critical — never raises)
        if uploaded_by:
            self._post_comment_safe(
                access_token=access_token,
                salesorder_id=salesorder_id,
                email=uploaded_by,
                body=f"GRN Uploaded\nGRN Number: {cf_grn_number}\nFile: {file.filename}",
            )

        # Invalidate cache before PO sync so that _get_order_status inside
        # send_grn_to_purchase_order fetches the freshly uploaded attachment.
        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        # Build an in-memory salesorder dict that already contains the new document
        # so send_grn_to_purchase_order does NOT need to re-fetch the SO.
        salesorder_with_grn = dict(salesorder)
        salesorder_with_grn["documents"] = list(salesorder.get("documents", [])) + [{
            "file_name": new_filename,
            "document_id": None,        # not yet known — PO sync will re-read
        }]

        po_sync_success = False
        try:
            # Must refetch here: we need the real document_id assigned by Zoho
            fresh_so = self._get_order_status(access_token, salesorder_id)
            self.send_grn_to_purchase_order(
                access_token=access_token,
                salesorder_id=salesorder_id,
                salesorder=fresh_so,
            )
            po_sync_success = True
        except Exception as e:
            print("⚠️ GRN sync to PO failed:", str(e))

        return {
            "message": (
                "GRN uploaded successfully and sent to supplier"
                if po_sync_success
                else "GRN uploaded successfully (PO sync failed)"
            ),
            "salesorder_id": salesorder_id,
            "grn_number": cf_grn_number,
            "file_name": new_filename,
            "po_synced": po_sync_success,
        }

    # -------------------------------------------------
    # Update GRN Attachment (PUT)
    # -------------------------------------------------
    def update_grn_attachment(
        self,
        access_token: str,
        salesorder_id: str,
        cf_grn_number: str,
        file: UploadFile,
        uploaded_by: str | None = None,
    ):
        # Single fetch covers validation + old-file lookup + filename
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_grn(salesorder)

        # Delete old GRN if one exists — pass salesorder to avoid re-fetch
        try:
            self.delete_attachment_by_prefix(
                access_token=access_token,
                salesorder_id=salesorder_id,
                prefix="_grn",
                salesorder=salesorder,
            )
        except HTTPException:
            pass  # no existing GRN — that's fine

        self.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=cf_grn_number,
        )

        file.file.seek(0)
        new_filename = self._build_filename(salesorder=salesorder, file=file, doc_type="grn")

        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment",
            headers=self._auth_headers(access_token),
            files={"attachment": (new_filename, file.file, file.content_type or "application/pdf")},
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if response.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Failed to upload updated GRN file")

        if uploaded_by:
            self._post_comment_safe(
                access_token=access_token,
                salesorder_id=salesorder_id,
                email=uploaded_by,
                body=f"GRN Updated\nNew GRN Number: {cf_grn_number}\nFile: {file.filename}",
            )

        # Invalidate before the PO sync refetch
        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        po_sync_success = False
        try:
            fresh_so = self._get_order_status(access_token, salesorder_id)
            self.send_grn_to_purchase_order(
                access_token=access_token,
                salesorder_id=salesorder_id,
                salesorder=fresh_so,
            )
            po_sync_success = True
        except Exception as e:
            print("⚠️ GRN update sync to PO failed:", str(e))

        return {
            "message": (
                "GRN updated successfully and synced to supplier"
                if po_sync_success
                else "GRN updated successfully (PO sync failed)"
            ),
            "salesorder_id": salesorder_id,
            "grn_number": cf_grn_number,
            "file_name": new_filename,
            "po_synced": po_sync_success,
        }

    # -------------------------------------------------
    # GRN / PO number field helpers
    # -------------------------------------------------
    def _update_custom_field(
        self, access_token: str, salesorder_id: str, api_name: str, value
    ):
        """Generic helper — single PUT to update one custom field."""
        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=self._json_headers(access_token),
            params={"organization_id": self.org_id},
            json={"custom_fields": [{"api_name": api_name, "value": value}]},
            timeout=15,
        )
        data = response.json()
        if response.status_code != 200 or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Failed to update {api_name}", "zoho_response": data},
            )
        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return data

    def update_grn_number_field(self, access_token: str, salesorder_id: str, grn_number: str):
        return self._update_custom_field(access_token, salesorder_id, "cf_grn_number", grn_number)

    def update_po_number_field(self, access_token: str, salesorder_id: str, po_number):
        return self._update_custom_field(access_token, salesorder_id, "cf_customer_po_no", po_number)

    def delete_po_number_field(self, access_token: str, salesorder_id: str):
        return self.update_po_number_field(access_token, salesorder_id, None)

    # -------------------------------------------------
    # GRN Data
    # -------------------------------------------------
    def get_grn_data(
        self,
        access_token: str,
        salesorder_id: str,
        contact_id: str,
        salesorder: dict | None = None,
    ):
        """
        Return GRN number + attachment metadata.
        Accepts an already-fetched salesorder to skip the GET when the caller
        already has one in hand (e.g. after get_order).
        """
        if salesorder is None:
            # Use the lightweight cached path instead of a scoped customer GET
            salesorder = self._get_order_status(access_token, salesorder_id)

        grn_number = ""
        for field in salesorder.get("custom_fields", []):
            if field.get("api_name") == "cf_grn_number":
                grn_number = field.get("value", "")
                break

        grn_attachment = None
        for doc in reversed(salesorder.get("documents", [])):
            if "_grn" in doc.get("file_name", ""):
                grn_attachment = {
                    "attachment_id": doc.get("document_id"),
                    "file_name": doc.get("file_name"),
                    "file_size": doc.get("file_size"),
                    "uploaded_on": doc.get("uploaded_on"),
                }
                break

        return {"grn_number": grn_number, "attachment": grn_attachment}

    # -------------------------------------------------
    # Attachment helpers
    # -------------------------------------------------
    def get_attachment_pdf_by_prefix(
        self,
        access_token: str,
        salesorder_id: str,
        prefix: str,
        salesorder: dict | None = None,
    ):
        if salesorder is None:
            salesorder = self._get_order_status(access_token, salesorder_id)

        document_id = None
        for doc in reversed(salesorder.get("documents", [])):
            if prefix in doc.get("file_name", ""):
                document_id = doc.get("document_id")
                break

        if not document_id:
            raise HTTPException(
                status_code=404,
                detail=f"No attachment found with prefix '{prefix}'",
            )

        file_response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if file_response.status_code != 200 or not file_response.content:
            raise HTTPException(status_code=400, detail="Failed to download attachment from Zoho")

        return file_response.content

    def download_attachment(self, access_token: str, salesorder_id: str, attachment_id: str):
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{attachment_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=30,
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to download attachment",
            )
        return response.content

    def delete_attachment_by_prefix(
        self,
        access_token: str,
        salesorder_id: str,
        prefix: str,
        salesorder: dict | None = None,
    ):
        if salesorder is None:
            salesorder = self._get_order_status(access_token, salesorder_id)

        document_id = None
        for doc in reversed(salesorder.get("documents", [])):
            if prefix in doc.get("file_name", ""):
                document_id = doc.get("document_id")
                break

        if not document_id:
            raise HTTPException(status_code=404, detail="Attachment not found")

        return self.delete_attachment(access_token, salesorder_id, document_id)

    def delete_attachment(self, access_token: str, salesorder_id: str, attachment_id: str):
        response = requests.delete(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{attachment_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code != 200 or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=400,
                detail={"message": "Failed to delete attachment", "zoho_response": data},
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return {"message": "Attachment deleted successfully"}

    # -------------------------------------------------
    # Supplier extraction (from already-fetched data)
    # -------------------------------------------------
    def _extract_supplier_from_custom_fields(self, custom_fields: list) -> dict:
        supplier_details = None
        for field in custom_fields:
            if field.get("api_name") == "cf_supplier_details":
                supplier_details = field.get("value")
                break

        if not supplier_details:
            return {"company_name": "No Supplier", "address": ""}

        lines = supplier_details.split("\n")
        return {
            "company_name": lines[0] if lines else "",
            "address": "\n".join(lines[1:]) if len(lines) > 1 else "",
        }

    # -------------------------------------------------
    # Create Draft Sales Order
    # -------------------------------------------------
    def create_draft_order(self, access_token: str, payload):
        headers = self._json_headers(access_token)
        contact_id = self._resolve_contact_id(payload.contact_id)

        line_items = [
            {
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": self._get_item_cached(headers, item.item_id).get("rate", 0),
                "name": self._get_item_cached(headers, item.item_id).get("name", ""),
                "tax_exemption_code": "NON",
            }
            for item in payload.items
        ]

        # Rebuild cleanly without repeated cache calls
        line_items = []
        for item in payload.items:
            item_data = self._get_item_cached(headers, item.item_id)
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
                "tax_exemption_code": "NON",
            })

        response = requests.post(
            f"{self.base_url}/salesorders",
            headers=headers,
            json={
                "customer_id": contact_id,
                "line_items": line_items,
                "notes": payload.notes or "Sales order requested from customer portal",
            },
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to create draft sales order", "zoho_response": response.json()},
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

        response = requests.get(
            f"{self.base_url}/salesorders",
            headers=self._auth_headers(access_token),
            params={
                "organization_id": self.org_id,
                "customer_id": contact_id,
                "include": "custom_fields",
            },
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch sales orders", "zoho_response": response.json()},
            )

        orders = response.json().get("salesorders", [])

        for order in orders:
            order["supplier"] = self._extract_supplier_from_custom_fields(
                order.get("custom_fields", [])
            )

        cache.set(cache_key, orders, ttl=_SO_LIST_CACHE_TTL)
        return orders

    # -------------------------------------------------
    # Get Sales Order (router-facing, customer-scoped)
    # -------------------------------------------------
    def get_order(self, access_token: str, salesorder_id: str, contact_id: str):
        """
        Full sales order fetch scoped to a customer.
        NOT cached by salesorder_id because it uses a customer_id param
        which Zoho uses for permission scoping — different from the
        unscoped _get_order_status cache.
        """
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch sales order",
            )

        salesorder = response.json().get("salesorder", {})
        salesorder["supplier"] = self._extract_supplier_from_custom_fields(
            salesorder.get("custom_fields", [])
        )
        return salesorder

    # -------------------------------------------------
    # Review / Approve
    # -------------------------------------------------
    def review_order(
        self,
        access_token: str,
        salesorder_id: str,
        payload,
        reviewer_id: str,
        contact_id: str,
    ):
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
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
                detail={"message": "Failed to review sales order", "zoho_response": response.json()},
            )

        order = response.json().get("salesorder", {})
        self._invalidate_salesorder_caches(contact_id, salesorder_id)
        return order

    def customer_approve_order(
        self,
        access_token: str,
        salesorder_id: str,
        payload,
        contact_id: str,
    ):
        return self.review_order(
            access_token, salesorder_id, payload,
            reviewer_id=contact_id, contact_id=contact_id,
        )

    # -------------------------------------------------
    # PDF
    # -------------------------------------------------
    def get_order_pdf(self, access_token: str, salesorder_id: str):
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers={**self._auth_headers(access_token), "Accept": "application/pdf"},
            params={"organization_id": self.org_id},
            timeout=30,
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
                    ),
                },
            )

        return response.content

    # -------------------------------------------------
    # Comments
    # -------------------------------------------------
    def _post_comment_safe(
        self,
        access_token: str,
        salesorder_id: str,
        email: str,
        body: str,
        show_to_client: bool = True,
    ):
        """Post a comment and swallow errors — comments are audit-only."""
        try:
            meta_block = build_comment_meta(email=email)
            requests.post(
                f"{self.base_url}/salesorders/{salesorder_id}/comments",
                headers=self._json_headers(access_token),
                params={"organization_id": self.org_id},
                json={"description": meta_block + body, "show_comment_to_clients": show_to_client},
                timeout=15,
            )
        except Exception as e:
            print("⚠️ Comment error:", str(e))

    def get_comments(self, access_token: str, salesorder_id: str):
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/comments",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch comments", "zoho_response": response.json()},
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
                "comments_html_format": c.get("comments_html_format"),
            })

        return result

    def add_comment(
        self,
        access_token: str,
        salesorder_id: str,
        description: str,
        email: str | None = None,
        show_to_client: bool = True,
    ):
        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/comments",
            headers=self._json_headers(access_token),
            json={
                "description": build_comment_meta(email=email) + description,
                "show_comment_to_clients": show_to_client,
            },
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to add comment", "zoho_response": response.json()},
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return response.json()

    def update_comment(
        self,
        access_token: str,
        salesorder_id: str,
        comment_id: str,
        description: str,
        email: str | None = None,
    ):
        meta_block = build_comment_meta(email=email)
        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}/comments/{comment_id}",
            headers=self._json_headers(access_token),
            json={"description": meta_block + description},
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to update comment", "zoho_response": response.json()},
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return response.json()

    def delete_comment(self, access_token: str, salesorder_id: str, comment_id: str):
        response = requests.delete(
            f"{self.base_url}/salesorders/{salesorder_id}/comments/{comment_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to delete comment", "zoho_response": response.json()},
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)
        return {"message": "Comment deleted successfully"}

    # -------------------------------------------------
    # Vendor Shipment Details
    # -------------------------------------------------
    def get_vendor_shipment_details(
        self, access_token: str, salesorder_id: str, contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)

        # Use cached SO for the permission check — avoids a duplicate GET
        salesorder = self._get_order_status(access_token, salesorder_id)

        if salesorder.get("customer_id") != contact_id:
            raise HTTPException(status_code=403, detail="Unauthorized access")

        pkg_resp = requests.get(
            f"{self.base_url}/packages",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "salesorder_id": salesorder_id},
            timeout=15,
        )

        if pkg_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=pkg_resp.text)

        related_packages = pkg_resp.json().get("packages", [])

        if not related_packages:
            return {"message": "No shipment created for this Sales Order"}

        valid_status = {"shipped", "delivered", "partially_shipped"}
        shipped_packages = [p for p in related_packages if p.get("status", "").lower() in valid_status]

        if not shipped_packages:
            return {"message": "Sales Order not shipped yet"}

        latest_package = shipped_packages[-1]
        return {"salesorder_id": salesorder_id, "status": latest_package.get("status")}

    # -------------------------------------------------
    # GRN → Purchase Order sync
    # -------------------------------------------------
    def send_grn_to_purchase_order(
        self, access_token: str, salesorder_id: str, salesorder: dict
    ):
        headers = self._auth_headers(access_token)
        salesorder_number = salesorder.get("salesorder_number")

        po = self._find_po_by_salesorder(access_token, salesorder_number)
        if not po:
            raise HTTPException(404, "Purchase Order not found for this Sales Order")

        po_id = po.get("purchaseorder_id")

        # Find GRN attachment
        grn_doc = next(
            (doc for doc in reversed(salesorder.get("documents", []))
             if "_grn" in (doc.get("file_name") or "").lower()),
            None,
        )
        if not grn_doc:
            raise HTTPException(404, "GRN attachment not found in Sales Order")

        document_id = grn_doc.get("document_id")
        file_name = grn_doc.get("file_name")

        # Download GRN file from Sales Order
        file_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if file_resp.status_code != 200 or not file_resp.content:
            raise HTTPException(400, "Failed to download GRN file")

        # Fetch PO details once — used for both old-GRN deletion and new upload
        po_details_resp = requests.get(
            f"{self.base_url}/purchaseorders/{po_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if po_details_resp.status_code == 200:
            po_documents = po_details_resp.json().get("purchaseorder", {}).get("documents", [])
            for doc in po_documents:
                existing_name = (doc.get("file_name") or "").lower()
                if "_grn" not in existing_name:
                    continue
                requests.delete(
                    f"{self.base_url}/purchaseorders/{po_id}/documents/{doc.get('document_id')}",
                    headers=headers,
                    params={"organization_id": self.org_id},
                    timeout=15,
                )

        # Upload new GRN to Purchase Order
        upload_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/attachment",
            headers=headers,
            params={"organization_id": self.org_id},
            files={"attachment": (file_name, file_resp.content, "application/pdf")},
            timeout=30,
        )

        if upload_resp.status_code not in (200, 201):
            raise HTTPException(
                400,
                {"message": "Failed to upload GRN to Purchase Order", "zoho_response": upload_resp.text},
            )

        return {
            "message": "GRN sent to supplier Purchase Order",
            "purchaseorder_id": po_id,
            "file_name": file_name,
        }

    # -------------------------------------------------
    # E-Way Bill PDF
    # -------------------------------------------------
    def get_eway_bill_pdf(self, access_token: str, salesorder_id: str) -> bytes:
        # Use cached SO to avoid a fresh GET just for the document list
        salesorder = self._get_order_status(access_token, salesorder_id)
        documents = salesorder.get("documents", [])

        document_id = next(
            (doc.get("document_id") for doc in reversed(documents)
             if "eway_bill" in doc.get("file_name", "").lower()),
            None,
        )

        if not document_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="E-Way Bill not found for this Sales Order",
            )

        file_response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if file_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Failed to download E-Way Bill",
            )

        return file_response.content

    # -------------------------------------------------
    # Create PO from Sales Order
    # -------------------------------------------------
    def create_po_with_grn(
        self, access_token: str, salesorder_id: str, created_by: str | None = None
    ):
        headers = self._json_headers(access_token)

        # Single fetch — used for vendor extraction, line items, PO lookup, and attachment
        salesorder = self._get_order_status(access_token, salesorder_id)
        salesorder_number = salesorder.get("salesorder_number")

        existing_po = self._find_po_by_salesorder(access_token, salesorder_number)
        if existing_po:
            return self._update_po_attachment(
                access_token=access_token,
                po_id=existing_po.get("purchaseorder_id"),
                salesorder=salesorder,
                salesorder_id=salesorder_id,
            )

        vendor_id = next(
            (f.get("value") for f in salesorder.get("custom_fields", [])
             if f.get("api_name") == "cf_supplier"),
            None,
        )

        if not vendor_id:
            raise HTTPException(status_code=400, detail="Supplier not set on this Sales Order")

        po_items = [
            {
                "item_id": item.get("item_id"),
                "rate": item.get("rate"),
                "quantity": item.get("quantity"),
                "name": item.get("name"),
                "tax_exemption_code": "NON",
            }
            for item in salesorder.get("line_items", [])
        ]

        if not po_items:
            raise HTTPException(status_code=400, detail="Sales Order has no line items")

        po_resp = requests.post(
            f"{self.base_url}/purchaseorders",
            headers=headers,
            params={"organization_id": self.org_id},
            json={
                "vendor_id": vendor_id,
                "reference_number": salesorder_number,
                "line_items": po_items,
                "notes": f"Created from Sales Order {salesorder_number}",
            },
            timeout=15,
        )

        if po_resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Failed to create purchase order")

        purchaseorder = po_resp.json().get("purchaseorder", {})
        po_id = purchaseorder.get("purchaseorder_id")

        issue_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/status/issued",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if issue_resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Failed to mark PO issued")

        # Find PO attachment in the already-fetched salesorder — no extra GET
        po_document = next(
            (doc for doc in reversed(salesorder.get("documents", []))
             if "_po" in doc.get("file_name", "")),
            None,
        )

        if not po_document:
            raise HTTPException(status_code=404, detail="No PO attachment found on Sales Order")

        file_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{po_document['document_id']}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if file_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to download PO attachment")

        upload_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/attachment",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            files={"attachment": (po_document["file_name"], file_resp.content, "application/pdf")},
            timeout=30,
        )

        if upload_resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Failed to attach PO document to Purchase Order")

        return {
            "message": "Purchase Order created with user uploaded PO attachment",
            "purchaseorder_id": po_id,
        }

    # -------------------------------------------------
    # Create Sales Order from Quote
    # -------------------------------------------------
    def create_salesorder_from_quote(self, access_token: str, estimate_id: str):
        headers = self._json_headers(access_token)

        quote_resp = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if quote_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch quote")

        estimate = quote_resp.json().get("estimate", {})

        if estimate.get("status") != "accepted":
            raise HTTPException(400, "Sales order can only be created from accepted quotes")

        supplier_id = next(
            (f.get("value") for f in estimate.get("custom_fields", [])
             if f.get("api_name") == "cf_supplier"),
            None,
        )

        if not supplier_id:
            raise HTTPException(status_code=400, detail="Supplier not set on this Quote")

        # Fetch supplier details (needed for cf_supplier_details)
        supplier_resp = requests.get(
            f"{self.base_url}/contacts/{supplier_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if supplier_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch supplier details")

        supplier = supplier_resp.json().get("contact", {})
        company_name = supplier.get("company_name", "")
        billing = supplier.get("billing_address", {})
        billing_address = ", ".join(
            part for part in [
                billing.get("address"), billing.get("street2"), billing.get("city"),
                billing.get("state"), billing.get("zip"), billing.get("country"),
            ] if part
        )
        supplier_details = f"{company_name}\n{billing_address}"

        customer_id = estimate.get("customer_id")
        estimate_number = estimate.get("estimate_number")

        if not customer_id:
            raise HTTPException(400, "Quote has no customer")

        line_items = []
        for item in estimate.get("line_items", []):
            item_id = item.get("item_id")
            quantity = item.get("quantity")
            if not item_id or not quantity:
                raise HTTPException(400, "Invalid item in quote")
            line_items.append({
                "item_id": item_id,
                "quantity": quantity,
                "rate": item.get("rate"),
            })

        if not line_items:
            raise HTTPException(400, "Quote has no items")

        create_resp = requests.post(
            f"{self.base_url}/salesorders",
            headers=headers,
            params={"organization_id": self.org_id},
            json={
                "customer_id": customer_id,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "reference_number": estimate_number,
                "line_items": line_items,
                "notes": f"Created automatically from Quote {estimate_number}",
                "custom_fields": [
                    {"api_name": "cf_supplier", "value": supplier_id},
                    {"api_name": "cf_supplier_details", "value": supplier_details},
                ],
            },
            timeout=15,
        )

        if create_resp.status_code not in (200, 201):
            raise HTTPException(400, create_resp.text)

        salesorder = create_resp.json().get("salesorder")
        if not salesorder:
            raise HTTPException(400, "Sales order creation failed")

        salesorder_id = salesorder.get("salesorder_id")
        self.mark_salesorder_open(access_token, salesorder_id)
        salesorder["status"] = "open"

        return salesorder

    def mark_salesorder_open(self, access_token: str, salesorder_id: str):
        resp = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/status/open",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Failed to mark sales order as open")

        return resp.json()

    # -------------------------------------------------
    # Supplier Details
    # -------------------------------------------------
    def get_supplier_details(self, access_token: str, salesorder_id: str):
        salesorder = self._get_order_status(access_token, salesorder_id)
        return self._extract_supplier_from_custom_fields(salesorder.get("custom_fields", []))

    # -------------------------------------------------
    # Tracking Data
    # -------------------------------------------------
    def get_tracking_data(self, access_token: str, salesorder_id: str):
        salesorder = self._get_order_status(access_token, salesorder_id)

        if "invoiced" not in (salesorder.get("status") or "").lower():
            raise HTTPException(403, "Tracking available only after invoice")

        salesorder_number = salesorder.get("salesorder_number")
        po = self._find_po_by_salesorder(access_token, salesorder_number)

        if not po:
            raise HTTPException(404, "Purchase Order not found")

        po_resp = requests.get(
            f"{self.base_url}/purchaseorders/{po['purchaseorder_id']}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if po_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch Purchase Order")

        purchaseorder = po_resp.json().get("purchaseorder", {})

        tracking_id = None
        carrier = None
        for field in purchaseorder.get("custom_fields", []):
            api_name = field.get("api_name")
            if api_name == "cf_tracking":
                tracking_id = field.get("value") or field.get("display_value")
            elif api_name == "cf_carrier":
                carrier = field.get("value") or field.get("display_value")

        return {"tracking_id": tracking_id, "carrier": carrier}

    # -------------------------------------------------
    # Purchase Order helpers
    # -------------------------------------------------
    def _find_po_by_salesorder(self, access_token: str, salesorder_number: str):
        resp = requests.get(
            f"{self.base_url}/purchaseorders",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "reference_number": salesorder_number},
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to search purchase orders")

        purchaseorders = resp.json().get("purchaseorders", [])
        return purchaseorders[0] if purchaseorders else None

    def _update_po_attachment(
        self, access_token: str, po_id: str, salesorder: dict, salesorder_id: str
    ):
        self._delete_po_attachments(access_token, po_id)

        po_document = next(
            (doc for doc in reversed(salesorder.get("documents", []))
             if "_po" in doc.get("file_name", "")),
            None,
        )

        if not po_document:
            raise HTTPException(status_code=404, detail="PO attachment not found on Sales Order")

        file_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{po_document['document_id']}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=30,
        )

        if file_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to download updated PO attachment")

        upload_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/attachment",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            files={"attachment": (po_document["file_name"], file_resp.content, "application/pdf")},
            timeout=30,
        )

        if upload_resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Failed to update PO attachment")

        return {
            "message": "PO updated and new attachment sent to supplier",
            "purchaseorder_id": po_id,
        }

    def _delete_po_attachments(self, access_token: str, po_id: str):
        resp = requests.get(
            f"{self.base_url}/purchaseorders/{po_id}",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id},
            timeout=15,
        )

        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Purchase Order attachments")

        documents = resp.json().get("purchaseorder", {}).get("documents", [])
        for doc in documents:
            if "_po" not in doc.get("file_name", ""):
                continue
            requests.delete(
                f"{self.base_url}/purchaseorders/{po_id}/documents/{doc['document_id']}",
                headers=self._auth_headers(access_token),
                params={"organization_id": self.org_id},
                timeout=15,
            )

    # -------------------------------------------------
    # SO lookup by estimate number (idempotency guard)
    # -------------------------------------------------
    def _find_so_by_estimate_number(self, access_token: str, estimate_number: str) -> dict | None:
        if not estimate_number:
            return None

        resp = requests.get(
            f"{self.base_url}/salesorders",
            headers=self._auth_headers(access_token),
            params={"organization_id": self.org_id, "reference_number": estimate_number},
            timeout=15,
        )

        if resp.status_code != 200:
            return None

        orders = resp.json().get("salesorders", [])
        return orders[0] if orders else None

    # -------------------------------------------------
    # Item cache (shared with quote/invoice services)
    # -------------------------------------------------
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
    # Tracking helpers (kept for any direct callers)
    # -------------------------------------------------
    def get_tracking_details(self, salesorder: dict):
        tracking_id = None
        carrier = None
        for field in salesorder.get("custom_fields", []):
            api_name = field.get("api_name")
            if api_name == "cf_tracking":
                tracking_id = field.get("value") or field.get("display_value")
            elif api_name == "cf_carrier":
                carrier = field.get("value") or field.get("display_value")
        return {"tracking_id": tracking_id, "carrier": carrier}