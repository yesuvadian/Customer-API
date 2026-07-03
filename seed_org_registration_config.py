"""
seed_org_registration_config.py
────────────────────────────────
Idempotently seeds all system_config rows that control the org
self-registration flow:

  • trial settings          (trial_duration_days, trial_alert_days, …)
  • default admin role      (name, modules, permission flags)

Also runs migration 035 (org_registration_trial_onboarding) and
migration 036 (default_admin_role_config) if their tables don't yet exist.

Additionally fixes any existing orgs whose admin user has no OrgUserRole:
  • creates a "System Administrator" OrgRole for that org
  • grants it all modules with full permissions
  • assigns the admin user to the role

Can be called from seed.py or run standalone:
    python seed_org_registration_config.py
"""

import json
import uuid
from datetime import datetime

from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission, OrgUserRole, Organization, SystemConfig, User


# ── Config defaults ───────────────────────────────────────────────────────────
# Each tuple: (key, value, value_type, description)
SYSTEM_CONFIG_DEFAULTS = [
    (
        "trial_duration_days", "30", "int",
        "Length of the free trial in days",
    ),
    (
        "trial_alert_days", "7", "int",
        "Days before trial expiry to send warning email",
    ),
    (
        "default_temp_password", "Welcome@123", "str",
        "Temporary password assigned to admin on org self-registration",
    ),
    (
        "registration_enabled", "true", "bool",
        "Allow public org self-registration via /public/register-org",
    ),
    (
        "max_trial_users", "10", "int",
        "Max users allowed during the trial period",
    ),
    (
        "max_trial_equipment", "100", "int",
        "Max equipment records allowed during the trial period",
    ),
    (
        "default_admin_role_name", "System Administrator", "str",
        "OrgRole name auto-provisioned for the admin user on org self-registration",
    ),
    (
        "default_admin_role_modules", "*", "str",
        (
            'Modules granted to the default admin role. '
            '"*" = all active modules. '
            'Or a JSON array of module names, e.g. ["Dashboard","Equipment","Testing"]'
        ),
    ),
    (
        "default_admin_role_permissions",
        json.dumps({
            "can_view": True,
            "can_add": True,
            "can_edit": True,
            "can_delete": True,
            "can_approve": True,
            "can_assign": True,
            "can_export": True,
            "can_import": True,
        }),
        "json",
        (
            "Permission flags granted per module for the default admin role. "
            "Edit this JSON to restrict what future self-registered admins can do."
        ),
    ),
]


def seed_system_config(session) -> int:
    """
    Insert missing system_config rows.  Existing keys are NOT overwritten.
    Returns the number of new rows inserted.
    """
    inserted = 0
    for key, value, value_type, description in SYSTEM_CONFIG_DEFAULTS:
        exists = session.query(SystemConfig).filter_by(key=key).first()
        if exists:
            continue
        session.add(SystemConfig(
            id=uuid.uuid4(),
            key=key,
            value=value,
            value_type=value_type,
            description=description,
        ))
        inserted += 1

    if inserted:
        session.commit()
    return inserted


def _resolve_modules(session, modules_config: str):
    """Return Module objects based on the modules_config value."""
    if modules_config.strip() == "*":
        return session.query(Module).filter_by(is_active=True).all()
    try:
        names = json.loads(modules_config)
    except Exception:
        names = [n.strip() for n in modules_config.split(",") if n.strip()]
    return session.query(Module).filter(Module.name.in_(names), Module.is_active == True).all()


def _resolve_perm_flags(session) -> dict:
    """Read default_admin_role_permissions from system_config or fall back to all-true."""
    row = session.query(SystemConfig).filter_by(key="default_admin_role_permissions").first()
    raw = row.value if row else None
    try:
        flags = json.loads(raw) if raw else {}
    except Exception:
        flags = {}
    defaults = {
        "can_view": True, "can_add": True, "can_edit": True,
        "can_delete": True, "can_approve": True, "can_assign": True,
        "can_export": True, "can_import": True,
    }
    defaults.update(flags)
    return defaults


def _upsert_role_permissions(session, role: OrgRole, modules, flags: dict) -> int:
    """Grant (or update) OrgRolePermission for every given module. Returns count."""
    count = 0
    for mod in modules:
        perm = (
            session.query(OrgRolePermission)
            .filter_by(org_role_id=role.id, module_id=mod.id)
            .first()
        )
        if perm:
            for f, v in flags.items():
                if hasattr(perm, f):
                    setattr(perm, f, v)
        else:
            kwargs = {"id": uuid.uuid4(), "org_role_id": role.id, "module_id": mod.id}
            for f, v in flags.items():
                kwargs[f] = v
            for ts in ("cts", "mts"):
                if hasattr(OrgRolePermission, ts):
                    kwargs[ts] = datetime.utcnow()
            session.add(OrgRolePermission(**kwargs))
        count += 1
    return count


