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

        new_filename = f"po_{file.filename}"

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

        if uploaded_by:
            self.add_comment(
                access_token=access_token,
                salesorder_id=salesorder_id,
                description=f"PO Uploaded\nFile: {file.filename}",
                email=uploaded_by,
                show_to_client=True
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

        files = {
            "attachment": (
                f"grn_{file.filename}",
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


    def update_grn_number_field(
    self,
    access_token: str,
    salesorder_id: str,
    grn_number: str ):
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
            if doc.get("file_name", "").startswith("grn_"):
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
        is_shipped = any(
            p.get("status", "").lower() == "shipped"
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

        # Step 1: Fetch sales order to get document list
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

        for doc in reversed(documents):  # latest first
            filename = doc.get("file_name", "")
            if filename.startswith(prefix):
                document_id = doc.get("document_id")
                break

        if not document_id:
            return b""

        # Step 2: Download attachment
        file_response = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}/attachment/{document_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if file_response.status_code != 200:
            return b""


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
            if filename.startswith(prefix):
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
            "include": "custom_fields",
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

        # 1️⃣ Fetch Sales Order
        so_resp = requests.get(
            f"{self.base_url}/salesorders/{salesorder_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if so_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Sales order not found")

        salesorder = so_resp.json().get("salesorder", {})

        packages = salesorder.get("packages", [])

        if not packages:
            return {"message": "No shipment created for this Sales Order"}

        # Get latest shipped package
        shipped_package = None
        for pkg in reversed(packages):
            if pkg.get("status", "").lower() == "shipped":
                shipped_package = pkg
                break

        if not shipped_package:
            return {"message": "Sales Order not shipped yet"}

        return {
            "salesorder_id": salesorder_id,
            "package_id": shipped_package.get("package_id"),
            "shipment_date": shipped_package.get("shipment_date"),
            "carrier": shipped_package.get("carrier"),
            "tracking_number": shipped_package.get("tracking_number"),
            "status": shipped_package.get("status")
        }