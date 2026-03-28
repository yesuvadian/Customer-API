import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

print("="*60)
print("DEBUG: Role Matching Logic")
print("="*60)

with engine.connect() as conn:
    # Get the testing request
    result = conn.execute(text("""
        SELECT id, organization_id, status
        FROM testing_requests
        ORDER BY cts DESC
        LIMIT 1
    """))
    req = result.fetchone()
    if req:
        print(f"\nTesting Request:")
        print(f"  ID: {req[0]}")
        print(f"  Org ID: {req[1]}")
        print(f"  Status: {req[2]}")

        req_org_id = req[1]
    else:
        print("[WARN] No testing requests found")
        req_org_id = None

    # Get tester role module requirements
    result = conn.execute(text("""
        SELECT id, organization_id, required_module_ids
        FROM tester_role_module_requirements
        WHERE is_active = TRUE
    """))
    configs = result.fetchall()
    print(f"\nTester Role Module Requirements:")
    for cfg in configs:
        org = "Global" if cfg[1] is None else str(cfg[1])
        print(f"  - Org: {org}, Modules: {cfg[2]}")

    # Get all roles for the testing request's organization
    if req_org_id:
        result = conn.execute(text("""
            SELECT id, name, organization_id
            FROM org_roles
            WHERE organization_id = :org_id
            AND is_active = TRUE
            ORDER BY name
        """), {"org_id": req_org_id})

        roles = result.fetchall()
        print(f"\nRoles in Testing Request's Organization ({req_org_id}):")
        for role in roles:
            print(f"  - {role[1]} (ID: {role[0]})")

            # Get permissions for this role
            perm_result = conn.execute(text("""
                SELECT module_id,
                       can_view, can_add, can_edit, can_delete, can_approve, can_assign
                FROM org_role_permissions
                WHERE org_role_id = :role_id
                ORDER BY module_id
            """), {"role_id": role[0]})

            perms = perm_result.fetchall()
            full_perm_modules = []
            for perm in perms:
                if all([perm[1], perm[2], perm[3], perm[4], perm[5], perm[6]]):
                    full_perm_modules.append(perm[0])

            print(f"    Full permission modules: {full_perm_modules}")
            print(f"    Match [45,46,49,51]? {set(full_perm_modules) == {45, 46, 49, 51}}")

print("\n" + "="*60)