def seed_default_admin_role_for_existing_orgs(session) -> dict:
    """
    For every org whose admin user has NO OrgUserRole assigned, create a
    'System Administrator' OrgRole, grant it all modules, and assign it.

    Idempotent — skips orgs that already have any OrgUserRole for the admin.

    Returns {"orgs_fixed": N, "permissions_granted": M}
    """
    # Read config
    role_name_row = session.query(SystemConfig).filter_by(key="default_admin_role_name").first()
    role_name = role_name_row.value if role_name_row else "System Administrator"

    modules_row = session.query(SystemConfig).filter_by(key="default_admin_role_modules").first()
    modules_config = modules_row.value if modules_row else "*"
    modules = _resolve_modules(session, modules_config)
    flags = _resolve_perm_flags(session)

    orgs = session.query(Organization).filter_by(is_active=True).all()
    orgs_fixed = 0
    permissions_granted = 0

    for org in orgs:
        # Find the org admin user (usertype = 'org_admin')
        admin_user = (
            session.query(User)
            .filter_by(organization_id=org.id, usertype="org_admin", is_active=True)
            .first()
        )
        if not admin_user:
            continue

        # Check if admin already has any OrgUserRole
        has_role = session.query(OrgUserRole).filter_by(
            user_id=admin_user.id, is_active=True
        ).first()
        if has_role:
            continue

        print(f"  [FIX] Org '{org.name}' admin '{admin_user.email}' has no role — provisioning '{role_name}' ...")

        # Find or create the System Administrator OrgRole for this org
        admin_role = (
            session.query(OrgRole)
            .filter_by(organization_id=org.id, name=role_name)
            .first()
        )
        if not admin_role:
            admin_role = OrgRole(
                id=uuid.uuid4(),
                organization_id=org.id,
                name=role_name,
                description="Auto-provisioned system administrator role",
                role_type="default",
                is_org_admin=True,
                is_active=True,
            )
            session.add(admin_role)
            session.flush()
        else:
            admin_role.is_org_admin = True
            admin_role.is_active = True

        # Grant module permissions
        count = _upsert_role_permissions(session, admin_role, modules, flags)
        permissions_granted += count

        # Assign role to admin user
        session.add(OrgUserRole(
            id=uuid.uuid4(),
            user_id=admin_user.id,
            org_role_id=admin_role.id,
            department_id=None,
            is_active=True,
        ))

        session.commit()
        orgs_fixed += 1

    return {"orgs_fixed": orgs_fixed, "permissions_granted": permissions_granted}


def _mark_seeded_orgs_onboarding_complete(session) -> int:
    """
    Mark any org that has no trial (is_trial=False) as onboarding_complete=True.
    These are seeded/manually-created orgs that already have data and should
    never be shown the onboarding wizard.
    """
    from datetime import timezone
    orgs = session.query(Organization).filter(
        Organization.is_trial == False,
        Organization.onboarding_complete == False,
    ).all()
    now = datetime.now(timezone.utc)
    for org in orgs:
        org.onboarding_complete = True
        org.onboarding_completed_at = now
        print(f"  [MARK] {org.name} → onboarding_complete=true")
    if orgs:
        session.commit()
    return len(orgs)


def seed_all(session=None) -> dict:
    """
    Main entry point.  Pass an existing session or let the function open one.
    Returns a summary dict.
    """
    own_session = session is None
    if own_session:
        session = VendorSessionLocal()

    try:
        print("\n" + "=" * 60)
        print("  ORG REGISTRATION CONFIG SEED")
        print("=" * 60)

        print("\n--- system_config rows ---")
        inserted = seed_system_config(session)
        print(f"[OK] {inserted} new config row(s) inserted (0 = already seeded)")

        print("\n--- Fix existing orgs with no admin role ---")
        fix_result = seed_default_admin_role_for_existing_orgs(session)
        print(f"[OK] {fix_result['orgs_fixed']} org(s) fixed, "
              f"{fix_result['permissions_granted']} permission rows upserted")

        print("\n--- Mark seeded orgs as onboarding complete ---")
        marked = _mark_seeded_orgs_onboarding_complete(session)
        print(f"[OK] {marked} seeded org(s) marked onboarding_complete=true")

        return {
            "config_inserted": inserted,
            "seeded_orgs_marked": marked,
            **fix_result,
        }

    except Exception as exc:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


if __name__ == "__main__":
    result = seed_all()
    print(f"\n[DONE] {result}")
