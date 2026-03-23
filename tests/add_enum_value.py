"""
Add pending_approval value to TestingRequestStatus enum
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

# Check current enum values
cur.execute("SELECT enum_range(NULL::testingrequeststatus)")
current_values = cur.fetchone()[0]
print(f"Current enum values: {current_values}")

# Add pending_approval if it doesn't exist
if 'pending_approval' not in current_values:
    print("Adding 'pending_approval' to enum...")
    cur.execute("ALTER TYPE testingrequeststatus ADD VALUE 'pending_approval'")
    conn.commit()
    print("[OK] Added 'pending_approval' to TestingRequestStatus enum")
else:
    print("[INFO] 'pending_approval' already exists in enum")

cur.close()
conn.close()
