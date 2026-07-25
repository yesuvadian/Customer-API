"""One-shot script: reset KPTCL billing back to org_level."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import VendorSessionLocal
from models import Organization, OrgDepartment, BillingScope

def run():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter_by(code="KPTCL").first()
        if not org:
            print("ERROR: KPTCL organisation not found.")
            return

        print(f"Found org: {org.name} (id={org.id})")
        print(f"Current billing_scope_id: {org.billing_scope_id}, billing_hierarchy_level: {org.billing_hierarchy_level}")

        # Clear all dept billing unit flags
        cleared = db.query(OrgDepartment).filter_by(
            organization_id=org.id, is_active=True
        ).update({"is_billing_unit": False, "subscription_end_date": None})
        print(f"Cleared {cleared} department(s).")

        # Switch billing mode back to org_level
        org_scope = db.query(BillingScope).filter_by(code="org_level").first()
        if org_scope:
            org.billing_scope_id = org_scope.id
            print(f"Set billing_scope -> org_level (id={org_scope.id})")
        else:
            print("WARNING: org_level BillingScope not found in DB.")

        org.billing_hierarchy_level = None

        db.commit()
        print("Done. KPTCL billing reset to Organisation Level.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
