import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()

# Check what the query would return
cur.execute("""
    SELECT id, request_number, status, organization_id
    FROM testing_requests
    WHERE status = 'submitted'
    AND organization_id = 'c24e52ee-db90-40f2-950e-ac5b469a94b2'
    ORDER BY cts DESC
""")

rows = cur.fetchall()
print(f"Found {len(rows)} requests")
for row in rows:
    print(f"  ID: {row[0]}")
    print(f"  Number: {row[1]}")
    print(f"  Status: {row[2]}")
    print(f"  Org ID: {row[3]}")
    print()

conn.close()
