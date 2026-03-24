#!/usr/bin/env python3
"""
Grant full permissions to Organization Admin role
"""

import uuid
from datetime import datetime
from sqlalchemy import text
from database import VendorSessionLocal

session = VendorSessionLocal()

try:
    print("\n" + "=" * 60)
    print("  GRANT PERMISSIONS TO ORGANIZATION ADMIN")
    print("=" * 60 + "\n")

    # Get KPTCL org
    org = session.execute(
        text("SELECT id FROM organizations WHERE code = 'KPTCL'")
    ).fetchone()

    if not org:
        print("[ERROR] KPTCL organization not found!")
        exit(1)

    org_id = str(org[0])

    # Get Organization Admin role
    role = session.execute(
        text("SELECT id, name FROM org_roles WHERE organization_id = :org_id AND name = 'Organization Admin'"),
        {'org_id': org_id}
    ).fetchone()

    if not role:
        print("[ERROR] Organization Admin role not found!")
        exit(1)

    role_id = str(role[0])
    role_name = role[1]

    print(f"Role: {role_name} (ID: {role_id})\n")

    # Get all modules
    modules = session.execute(
        text("SELECT id, name, description FROM modules WHERE is_active = true ORDER BY name")
    ).fetchall()

    print(f"Found {len(modules)} active modules\n")

    # Delete existing permissions for this role
    deleted = session.execute(
        text("DELETE FROM org_role_permissions WHERE org_role_id = :role_id"),
        {'role_id': role_id}
    ).rowcount

    if deleted > 0:
        print(f"[INFO] Deleted {deleted} existing permissions\n")

    # Create permissions for each module
    created = 0
    for module_id, module_name, description in modules:
        # Check if permission already exists
        existing = session.execute(
            text("""
                SELECT id FROM org_role_permissions
                WHERE org_role_id = :role_id AND module_id = :module_id
            """),
            {'role_id': role_id, 'module_id': module_id}
        ).fetchone()

        if not existing:
            session.execute(
                text("""
                    INSERT INTO org_role_permissions (
                        id, org_role_id, module_id,
                        can_view, can_add, can_edit, can_delete,
                        can_approve, can_assign, can_export, can_import,
                        cts, mts
                    ) VALUES (
                        :id, :role_id, :module_id,
                        true, true, true, true,
                        true, true, true, true,
                        :cts, :mts
                    )
                """),
                {
                    'id': str(uuid.uuid4()),
                    'role_id': role_id,
                    'module_id': module_id,
                    'cts': datetime.now(),
                    'mts': datetime.now()
                }
            )
            created += 1
            print(f"[OK] Granted full access to: {module_name}")

    session.commit()

    print("\n" + "=" * 60)
    print(f"  [SUCCESS] Granted {created} module permissions")
    print("=" * 60 + "\n")

    print("Organization Admin now has full access to all modules!")
    print("\nYou can now login with:")
    print("  Email: orgadmin@kptcl.com")
    print("  Password: admin123")
    print("\n" + "=" * 60 + "\n")

except Exception as e:
    session.rollback()
    print(f"\n[ERROR] Failed: {e}")
    import traceback
    traceback.print_exc()
finally:
    session.close()
