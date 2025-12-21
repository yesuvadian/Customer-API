from services.zoho_client import zoho_request
import config


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
                # Log but don't kill dashboard
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

    # ----------- MAIN SUMMARY BUILDER ------------

    def build_dashboard_summary(self, contact_id: str) -> dict:

        quotes = self.get_quotes(contact_id)
        invoices = self.get_invoices(contact_id)
        sales_orders = self.get_sales_orders(contact_id)
        payments = self.get_payments(contact_id)

        # QUOTES SUMMARY
        pending_quotes = len([
            q for q in quotes
            if q.get("status", "").lower() in ["sent"]
        ])
        total_estimates_amount = sum(float(q.get("total", 0) or 0) for q in quotes)
        total_estimates_count = len(quotes)

        # INVOICES SUMMARY
        total_invoices_amount = sum(float(i.get("total", 0) or 0) for i in invoices)
        total_invoices_count = len(invoices)

        outstanding = [i for i in invoices if float(i.get("balance", 0) or 0) > 0]
        outstanding_balance = sum(float(i.get("balance", 0) or 0) for i in outstanding)
        outstanding_count = len(outstanding)

        unused_credits = sum(float(i.get("credits_applied", 0) or 0) for i in invoices)

        # SALES ORDERS SUMMARY
        open_so = len([o for o in sales_orders if o.get("status", "").lower() == "open"])
        packed_so = len([o for o in sales_orders if o.get("status", "").lower() == "packed"])
        shipped_so = len([o for o in sales_orders if o.get("status", "").lower() == "shipped"])
        draft_so = len([o for o in sales_orders if o.get("status", "").lower() == "draft"])

        # LAST PAYMENT
        payments_sorted = sorted(
            payments, key=lambda x: x.get("date", ""), reverse=True
        )
        last_payment = payments_sorted[0] if payments_sorted else None

        return {
            "total_estimates_amount": total_estimates_amount,
            "total_estimates_count": total_estimates_count,

            "total_invoices_amount": total_invoices_amount,
            "total_invoices_count": total_invoices_count,

            "outstanding_invoice_balance": outstanding_balance,
            "outstanding_invoice_count": outstanding_count,

            "unused_credits": unused_credits,

            "open_sales_orders": open_so,
            "packed_sales_orders": packed_so,
            "shipped_sales_orders": shipped_so,
            "draft_sales_orders": draft_so,

            "pending_quotes": pending_quotes,

            "last_payment_amount": last_payment.get("amount") if last_payment else None,
            "last_payment_date": last_payment.get("date") if last_payment else None
        }


zoho_dashboard_service = ZohoDashboardService()
