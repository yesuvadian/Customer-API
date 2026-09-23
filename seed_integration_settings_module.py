"""
Register the "Integration Settings" module and grant full permissions to
every org-admin role.

Safe to run multiple times — skips insert if the module already exists.

Usage:
    python seed_integration_settings_module.py
"""
import uuid

from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission


MODULE_PATH = "integration_settings"
MODULE_NAME = "Integration Settings"


def run(db=None):
    close_db = db is None
    if db is None:
        db = VendorSessionLocal()

    try:
        existing = db.query(Module).filter_by(path=MODULE_PATH).first()
        if existing:
            print(f"[INFO] Module already exists: id={existing.id}")
            mod_id = existing.id
        else:
            mod = Module(
                name=MODULE_NAME,
                description=(
                    "Admin-configurable SMTP + SMS gateway credentials, org-"
                    "overridable — replaces .env-only integration settings."
                ),
                path=MODULE_PATH,
                group_name="Integration",
                is_active=True,
                is_menu=True,
            )
            db.add(mod)
            db.flush()
            mod_id = mod.id
            print(f"[OK] Module created: id={mod_id}")

        admin_roles = (
            db.query(OrgRole)
            .filter(OrgRole.is_org_admin == True, OrgRole.is_active == True)
            .all()
        )

        granted = 0
        for role in admin_roles:
            exists = db.query(OrgRolePermission).filter_by(
                org_role_id=role.id, module_id=mod_id
            ).first()
            if not exists:
                db.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod_id,
                    can_view=True,
                    can_add=True,
                    can_edit=True,
                    can_delete=True,
                    can_approve=False,
                    can_assign=False,
                    can_export=False,
                    can_import=False,
                ))
                granted += 1
                print(f"[OK] Granted full permissions -> {role.name}")
            else:
                exists.can_view = True
                exists.can_add = True
                exists.can_edit = True
                exists.can_delete = True
                granted += 1
                print(f"[OK] Updated permissions -> {role.name}")

        db.commit()
        print(f"\n[DONE] Integration Settings module ready. Granted to {granted} role(s).")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    run()
