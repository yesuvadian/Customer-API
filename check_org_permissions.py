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

# Find Organization module
print('=== Organization Module ===')
cur.execute("""
SELECT id, name, is_active
FROM modules
WHERE name = 'Organization'
""")
org_module = cur.fetchone()
if org_module:
    print(f'Module found: id={org_module[0]}, name={org_module[1]}, is_active={org_module[2]}')
    org_module_id = org_module[0]
else:
    print('Organization module NOT FOUND')
    org_module_id = None

print('\n=== KPTCL Organization ===')
cur.execute("""
SELECT id, name, email_domain
FROM organizations
WHERE email_domain = 'utility.com' OR name LIKE '%KPTCL%'
""")
orgs = cur.fetchall()
if orgs:
    for org in orgs:
        print(f'Org: id={org[0]}, name={org[1]}, domain={org[2]}')
        kptcl_org_id = org[0]
else:
    print('KPTCL organization NOT FOUND')
    kptcl_org_id = None

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
            admin_role_id = role[0]

            if org_module_id:
                print(f'\n=== Checking permissions for role_id={admin_role_id}, module_id={org_module_id} ===')
                cur.execute("""
                SELECT can_view, can_add, can_edit, can_delete, can_approve
                FROM org_role_permissions
                WHERE role_id = %s AND module_id = %s
                """, (admin_role_id, org_module_id))
                perms = cur.fetchone()
                if perms:
                    print(f'Permissions found:')
                    print(f'  can_view={perms[0]}')
                    print(f'  can_add={perms[1]}')
                    print(f'  can_edit={perms[2]}')
                    print(f'  can_delete={perms[3]}')
                    print(f'  can_approve={perms[4]}')
                else:
                    print('NO PERMISSIONS FOUND for Organization module')
    else:
        print('No admin roles found')

# Also check all modules to see what exists
print('\n=== All Modules ===')
cur.execute("""
SELECT id, name, is_active
FROM modules
WHERE is_active = true
ORDER BY name
""")
modules = cur.fetchall()
for mod in modules:
    print(f'  {mod[0]}: {mod[1]} (active={mod[2]})')

cur.close()
conn.close()
