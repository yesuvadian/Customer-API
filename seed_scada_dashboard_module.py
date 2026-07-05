"""
One-off script to add the SCADA Dashboard module.
Safe to run multiple times — skips if already exists.
"""
import uuid
from database import VendorSessionLocal
from models import Module, OrgRolePermission, OrgRole


def run():
    db = VendorSessionLocal()
    try:
        # 1. Insert module if not exists
        existing = db.query(Module).filter_by(path="scada-dashboard").first()
        if existing:
            print(f"[INFO] Module already exists: {existing.id}")
            mod_id = existing.id
        else:
            mod = Module(
                name="SCADA Dashboard",
                description=(
                    "Real-time SCADA monitoring dashboard — live tag readings, "
                    "alarm conditions, trend analytics, and breach forecasts "
                    "across all connected equipment."
                ),
                path="scada-dashboard",
                group_name="SCADA",
                is_active=True,
            )
            db.add(mod)
            db.flush()
            mod_id = mod.id
            print(f"[OK] Module created: {mod_id}")

        # 2. Grant full permissions to System Administrator
        role_names = ["System Administrator"]

        roles = db.query(OrgRole).filter(OrgRole.name.in_(role_names)).all()
        granted = 0
        for role in roles:
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
                    can_approve=True,
                    can_assign=True,
                    can_export=True,
                    can_import=True,
                ))
                granted += 1
                print(f"[OK] Granted full permissions to {role.name}")
            else:
                print(f"[INFO] Already granted to {role.name}")

        db.commit()
        print(f"\n[DONE] SCADA Dashboard module ready. Granted to {granted} role(s).")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
