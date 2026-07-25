"""Reset KPTCL to trial-expired state for testing."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import VendorSessionLocal
from models import Organization, OrgDepartment, BillingOrder
from datetime import datetime, timezone, timedelta

def run():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter_by(code="KPTCL").first()
        if not org:
            print("ERROR: KPTCL not found.")
            return

        # Set trial as expired (ended 2 days ago)
        now = datetime.now(timezone.utc)
        org.is_trial = True
        org.trial_status = "expired"
        org.trial_end_date = now - timedelta(days=2)
        org.subscription_end_date = now - timedelta(days=2)
        org.plan_id = None

        # Cancel all pending orders
        cancelled = db.query(BillingOrder).filter_by(org_id=org.id, status="pending").update({"status": "cancelled"})

        # Reset all billing units to pending_payment
        units = db.query(OrgDepartment).filter_by(
            organization_id=org.id, is_billing_unit=True
        ).update({"subscription_end_date": None})

        db.commit()
        print(f"Done. KPTCL trial expired 2 days ago.")
        print(f"  Cancelled {cancelled} pending orders.")
        print(f"  Reset {units} billing units to pending_payment.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
