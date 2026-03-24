import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

print("="*60)
print("CHECKING TESTER ROLE CONFIGURATION SETUP")
print("="*60)

with engine.connect() as conn:
    # Check tester role module requirements
    print("\n1. Tester Role Module Requirements:")
    result = conn.execute(text("""
        SELECT id, organization_id, required_module_ids, description, is_active
        FROM tester_role_module_requirements
    """))
    rows = result.fetchall()
    if rows:
        for row in rows:
            org = "Global" if row[1] is None else str(row[1])
            print(f"  - Org: {org}")
            print(f"    Modules: {row[2]}")
            print(f"    Active: {row[4]}")
            print(f"    Description: {row[3]}")
    else:
        print("  [WARN] No tester role module requirements found!")

    # Check tester roles
    print("\n2. Tester Roles (Field Tester, Lab Tester):")
    result = conn.execute(text("""
        SELECT r.id, r.name, r.organization_id
        FROM org_roles r
        WHERE r.name IN ('Field Tester', 'Lab Tester')
    """))
    roles = result.fetchall()
    if roles:
        for role in roles:
            print(f"  - {role[1]} (ID: {role[0]})")

            # Check permissions for this role
            perm_result = conn.execute(text("""
                SELECT module_id, can_view, can_add, can_edit, can_delete, can_approve, can_assign
                FROM org_role_permissions
                WHERE org_role_id = :role_id
                ORDER BY module_id
            """), {"role_id": role[0]})

            perms = perm_result.fetchall()
            full_perm_modules = []
            for perm in perms:
                if all([perm[1], perm[2], perm[3], perm[4], perm[5], perm[6]]):
                    full_perm_modules.append(perm[0])

            print(f"    Modules with FULL permissions: {full_perm_modules}")
            print(f"    Total permission entries: {len(perms)}")
    else:
        print("  [WARN] No tester roles found!")

    # Check tester users
    print("\n3. Tester Users:")
    result = conn.execute(text("""
        SELECT u.email, u.firstname, u.lastname, r.name as role_name
        FROM users u
        JOIN org_user_roles our ON u.id = our.user_id
        JOIN org_roles r ON our.org_role_id = r.id
        WHERE r.name IN ('Field Tester', 'Lab Tester')
        ORDER BY r.name, u.email
    """))
    users = result.fetchall()
    if users:
        for user in users:
            print(f"  - {user[0]} ({user[1]} {user[2]}) - Role: {user[3]}")
    else:
        print("  [WARN] No tester users found!")

print("\n" + "="*60)
