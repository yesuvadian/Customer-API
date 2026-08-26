"""
Alter: Consolidated Overview Dashboard module + admin privileges
=============================================================
One-time fix applied to the already-provisioned Module id=62 row. Safe to
run multiple times — patches instead of duplicating.

Module id=62 (path="see_dashboard") backs the new org-hierarchy-adaptive
OverviewDashboard (lib/pages/zoho/role_dashboards/overview_dashboard.dart +
GET /dashboard/overview) for the ENTIRE AE->CEE role chain — not just SEE
anymore, hence the rename away from "SEE Dashboard" here. The path itself
is left untouched (still "see_dashboard") since OrgRole.default_module_id
rows for existing roles already point at Module ids whose *path* is what
dashboard.dart / customer_home.dart switch on — renaming the path would be
a breaking change for zero benefit; only the display name/description was
stale.

Before this script: is_active=False, is_menu=False, zero OrgRolePermission
grants for any role. That combination meant the module didn't show up in
GET /modules (active-only by default), and — critically — the org-admin
"default dashboard" picker in org_role_permissions_page.dart filters
modules to isMenu==true, so it wasn't selectable there either, even though
the dashboard code behind it was fully wired up and working via
default_module_path for anyone whose default_module_id already pointed at
it directly. is_menu=True does NOT also add it as a clickable sidebar
item: portal_app_drawer.dart's drawer loop only shows modules whose path
is in its own curated _pathToLabel/_pathToIcon/_pathToSection maps, and
'see_dashboard' was deliberately removed from those (see the NOTE comment
there) when the old per-role dashboards were retired — it stays reachable
only via default_module_path, same as asset_dashboard/admin_dashboard.

Grants:
  - System Administrator  -> full access

Also patches the live `RoleTemplate` row named "System Administrator" so
brand-new organizations provisioned after this script runs get the module
by default too (same gap prior dashboard-module additions — AI Graph,
SCADA — left behind; see seed_comparison_view_module.py for the precedent
this follows).
"""
import uuid
from database import VendorSessionLocal
from models import Module, OrgRolePermission, OrgRole, RoleTemplate


MODULE_PATH = "see_dashboard"
MODULE_NAME = "Department Dashboard"
MODULE_DESCRIPTION = (
    "Org-hierarchy-adaptive dashboard — task view at leaf departments, "
    "worst-first rollup of children higher up. Shared by every "
    "AE/AEE/EE-TLSS/SEE/CEE role via default_module_id."
)

ROLE_PERMS = {
    "System Administrator": dict(
        can_view=True, can_add=True, can_edit=True, can_delete=True,
        can_approve=True, can_assign=True, can_export=True, can_import=True,
    ),
}


def alter_overview_dashboard_module():
    db = VendorSessionLocal()
    try:
        # 1. Module — activate + rename, path stays the same
        mod = db.query(Module).filter_by(path=MODULE_PATH).first()
        if not mod:
            print(f"[ERROR] Module with path={MODULE_PATH} not found — expected it to already exist (id 62).")
            return
        mod.name = MODULE_NAME
        mod.description = MODULE_DESCRIPTION
        mod.is_active = True
        # True so it's selectable in org_role_permissions_page.dart's default-
        # module picker (filters on isMenu) — does NOT add a sidebar drawer
        # item, since portal_app_drawer.dart only shows paths it has curated
        # entries for, and 'see_dashboard' was deliberately dropped from those.
        mod.is_menu = True
        mod_id = mod.id
        print(f"[OK] Module updated: {mod_id} ({MODULE_PATH}) -> name={MODULE_NAME!r}, is_active=True, is_menu=True")

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
            # _provision_default_roles() (services/organization_service.py) copies
            # this straight into the new org's OrgRole.default_module_id — that
            # copy was previously missing entirely (RoleTemplate.default_module_id
            # was set nowhere and read nowhere), so every new org's System
            # Administrator landed with default_module_id=None regardless of this
            # field. Fixed in organization_service.py alongside this data patch.
            if rt.default_module_id != mod_id:
                print(f"[OK] RoleTemplate 'System Administrator' default_module_id: {rt.default_module_id} -> {mod_id}")
                rt.default_module_id = mod_id
            else:
                print("[INFO] RoleTemplate 'System Administrator' default_module_id already set.")

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
        print(f"\n[DONE] Department Dashboard module ready. Granted to {granted} new role(s).")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    alter_overview_dashboard_module()
