from decimal import ROUND_HALF_UP, Decimal
import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from services.redis_cache import RedisCacheService as cache
from services.bill_service import BillService  # Add this import
from datetime import datetime, timedelta


class PaymentService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()
        self.bill_service = BillService()  # Already there

    # -------------------------------------------------
    # Cache helpers
    # -------------------------------------------------
    def _invalidate_payment_caches(
        self,
        contact_id: str | None = None,
        payment_id: str | None = None
    ):
        if contact_id:
            cache.delete(f"zoho:payments:{contact_id}")
            cache.delete(f"zoho:dashboard:{contact_id}")

        if payment_id:
            cache.delete(f"zoho:payment:{payment_id}")

    # -------------------------------------------------
    # Utility
    # -------------------------------------------------
    def _resolve_contact_id(self, contact_id: str) -> str:
        if "@" in contact_id:
            contact = self.contact_service.get_contact_id_by_email(contact_id)
            return contact["contact_id"]
        return contact_id

    # -------------------------------------------------
    # Create Bill Helper (Optional - keep if you still need Zoho bills)
    # -------------------------------------------------
    def _create_bill(self, access_token: str, payment_data: dict, invoice_id: str, amount: Decimal, vendor_id: str = None):
        """Create a bill in Zoho Books for the payment."""
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        # Use provided vendor_id or fallback to default
        vendor_id_to_use = vendor_id or config.ZOHO_DEFAULT_VENDOR_ID
        
        # Generate a unique bill number using the payment number from Zoho
        bill_number = f"BILL-{payment_data['payment_number']}"
        
        # Set due date 30 days from now (adjust as needed)
        due_date = (datetime.now() + timedelta(days=30)).date().isoformat()
        
        # Create line item for the bill
        line_items = [{
            "name": f"Payment for Invoice {invoice_id}",
            "description": f"Payment recorded on {datetime.now().date().isoformat()} for invoice {invoice_id}",
            "rate": float(amount),
            "quantity": 1,
            "account_id": config.ZOHO_EXPENSE_ACCOUNT_ID,
        }]
        
        # Build the bill payload
        payload = {
            "vendor_id": vendor_id_to_use,
            "bill_number": bill_number,
            "date": datetime.now().date().isoformat(),
            "due_date": due_date,
            "reference_number": payment_data.get("reference_number", ""),
            "line_items": line_items,
            "notes": f"Created automatically from payment {payment_data['payment_number']}"
        }
        
        # Make API call to Zoho Books
        response = requests.post(
            f"{self.base_url}/bills",
            headers=headers,
            json=payload,
            params={"organization_id": self.org_id},
            timeout=15
        )
        
        # Handle errors
        if response.status_code not in (200, 201):
            error_detail = response.json()
            print(f"Bill creation failed with status {response.status_code}")
            print(f"Error details: {error_detail}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create bill in Zoho Books",
                    "zoho_response": error_detail
                }
            )
        
        # Return the created bill
        return response.json().get("bill", {})

    # -------------------------------------------------
    # Create Customer Payment
    # -------------------------------------------------
    def create_payment(self, access_token: str, payload):
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }

        contact_id = self._resolve_contact_id(payload.contact_id)

        body = {
            "customer_id": contact_id,
            "payment_mode": payload.payment_mode,
            "amount": str(
                Decimal(payload.amount).quantize(
                    Decimal("0.00"), rounding=ROUND_HALF_UP
                )
            ),
            "date": payload.payment_date.isoformat(),
            "reference_number": payload.reference_number,
            "description": payload.description or "Payment recorded from customer portal",
            "invoices": [
                {
                    "invoice_id": inv.invoice_id,
                    "amount_applied": inv.amount_applied
                }
                for inv in payload.invoices
            ]
        }

        response = requests.post(
            f"{self.base_url}/customerpayments",
            headers=headers,
            json=body,
            params={"organization_id": self.org_id},
            timeout=15
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create customer payment",
                    "zoho_response": response.json()
                }
            )

        payment = response.json()["payment"]
        
        # --- Create bill in LOCAL DATABASE ---
        try:
            bill_data = {
                "bill_number": f"BILL-{payment['payment_number']}",
                "payment_id": payment["payment_id"],
                "invoice_id": payload.invoices[0].invoice_id,
                "invoice_number": None,
                "contact_id": payload.contact_id,
                "amount": payload.amount,
                "payment_mode": payload.payment_mode,
                "reference_number": payload.reference_number,
                "payment_date": payload.payment_date.isoformat(),
                "status": "open",
                "created_by": payload.contact_id,
                "vendor_id": None
            }
            
            bill = self.bill_service.create_bill(bill_data)
            payment['bill'] = {
                "bill_id": str(bill["id"]),
                "bill_number": bill["bill_number"]
            }
            print(f"✅ Local bill created: {bill['bill_number']}")
            
        except Exception as e:
            print(f"Warning: Failed to create local bill: {e}")
            payment['bill'] = {}
        
        self._invalidate_payment_caches(contact_id, payment["payment_id"])
        return payment

    # -------------------------------------------------
    # List Payments
    # -------------------------------------------------
    def list_payments_for_customer(self, access_token: str, contact_id: str):
        contact_id = self._resolve_contact_id(contact_id)
        cache_key = f"zoho:payments:{contact_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        response = requests.get(
            f"{self.base_url}/customerpayments",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch customer payments",
                    "zoho_response": response.json()
                }
            )

        payments = response.json().get("customerpayments", [])
        cache.set(cache_key, payments)
        return payments

    # -------------------------------------------------
    # Get Payment
    # -------------------------------------------------
    def get_payment(self, access_token: str, payment_id: str, contact_id: str):
        cache_key = f"zoho:payment:{payment_id}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.get(
            f"{self.base_url}/customerpayments/{payment_id}",
            headers=headers,
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Failed to fetch payment {payment_id}",
                    "zoho_response": response.json()
                }
            )

        payment = response.json().get("payment")
        if payment:
            cache.set(cache_key, payment)
        return payment or {}

    # -------------------------------------------------
    # ERP Review Payment
    # -------------------------------------------------
    def review_payment(
        self,
        access_token: str,
        payment_id: str,
        payload,
        reviewer_id: str,
        contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.put(
            f"{self.base_url}/customerpayments/{payment_id}",
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
                    "message": "Failed to review payment",
                    "zoho_response": response.json()
                }
            )

        payment = response.json().get("payment", {})
        self._invalidate_payment_caches(contact_id, payment_id)
        return payment

    # -------------------------------------------------
    # Customer Approval
    # -------------------------------------------------
    def customer_approve_payment(
        self,
        access_token: str,
        payment_id: str,
        payload,
        contact_id: str
    ):
        contact_id = self._resolve_contact_id(contact_id)
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        response = requests.put(
            f"{self.base_url}/customerpayments/{payment_id}",
            headers=headers,
            json={
                "status": payload.status,
                "notes": payload.notes or f"Response from customer {contact_id}"
            },
            params={"organization_id": self.org_id, "customer_id": contact_id},
            timeout=15
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to update payment status",
                    "zoho_response": response.json()
                }
            )

        payment = response.json().get("payment", {})
        self._invalidate_payment_caches(contact_id, payment_id)
        return payment

    # -------------------------------------------------
    # Get Payment PDF (NO CACHE)
    # -------------------------------------------------
    def get_payment_pdf(self, access_token: str, payment_id: str):
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        params = {
            "organization_id": self.org_id,
            "print": "true",
            "accept": "pdf"
        }

        response = requests.get(
            f"{self.base_url}/customerpayments/{payment_id}",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch payment PDF",
                    "zoho_response": (
                        response.json()
                        if "application/json" in response.headers.get("Content-Type", "")
                        else None
                    )
                }
            )

        return response.content  # raw PDF bytes