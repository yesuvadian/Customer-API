"""
Migrate organization admin permissions for new organization modules.
Adds permissions for Organization User Roles and Organization Role Permissions modules
to all existing organization admin roles.
"""
import sys
import os

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from database import SessionLocal
from models import Module, OrgRole, OrgRolePermission
from datetime import datetime
import uuid

def migrate_org_permissions():
    session = SessionLocal()

    try:
        # Get the new organization modules
        org_modules = session.query(Module).filter(
            Module.group_name == 'Organization'
        ).all()

        print(f"Found {len(org_modules)} organization modules:")
        for mod in org_modules:
            print(f"  - {mod.name} (ID: {mod.id})")

        # Get all org admin roles
        org_admin_roles = session.query(OrgRole).filter(
            OrgRole.is_org_admin == True,
            OrgRole.is_active == True
        ).all()

        print(f"\nFound {len(org_admin_roles)} organization admin roles")

        added_count = 0
        updated_count = 0

        for role in org_admin_roles:
            print(f"\nProcessing role: {role.name} (Org ID: {role.organization_id})")

            for module in org_modules:
                # Check if permission already exists
                existing = session.query(OrgRolePermission).filter(
                    OrgRolePermission.org_role_id == role.id,
                    OrgRolePermission.module_id == module.id
                ).first()

                if existing:
                    # Update to full permissions
                    existing.can_view = True
                    existing.can_add = True
                    existing.can_edit = True
                    existing.can_delete = True
                    existing.can_approve = True
                    existing.can_assign = True
                    existing.can_export = True
                    existing.can_import = True
                    existing.mts = datetime.now(datetime.now().astimezone().tzinfo)
                    updated_count += 1
                    print(f"  [OK] Updated permissions for {module.name}")
                else:
                    # Create new permission with full access for org admin
                    permission = OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=role.id,
                        module_id=module.id,
                        can_view=True,
                        can_add=True,
                        can_edit=True,
                        can_delete=True,
                        can_approve=True,
                        can_assign=True,
                        can_export=True,
                        can_import=True,
                        cts=datetime.now(datetime.now().astimezone().tzinfo),
                        mts=datetime.now(datetime.now().astimezone().tzinfo)
                    )
                    session.add(permission)
                    added_count += 1
                    print(f"  [OK] Added permissions for {module.name}")

        session.commit()
        print(f"\n[OK] Migration complete: {added_count} added, {updated_count} updated")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    print("="*80)
    print("  MIGRATING ORGANIZATION PERMISSIONS")
    print("="*80)
    migrate_org_permissions()
