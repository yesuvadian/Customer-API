import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()

# Check all testing requests
cur.execute("""
    SELECT id, request_number, status, organization_id
    FROM testing_requests
    ORDER BY cts DESC
""")

rows = cur.fetchall()
print(f"Found {len(rows)} total requests:")
for row in rows:
    print(f"  {row[1]}: status={row[2]}, org={row[3]}")

conn.close()
