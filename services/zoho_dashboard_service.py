from services.zoho_client import zoho_request
import config
from services.redis_cache import RedisCacheService as cache


class ZohoDashboardService:

    def _safe_list(self, path: str, contact_id: str, key: str):
        """
        Fetch list-based Zoho resources but NEVER fail.
        Returns [] on any error.
        """
        try:
            response = zoho_request(
                method="GET",
                path=path,
                params={
                    "organization_id": config.ZOHO_ORG_ID,
                    "customer_id": contact_id
                }
            )

            if response.status_code != 200:
                print(f"[WARN] {path} returned {response.status_code}: {response.text}")
                return []

            data = response.json()
            return data.get(key, [])

        except Exception as e:
            print(f"[ERROR] Failed to fetch {path}: {e}")
            return []

    # ----------- FETCHERS (safe) ------------

    def get_quotes(self, contact_id: str):
        return self._safe_list("/estimates", contact_id, "estimates")

    def get_invoices(self, contact_id: str):
        return self._safe_list("/invoices", contact_id, "invoices")

    def get_sales_orders(self, contact_id: str):
        return self._safe_list("/salesorders", contact_id, "salesorders")

    def get_payments(self, contact_id: str):
        return self._safe_list("/customerpayments", contact_id, "customerpayments")

    def get_retainer_invoices(self, contact_id: str):
        return self._safe_list(
            "/retainerinvoices",
            contact_id,
            "retainerinvoices"
        )

    # ----------- SALES ORDER STATUS RESOLVER ------------

    def _resolve_sales_order_status(self, o):
        order_status = (o.get("order_status") or "").lower()
        status = (o.get("status") or "").lower()
        shipped_status = (o.get("shipped_status") or "").lower()

        quantity_packed = float(o.get("quantity_packed", 0) or 0)
        quantity_shipped = float(o.get("quantity_shipped", 0) or 0)
        quantity_invoiced = float(o.get("quantity_invoiced", 0) or 0)

        if order_status == "closed":
            return "closed"

        if quantity_invoiced > 0:
            return "invoiced"

        if quantity_shipped > 0 or shipped_status == "shipped":
            return "shipped"

        if quantity_packed > 0:
            return "packed"

        if status == "draft":
            return "draft"

        return "open"

    # ----------- MAIN SUMMARY BUILDER ------------

    def build_dashboard_summary(self, contact_id: str) -> dict:
        cache_key = f"zoho:dashboard:{contact_id}"

        # 🔹 1. Try cache first
        cached = cache.get(cache_key)
        if cached:
            return cached

        # 🔹 2. Fetch from Zoho
        quotes = self.get_quotes(contact_id)
        invoices = self.get_invoices(contact_id)
        sales_orders = self.get_sales_orders(contact_id)
        payments = self.get_payments(contact_id)
        retainers = self.get_retainer_invoices(contact_id)

        # -------- QUOTES SUMMARY --------
        pending_quotes = len([
            q for q in quotes
            if q.get("status", "").lower() == "sent"
        ])

        total_estimates_amount = sum(
            float(q.get("total", 0) or 0) for q in quotes
        )

        total_estimates_count = len(quotes)

        # -------- INVOICES SUMMARY --------
        total_invoices_amount = sum(
            float(i.get("total", 0) or 0) for i in invoices
        )

        total_invoices_count = len(invoices)

        outstanding = [
            i for i in invoices
            if float(i.get("balance", 0) or 0) > 0
        ]

        outstanding_balance = sum(
            float(i.get("balance", 0) or 0) for i in outstanding
        )

        outstanding_count = len(outstanding)

        unused_credits = sum(
            float(i.get("credits_applied", 0) or 0) for i in invoices
        )

        # -------- AVAILABLE RETAINERS --------
        active_retainers = [
            r for r in retainers
            if r.get("status", "").lower() not in ("cancelled", "void")
            and float(r.get("total", 0) or 0) > 0
        ]

        available_retainers = sum(
            float(r.get("total", 0) or 0) for r in active_retainers
        )

        available_retainer_count = len(active_retainers)

        # -------- SALES ORDERS SUMMARY --------
        open_so = 0
        packed_so = 0
        shipped_so = 0
        draft_so = 0

        for o in sales_orders:
            resolved = self._resolve_sales_order_status(o)

            if resolved == "open":
                open_so += 1
            elif resolved == "packed":
                packed_so += 1
            elif resolved == "shipped":
                shipped_so += 1
            elif resolved == "draft":
                draft_so += 1

        # -------- LAST PAYMENT --------
        payments_sorted = sorted(
            payments,
            key=lambda x: x.get("date", ""),
            reverse=True
        )

        last_payment = payments_sorted[0] if payments_sorted else None

        summary = {
            # Estimates
            "total_estimates_amount": total_estimates_amount,
            "total_estimates_count": total_estimates_count,
            "pending_quotes": pending_quotes,

            # Invoices
            "total_invoices_amount": total_invoices_amount,
            "total_invoices_count": total_invoices_count,
            "outstanding_invoice_balance": outstanding_balance,
            "outstanding_invoice_count": outstanding_count,
            "unused_credits": unused_credits,

            # Retainers
            "available_retainers": available_retainers,
            "available_retainer_count": available_retainer_count,

            # Sales Orders
            "open_sales_orders": open_so,
            "packed_sales_orders": packed_so,
            "shipped_sales_orders": shipped_so,
            "draft_sales_orders": draft_so,

            # Payments
            "last_payment_amount": last_payment.get("amount") if last_payment else None,
            "last_payment_date": last_payment.get("date") if last_payment else None,
        }

        # 🔹 3. Store in cache
        cache.set(cache_key, summary)

        return summary


zoho_dashboard_service = ZohoDashboardService()