"""
Run migration 043: overall dashboard view permission.

The Overall Dashboard screen's data calls (GET /dashboard/overview,
GET /organizations/{id}, GET /organizations/{id}/departments/{id}) are
gated by the module-permission middleware (middleware/auth_privilege.py)
against OrgRolePermission.can_view for the "dashboard" and "organizations"
modules specifically — not against the role-specific sidebar-visibility
modules (e.g. "see_dashboard", "ae_dashboard", "admin_dashboard") that
actually control whether "Overall Dashboard" shows up in a role's sidebar.

Confirmed live: AE_JE had can_view=True on "see_dashboard"/"ae_dashboard"
(so the page appeared in its sidebar and was reachable) but can_view=False
on "dashboard" and "organizations" — every fetch the page made came back
403, leaving the screen permanently stuck on "Error loading dashboard".
Every other role at this org had the same gap to a greater or lesser
degree, since nothing had ever granted these two modules explicitly.

This grants can_view on "dashboard" and "organizations" to every org role
at Karnataka Power Transmission Corporation Limited (scoped to this one
organization, not platform-wide) so Overall Dashboard actually loads for
whichever roles already show it in their sidebar. Safe to re-run: the
INSERT ON CONFLICT only ever sets can_view = true, never touches add/
edit/delete/approve/assign/export/import, and never overwrites an existing
grant with anything weaker.

Part 2 fixes the general case this bug is one instance of: a role whose
default_module_id (its post-login landing page) doesn't have can_view on
that same module lands somewhere it can't actually load data for — exactly
what services/org_role_service.py's update_role/update_role_permission/
set_role_permissions now refuse to let a fresh save create. But those
guards are forward-only; they don't retroactively fix a role that was
already saved into that state before the guards existed. Confirmed live:
Sample Organization's AEE_MAINTENANCE had default_module_id="asset_dashboard"
with no can_view grant at all — audited platform-wide, it was the only
other role in this state. Grants can_view on a role's own default module,
platform-wide, for any role where that's missing; same safe-to-re-run
ON CONFLICT shape as part 1.
"""
from database import SessionLocal
from sqlalchemy import text

ORG_NAME = "Karnataka Power Transmission Corporation Limited"
MODULE_PATHS = ("dashboard", "organizations")


def run():
    db = SessionLocal()
    try:
        result = db.execute(text("""
            INSERT INTO public.org_role_permissions
                (id, org_role_id, module_id, can_view, can_add, can_edit,
                 can_delete, can_approve, can_assign, can_export, can_import,
                 cts, mts)
            SELECT gen_random_uuid(), r.id, m.id, true, false, false,
                   false, false, false, false, false, now(), now()
            FROM public.org_roles r
            JOIN public.organizations o ON o.id = r.organization_id
            CROSS JOIN public.modules m
            WHERE o.name = :org_name
              AND m.path = ANY(:module_paths)
            ON CONFLICT (org_role_id, module_id)
                DO UPDATE SET can_view = true, mts = now()
                WHERE public.org_role_permissions.can_view IS DISTINCT FROM true
        """), {"org_name": ORG_NAME, "module_paths": list(MODULE_PATHS)})
        db.commit()
        print(f"Migration 043 complete: {result.rowcount} org_role_permissions "
              f"row(s) granted/updated with can_view=True on "
              f"{', '.join(MODULE_PATHS)} for '{ORG_NAME}'.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()

    db = SessionLocal()
    try:
        result = db.execute(text("""
            INSERT INTO public.org_role_permissions
                (id, org_role_id, module_id, can_view, can_add, can_edit,
                 can_delete, can_approve, can_assign, can_export, can_import,
                 cts, mts)
            SELECT gen_random_uuid(), r.id, r.default_module_id, true, false,
                   false, false, false, false, false, false, now(), now()
            FROM public.org_roles r
            WHERE r.default_module_id IS NOT NULL
            ON CONFLICT (org_role_id, module_id)
                DO UPDATE SET can_view = true, mts = now()
                WHERE public.org_role_permissions.can_view IS DISTINCT FROM true
        """))
        db.commit()
        print(f"Migration 043 part 2 complete: {result.rowcount} org_role_permissions "
              f"row(s) granted/updated so every role's default_module_id has "
              f"can_view=True, platform-wide.")
    except Exception as e:
        db.rollback()
        print(f"Migration part 2 failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
