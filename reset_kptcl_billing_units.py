"""Reset KPTCL billing units: set subscription_end_date to NULL (pending_payment)."""
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

        print(f"Org: {org.name} | is_trial={org.is_trial} | billing_scope_id={org.billing_scope_id}")

        updated = db.query(OrgDepartment).filter_by(
            organization_id=org.id,
            is_billing_unit=True,
        ).update({"subscription_end_date": None})

        db.commit()
        print(f"Done. Reset {updated} billing units to pending_payment (subscription_end_date=NULL).")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
