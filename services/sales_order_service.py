import requests
from fastapi import HTTPException, status
import config
import base64
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache
from fastapi import UploadFile
from datetime import datetime


class SalesOrderService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    def _build_filename(self, salesorder: dict, file: UploadFile, doc_type: str) -> str:
        salesorder_number = salesorder.get("salesorder_number", "")
        clean_number = salesorder_number.lower().replace("-", "_")
        extension = file.filename.split(".")[-1] if "." in file.filename else "pdf"
        return f"{clean_number}_{doc_type}.{extension}"
    
    def upload_po_attachment(
        self,
        access_token: str,
        salesorder_id: str,
        file: UploadFile,
        po_number: str,
        uploaded_by: str | None = None
    ):
        # ✅ Fetch current order status properly
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_po(salesorder.get("status"))

        # ✅ STEP 1: Update PO custom field
        self.update_po_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            po_number=po_number
        )

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        file.file.seek(0)

        new_filename = self._build_filename(
            salesorder=salesorder,
            file=file,
            doc_type="po"
        )

        files = {
            "attachment": (
                new_filename,
                file.file,
                file.content_type or "application/pdf"
            )
        }

        # ✅ STEP 2: Upload file
        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment",
            headers=headers,
            files=files,
            params={"organization_id": self.org_id},
            timeout=30
        )

        print("🔎 Zoho upload status:", response.status_code)
        print("🔎 Zoho upload response:", response.text)

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code not in (200, 201) or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Failed to upload PO attachment",
                    "zoho_response": data
                }
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
        uploaded_by: str | None = None
    ):
        # 1️⃣ Fetch sales order
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_grn(salesorder)

        # 2️⃣ Update GRN custom field
        self.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=cf_grn_number
        )

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 3️⃣ Prepare file
        file.file.seek(0)

        new_filename = self._build_filename(
            salesorder=salesorder,
            file=file,
            doc_type="grn"
        )

        files = {
            "attachment": (
                new_filename,
                file.file,
                file.content_type or "application/pdf"
            )
        }

        # 4️⃣ Upload GRN to Sales Order
        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment",
            headers=headers,
            files=files,
            params={"organization_id": self.org_id},
            timeout=30
        )

        print("🔎 Zoho upload status:", response.status_code)
        print("🔎 Zoho upload response:", response.text)

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code not in (200, 201) or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to upload GRN attachment",
                    "zoho_response": data
                }
            )

        # 5️⃣ Add comment
        if uploaded_by:
            try:
                meta_block = build_comment_meta(email=uploaded_by)

                comment_payload = {
                    "description": (
                        meta_block +
                        f"GRN Uploaded\n"
                        f"GRN Number: {cf_grn_number}\n"
                        f"File: {file.filename}"
                    ),
                    "show_comment_to_clients": True
                }

                comment_response = requests.post(
                    f"{self.base_url}/salesorders/{salesorder_id}/comments",
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "Content-Type": "application/json"
                    },
                    params={"organization_id": self.org_id},
                    json=comment_payload,
                    timeout=15
                )

                if comment_response.status_code not in (200, 201):
                    print("⚠️ Comment failed:", comment_response.text)

            except Exception as e:
                print("⚠️ Comment error:", str(e))

        # 6️⃣ 🔥 SEND GRN TO SUPPLIER PO
        po_sync_success = False

        try:
            # Refetch latest SO (important to get new attachment)
            salesorder = self._get_order_status(access_token, salesorder_id)

            self.send_grn_to_purchase_order(
                access_token=access_token,
                salesorder_id=salesorder_id,
                salesorder=salesorder
            )

            po_sync_success = True

        except Exception as e:
            print("⚠️ GRN sync to PO failed:", str(e))

        # 7️⃣ Clear cache
        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        # 8️⃣ Return proper response
        return {
            "message": (
                "GRN uploaded successfully and sent to supplier"
                if po_sync_success
                else "GRN uploaded successfully (PO sync failed)"
            ),
            "salesorder_id": salesorder_id,
            "grn_number": cf_grn_number,
            "file_name": new_filename,
            "po_synced": po_sync_success
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
        uploaded_by: str | None = None
    ):
        # 1️⃣ Fetch order
        salesorder = self._get_order_status(access_token, salesorder_id)

        # 2️⃣ Validate GRN rules
        self._validate_status_for_grn(salesorder)

        # 3️⃣ Delete old GRN file (if exists)
        try:
            self.delete_attachment_by_prefix(
                access_token=access_token,
                salesorder_id=salesorder_id,
                prefix="_grn"
            )
        except HTTPException:
            pass  # ignore if no GRN exists

        # 4️⃣ Update GRN number
        self.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=cf_grn_number
        )

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 5️⃣ Upload new GRN file
        file.file.seek(0)

        new_filename = self._build_filename(
            salesorder=salesorder,
            file=file,
            doc_type="grn"
        )

        files = {
            "attachment": (
                new_filename,
                file.file,
                file.content_type or "application/pdf"
            )
        }

        response = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment",
            headers=headers,
            files=files,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=400,
                detail="Failed to upload updated GRN file"
            )

        # 6️⃣ Add comment (safe)
        if uploaded_by:
            try:
                meta_block = build_comment_meta(email=uploaded_by)

                comment_payload = {
                    "description": (
                        meta_block +
                        f"GRN Updated\n"
                        f"New GRN Number: {cf_grn_number}\n"
                        f"File: {file.filename}"
                    ),
                    "show_comment_to_clients": True
                }

                comment_resp = requests.post(
                    f"{self.base_url}/salesorders/{salesorder_id}/comments",
                    headers={
                        "Authorization": f"Zoho-oauthtoken {access_token}",
                        "Content-Type": "application/json"
                    },
                    params={"organization_id": self.org_id},
                    json=comment_payload,
                    timeout=15
                )

                if comment_resp.status_code not in (200, 201):
                    print("⚠️ Comment failed:", comment_resp.text)

            except Exception as e:
                print("⚠️ Comment error:", str(e))

        # 7️⃣ 🔥 SEND UPDATED GRN TO SUPPLIER PO (CRITICAL FIX)
        po_sync_success = False

        try:
            # Refetch to get latest GRN attachment
            salesorder = self._get_order_status(access_token, salesorder_id)

            self.send_grn_to_purchase_order(
                access_token=access_token,
                salesorder_id=salesorder_id,
                salesorder=salesorder
            )

            po_sync_success = True

        except Exception as e:
            print("⚠️ GRN update sync to PO failed:", str(e))

        # 8️⃣ Clear cache
        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        # 9️⃣ Return proper response
        return {
            "message": (
                "GRN updated successfully and synced to supplier"
                if po_sync_success
                else "GRN updated successfully (PO sync failed)"
            ),
            "salesorder_id": salesorder_id,
            "grn_number": cf_grn_number,
            "file_name": new_filename,
            "po_synced": po_sync_success
        }

    def update_grn_number_field(
        self,
        access_token: str,
        salesorder_id: str,
        grn_number: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            json={
                "custom_fields": [
                    {
                        "api_name": "cf_grn_number",  # Make sure this matches Zoho API name
                        "value": grn_number
                    }
                ]
            },
            timeout=15
        )

        data = response.json()

        if response.status_code != 200 or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to update GRN number field",
                    "zoho_response": data
                }
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        return response.json()

    def get_grn_data(self, access_token: str, salesorder_id: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(
                f"{self.base_url}/salesorders/{salesorder_id}",
                headers=headers,
                params={
                    "organization_id": self.org_id,
                    "customer_id": contact_id,
                },
                timeout=15
            )

        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch sales order")

        salesorder = response.json().get("salesorder", {})

        # 1️⃣ Extract GRN number
        grn_number = ""

        for field in salesorder.get("custom_fields", []):
            if field.get("api_name") == "cf_grn_number":
                grn_number = field.get("value", "")
                break

        # 2️⃣ Extract GRN attachment
        grn_attachment = None

        documents = salesorder.get("documents", [])

        for doc in reversed(documents):
            if "_grn" in doc.get("file_name", ""):
                grn_attachment = {
                    "attachment_id": doc.get("document_id"),
                    "file_name": doc.get("file_name"),
                    "file_size": doc.get("file_size"),
                    "uploaded_on": doc.get("uploaded_on")
                }
                break

        return {
            "grn_number": grn_number,
            "attachment": grn_attachment
        }

    def _get_order_status(self, access_token: str, salesorder_id: str) -> dict:
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={
                "organization_id": self.org_id
            },
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to fetch sales order status"
            )

        salesorder = response.json().get("salesorder", {})

        print("🔥 status:", salesorder.get("status"))
        return salesorder

    def _validate_status_for_po(self, order_status: str | None):
        if not order_status:
            return

        if order_status.lower() in ["packed", "shipped"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PO cannot be updated when order status is '{order_status}'"
            )

    def _validate_status_for_grn(self, salesorder):
        return

    def get_attachment_pdf_by_prefix(
        self,
        access_token: str,
        salesorder_id: str,
        prefix: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # Step 1: Fetch sales order
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Sales order not found")

        salesorder = response.json().get("salesorder", {})
        documents = salesorder.get("documents", [])

        document_id = None

        for doc in reversed(documents):
            filename = doc.get("file_name", "")
            if prefix in filename:
                document_id = doc.get("document_id")
                break

        if not document_id:
            raise HTTPException(
                status_code=404,
                detail=f"No attachment found with prefix '{prefix}'"
            )

        # Step 2: Download file
        file_response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if file_response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to download attachment from Zoho"
            )

        if not file_response.content:
            raise HTTPException(
                status_code=404,
                detail="Attachment file is empty"
            )

        return file_response.content

    def download_attachment(
        self,
        access_token: str,
        salesorder_id: str,
        attachment_id: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{attachment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to download attachment"
            )

        return response.content

    def delete_attachment_by_prefix(
        self,
        access_token: str,
        salesorder_id: str,
        prefix: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 1️⃣ Fetch sales order to get documents
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Sales order not found")

        salesorder = response.json().get("salesorder", {})
        documents = salesorder.get("documents", [])

        document_id = None

        # 2️⃣ Find latest file with prefix
        for doc in reversed(documents):  # latest first
            filename = doc.get("file_name", "")
            if prefix in filename:
                document_id = doc.get("document_id")
                break

        if not document_id:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # 3️⃣ Delete using existing method
        return self.delete_attachment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            attachment_id=document_id
        )

    def delete_attachment(
        self,
        access_token: str,
        salesorder_id: str,
        attachment_id: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.delete(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{attachment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        print("🔎 DELETE STATUS:", response.status_code)
        print("🔎 DELETE RESPONSE:", response.text)

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code != 200 or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Failed to delete attachment",
                    "zoho_response": data
                }
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        return {"message": "Attachment deleted successfully"}

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
            params={
                "organization_id": self.org_id,
                "customer_id": contact_id,
                "include": "custom_fields"
            },
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

        for order in orders:
            supplier_data = self.get_supplier_details(
                access_token,
                order.get("salesorder_id")
            )
            order["supplier"] = supplier_data

        cache.set(cache_key, orders)
        return orders

    # -------------------------------------------------
    # Get Sales Order
    # -------------------------------------------------
    def get_order(self, access_token: str, salesorder_id: str, contact_id: str):
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
                detail="Failed to fetch sales order"
            )

        salesorder = response.json().get("salesorder", {})

        supplier_data = self.get_supplier_details(
            access_token,
            salesorder_id
        )

        salesorder["supplier"] = supplier_data

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
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Accept": "application/pdf"
        }
        params = {"organization_id": self.org_id}

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
                "description": build_comment_meta(email=email) + description,
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

    def get_vendor_shipment_details(
        self,
        access_token: str,
        salesorder_id: str,
        contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 1️⃣ Fetch Sales Order
        so_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if so_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=so_resp.text)

        salesorder = so_resp.json().get("salesorder", {})

        # 2️⃣ Security check
        if salesorder.get("customer_id") != contact_id:
            raise HTTPException(status_code=403, detail="Unauthorized access")

        # 2️⃣ Fetch packages separately
        pkg_resp = requests.get(
            f"{self.base_url}/packages",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if pkg_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=pkg_resp.text)

        all_packages = pkg_resp.json().get("packages", [])

        # 3️⃣ Filter packages for this salesorder
        related_packages = [
            p for p in all_packages
            if p.get("salesorder_id") == salesorder_id
        ]

        if not related_packages:
            return {"message": "No shipment created for this Sales Order"}

        # 4️⃣ Filter shipped
        valid_status = ["shipped", "delivered", "partially_shipped"]

        shipped_packages = [
            p for p in related_packages
            if p.get("status", "").lower() in valid_status
        ]

        if not shipped_packages:
            return {"message": "Sales Order not shipped yet"}

        latest_package = shipped_packages[-1]

        return {
            "salesorder_id": salesorder_id,
            "status": latest_package.get("status")
        }
    
    def send_grn_to_purchase_order(
        self,
        access_token: str,
        salesorder_id: str,
        salesorder: dict
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 1️⃣ Find Purchase Order using reference_number
        salesorder_number = salesorder.get("salesorder_number")

        po = self._find_po_by_salesorder(access_token, salesorder_number)

        if not po:
            raise HTTPException(404, "Purchase Order not found for this Sales Order")

        po_id = po.get("purchaseorder_id")

        # 2️⃣ Find GRN attachment in Sales Order
        documents = salesorder.get("documents", [])

        grn_doc = None
        for doc in reversed(documents):  # latest first
            file_name = (doc.get("file_name") or "").lower()
            if "_grn" in file_name:
                grn_doc = doc
                break

        if not grn_doc:
            raise HTTPException(404, "GRN attachment not found in Sales Order")

        document_id = grn_doc.get("document_id")
        file_name = grn_doc.get("file_name")

        # 3️⃣ Download GRN file from Sales Order
        file_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if file_resp.status_code != 200 or not file_resp.content:
            raise HTTPException(400, "Failed to download GRN file")

        # 4️⃣ 🔥 DELETE OLD GRN FILES FROM PO (IMPORTANT)
        try:
            po_details_resp = requests.get(
                f"{self.base_url}/purchaseorders/{po_id}",
                headers=headers,
                params={"organization_id": self.org_id},
                timeout=15
            )

            if po_details_resp.status_code == 200:
                po_data = po_details_resp.json().get("purchaseorder", {})
                po_documents = po_data.get("documents", [])

                for doc in po_documents:
                    existing_name = (doc.get("file_name") or "").lower()

                    # delete only GRN files
                    if "_grn" not in existing_name:
                        continue

                    doc_id = doc.get("document_id")

                    del_resp = requests.delete(
                        f"{self.base_url}/purchaseorders/{po_id}/documents/{doc_id}",
                        headers=headers,
                        params={"organization_id": self.org_id},
                        timeout=15
                    )

                    print(f"🗑️ Deleted old GRN from PO: {existing_name}")
                    print("Delete response:", del_resp.text)

        except Exception as e:
            print("⚠️ Failed deleting old GRN in PO:", str(e))

        # 5️⃣ Upload new GRN to Purchase Order
        files = {
            "attachment": (
                file_name,
                file_resp.content,
                "application/pdf"
            )
        }

        upload_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/attachment",
            headers=headers,
            params={"organization_id": self.org_id},
            files=files,
            timeout=30
        )

        if upload_resp.status_code not in (200, 201):
            raise HTTPException(
                400,
                {
                    "message": "Failed to upload GRN to Purchase Order",
                    "zoho_response": upload_resp.text
                }
            )

        return {
            "message": "GRN sent to supplier Purchase Order",
            "purchaseorder_id": po_id,
            "file_name": file_name
        }

    # -------------------------------------------------
    # Get E-Way Bill PDF from Sales Order
    # -------------------------------------------------
    def get_eway_bill_pdf(self, access_token: str, salesorder_id: str) -> bytes:
        """
        Returns the E-Way Bill PDF bytes uploaded against this sales order.
        Searches for any attachment whose filename contains 'eway_bill'.
        """
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        # Fetch sales order to get document list
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Sales order not found")

        salesorder = response.json().get("salesorder", {})
        documents = salesorder.get("documents", [])

        # Find latest file whose name contains 'eway_bill'
        document_id = None
        for doc in reversed(documents):
            filename = doc.get("file_name", "").lower()
            if "eway_bill" in filename:
                document_id = doc.get("document_id")
                break

        if not document_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="E-Way Bill not found for this Sales Order"
            )

        # Download the file
        file_response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if file_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Failed to download E-Way Bill"
            )

        return file_response.content

    # -------------------------------------------------
    # Create PO with GRN
    # -------------------------------------------------
    def create_po_with_grn(
        self,
        access_token: str,
        salesorder_id: str,
        created_by: str | None = None
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # 1️⃣ Get Sales Order
        so_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if so_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Unable to fetch sales order")

        salesorder = so_resp.json().get("salesorder", {})

        # CHECK IF PURCHASE ORDER ALREADY EXISTS
        salesorder_number = salesorder.get("salesorder_number")

        existing_po = self._find_po_by_salesorder(
            access_token,
            salesorder_number
        )

        # If PO exists → update attachment instead of creating new one
        if existing_po:
            po_id = existing_po.get("purchaseorder_id")

            return self._update_po_attachment(
                access_token=access_token,
                po_id=po_id,
                salesorder=salesorder,
                salesorder_id=salesorder_id
            )

        # 2️⃣ Extract Vendor
        vendor_id = None

        for field in salesorder.get("custom_fields", []):
            if field.get("api_name") == "cf_supplier":
                vendor_id = field.get("value")
                break

        if not vendor_id:
            raise HTTPException(
                status_code=400,
                detail="Supplier not set on this Sales Order"
            )

        # 3️⃣ Prepare PO items
        po_items = []

        for item in salesorder.get("line_items", []):
            po_items.append({
                "item_id": item.get("item_id"),
                "rate": item.get("rate"),
                "quantity": item.get("quantity"),
                "name": item.get("name"),
                "tax_exemption_code": "NON"
            })

        if not po_items:
            raise HTTPException(
                status_code=400,
                detail="Sales Order has no line items"
            )

        # 4️⃣ Create Purchase Order
        po_resp = requests.post(
            f"{self.base_url}/purchaseorders",
            headers=headers,
            params={"organization_id": self.org_id},
            json={
                "vendor_id": vendor_id,
                "reference_number": salesorder.get("salesorder_number"),
                "line_items": po_items,
                "notes": f"Created from Sales Order {salesorder.get('salesorder_number')}"
            },
            timeout=15
        )

        if po_resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=400,
                detail="Failed to create purchase order"
            )

        purchaseorder = po_resp.json().get("purchaseorder", {})
        po_id = purchaseorder.get("purchaseorder_id")

        # 5️⃣ Mark PO issued
        issue_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/status/issued",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": self.org_id},
            timeout=15
        )

        if issue_resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=400,
                detail="Failed to mark PO issued"
            )

        # 6️⃣ Find PO attachment in Sales Order
        documents = salesorder.get("documents", [])

        po_document = None

        for doc in reversed(documents):
            if "_po" in doc.get("file_name", ""):
                po_document = doc
                break

        if not po_document:
            raise HTTPException(
                status_code=404,
                detail="No PO attachment found on Sales Order"
            )

        document_id = po_document.get("document_id")
        file_name = po_document.get("file_name")

        # 7️⃣ Download attachment
        file_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": self.org_id},
            timeout=30
        )

        if file_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to download PO attachment"
            )

        file_bytes = file_resp.content

        # 8️⃣ Attach to Purchase Order
        files = {
            "attachment": (
                file_name,
                file_bytes,
                "application/pdf"
            )
        }

        upload_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/attachment",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"organization_id": self.org_id},
            files=files,
            timeout=30
        )

        if upload_resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=400,
                detail="Failed to attach PO document to Purchase Order"
            )

        return {
            "message": "Purchase Order created with user uploaded PO attachment",
            "purchaseorder_id": po_id
        }

    def _find_po_by_salesorder(self, access_token: str, salesorder_number: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        resp = requests.get(
            f"{self.base_url}/purchaseorders",
            headers=headers,
            params={
                "organization_id": self.org_id,
                "reference_number": salesorder_number
            },
            timeout=15
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to search purchase orders"
            )

        purchaseorders = resp.json().get("purchaseorders", [])

        if purchaseorders:
            return purchaseorders[0]

        return None

    def _update_po_attachment(
        self,
        access_token: str,
        po_id: str,
        salesorder: dict,
        salesorder_id: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 1️⃣ Delete existing attachments from PO
        self._delete_po_attachments(access_token, po_id)

        # 2️⃣ Find PO file in Sales Order
        documents = salesorder.get("documents", [])

        po_document = None

        for doc in reversed(documents):
            if "_po" in doc.get("file_name", ""):
                po_document = doc
                break

        if not po_document:
            raise HTTPException(
                status_code=404,
                detail="PO attachment not found on Sales Order"
            )

        document_id = po_document.get("document_id")
        file_name = po_document.get("file_name")

        # 3️⃣ Download file from Sales Order
        file_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/documents/{document_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if file_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to download updated PO attachment"
            )

        # 4️⃣ Upload to Purchase Order
        files = {
            "attachment": (
                file_name,
                file_resp.content,
                "application/pdf"
            )
        }

        upload_resp = requests.post(
            f"{self.base_url}/purchaseorders/{po_id}/attachment",
            headers=headers,
            params={"organization_id": self.org_id},
            files=files,
            timeout=30
        )

        if upload_resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=400,
                detail="Failed to update PO attachment"
            )

        return {
            "message": "PO updated and new attachment sent to supplier",
            "purchaseorder_id": po_id
        }
    
    def update_po_number_field(
        self,
        access_token: str,
        salesorder_id: str,
        po_number: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.put(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            json={
                "custom_fields": [
                    {
                        "api_name": "cf_customer_po_no",  # ✅ your PO field
                        "value": po_number
                    }
                ]
            },
            timeout=15
        )

        data = response.json()

        if response.status_code != 200 or data.get("code") not in (0, None):
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Failed to update PO number field",
                    "zoho_response": data
                }
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        return data
    
    def delete_po_number_field(
        self,
        access_token: str,
        salesorder_id: str
    ):
        return self.update_po_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            po_number=None
        )

    def _delete_po_attachments(self, access_token: str, po_id: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 1️⃣ Get Purchase Order details
        resp = requests.get(
            f"{self.base_url}/purchaseorders/{po_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to fetch Purchase Order attachments"
            )

        purchaseorder = resp.json().get("purchaseorder", {})
        documents = purchaseorder.get("documents", [])

        # 2️⃣ Delete only PO attachment
        for doc in documents:
            file_name = doc.get("file_name", "")

            # Only delete files with "_po"
            if "_po" not in file_name:
                continue

            document_id = doc.get("document_id")

            del_resp = requests.delete(
                f"{self.base_url}/purchaseorders/{po_id}/documents/{document_id}",
                headers=headers,
                params={"organization_id": self.org_id},
                timeout=15
            )

            print("Deleting PO attachment:", file_name)
            print("Delete response:", del_resp.text)

    def create_salesorder_from_quote(self, access_token: str, estimate_id: str):

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # 1️⃣ Fetch Quote
        quote_resp = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if quote_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch quote")

        estimate = quote_resp.json().get("estimate", {})

        supplier_id = None

        for field in estimate.get("custom_fields", []):
            if field.get("api_name") == "cf_supplier":
                supplier_id = field.get("value")
                break

        if not supplier_id:
            raise HTTPException(
                status_code=400,
                detail="Supplier not set on this Quote"
            )

        supplier_resp = requests.get(
            f"{self.base_url}/contacts/{supplier_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if supplier_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch supplier details")

        supplier = supplier_resp.json().get("contact", {})

        company_name = supplier.get("company_name", "")

        billing = supplier.get("billing_address", {})

        address_parts = [
            billing.get("address"),
            billing.get("street2"),
            billing.get("city"),
            billing.get("state"),
            billing.get("zip"),
            billing.get("country"),
        ]

        billing_address = ", ".join(part for part in address_parts if part)

        supplier_details = f"{company_name}\n{billing_address}"

        if estimate.get("status") != "accepted":
            raise HTTPException(
                400,
                "Sales order can only be created from accepted quotes"
            )

        customer_id = estimate.get("customer_id")
        estimate_number = estimate.get("estimate_number")

        if not customer_id:
            raise HTTPException(400, "Quote has no customer")

        # 2️⃣ Build Line Items
        line_items = []

        for item in estimate.get("line_items", []):
            item_id = item.get("item_id")
            quantity = item.get("quantity")
            rate = item.get("rate")

            if not item_id or not quantity:
                raise HTTPException(400, "Invalid item in quote")

            line_items.append({
                "item_id": item_id,
                "quantity": quantity,
                "rate": rate
            })

        if not line_items:
            raise HTTPException(400, "Quote has no items")

        # 3️⃣ Create Sales Order
        payload = {
            "customer_id": customer_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "reference_number": estimate_number,
            "line_items": line_items,
            "notes": f"Created automatically from Quote {estimate_number}",
            "custom_fields": [
                {
                    "api_name": "cf_supplier",
                    "value": supplier_id
                },
                {
                    "api_name": "cf_supplier_details",
                    "value": supplier_details
                }
            ]
        }

        create_resp = requests.post(
            f"{self.base_url}/salesorders",
            headers=headers,
            params={"organization_id": self.org_id},
            json=payload,
            timeout=15
        )

        print("CREATE SO RESPONSE:", create_resp.status_code)
        print("CREATE SO BODY:", create_resp.text)

        if create_resp.status_code not in (200, 201):
            raise HTTPException(400, create_resp.text)

        # 4️⃣ Extract Sales Order
        salesorder = create_resp.json().get("salesorder")

        if not salesorder:
            raise HTTPException(400, "Sales order creation failed")

        salesorder_id = salesorder.get("salesorder_id")

        # 5️⃣ Mark Sales Order as OPEN
        self.mark_salesorder_open(access_token, salesorder_id)

        # Update local response status
        salesorder["status"] = "open"

        return salesorder
    
    def mark_salesorder_open(self, access_token: str, salesorder_id: str):
        """
        Mark a Sales Order as OPEN in Zoho Books
        """

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        resp = requests.post(
            f"{self.base_url}/salesorders/{salesorder_id}/status/open",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        print("MARK SO OPEN STATUS:", resp.status_code)
        print("MARK SO OPEN BODY:", resp.text)

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=400,
                detail="Failed to mark sales order as open"
            )

        return resp.json()

    def get_tracking_details(self, salesorder: dict):
        tracking_id = None
        carrier = None

        for field in salesorder.get("custom_fields", []):
            api_name = field.get("api_name")

            if api_name == "cf_tracking":
                tracking_id = field.get("value") or field.get("display_value")

            elif api_name == "cf_carrier":
                carrier = field.get("value") or field.get("display_value")

        return {
            "tracking_id": tracking_id,
            "carrier": carrier
        }
    
    def get_tracking_data(self, access_token: str, salesorder_id: str):

        # 1️⃣ Get Sales Order
        salesorder = self._get_order_status(access_token, salesorder_id)

        status = (salesorder.get("status") or "").lower()

        if "invoiced" not in status:
            raise HTTPException(403, "Tracking available only after invoice")

        # 2️⃣ Find Purchase Order
        salesorder_number = salesorder.get("salesorder_number")

        po = self._find_po_by_salesorder(access_token, salesorder_number)

        if not po:
            raise HTTPException(404, "Purchase Order not found")

        po_id = po.get("purchaseorder_id")

        # 3️⃣ Fetch Purchase Order details
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        po_resp = requests.get(
            f"{self.base_url}/purchaseorders/{po_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if po_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch Purchase Order")

        purchaseorder = po_resp.json().get("purchaseorder", {})

        # 4️⃣ Extract tracking from PO
        tracking_id = None
        carrier = None

        for field in purchaseorder.get("custom_fields", []):
            api_name = field.get("api_name")

            if api_name == "cf_tracking":
                tracking_id = field.get("value") or field.get("display_value")

            elif api_name == "cf_carrier":
                carrier = field.get("value") or field.get("display_value")

        return {
            "tracking_id": tracking_id,
            "carrier": carrier
        }