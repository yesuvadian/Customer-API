"""
Registers the "Subscription & Billing" module and grants org admin roles view-only access.
  - Org admin roles → can_view=True only (view status + payment history)
  - can_add / can_edit (initiate payment / configure billing) granted per-org via
    role management UI — not seeded globally.
Safe to run multiple times.
"""
import uuid
from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission

MODULE_PATH = "subscription-billing"
MODULE_NAME = "Subscription & Billing"


def run(db=None):
    close_db = db is None
    if db is None:
        db = VendorSessionLocal()
    try:
        # 1. Ensure module exists
        existing = db.query(Module).filter_by(path=MODULE_PATH).first()
        if existing:
            mod_id = existing.id
            print(f"[INFO] Module already exists: id={mod_id}")
        else:
            mod = Module(
                name=MODULE_NAME,
                description=(
                    "View subscription status, payment history, and manage billing "
                    "for the organisation or department. Users with add/edit privilege "
                    "can initiate payment or configure billing mode."
                ),
                path=MODULE_PATH,
                group_name="Administration",
                is_active=True,
                is_menu=True,
            )
            db.add(mod)
            db.flush()
            mod_id = mod.id
            print(f"[OK] Module created: id={mod_id}")

        # 2. Org admin roles → view only
        admin_roles = (
            db.query(OrgRole)
            .filter(OrgRole.is_org_admin == True, OrgRole.is_active == True)
            .all()
        )
        for role in admin_roles:
            perm = db.query(OrgRolePermission).filter_by(
                org_role_id=role.id, module_id=mod_id
            ).first()
            if not perm:
                db.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod_id,
                    can_view=True,
                    can_add=False,
                    can_edit=False,
                    can_delete=False,
                    can_approve=False,
                    can_assign=False,
                    can_export=False,
                    can_import=False,
                ))
                print(f"[OK] View-only granted → {role.name}")
            else:
                # Ensure at least can_view is set; do NOT upgrade add/edit
                if not perm.can_view:
                    perm.can_view = True
                    print(f"[OK] can_view enabled → {role.name}")
                else:
                    print(f"[INFO] Already has permission → {role.name}")

        db.commit()
        print("[DONE] Subscription & Billing module seed complete.")
    except Exception as e:
        db.rollback()
        raise
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    run()
