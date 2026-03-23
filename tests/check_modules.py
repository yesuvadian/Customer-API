import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()
cur.execute("""
    SELECT id, name, description, group_name
    FROM modules
    WHERE name ILIKE '%test%'
    ORDER BY name
""")

rows = cur.fetchall()
print(f"Found {len(rows)} testing-related modules:")
for row in rows:
    print(f"  ID: {row[0]:3d} | Name: {row[1]:40s} | Group: {row[3]}")

conn.close()
