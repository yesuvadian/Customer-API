import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService


class QuoteService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

    def create_draft_quote(self, access_token: str, payload):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # -------------------------------------------------
        # Resolve contact_id (email → Zoho contact_id)
        # -------------------------------------------------
        contact_id = payload.contact_id
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            contact_id = contact["contact_id"]

        # -------------------------------------------------
        # Build line items with tax exemption and rate from Zoho item
        # -------------------------------------------------
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
                        "message": f"Failed to fetch item {item.item_id} from Zoho Books",
                        "zoho_response": item_response.json()
                    }
                )

            item_data = item_response.json().get("item", {})
            line_items.append({
                "item_id": item.item_id,
                "quantity": item.quantity,
                "rate": item_data.get("rate", 0),
                "name": item_data.get("name", ""),
                "tax_id": "",                     # always blank for draft quotes
                "tax_exemption_code": "NON"       # always exempt
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

        # Zoho returns 201 on success
        if response.status_code != 201:
            try:
                error_detail = response.json()
            except ValueError:
                error_detail = response.text

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create draft quote in Zoho Books",
                    "zoho_response": error_detail
                }
            )

        data = response.json()
        # Zoho Books returns "estimate" not "quote"
        if "estimate" not in data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Zoho response missing estimate object"
            )
        estimate = data["estimate"]
            # -------------------------------------------------
        # Fetch org email
        # -------------------------------------------------
        org_response = requests.get(
            f"{self.base_url}/organizations/{self.org_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )
        org_email = org_response.json()["organization"]["email"]

        # -------------------------------------------------
        # Collect creator + org email
        # -------------------------------------------------
        recipients = []
        for person in estimate.get("contact_persons_associated", []):
            if person.get("contact_person_email"):
                recipients.append(person["contact_person_email"])
        if org_email:
            recipients.append(org_email)

        # -------------------------------------------------
        # Send estimate email
        # -------------------------------------------------
        if recipients:
            email_payload = {
                "to_mail_ids": recipients,
                "subject": f"Request for Quote {estimate['estimate_number']} from {contact['contact_name']}",
                "body": "Please find attached your quote."
            }
            email_response = requests.post(
                f"{self.base_url}/estimates/{estimate['estimate_id']}/email",
                headers=headers,
                json=email_payload,
                params={"organization_id": self.org_id},
                timeout=15
            )
            if email_response.status_code not in (200, 201):
                # fallback: return draft estimate if email fails
                return estimate
        return estimate
    def send_estimate_email(self, access_token: str, estimate_id: str, customer_id: str):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # Fetch customer to get email IDs
        customer_response = requests.get(
            f"{self.base_url}/customers/{customer_id}",
            headers=headers,
            params={"organization_id": self.org_id},
            timeout=15
        )
        customer_data = customer_response.json().get("customer", {})
        emails = [p["contact_person_email"] for p in customer_data.get("contact_persons", []) if p.get("contact_person_email")]

        payload = {
            "to_mail_ids": emails,
            "subject": "Your Quote from Our Company",
            "body": "Please find attached your draft quote."
        }

        response = requests.post(
            f"{self.base_url}/estimates/{estimate_id}/email",
            headers=headers,
            json=payload,
            params={"organization_id": self.org_id},
            timeout=15
        )

        return response.json()