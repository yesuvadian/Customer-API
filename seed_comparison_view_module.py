"""
Seed: AI-Assisted Comparison View module + role privileges
=============================================================
Safe to run multiple times — skips/patches instead of duplicating.

Grants:
  - System Administrator  → full access

Also patches the live `RoleTemplate` row named "System Administrator" so
that brand-new organizations provisioned after this script runs get the
module by default too (this is the step prior dashboard-module additions
— AI Graph, SCADA — skipped: they only granted access to *existing* orgs'
roles, never touched RoleTemplate.permissions_template, so any org created
afterwards never saw those dashboards). Editing seed.py's source list alone
is not enough for a live database — the already-persisted RoleTemplate row
has to be patched directly, the same way OrgTestTemplate DB rows have to be
patched separately from test_templates.py source edits.
"""
import uuid
from database import VendorSessionLocal
from models import Module, OrgRolePermission, OrgRole, RoleTemplate


MODULE_PATH = "comparison-view"
MODULE_NAME = "AI-Assisted Comparison View"
MODULE_DESCRIPTION = (
    "Multi-test-type comparison dashboard for any equipment type — "
    "compare its test types side by side, sliced by department and "
    "year range, with each test type's counts always kept separate."
)

# Roles → permission sets  {can_view, can_add, can_edit, can_delete,
#                            can_approve, can_assign, can_export, can_import}
ROLE_PERMS = {
    "System Administrator": dict(
        can_view=True, can_add=True, can_edit=True, can_delete=True,
        can_approve=True, can_assign=True, can_export=True, can_import=True,
    ),
}


def seed_comparison_view_module():
    db = VendorSessionLocal()
    try:
        # 1. Module
        existing = db.query(Module).filter_by(path=MODULE_PATH).first()
        if existing:
            print(f"[INFO] Module already exists: {existing.id} ({MODULE_PATH})")
            existing.is_menu = True
            existing.is_active = True
            existing.group_name = "Condition Monitoring"
            existing.description = MODULE_DESCRIPTION
            mod_id = existing.id
        else:
            mod = Module(
                name=MODULE_NAME,
                description=MODULE_DESCRIPTION,
                path=MODULE_PATH,
                group_name="Condition Monitoring",
                is_active=True,
                is_menu=True,
            )
            db.add(mod)
            db.flush()
            mod_id = mod.id
            print(f"[OK] Module created: {mod_id}  path={MODULE_PATH}")

        # 2. Role permissions — existing orgs
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
                for k, v in perms.items():
                    setattr(exists, k, v)
                print(f"[UPDATE] Refreshed permissions for {role.name} (org_role_id={role.id})")
                continue
            db.add(OrgRolePermission(
                id=uuid.uuid4(),
                org_role_id=role.id,
                module_id=mod_id,
                **perms,
            ))
            granted += 1
            print(f"[OK]  Granted to {role.name} (org_role_id={role.id})")

        for name in role_names:
            if name not in found_names:
                print(f"[SKIP] Role not found in DB: {name}")

        # 3. RoleTemplate — so NEW orgs get this module automatically too
        rt = db.query(RoleTemplate).filter_by(name="System Administrator").first()
        if rt:
            perms_list = list(rt.permissions_template or [])
            already = any(p.get("module_id") == mod_id for p in perms_list)
            if already:
                print("[INFO] RoleTemplate 'System Administrator' already includes this module.")
            else:
                perms_list.append({
                    "module_id": mod_id,
                    "can_view": True, "can_add": True, "can_edit": True,
                    "can_delete": True, "can_approve": True, "can_assign": True,
                    "can_export": True, "can_import": True,
                })
                rt.permissions_template = perms_list
                print("[OK] RoleTemplate 'System Administrator' patched — new orgs will get this module.")
        else:
            print("[WARN] RoleTemplate 'System Administrator' not found — new-org provisioning will NOT include this module until seed_role_templates() is run.")

        db.commit()
        print(f"\n[DONE] AI-Assisted Comparison View module ready. Granted to {granted} new role(s).")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    seed_comparison_view_module()
