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

# Check organizations table columns
print('=== Organizations Table Columns ===')
cur.execute("""
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'organizations'
ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]}')

# Find KPTCL organization
print('\n=== Finding KPTCL Organization ===')
cur.execute("""
SELECT id, name, domain
FROM organizations
WHERE domain = 'utility.com' OR name LIKE '%KPTCL%'
""")
orgs = cur.fetchall()
for org in orgs:
    print(f'Org: id={org[0]}, name={org[1]}, domain={org[2]}')

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

cur.close()
conn.close()
