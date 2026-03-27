import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta
from services.redis_cache import RedisCacheService as cache

class InvoiceService:
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
    # Create Invoice
    # -----------------------------
    def create_invoice(self, access_token: str, payload):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"}
        contact_id = self._resolve_contact_id(payload.contact_id)

        line_items = []
        for item in payload.items:
            item_response = requests.get(
                f"{self.base_url}/items/{item.item_id}",
                headers=headers,
                params={"organization_id": self.org_id},
                timeout=30
            )
            if item_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail={"message": f"Failed to fetch item {item.item_id}",
                                            "zoho_response": item_response.json()})
            item_data = item_response.json().get("item", {})
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
                "tax_id": "",
                "tax_exemption_code": "NON"
            })

        body = {"customer_id": contact_id, "line_items": line_items,
                "notes": payload.notes or "Invoice created from customer portal"}

        response = requests.post(
            f"{self.base_url}/invoices",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=30
        )
        if response.status_code != 201:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail={"message": "Failed to create invoice",
                                        "zoho_response": response.json()})
        invoice = response.json()["invoice"]
        self._invalidate_invoice_caches(contact_id, invoice["invoice_id"])
        return invoice

    
    def _invalidate_invoice_caches(self, contact_id: str | None = None, invoice_id: str | None = None):
        if contact_id:
            try:
                cache.delete(f"zoho:invoices:{contact_id}")
                cache.delete(f"zoho:dashboard:{contact_id}")
            except:
                pass  # Redis not available
        if invoice_id:
            try:
                cache.delete(f"zoho:invoice:{invoice_id}")
            except:
                pass  # Redis not available


    # -----------------------------
    # List Invoices for Customer
    # -----------------------------
    def list_invoices_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        
        # Skip Redis cache for now
        # cache_key = f"zoho:invoices:{contact_id}"
        # try:
        #     cached = cache.get(cache_key)
        #     if cached:
        #         return cached
        # except:
        #     pass  # Redis not available

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.get(
            f"{self.base_url}/invoices",
            headers=headers,
            params={
                "organization_id": self.org_id,
                "customer_id": contact_id
            },
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch invoices",
                    "zoho_response": response.json()
                }
            )

        invoices = response.json().get("invoices", [])

        # MAP SALES ORDER NUMBER AND FETCH VENDOR ID FROM PURCHASE ORDER
        for inv in invoices:
            inv["salesorder_number"] = inv.get("reference_number")
            
            # Try to get vendor_id from custom fields first
            custom_field_hash = inv.get("custom_field_hash", {})
            vendor_id = custom_field_hash.get("cf_vendor_id")
            
            # If not found in custom fields, try to get through PO chain
            if not vendor_id:
                so_number = inv.get("reference_number")
                
                if so_number:
                    try:
                        print(f"Fetching vendor for SO: {so_number}")
                        
                        # Fetch sales order by number
                        so_response = requests.get(
                            f"{self.base_url}/salesorders",
                            headers=headers,
                            params={
                                "organization_id": self.org_id,
                                "salesorder_number": so_number
                            },
                            timeout=30
                        )
                        
                        if so_response.status_code == 200:
                            sales_orders = so_response.json().get("salesorders", [])
                            if sales_orders:
                                so = sales_orders[0]
                                
                                # Check if sales order has vendor_id directly
                                if so.get("vendor_id"):
                                    vendor_id = so.get("vendor_id")
                                    print(f"Found vendor_id in SO: {vendor_id}")
                                else:
                                    # Get purchase order number from sales order
                                    po_number = so.get("purchaseorder_number")
                                    if po_number:
                                        print(f"Fetching PO: {po_number}")
                                        
                                        # Fetch purchase order to get vendor
                                        po_response = requests.get(
                                            f"{self.base_url}/purchaseorders",
                                            headers=headers,
                                            params={
                                                "organization_id": self.org_id,
                                                "purchaseorder_number": po_number
                                            },
                                            timeout=30
                                        )
                                        
                                        if po_response.status_code == 200:
                                            pos = po_response.json().get("purchaseorders", [])
                                            if pos:
                                                vendor_id = pos[0].get("vendor_id")
                                                print(f"Found vendor_id in PO: {vendor_id}")
                                    else:
                                        print(f"No PO number found in SO: {so_number}")
                            else:
                                print(f"No sales orders found for: {so_number}")
                        else:
                            print(f"SO fetch failed: {so_response.status_code}")
                            
                    except Exception as e:
                        print(f"Error fetching vendor from PO chain for {so_number}: {e}")
            
            inv["vendor_id"] = vendor_id

        # Skip Redis cache set
        # try:
        #     cache.set(cache_key, invoices)
        # except:
        #     pass

        return invoices


    # -----------------------------
    # Get Invoice Details
    # -----------------------------
    def get_invoice(self, access_token: str, invoice_id: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        
        # Skip Redis cache for now
        # cache_key = f"zoho:invoice:{invoice_id}"
        # try:
        #     cached = cache.get(cache_key)
        #     if cached:
        #         return cached
        # except:
        #     pass

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        response = requests.get(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch invoice {invoice_id}",
                    "zoho_response": response.json()
                }
            )

        invoice = response.json().get("invoice", {})
        
        # ADD VENDOR ID FROM CUSTOM FIELDS for single invoice as well
        custom_field_hash = invoice.get("custom_field_hash", {})
        vendor_id = custom_field_hash.get("cf_vendor_id")
        if not vendor_id:
            vendor_id = custom_field_hash.get("vendor_id")
        invoice["vendor_id"] = vendor_id
        
        # Skip Redis cache set
        # try:
        #     cache.set(cache_key, invoice)
        # except:
        #     pass
        
        return invoice


    # -----------------------------
    # ERP Review Invoice
    # -----------------------------
    def review_invoice(self, access_token: str, invoice_id: str, payload, reviewer_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)
        body = {"status": payload.status, "notes": payload.notes or f"Reviewed by ERP user {reviewer_id}"}
        response = requests.put(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=30
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail={"message": "Failed to review invoice", "zoho_response": response.json()})
        invoice = response.json()["invoice"]
        self._invalidate_invoice_caches(contact_id, invoice["invoice_id"])
        return invoice


    # -----------------------------
    # Customer Approval Invoice
    # -----------------------------
    def customer_approve_invoice(self, access_token: str, invoice_id: str, payload, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)
        body = {"status": payload.status, "notes": payload.notes or f"Response from customer {contact_id}"}
        response = requests.put(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=30
        )
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail={"message": "Failed to update invoice status", "zoho_response": response.json()})
        invoice = response.json().get("invoice", {})
        self._invalidate_invoice_caches(contact_id, invoice_id)
        return invoice

    def get_invoice_pdf(self, access_token: str, invoice_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        params = {
            "organization_id": self.org_id,
            "print": "true",
            "accept": "pdf"
        }

        response = requests.get(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch PDF for invoice {invoice_id}",
                    "zoho_response": response.json() if "application/json" in response.headers.get("Content-Type","") else None
                }
            )

        return response.content  # raw PDF bytes
    
    # ----------------------------------------------
    # GET COMMENTS FOR INVOICE
    # ----------------------------------------------
    def get_invoice_comments(self, access_token: str, invoice_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        resp = requests.get(
            f"{self.base_url}/invoices/{invoice_id}/comments",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch invoice comments",
                    "zoho_response": resp.json()
                }
            )

        comments = resp.json().get("comments", [])
        result = []

        for c in comments:
            meta = extract_comment_meta(c.get("description", ""))
            description = c.get("description", "")
            if "[CUSTOM_META]" not in description:
                continue

            result.append({
                "comment_id": c.get("comment_id", ""),
                "invoice_id": invoice_id,
                "description": strip_comment_meta(c.get("description", "")),
                "commented_by": meta.get("customer_name", c.get("commented_by", "")),
                "commented_by_id": meta.get("customer_id", c.get("commented_by_id", "")),
                "comment_type": "client",
                "date": c.get("date", ""),
                "date_description": c.get("date_description", ""),
                "time": c.get("time", ""),
                "comments_html_format": c.get("comments_html_format", "")
            })

        return result


    # ----------------------------------------------
    # ADD NEW COMMENT
    # ----------------------------------------------
    def add_invoice_comment(
    self,
    access_token: str,
    invoice_id: str,
    description: str,
    email: str | None = None
):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        meta_block = build_comment_meta(email=email)

        payload = {
            "description": meta_block + description
        }

        resp = requests.post(
            f"{self.base_url}/invoices/{invoice_id}/comments",
            headers=headers,
            params={"organization_id": self.org_id},
            json=payload,
            timeout=30
        )

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to add invoice comment",
                    "zoho_response": resp.json()
                }
            )

        return resp.json()


    # ----------------------------------------------
    # UPDATE A COMMENT
    # ----------------------------------------------
    def update_invoice_comment(self, access_token: str, invoice_id: str, comment_id: str, payload: dict):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "content-type": "application/json"
        }

        resp = requests.put(
            f"{self.base_url}/invoices/{invoice_id}/comments/{comment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            json=payload,
            timeout=30
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to update invoice comment",
                    "zoho_response": resp.json()
                }
            )

        return resp.json()


    # ----------------------------------------------
    # DELETE A COMMENT
    # ----------------------------------------------
    def delete_invoice_comment(self, access_token: str, invoice_id: str, comment_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        resp = requests.delete(
            f"{self.base_url}/invoices/{invoice_id}/comments/{comment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to delete invoice comment",
                    "zoho_response": resp.json()
                }
            )
        

    def get_invoice_attachments(self, access_token: str, invoice_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        resp = requests.get(
            f"{self.base_url}/invoices/{invoice_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to fetch invoice"
            )

        invoice = resp.json().get("invoice", {})
        documents = invoice.get("documents", [])

        return [
            {
                "attachment_id": doc.get("document_id"),
                "file_name": doc.get("file_name"),
                "file_type": doc.get("file_type"),
                "file_size": doc.get("file_size")
            }
            for doc in documents
        ]
    
    def download_invoice_attachment(
        self,
        access_token: str,
        invoice_id: str,
        attachment_id: str
    ):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        resp = requests.get(
            f"{self.base_url}/invoices/{invoice_id}/documents/{attachment_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=30
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to download attachment"
            )

        return resp.content