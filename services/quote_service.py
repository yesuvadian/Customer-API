import re
import requests
from fastapi import HTTPException, UploadFile, status
import config
from services.zoho_contact_service import ZohoContactService
from utils.comment_meta_util import build_comment_meta, extract_comment_meta, strip_comment_meta, strip_comment_meta

class QuoteService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    # -----------------------------
    # Utility: resolve contact_id
    # -----------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:  # treat as email
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id
        # -----------------------------
    # Upload Attachment to Quote
    # -----------------------------
    def upload_attachment(
        self,
        access_token: str,
        estimate_id: str,
        file: UploadFile,
        uploaded_by: str | None = None
    ):
        """
        Upload an attachment to a Zoho Books Estimate
        """

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

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
                detail={
                    "message": "Failed to upload attachment",
                    "zoho_response": response.json()
                }
            )

        # Optional: add audit comment
        if uploaded_by:
            try:
                self.add_comment(
                    access_token=access_token,
                    estimate_id=estimate_id,
                    description=f"Attachment uploaded: {file.filename}",
                    email=uploaded_by
                )
            except Exception:
                pass  # attachment succeeded, comment is optional

        return response.json()
        # -----------------------------
    # Create Draft Quote (Enquiry – No Items)
    # -----------------------------
    def create_draft_quote_enquiry(self, access_token: str, payload):
        """
        Create a draft quote as an enquiry:
        - No predefined items
        - Uses a dummy line item
        - Attachments are uploaded separately
        """

        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        contact_id = self._resolve_contact_id(payload.contact_id)

        # Single dummy line item (Zoho requires at least one)
        line_items = [
            {
                "name": "Enquiry Request",
                "quantity": 1,
                "rate": 0,
                "description": payload.enquiry_description
                if hasattr(payload, "enquiry_description")
                else "Customer enquiry submitted from portal",
                "tax_exemption_code": "NON"
            }
        ]

        body = {
            "customer_id": contact_id,
            "line_items": line_items,
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
                detail={
                    "message": "Failed to create enquiry draft quote",
                    "zoho_response": response.json()
                }
            )

        return response.json()["estimate"]

    # -----------------------------
    # Create Draft Quote
    # -----------------------------
    def create_draft_quote(self, access_token: str, payload):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        contact_id = self._resolve_contact_id(payload.contact_id)

        # Build line items
        line_items = []
        for item in payload.items:
            item_response = requests.get(
                f"{self.base_url}/items/{item.item_id}",
                headers=headers,
                params={"organization_id": self.org_id},
                timeout=15
            )
            if item_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": f"Failed to fetch item {item.item_id}",
                        "zoho_response": item_response.json()
                    }
                )
            item_data = item_response.json().get("item", {})
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
                "tax_id": "",
                "tax_exemption_code": "NON"
            })

        body = {
            "customer_id": contact_id,
            "line_items": line_items,
            "notes": payload.notes or "Quote requested from customer portal"
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
                detail={
                    "message": "Failed to create draft quote",
                    "zoho_response": response.json()
                }
            )

        return response.json()["estimate"]

    # -----------------------------
    # List Quotes for Customer
    # -----------------------------
    def list_quotes_for_customer(self, access_token: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/estimates",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to fetch quotes", "zoho_response": response.json()}
            )
        estimates = response.json().get("estimates", {})

         # ❌ EXCLUDE draft quotes
        quotes = [
            q for q in estimates 
            if q.get("status", "").lower() != "draft"
        ]

        return quotes

    # -----------------------------
    # Get Quote Details
    # -----------------------------
    def get_quote(self, access_token: str, estimate_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Failed to fetch quote {estimate_id}", "zoho_response": response.json()}
            )

        estimate = response.json().get("estimate", {})

        

        return estimate


    # -----------------------------
    # ERP Review Quote
    # -----------------------------
    def review_quote(self, access_token: str, estimate_id: str, payload, reviewer_id: str, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Reviewed by ERP user {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to review quote", "zoho_response": response.json()}
            )
        return response.json().get("estimate", {})

    # -----------------------------
    # Customer Approval
    # -----------------------------
    def customer_approve_quote(self, access_token: str, estimate_id: str, payload, contact_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        contact_id = self._resolve_contact_id(contact_id)

        body = {
            "status": payload.status,
            "notes": payload.notes or f"Response from customer {contact_id}"
        }

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Failed to update quote status", "zoho_response": response.json()}
            )
        return response.json().get("estimate", {})
    
    def update_quote_status(self, access_token: str, estimate_id: str, action: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/status/{action}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        data = response.json()

        if response.status_code != 200 or data.get("code") != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to mark quote as {action}",
                    "zoho_response": data
                }
            )

        return {
            "message": data.get("message", "Status updated"),
            "estimate_number": data.get("estimate", {}).get("estimate_number", ""),
            "estimate_id": estimate_id,
            "status": action
        }

    def get_quote_pdf(self, access_token: str, estimate_id: str):
            headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
            params = {
                "organization_id": self.org_id,
                "print": "true",
                "accept": "pdf"
            }

            response = requests.get(
                f"{self.base_url}/estimates/{estimate_id}",
                headers=headers,
                params=params,
                timeout=30
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": f"Failed to fetch PDF for estimate {estimate_id}",
                        "zoho_response": response.json() if "application/json" in response.headers.get("Content-Type","") else None
                    }
                )

            return response.content  # raw PDF bytes
    # -----------------------------
    # Add Comment
    # -----------------------------
    def add_comment(
    self,
    access_token: str,
    estimate_id: str,
    description: str,
    email: str | None = None
):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # ONE call – everything handled internally
        meta_block = build_comment_meta(email=email)

        payload = {
            "description": meta_block + description
        }

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=headers,
            json=payload,
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

        return response.json()


    # -----------------------------
    # Update Comment
    # -----------------------------
    def update_comment(self, access_token: str, estimate_id: str, comment_id: str, description: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        payload = {"description": description}

        response = requests.put(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
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

        return response.json()
    # -----------------------------
    # Delete Comment
    # -----------------------------
    def delete_comment(self, access_token: str, estimate_id: str, comment_id: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.delete(
            f"{self.base_url}/estimates/{estimate_id}/comments/{comment_id}",
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

        return {"message": "Comment deleted successfully"}
    # -----------------------------
    # List Comments
    # -----------------------------
    def get_comments(self, access_token: str, estimate_id: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(
            f"{self.base_url}/estimates/{estimate_id}/comments",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch comments for estimate {estimate_id}",
                    "zoho_response": response.json()
                }
            )

        comments = response.json().get("comments", [])
        result = []

        for c in comments:
            meta = extract_comment_meta(c.get("description", ""))

            description = c.get("description", "")
            if "[CUSTOM_META]" not in description:
                continue

            result.append({
                "comment_id": c.get("comment_id", ""),
                "estimate_id": c.get("estimate_id", ""),
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



# -----------------------------
# Comment Meta Utilities
# -----------------------------
    def _build_comment_meta(self, meta: dict) -> str:
        """
        Build metadata block to embed in comment description
        """
        if not meta:
            return ""

        lines = "\n".join(f"{k}={v}" for k, v in meta.items())
        return f"[CUSTOM_META]\n{lines}\n[/CUSTOM_META]\n\n"


    def _extract_comment_meta(self, description: str) -> dict:
        """
        Extract metadata from comment description
        """
        if not description:
            return {}

        match = re.search(r"\[CUSTOM_META\](.*?)\[/CUSTOM_META\]", description, re.S)
        if not match:
            return {}

        meta_lines = match.group(1).strip().split("\n")
        return {
            k.strip(): v.strip()
            for line in meta_lines
            if "=" in line
            for k, v in [line.split("=", 1)]
        }


    def _strip_comment_meta(self, description: str) -> str:
        """
        Remove metadata block from description for UI
        """
        return re.sub(
            r"\[CUSTOM_META\].*?\[/CUSTOM_META\]\s*",
            "",
            description or "",
            flags=re.S
        ).strip()
