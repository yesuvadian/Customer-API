"""
Seed role templates for auto-provisioning default roles to new organizations.
Run this script once to create the default role templates in the database.

Usage:
    python seed_role_templates.py
"""

from sqlalchemy.orm import Session
from database import VendorSessionLocal
from models import RoleTemplate, Module
from utils.common_service import UTCDateTimeMixin
import uuid


def get_all_modules(db: Session):
    """Get all module IDs from the database."""
    modules = db.query(Module.id).all()
    return [m.id for m in modules]


def seed_default_role_templates(db: Session):
    """Create default role templates for auto-provisioning."""

    # Get all module IDs
    module_ids = get_all_modules(db)

    if not module_ids:
        print("Warning: No modules found in database. Please seed modules first.")
        print("Role templates will be created but without permission templates.")
        module_ids = []

    templates = [
        {
            "name": "Admin",
            "description": "Full administrative access to the organization. Can manage users, roles, departments, and all organization resources.",
            "is_org_admin": True,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": True,
                    "can_approve": True,
                    "can_assign": True,
                    "can_export": True,
                    "can_import": True
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Originator",
            "description": "Creates testing requests and raises procurement. Full access to testing requests and procurement modules.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": True,
                    "can_approve": False,
                    "can_assign": True,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Tester",
            "description": "Performs transformer testing and uploads results. Full access to testing and recommendations modules.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Approver",
            "description": "Reviews and approves or rejects recommendations. Approval access to testing workflow.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": True,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Department Manager",
            "description": "Manage department users and departmental resources. Can view and manage users within their department.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": False,
                    "can_approve": True,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Employee",
            "description": "Standard employee access. Can view organization resources and manage their own data.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": False,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Viewer",
            "description": "Read-only access to organization resources.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": False,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Contributor",
            "description": "Can add and edit resources but cannot delete or approve.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": True
                }
                for mid in module_ids
            ]
        }
    ]

    created_count = 0
    updated_count = 0

    for template_data in templates:
        # Check if template already exists
        existing = db.query(RoleTemplate).filter(
            RoleTemplate.name == template_data["name"]
        ).first()

        if existing:
            print(f"Updating existing template: {template_data['name']}")
            # Update existing template
            existing.description = template_data["description"]
            existing.is_org_admin = template_data["is_org_admin"]
            existing.is_dept_admin = template_data["is_dept_admin"]
            existing.auto_provision = template_data["auto_provision"]
            existing.permissions_template = template_data["permissions_template"]
            existing.mts = UTCDateTimeMixin._utc_now()
            updated_count += 1
        else:
            print(f"Creating new template: {template_data['name']}")
            # Create new template
            template = RoleTemplate(
                id=uuid.uuid4(),
                name=template_data["name"],
                description=template_data["description"],
                is_org_admin=template_data["is_org_admin"],
                is_dept_admin=template_data["is_dept_admin"],
                auto_provision=template_data["auto_provision"],
                permissions_template=template_data["permissions_template"],
                cts=UTCDateTimeMixin._utc_now(),
                mts=UTCDateTimeMixin._utc_now()
            )
            db.add(template)
            created_count += 1

    db.commit()
    print(f"\n✅ Role template seeding complete!")
    print(f"   - Created: {created_count} new templates")
    print(f"   - Updated: {updated_count} existing templates")
    print(f"   - Total: {created_count + updated_count} templates in database")


def list_templates(db: Session):
    """List all role templates in the database."""
    templates = db.query(RoleTemplate).all()

    if not templates:
        print("No role templates found in database.")
        return

    print("\n📋 Role Templates:")
    print("-" * 80)
    for template in templates:
        print(f"\n  Name: {template.name}")
        print(f"  Description: {template.description}")
        print(f"  Org Admin: {template.is_org_admin}")
        print(f"  Dept Admin: {template.is_dept_admin}")
        print(f"  Auto Provision: {template.auto_provision}")
        print(f"  Permissions: {len(template.permissions_template)} modules configured")
        print("-" * 80)


def main():
    """Main function to run the seeding."""
    print("=" * 80)
    print("  ROLE TEMPLATE SEEDER")
    print("=" * 80)

    db = VendorSessionLocal()

    try:
        print("\n🌱 Seeding role templates...")
        seed_default_role_templates(db)

        print("\n📊 Current templates in database:")
        list_templates(db)

        print("\n" + "=" * 80)
        print("  ✅ SEEDING COMPLETED SUCCESSFULLY")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Error during seeding: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
