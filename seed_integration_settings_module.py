"""
Register the "Integration Settings" module and grant full permissions to
every org-admin role.

Safe to run multiple times — skips insert if the module already exists.

Usage:
    python seed_integration_settings_module.py
"""
import uuid

from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission, RoleTemplate


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


def seed_integration_settings_role_templates(db=None):
    """
    Patch all RoleTemplate records so future org provisioning includes
    Integration Settings — without this, run() above only grants the module
    to org-admin roles that ALREADY EXIST; any org created afterwards via
    OrganizationService.create_organization_with_admin() builds its roles
    purely from RoleTemplate.permissions_template (see
    services/organization_service.py:164-205's _provision_default_roles())
    and would never see this module at all.

    Same fix pattern as seed_pm_schedules_module.py's
    seed_pm_schedules_role_templates() — the first module addition (AI
    Graph, SCADA) to hit this gap; PM Schedules was the first to actually
    fix it. Threshold Config has this same unpatched gap (pre-existing,
    not introduced here) and should get the identical fix separately.

    Integration Settings holds SMTP/SMS credentials, so unlike PM
    Schedules' can_view-for-everyone default, non-org-admin templates get
    no entry at all here (no access, not even read-only) rather than a
    diminished-permission one — matching run()'s own org-admin-only grant
    above.

    Idempotent — skips templates that already include the module.
    """
    close_db = db is None
    if db is None:
        db = VendorSessionLocal()

    try:
        mod = db.query(Module).filter_by(path=MODULE_PATH).first()
        if not mod:
            print(f"[WARN] '{MODULE_NAME}' module not found — run seed_integration_settings_module first.")
            return 0

        templates = db.query(RoleTemplate).all()
        updated = 0

        for tmpl in templates:
            if not tmpl.is_org_admin:
                continue  # credentials screen — admin-only, no diminished grant for others

            perms = list(tmpl.permissions_template or [])
            already = any(str(p.get("module_id")) == str(mod.id) for p in perms)
            if already:
                print(f"[INFO] RoleTemplate '{tmpl.name}': Integration Settings already present — skipped.")
                continue

            perms.append({
                "module_id": str(mod.id),
                "can_view": True, "can_add": True, "can_edit": True,
                "can_delete": True, "can_approve": False, "can_assign": False,
                "can_export": False, "can_import": False,
            })
            tmpl.permissions_template = perms
            updated += 1
            print(f"[OK] RoleTemplate '{tmpl.name}': Integration Settings entry added.")

        db.commit()
        print(f"[DONE] Role templates updated: {updated} template(s) patched.")
        return updated
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    run()
    seed_integration_settings_role_templates()
