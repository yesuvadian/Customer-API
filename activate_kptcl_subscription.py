"""One-shot script: manually activate the latest pending order for KPTCL."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import VendorSessionLocal
from models import Organization, BillingOrder
from datetime import datetime, timezone, timedelta

def run():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter_by(code="KPTCL").first()
        if not org:
            print("ERROR: KPTCL not found.")
            return

        print(f"Org: {org.name} | is_trial={org.is_trial} | trial_status={org.trial_status}")

        # Find the latest pending order
        order = (
            db.query(BillingOrder)
            .filter_by(org_id=org.id, status="pending")
            .order_by(BillingOrder.created_at.desc())
            .first()
        )
        if not order:
            print("No pending orders found for KPTCL.")
            return

        print(f"Order: {order.id} | plan_id={order.plan_id} | duration={order.duration_days}d | amount={order.amount_paise}")

        now = datetime.now(timezone.utc)
        order.status = "paid"
        order.razorpay_payment_id = "manual_dev_activation"
        order.paid_at = now

        # Activate subscription
        org.is_trial = False
        org.trial_status = "converted"
        base = max(now, org.subscription_end_date or now)
        org.subscription_end_date = base + timedelta(days=order.duration_days)
        if order.plan_id:
            org.plan_id = order.plan_id
        org.onboarding_complete = True
        org.onboarding_completed_at = now

        db.commit()
        print(f"Done. Subscription active until {org.subscription_end_date.date()}")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
