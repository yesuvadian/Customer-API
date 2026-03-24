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
    SELECT id, email, firstname, lastname, organization_id
    FROM users
    WHERE organization_id = 'c24e52ee-db90-40f2-950e-ac5b469a94b2'
    ORDER BY email
""")

rows = cur.fetchall()
print(f"Found {len(rows)} users in KPTCL organization:")
for row in rows:
    print(f"  {row[1]:30s} - {row[2]} {row[3]}")

conn.close()
