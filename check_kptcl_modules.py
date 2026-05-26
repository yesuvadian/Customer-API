import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=os.getenv('DB_PORT'),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()

# Find KPTCL organization
print('=== Finding KPTCL Organization ===')
cur.execute("""
SELECT id, name, code, primary_email
FROM organizations
WHERE name LIKE '%KPTCL%' OR code LIKE '%KPTCL%' OR name LIKE '%utility%'
""")
orgs = cur.fetchall()
if orgs:
    for org in orgs:
        print(f'Org: id={org[0]}, name={org[1]}, code={org[2]}, email={org[3]}')
        kptcl_org_id = org[0]
else:
    print('KPTCL organization NOT FOUND - checking all orgs:')
    cur.execute("SELECT id, name, code, primary_email FROM organizations")
    for org in cur.fetchall():
        print(f'  {org[0]}: {org[1]} ({org[2]}) - {org[3]}')
    kptcl_org_id = None

# Check all modules
print('\n=== All Modules ===')
cur.execute("""
SELECT id, name, is_active
FROM modules
ORDER BY name
""")
modules = cur.fetchall()
for mod in modules:
    print(f'  {mod[0]}: {mod[1]} (active={mod[2]})')

# Check if Organization module exists
org_module = [m for m in modules if 'organization' in m[1].lower()]
if not org_module:
    print('\n*** Organization module NOT FOUND in modules table ***')
    print('This is why the Organization tabs are not appearing!')

if kptcl_org_id:
    print(f'\n=== Admin Roles in KPTCL (org_id={kptcl_org_id}) ===')
    cur.execute("""
    SELECT id, name, is_org_admin
    FROM org_roles
    WHERE organization_id = %s AND (name = 'Admin' OR is_org_admin = true)
    """, (kptcl_org_id,))
    admin_roles = cur.fetchall()
    if admin_roles:
        for role in admin_roles:
            print(f'Role: id={role[0]}, name={role[1]}, is_org_admin={role[2]}')

            print(f'\n=== ALL Permissions for role_id={role[0]} ===')
            cur.execute("""
            SELECT m.name, p.can_view, p.can_add, p.can_edit, p.can_delete, p.can_approve
            FROM org_role_permissions p
            JOIN modules m ON p.module_id = m.id
            WHERE p.role_id = %s
            ORDER BY m.name
            """, (role[0],))
            perms = cur.fetchall()
            if perms:
                for perm in perms:
                    print(f'  {perm[0]}: view={perm[1]}, add={perm[2]}, edit={perm[3]}, delete={perm[4]}, approve={perm[5]}')
            else:
                print('  NO PERMISSIONS FOUND')

cur.close()
conn.close()
