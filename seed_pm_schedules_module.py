"""
Seed script: PM Schedules module + role permissions.

Creates the 'PM Schedules' module (path: pm_schedules) and grants access to
all OrgRoles in every organisation that should see the preventive maintenance
schedule dashboard.

Safe to run multiple times — idempotent.

Standalone usage:
    python seed_pm_schedules_module.py

Called from seed.py (new installations):
    from seed_pm_schedules_module import (
        seed_pm_schedules_module, seed_pm_schedules_permissions,
        seed_pm_schedules_role_templates,
    )
    seed_pm_schedules_module(session)
    seed_pm_schedules_permissions(session)
    seed_pm_schedules_role_templates(session)
"""

import uuid

from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission, Organization, RoleTemplate

# ── Constants ────────────────────────────────────────────────────────────────

MODULE_NAME = "PM Schedules"
MODULE_PATH = "pm_schedules"
MODULE_GROUP = "Condition Monitoring"
MODULE_DESCRIPTION = (
    "Preventive maintenance schedule dashboard — operational view of maintenance "
    "schedules per equipment with upcoming, overdue, and compliance tracking. "
    "Mirrors CM Schedules but scoped to the maintenance request category."
)

# Roles that get full access (can_add / can_edit / can_delete in addition to can_view)
FULL_ACCESS_ROLE_NAMES = {
    "Maintenance Officer",
    "Test & Work Coordinator",
}

# Roles that get read-only access
READONLY_ROLE_NAMES = {
    "System Administrator",
    "Asset Data Officer",
    "Test Engineer",
    "Reviewing Officer",
    "Supervisory Officer",
    "Senior Management Approver",
    "TA&QC Inspector",
    "Transformer Repair Coordinator",
    "Procurement Officer",
    "Procurement Approver",
    "AI / Analytics User",
    "Read-Only Auditor / MIS User",
    "Admin",
}


# ── Core functions (importable from seed.py) ─────────────────────────────────

def seed_pm_schedules_module(session):
    """
    Insert the PM Schedules module if it does not already exist.
    Returns the module id.
    Idempotent — safe to call on every full reseed.
    """
    existing = session.query(Module).filter_by(path=MODULE_PATH).first()
    if existing:
        # Update name/description in case they changed
        if existing.name != MODULE_NAME:
            existing.name = MODULE_NAME
            existing.description = MODULE_DESCRIPTION
            session.flush()
            print(f"[OK] PM Schedules module updated (id={existing.id})")
        else:
            print(f"[INFO] PM Schedules module already exists (id={existing.id})")
        return existing.id

    mod = Module(
        name=MODULE_NAME,
        description=MODULE_DESCRIPTION,
        path=MODULE_PATH,
        group_name=MODULE_GROUP,
        is_active=True,
    )
    session.add(mod)
    session.flush()
    print(f"[OK] PM Schedules module created (id={mod.id})")
    return mod.id


