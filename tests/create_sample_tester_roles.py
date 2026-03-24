"""
Create sample tester roles with EXACT module permissions [45, 46, 49, 51]
This demonstrates the exact module matching for tester role selection
"""
import psycopg2
import uuid

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()

# Get Sample Organization
cur.execute("SELECT id, name FROM organizations WHERE name = 'Sample Organization'")
org = cur.fetchone()
if not org:
    print("[ERROR] Sample Organization not found!")
    exit(1)

org_id = org[0]
org_name = org[1]
print(f"[OK] Found organization: {org_name}")
print(f"     ID: {org_id}")

# Required modules for testers
REQUIRED_MODULES = [45, 46, 49, 51]
print(f"\n[INFO] Required modules: {REQUIRED_MODULES}")

# Module names for reference
cur.execute("SELECT id, name FROM modules WHERE id = ANY(%s)", (REQUIRED_MODULES,))
modules = cur.fetchall()
print("[INFO] Module names:")
for mod in modules:
    print(f"  [{mod[0]}] {mod[1]}")

print("\n" + "=" * 80)
print("  CREATING SAMPLE TESTER ROLES")
print("=" * 80)

# Create 2 sample tester roles
tester_roles = [
    {
        "name": "Field Tester",
        "description": "Field tester role with exact module permissions for tester assignment"
    },
    {
        "name": "Lab Tester",
        "description": "Laboratory tester role with exact module permissions for tester assignment"
    }
]

for tester_config in tester_roles:
    print(f"\n[INFO] Creating role: {tester_config['name']}")

    # Check if role already exists
    cur.execute("""
        SELECT id FROM org_roles
        WHERE organization_id = %s AND name = %s
    """, (org_id, tester_config['name']))

    existing = cur.fetchone()
    if existing:
        role_id = existing[0]
        print(f"  [SKIP] Role already exists (ID: {role_id})")

        # Delete existing permissions
        cur.execute("DELETE FROM org_role_permissions WHERE org_role_id = %s", (role_id,))
        print(f"  [OK] Cleared existing permissions")
    else:
        # Create new role
        role_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO org_roles (
                id, organization_id, name, description,
                is_org_admin, is_dept_admin, is_active
            ) VALUES (
                %s, %s, %s, %s, FALSE, FALSE, TRUE
            )
        """, (role_id, org_id, tester_config['name'], tester_config['description']))
        print(f"  [OK] Created role (ID: {role_id})")

    # Add FULL permissions for EXACT modules
    for module_id in REQUIRED_MODULES:
        perm_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO org_role_permissions (
                id, org_role_id, module_id,
                can_view, can_add, can_edit, can_delete, can_approve, can_assign
            ) VALUES (
                %s, %s, %s,
                TRUE, TRUE, TRUE, TRUE, TRUE, TRUE
            )
        """, (perm_id, role_id, module_id))

    print(f"  [OK] Added FULL permissions for modules: {REQUIRED_MODULES}")

conn.commit()

print("\n" + "=" * 80)
print("  SAMPLE TESTER ROLES CREATED SUCCESSFULLY")
print("=" * 80)

# Verify
print("\n[VERIFY] Checking created roles:")
cur.execute("""
    SELECT r.name, array_agg(p.module_id ORDER BY p.module_id) as modules
    FROM org_roles r
    LEFT JOIN org_role_permissions p ON p.org_role_id = r.id
    WHERE r.organization_id = %s
      AND r.name IN ('Field Tester', 'Lab Tester')
      AND p.can_view AND p.can_add AND p.can_edit
      AND p.can_delete AND p.can_approve AND p.can_assign
    GROUP BY r.id, r.name
""", (org_id,))

roles = cur.fetchall()
for role in roles:
    print(f"\n  Role: {role[0]}")
    print(f"  Modules: {role[1]}")
    if set(role[1]) == set(REQUIRED_MODULES):
        print(f"  >>> EXACT MATCH! Will appear in tester dropdown <<<")

# Create sample users for these roles
print("\n" + "=" * 80)
print("  CREATING SAMPLE USERS")
print("=" * 80)

users_to_create = [
    {
        "email": "fieldtester1@sampleorg.com",
        "password": "Tester123!",
        "role": "Field Tester",
        "firstname": "Field",
        "lastname": "Tester One"
    },
    {
        "email": "fieldtester2@sampleorg.com",
        "password": "Tester123!",
        "role": "Field Tester",
        "firstname": "Field",
        "lastname": "Tester Two"
    },
    {
        "email": "labtester1@sampleorg.com",
        "password": "Tester123!",
        "role": "Lab Tester",
        "firstname": "Lab",
        "lastname": "Tester One"
    }
]

from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

for user_config in users_to_create:
    # Check if user exists
    cur.execute("SELECT id FROM users WHERE email = %s", (user_config['email'],))
    existing_user = cur.fetchone()

    if existing_user:
        user_id = existing_user[0]
        print(f"[SKIP] User already exists: {user_config['email']}")
    else:
        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = pwd_context.hash(user_config['password'])

        cur.execute("""
            INSERT INTO users (
                id, email, password_hash, firstname, lastname,
                phone_number, organization_id, isactive
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, TRUE
            )
        """, (user_id, user_config['email'], hashed_password,
              user_config['firstname'], user_config['lastname'], '9999999999', org_id))
        print(f"[OK] Created user: {user_config['email']}")

    # Get role ID
    cur.execute("SELECT id FROM org_roles WHERE organization_id = %s AND name = %s",
                (org_id, user_config['role']))
    role_result = cur.fetchone()
    if not role_result:
        print(f"[ERROR] Role not found: {user_config['role']}")
        continue

    role_id = role_result[0]

    # Assign user to role
    cur.execute("""
        SELECT id FROM org_user_roles
        WHERE user_id = %s AND org_role_id = %s
    """, (user_id, role_id))

    if cur.fetchone():
        print(f"  [SKIP] User already has role: {user_config['role']}")
    else:
        user_role_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO org_user_roles (
                id, user_id, org_role_id, is_active
            ) VALUES (
                %s, %s, %s, TRUE
            )
        """, (user_role_id, user_id, role_id))
        print(f"  [OK] Assigned role: {user_config['role']}")

conn.commit()
conn.close()

print("\n" + "=" * 80)
print("  COMPLETE!")
print("=" * 80)
print("\nCreated:")
print("  - 2 tester roles with EXACT module permissions [45, 46, 49, 51]")
print("  - 3 test users assigned to these roles")
print("\nTest Users:")
print("  - fieldtester1@sampleorg.com / Tester123!")
print("  - fieldtester2@sampleorg.com / Tester123!")
print("  - labtester1@sampleorg.com / Tester123!")
print("\nNext: Test tester role selection in approval workflow")
