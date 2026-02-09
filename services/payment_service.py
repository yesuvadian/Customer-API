from decimal import ROUND_HALF_UP, Decimal
import requests
from fastapi import HTTPException, status
import config
from services.zoho_contact_service import ZohoContactService
from services.redis_cache import RedisCacheService as cache


class PaymentService:
    def __init__(self):
        self.base_url = f"{config.ZOHO_API_BASE}/books/v3"
        self.org_id = config.ZOHO_ORG_ID
        self.contact_service = ZohoContactService()

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
