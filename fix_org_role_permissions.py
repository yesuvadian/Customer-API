"""
Fix organization role permissions - remove excessive permissions from roles.
Updates existing organizations to have role-appropriate module access.
"""
import sys
import os

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from database import SessionLocal
from models import Module, OrgRole, OrgRolePermission
from datetime import datetime

def fix_org_role_permissions():
    session = SessionLocal()

    try:
        # Get all modules with their details
        all_modules = session.query(Module).filter(Module.is_active == True).all()

        # Build module lookup by group and name
        modules_by_group = {}
        modules_by_name = {}
        for mod in all_modules:
            if mod.group_name:
                modules_by_group.setdefault(mod.group_name, []).append(mod.id)
            if mod.name:
                modules_by_name[mod.name] = mod.id

        # Define module sets for different roles
        testing_modules = set(modules_by_group.get("Testing", []))

        procurement_module_names = [
            "Request Quote", "RQ with Vendor", "Request Product", "Quotes",
            "Sales Orders", "Invoices", "Retainer Invoices", "Payments Made",
            "Statements", "Enquiry", "Contact Us"
        ]
        procurement_modules = set([modules_by_name.get(name) for name in procurement_module_names if modules_by_name.get(name)])

        org_modules = set(modules_by_group.get("Organization", []))
        dashboard_module = set([modules_by_name.get("Dashboard")]) if modules_by_name.get("Dashboard") else set()

        # Exclude User & Access modules (super admin only)
        user_access_modules = set(modules_by_group.get("User & Access", []))

        # Role definitions: role_name -> (allowed_modules, description)
        role_module_mapping = {
            "Admin": (None, "Full access to all modules (unchanged)"),  # None = all modules
            "Originator": (testing_modules | procurement_modules | dashboard_module, "Testing + Procurement + Dashboard"),
            "Tester": (testing_modules | dashboard_module, "Testing + Dashboard only"),
            "Approver": (testing_modules | dashboard_module, "Testing + Dashboard only"),
            "Department Manager": (testing_modules | procurement_modules | org_modules | dashboard_module, "Testing + Procurement + Organization + Dashboard"),
            "Employee": (testing_modules | procurement_modules | dashboard_module, "View-only: Testing + Procurement + Dashboard"),
            "Viewer": (testing_modules | procurement_modules | dashboard_module, "View-only: Testing + Procurement + Dashboard"),
            "Contributor": (testing_modules | procurement_modules | dashboard_module, "Testing + Procurement + Dashboard"),
        }

        print(f"Found {len(all_modules)} active modules")
        print(f"  - Testing modules: {len(testing_modules)}")
        print(f"  - Procurement modules: {len(procurement_modules)}")
        print(f"  - Organization modules: {len(org_modules)}")
        print(f"  - User & Access modules (excluded): {len(user_access_modules)}")
        print()

        # Get all organization roles
        all_org_roles = session.query(OrgRole).filter(OrgRole.is_active == True).all()
        print(f"Found {len(all_org_roles)} active organization roles\n")

        removed_count = 0
        unchanged_count = 0

        for role in all_org_roles:
            print(f"Processing: {role.name} (Org: {role.organization_id[:8]}...)")

            # Get allowed modules for this role
            if role.name not in role_module_mapping:
                print(f"  [SKIP] Unknown role name, keeping existing permissions")
                continue

            allowed_modules, description = role_module_mapping[role.name]

            if allowed_modules is None:
                # Admin role - keep all permissions
                print(f"  [OK] Admin role - keeping all permissions")
                unchanged_count += 1
                continue

            print(f"  [INFO] Should have: {description}")

            # Get existing permissions
            existing_perms = session.query(OrgRolePermission).filter(
                OrgRolePermission.org_role_id == role.id
            ).all()

            removed_for_role = 0
            for perm in existing_perms:
                # Check if this permission should be removed
                if perm.module_id not in allowed_modules:
                    # Get module name for logging
                    module = session.query(Module).filter(Module.id == perm.module_id).first()
                    module_name = module.name if module else f"Module ID {perm.module_id}"

                    # Don't remove if it's already all False (no permissions)
                    if not any([perm.can_view, perm.can_add, perm.can_edit, perm.can_delete,
                               perm.can_approve, perm.can_assign, perm.can_export, perm.can_import]):
                        continue

                    print(f"  [REMOVE] {module_name}")
                    session.delete(perm)
                    removed_for_role += 1
                    removed_count += 1

            if removed_for_role == 0:
                print(f"  [OK] No changes needed")
                unchanged_count += 1
            else:
                print(f"  [OK] Removed {removed_for_role} excessive permissions")
            print()

        session.commit()
        print("=" * 80)
        print(f"[SUCCESS] Migration complete:")
        print(f"  - Roles processed: {len(all_org_roles)}")
        print(f"  - Roles unchanged: {unchanged_count}")
        print(f"  - Total permissions removed: {removed_count}")
        print("=" * 80)

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    print("=" * 80)
    print("  FIXING ORGANIZATION ROLE PERMISSIONS")
    print("  Removing excessive module access from non-admin roles")
    print("=" * 80)
    print()

    response = input("This will modify existing role permissions. Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    print()
    fix_org_role_permissions()
