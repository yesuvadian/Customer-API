import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()

# Get KPTCL organization ID
cur.execute("SELECT id FROM organizations WHERE name LIKE 'Karnataka Power%'")
org_id = cur.fetchone()[0]
print(f"KPTCL Organization ID: {org_id}")

# Update testing request with organization_id
cur.execute("""
    UPDATE testing_requests
    SET organization_id = %s
    WHERE id = '5a56571f-42e7-4f38-bc3f-30eb76db3002'
    RETURNING id, request_number, organization_id
""", (org_id,))

result = cur.fetchone()
print(f"[OK] Updated request {result[1]} with organization_id: {result[2]}")

conn.commit()
cur.close()
conn.close()
