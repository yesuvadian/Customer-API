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

# Find all tables in the database
cur.execute("""
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
AND table_name LIKE %s
ORDER BY table_schema, table_name;
""", ('%module%',))

print('Tables containing "module":')
for row in cur.fetchall():
    print(f'  {row[0]}.{row[1]}')

print('\n---\n')

# Find all tables that might be related to roles/permissions
cur.execute("""
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
AND (table_name LIKE %s OR table_name LIKE %s OR table_name LIKE %s)
ORDER BY table_schema, table_name;
""", ('%role%', '%permission%', '%org%'))

print('Tables containing "role", "permission", or "org":')
for row in cur.fetchall():
    print(f'  {row[0]}.{row[1]}')

cur.close()
conn.close()
