import requests
from fastapi import HTTPException, status
import config
import base64
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache
from fastapi import UploadFile


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
        uploaded_by: str | None = None
    ):
        # ✅ Fetch current order status properly
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_po(salesorder.get("status"))

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
        salesorder = self._get_order_status(access_token, salesorder_id)
        self._validate_status_for_grn(salesorder)

        # 1️⃣ Update GRN custom field
        self.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=cf_grn_number
        )

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

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

        # 2️⃣ Add comment
        if uploaded_by:
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
                raise HTTPException(
                    status_code=400,
                    detail="GRN uploaded but comment failed"
                )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        return data

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
            # Ignore if no file exists
            pass

        # 4️⃣ Update GRN number
        self.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=cf_grn_number
        )

        # 5️⃣ Upload new file
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

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

        # 6️⃣ Add update comment
        if uploaded_by:
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

            requests.post(
                f"{self.base_url}/salesorders/{salesorder_id}/comments",
                headers={
                    "Authorization": f"Zoho-oauthtoken {access_token}",
                    "Content-Type": "application/json"
                },
                params={"organization_id": self.org_id},
                json=comment_payload,
                timeout=15
            )

        self._invalidate_salesorder_caches(salesorder_id=salesorder_id)

        return {"message": "GRN updated successfully"}

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
                "customer_id": contact_id
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
            params={"organization_id": self.org_id},
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

    def _validate_status_for_grn(self, salesorder: dict):
        packages = salesorder.get("packages", [])

        if not packages:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="GRN allowed only after package is created"
            )

        # Check if at least one package is shipped
        valid_status = ["shipped", "delivered", "partially_shipped", "fulfilled"]

        is_shipped = any(
            p.get("status", "").lower() in valid_status
            for p in packages
        )

        if not is_shipped:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="GRN allowed only when package status is shipped"
            )

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

        return response.json().get("salesorder", {})

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

        # 1️⃣ First verify sales order exists
        so_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if so_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=so_resp.text)

        salesorder = so_resp.json().get("salesorder", {})

        # Security check
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
            "package_id": latest_package.get("package_id"),
            "shipment_date": latest_package.get("shipment_date"),
            "carrier": latest_package.get("carrier"),
            "tracking_number": latest_package.get("tracking_number"),
            "status": latest_package.get("status")
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
    # Get Supplier Details
    # -------------------------------------------------
    def get_supplier_details(
        self,
        access_token: str,
        salesorder_id: str
    ):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        # 1️⃣ Fetch Sales Order
        response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to fetch sales order"
            )

        salesorder = response.json().get("salesorder", {})

        # 2️⃣ Extract supplier custom field
        supplier_id = None

        for field in salesorder.get("custom_fields", []):
            if field.get("api_name") == "cf_supplier":
                supplier_id = field.get("value")
                break

        if not supplier_id:
            raise HTTPException(
                status_code=404,
                detail="Supplier not set on this Sales Order"
            )

        # 3️⃣ Fetch supplier contact details
        supplier_resp = requests.get(
            f"{self.base_url}/contacts/{supplier_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if supplier_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to fetch supplier details"
            )

        supplier = supplier_resp.json().get("contact", {})

        # 🔍 DEBUG: print full supplier to inspect field names
        print("🔍 RAW SUPPLIER DATA:", supplier_resp.json())

        billing = supplier.get("billing_address", {})
        address_parts = [
            billing.get("address"),
            billing.get("street2"),
            billing.get("city"),
            billing.get("state"),
            billing.get("zip"),
            billing.get("country"),
        ]
        address = ", ".join(part for part in address_parts if part)

        return {
            "supplier_id": supplier.get("contact_id"),
            "supplier_name": supplier.get("contact_name"),
            "email": supplier.get("email"),
            "phone": supplier.get("phone"),
            "mobile": supplier.get("mobile"),
            "company_name": supplier.get("company_name"),
            "address": address
        }

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