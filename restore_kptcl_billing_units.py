"""Restore KPTCL billing units: copy org subscription_end_date to all billing units."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import VendorSessionLocal
from models import Organization, OrgDepartment

def run():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter_by(code="KPTCL").first()
        if not org:
            print("ERROR: KPTCL not found.")
            return

        if not org.subscription_end_date:
            print("ERROR: org.subscription_end_date is NULL — nothing to copy.")
            return

        print(f"Org subscription ends: {org.subscription_end_date.date()}")

        updated = db.query(OrgDepartment).filter_by(
            organization_id=org.id,
            is_billing_unit=True,
        ).update({"subscription_end_date": org.subscription_end_date})

        db.commit()
        print(f"Done. Restored {updated} billing units to {org.subscription_end_date.date()}.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
