"""
Complete test for tester role configuration with exact module matching
Tests all scenarios from the implementation plan
"""
import requests
import json

BASE_URL = "http://localhost:8020"

def login(email, password):
    response = requests.post(
        f"{BASE_URL}/token",
        data={"username": email, "password": password}
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"[ERROR] Login failed for {email}: {response.status_code} - {response.text[:100]}")
        return None

print("=" * 80)
print("  TESTER ROLE CONFIGURATION - COMPLETE TEST")
print("=" * 80)
print()

# Test 1: Check configurations
print("[TEST 1] Check Tester Role Configurations")
print("-" * 80)

admin_token = login("orgadmin@sampleorg.com", "admin123")
if not admin_token:
    print("[SKIP] Could not login as admin, skipping admin tests")
else:
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(f"{BASE_URL}/admin/tester-role-config", headers=headers)
    if response.status_code == 200:
        configs = response.json()
        print(f"[OK] Found {len(configs)} configurations:")
        for config in configs:
            print(f"\n  Config ID: {config['id']}")
            print(f"  Organization: {config['organization_name']}")
            print(f"  Required Modules: {config['required_module_ids']}")
            print(f"  Module Names: {', '.join(config['module_names'])}")
            print(f"  Active: {config['is_active']}")
    else:
        print(f"[ERROR] Failed to get configs: {response.status_code}")
        print(response.text)

print("\n")

# Test 2: Check current roles in organization
print("[TEST 2] Check Roles in Organization")
print("-" * 80)
print("[INFO] Querying database for role permissions...")

import psycopg2
conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)
cur = conn.cursor()

# Get Sample Organization ID
cur.execute("SELECT id, name FROM organizations WHERE name = 'Sample Organization' LIMIT 1")
org = cur.fetchone()
if org:
    org_id, org_name = org
    print(f"[OK] Found organization: {org_name} (ID: {org_id})")

    # Get all roles
    cur.execute("""
        SELECT r.id, r.name, r.is_org_admin, r.is_dept_admin
        FROM org_roles r
        WHERE r.organization_id = %s AND r.is_active = TRUE
        ORDER BY r.name
    """, (org_id,))

    roles = cur.fetchall()
    print(f"\n[OK] Found {len(roles)} active roles:")

    for role in roles:
        role_id, role_name, is_org_admin, is_dept_admin = role
        print(f"\n  Role: {role_name}")
        print(f"    Admin flags: org_admin={is_org_admin}, dept_admin={is_dept_admin}")

        # Get modules with FULL permissions
        cur.execute("""
            SELECT m.id, m.name
            FROM org_role_permissions orp
            JOIN modules m ON m.id = orp.module_id
            WHERE orp.org_role_id = %s
              AND orp.can_view = TRUE
              AND orp.can_add = TRUE
              AND orp.can_edit = TRUE
              AND orp.can_delete = TRUE
              AND orp.can_approve = TRUE
              AND orp.can_assign = TRUE
            ORDER BY m.id
        """, (role_id,))

        full_perms = cur.fetchall()
        module_ids = [p[0] for p in full_perms]

        print(f"    Full permissions on {len(full_perms)} modules: {module_ids}")
        for mod in full_perms:
            print(f"      - [{mod[0]}] {mod[1]}")

        # Check if matches config [45, 46, 49, 51]
        if set(module_ids) == {45, 46, 49, 51}:
            print(f"    >>> EXACT MATCH! This role should appear in dropdown <<<")
        elif 45 in module_ids or 46 in module_ids:
            print(f"    >>> Has testing modules but NOT exact match <<<")
else:
    print("[ERROR] Sample Organization not found")

conn.close()

print("\n\n" + "=" * 80)
print("  TEST COMPLETE")
print("=" * 80)
print("\nSummary:")
print("1. Check configuration - shows required modules [45, 46, 49, 51]")
print("2. Check roles - shows which roles have exact match")
print("\nNext Steps:")
print("1. Create sample roles with exact module permissions")
print("2. Test tester role selection in approval flow")
print("3. Verify only matching roles appear in dropdown")
