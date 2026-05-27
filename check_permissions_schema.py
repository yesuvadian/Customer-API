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

# Check org_role_permissions table columns
print('=== org_role_permissions Table Columns ===')
cur.execute("""
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'org_role_permissions'
ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]}')

# Check permissions for KPTCL Admin role
kptcl_admin_role_id = 'd1d9f1e3-8d80-49f3-9a73-99e50d55dbd6'

print(f'\n=== ALL Permissions for KPTCL Admin Role ===')
cur.execute("""
SELECT org_role_id, module_id, can_view, can_add, can_edit, can_delete, can_approve
FROM org_role_permissions
WHERE org_role_id = %s
""", (kptcl_admin_role_id,))

perms = cur.fetchall()
if perms:
    print(f'Found {len(perms)} permissions')

    # Get module names
    print('\nPermissions with module names:')
    cur.execute("""
    SELECT m.id, m.name, p.can_view, p.can_add, p.can_edit, p.can_delete, p.can_approve
    FROM org_role_permissions p
    JOIN modules m ON p.module_id = m.id
    WHERE p.org_role_id = %s
    ORDER BY m.name
    """, (kptcl_admin_role_id,))

    for perm in cur.fetchall():
        print(f'  {perm[1]}: view={perm[2]}, add={perm[3]}, edit={perm[4]}, delete={perm[5]}, approve={perm[6]}')
else:
    print('NO PERMISSIONS FOUND')

# Check specifically for Organization-related modules
print('\n=== Organization-Related Modules ===')
cur.execute("""
SELECT id, name, is_active
FROM modules
WHERE name LIKE '%Organization%' OR name LIKE '%Org %'
ORDER BY name
""")
org_modules = cur.fetchall()
for mod in org_modules:
    print(f'  {mod[0]}: {mod[1]} (active={mod[2]})')

    # Check if Admin has permission for this module
    cur.execute("""
    SELECT can_view, can_add, can_edit, can_delete, can_approve
    FROM org_role_permissions
    WHERE org_role_id = %s AND module_id = %s
    """, (kptcl_admin_role_id, mod[0]))

    perm = cur.fetchone()
    if perm:
        print(f'    Admin has permission: view={perm[0]}, add={perm[1]}, edit={perm[2]}, delete={perm[3]}, approve={perm[4]}')
    else:
        print(f'    *** Admin MISSING permission for this module ***')

cur.close()
conn.close()
