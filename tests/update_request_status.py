"""
Update testing request status to pending_approval for testing
"""
import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()

# Update specific testing request to submitted
cur.execute("""
    UPDATE testing_requests
    SET status = 'submitted'
    WHERE id = '5a56571f-42e7-4f38-bc3f-30eb76db3002'
    RETURNING id, request_number, status
""")

result = cur.fetchone()
if result:
    print(f"[OK] Updated request {result[1]} (ID: {result[0]}) to status: {result[2]}")
else:
    print("[INFO] No draft requests found")

conn.commit()
cur.close()
conn.close()