def seed_pm_schedules_permissions(session, org=None):
    """
    Grant PM Schedules module access to OrgRoles.

    If *org* is provided, only that organisation's roles are processed.
    If *org* is None, all active organisations are processed.

    Access matrix:
      is_org_admin roles              → full access (all flags)
      FULL_ACCESS_ROLE_NAMES roles    → can_view + can_add + can_edit
      READONLY_ROLE_NAMES roles       → can_view only

    Idempotent — inserts missing rows, updates existing ones.
    """
    mod = session.query(Module).filter_by(path=MODULE_PATH).first()
    if not mod:
        print(f"[WARN] '{MODULE_NAME}' module not found — run seed_pm_schedules_module first.")
        return 0

    orgs = [org] if org is not None else session.query(Organization).filter_by(is_active=True).all()
    if not orgs:
        print("[WARN] seed_pm_schedules_permissions: no organisations found — skipped.")
        return 0

    total_granted = 0

    for organisation in orgs:
        roles = (
            session.query(OrgRole)
            .filter(
                OrgRole.organization_id == organisation.id,
                OrgRole.is_active.is_(True),
            )
            .all()
        )

        granted = 0
        for role in roles:
            is_admin = role.is_org_admin
            is_full = role.name in FULL_ACCESS_ROLE_NAMES
            is_readonly = role.name in READONLY_ROLE_NAMES

            if not is_admin and not is_full and not is_readonly:
                continue  # role should not see this module

            existing = (
                session.query(OrgRolePermission)
                .filter_by(org_role_id=role.id, module_id=mod.id)
                .first()
            )

            if is_admin or is_full:
                if existing:
                    existing.can_view = existing.can_add = existing.can_edit = True
                    existing.can_delete = existing.can_approve = existing.can_assign = True
                    existing.can_export = existing.can_import = True
                else:
                    session.add(OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=role.id,
                        module_id=mod.id,
                        can_view=True, can_add=True, can_edit=True,
                        can_delete=True, can_approve=True, can_assign=True,
                        can_export=True, can_import=True,
                    ))
                    granted += 1
            else:
                # Read-only
                if existing:
                    existing.can_view = True
                else:
                    session.add(OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=role.id,
                        module_id=mod.id,
                        can_view=True, can_add=False, can_edit=False,
                        can_delete=False, can_approve=False, can_assign=False,
                        can_export=False, can_import=False,
                    ))
                    granted += 1

        total_granted += granted
        print(
            f"[OK] PM Schedules ({organisation.display_name}): "
            f"permissions seeded for {len(roles)} role(s) ({granted} new rows)."
        )

    session.commit()
    print(f"[DONE] PM Schedules permissions: {total_granted} total new rows inserted.")
    return total_granted


def seed_pm_schedules_role_templates(session):
    """
    Patch all RoleTemplate records so future org provisioning includes PM Schedules.

    RoleTemplate.permissions_template is a stored JSON list built at seed time.
    When a new org is provisioned, _provision_default_roles() iterates this list
    to create OrgRolePermission rows — so PM Schedules must be in the list or
    new orgs won't get it.

    This function appends a PM Schedules entry to every template that doesn't
    already have one, matching the same can_* flags the template uses for other
    full-access modules (org-admin templates get full access; others get can_view).

    Idempotent — skips templates that already include the module.
    """
    mod = session.query(Module).filter_by(path=MODULE_PATH).first()
    if not mod:
        print(f"[WARN] '{MODULE_NAME}' module not found — run seed_pm_schedules_module first.")
        return 0

    templates = session.query(RoleTemplate).all()
    updated = 0

    for tmpl in templates:
        perms = list(tmpl.permissions_template or [])
        already = any(str(p.get("module_id")) == str(mod.id) for p in perms)
        if already:
            print(f"[INFO] RoleTemplate '{tmpl.name}': PM Schedules already present — skipped.")
            continue

        # Full access for org-admin templates; read-only for everyone else
        if tmpl.is_org_admin:
            entry = {
                "module_id": str(mod.id),
                "can_view": True, "can_add": True, "can_edit": True,
                "can_delete": True, "can_approve": True, "can_assign": True,
                "can_export": True, "can_import": True,
            }
        else:
            entry = {
                "module_id": str(mod.id),
                "can_view": True, "can_add": False, "can_edit": False,
                "can_delete": False, "can_approve": False, "can_assign": False,
                "can_export": False, "can_import": False,
            }

        perms.append(entry)
        tmpl.permissions_template = perms
        updated += 1
        print(f"[OK] RoleTemplate '{tmpl.name}': PM Schedules entry added.")

    session.commit()
    print(f"[DONE] Role templates updated: {updated} template(s) patched.")
    return updated


# ── Standalone entry point ────────────────────────────────────────────────────

def run():
    db = VendorSessionLocal()
    try:
        seed_pm_schedules_module(db)
        seed_pm_schedules_permissions(db)
        seed_pm_schedules_role_templates(db)
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
