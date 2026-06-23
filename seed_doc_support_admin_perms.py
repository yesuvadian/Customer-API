"""
Add document-support and document-support-queue module permissions
to the System Administrator role only. Does NOT touch any other role.
Idempotent — safe to re-run.
"""
import sys, uuid
sys.path.insert(0, ".")

from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission, Organization

MODULES_TO_ADD = ["document-support", "document-support-queue"]

def run():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter_by(code="KPTCL").first() \
              or db.query(Organization).first()
        if not org:
            raise RuntimeError("No organization found")

        role = db.query(OrgRole).filter_by(
            organization_id=org.id, name="System Administrator"
        ).first()
        if not role:
            raise RuntimeError("System Administrator role not found")

        for path in MODULES_TO_ADD:
            mod = db.query(Module).filter_by(path=path).first()
            if not mod:
                print(f"  [SKIP] Module '{path}' not found — run seed_doc_support_roles_users first")
                continue

            existing = db.query(OrgRolePermission).filter_by(
                org_role_id=role.id, module_id=mod.id
            ).first()
            if existing:
                # Update to FULL if not already
                existing.can_view = existing.can_add = existing.can_edit = True
                existing.can_delete = existing.can_approve = existing.can_assign = True
                existing.can_export = existing.can_import = True
                print(f"  [UPDATE] {path} → FULL")
            else:
                db.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod.id,
                    can_view=True, can_add=True, can_edit=True, can_delete=True,
                    can_approve=True, can_assign=True, can_export=True, can_import=True,
                ))
                print(f"  [CREATE] {path} → FULL")

        db.commit()
        print("Done.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
