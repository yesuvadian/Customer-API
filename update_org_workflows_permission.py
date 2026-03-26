"""
Update existing organization roles to include Workflows module permissions.
Run this after adding new modules to grant permissions to existing organizations.
"""

import uuid
from database import VendorSessionLocal
from models import Organization, OrgRole, OrgRolePermission, Module

def update_org_role_permissions():
    """Add Workflows module permissions to all existing organization admin roles."""
    session = VendorSessionLocal()

    try:
        # Get the Workflows module
        workflows_module = session.query(Module).filter(
            Module.name == "Workflows",
            Module.is_active == True
        ).first()

        if not workflows_module:
            print("[ERROR] Workflows module not found or inactive")
            return

        print(f"[INFO] Found Workflows module (ID: {workflows_module.id})")

        # Get all organizations
        orgs = session.query(Organization).filter(Organization.is_active == True).all()
        print(f"[INFO] Found {len(orgs)} active organizations")

        updated_count = 0

        for org in orgs:
            print(f"\n[INFO] Processing organization: {org.name} ({org.id})")

            # Get all roles in this organization
            roles = session.query(OrgRole).filter(
                OrgRole.organization_id == org.id,
                OrgRole.is_active == True
            ).all()

            for role in roles:
                # Check if permission already exists
                existing_perm = session.query(OrgRolePermission).filter(
                    OrgRolePermission.org_role_id == role.id,
                    OrgRolePermission.module_id == workflows_module.id
                ).first()

                if existing_perm:
                    print(f"  [SKIP] Role '{role.name}' already has Workflows permission")
                    continue

                # Determine permissions based on role type
                if role.is_org_admin:
                    # Admin gets full access
                    permissions = {
                        "can_view": True,
                        "can_add": True,
                        "can_edit": True,
                        "can_delete": True,
                        "can_approve": True,
                        "can_assign": True,
                        "can_export": True,
                        "can_import": True
                    }
                elif role.name in ["Originator", "Tester", "Department Manager"]:
                    # Regular users get view + some edit
                    permissions = {
                        "can_view": True,
                        "can_add": True,
                        "can_edit": True,
                        "can_delete": False,
                        "can_approve": False,
                        "can_assign": True,
                        "can_export": True,
                        "can_import": False
                    }
                elif role.name == "Approver":
                    # Approver gets view + approve
                    permissions = {
                        "can_view": True,
                        "can_add": False,
                        "can_edit": False,
                        "can_delete": False,
                        "can_approve": True,
                        "can_assign": False,
                        "can_export": True,
                        "can_import": False
                    }
                elif role.name == "Viewer":
                    # Viewer gets only view
                    permissions = {
                        "can_view": True,
                        "can_add": False,
                        "can_edit": False,
                        "can_delete": False,
                        "can_approve": False,
                        "can_assign": False,
                        "can_export": False,
                        "can_import": False
                    }
                else:
                    # Default: view only
                    permissions = {
                        "can_view": True,
                        "can_add": False,
                        "can_edit": False,
                        "can_delete": False,
                        "can_approve": False,
                        "can_assign": False,
                        "can_export": False,
                        "can_import": False
                    }

                # Create permission
                new_perm = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=workflows_module.id,
                    **permissions
                )
                session.add(new_perm)
                updated_count += 1

                print(f"  [ADD] Added Workflows permission to role '{role.name}'")

        session.commit()
        print(f"\n[OK] Successfully added Workflows permissions to {updated_count} roles across {len(orgs)} organizations")

    except Exception as e:
        session.rollback()
        print(f"[ERROR] Failed to update permissions: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    print("=" * 80)
    print("  UPDATE ORGANIZATION WORKFLOWS PERMISSIONS")
    print("=" * 80)
    print()

    update_org_role_permissions()

    print()
    print("=" * 80)
    print("  [DONE]")
    print("=" * 80)
