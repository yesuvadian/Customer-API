"""
Seed: AI Graph Dashboard module + role privileges
==================================================
Safe to run multiple times — skips if already exists.

Grants:
  - System Administrator  → full access
  - EE_TLSS               → view + export
  - AEE_MAINTENANCE       → view
  - SE_OPERATIONS         → view
"""
import uuid
from database import VendorSessionLocal
from models import Module, OrgRolePermission, OrgRole


MODULE_PATH = "ai-graph-dashboard"
MODULE_NAME = "AI Graph Dashboard"

# Roles → permission sets  {can_view, can_add, can_edit, can_delete,
#                            can_approve, can_assign, can_export, can_import}
ROLE_PERMS = {
    "System Administrator": dict(
        can_view=True, can_add=True, can_edit=True, can_delete=True,
        can_approve=True, can_assign=True, can_export=True, can_import=True,
    ),
    "EE_TLSS": dict(
        can_view=True, can_add=False, can_edit=False, can_delete=False,
        can_approve=False, can_assign=False, can_export=True, can_import=False,
    ),
    "AEE_MAINTENANCE": dict(
        can_view=True, can_add=False, can_edit=False, can_delete=False,
        can_approve=False, can_assign=False, can_export=True, can_import=False,
    ),
}


def seed_ai_graph_module():
    db = VendorSessionLocal()
    try:
        # 1. Module
        existing = db.query(Module).filter_by(path=MODULE_PATH).first()
        if existing:
            print(f"[INFO] Module already exists: {existing.id} ({MODULE_PATH})")
            # Ensure flags are correct even on re-run
            existing.is_menu = True
            existing.is_active = True
            existing.group_name = "Condition Monitoring"
            mod_id = existing.id
        else:
            mod = Module(
                name=MODULE_NAME,
                description=(
                    "AI-powered fleet analytics dashboard — fleet health score, "
                    "remaining life distribution, ageing risk radar, and dielectric "
                    "condition trends across the substation equipment fleet."
                ),
                path=MODULE_PATH,
                group_name="Condition Monitoring",
                is_active=True,
                is_menu=True,
            )
            db.add(mod)
            db.flush()
            mod_id = mod.id
            print(f"[OK] Module created: {mod_id}  path={MODULE_PATH}")

        # 2. Role permissions
        role_names = list(ROLE_PERMS.keys())
        roles = db.query(OrgRole).filter(OrgRole.name.in_(role_names)).all()
        found_names = {r.name for r in roles}
        print(f"[INFO] Roles found in DB: {found_names}")

        granted = 0
        for role in roles:
            perms = ROLE_PERMS[role.name]
            exists = db.query(OrgRolePermission).filter_by(
                org_role_id=role.id, module_id=mod_id
            ).first()
            if exists:
                # Patch existing row to ensure can_view is set correctly
                for k, v in perms.items():
                    setattr(exists, k, v)
                print(f"[UPDATE] Refreshed permissions for {role.name}")
                continue
            db.add(OrgRolePermission(
                id=uuid.uuid4(),
                org_role_id=role.id,
                module_id=mod_id,
                **perms,
            ))
            granted += 1
            print(f"[OK]  Granted to {role.name} — view={perms['can_view']} export={perms['can_export']}")

        for name in role_names:
            if name not in found_names:
                print(f"[SKIP] Role not found in DB: {name}")

        db.commit()
        print(f"\n[DONE] AI Graph Dashboard module ready. Granted to {granted} new role(s).")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    seed_ai_graph_module()
