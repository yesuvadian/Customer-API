"""Set KPTCL billing units to expire in 5 days for testing."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import VendorSessionLocal
from models import Organization, OrgDepartment
from datetime import datetime, timezone, timedelta

def run():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter_by(code="KPTCL").first()
        if not org:
            print("ERROR: KPTCL not found.")
            return

        expiry = datetime.now(timezone.utc) + timedelta(days=5)

        updated = db.query(OrgDepartment).filter_by(
            organization_id=org.id, is_billing_unit=True
        ).update({"subscription_end_date": expiry})

        # Also update org subscription_end_date
        org.subscription_end_date = expiry

        db.commit()
        print(f"Done. {updated} billing units expire on {expiry.date()} (5 days from now).")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
