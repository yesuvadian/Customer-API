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
    SELECT id, email
    FROM users
    WHERE organization_id = 'c24e52ee-db90-40f2-950e-ac5b469a94b2'
    AND email = 'tester1@kptcl.com'
""")

row = cur.fetchone()
print(f"Tester ID: {row[0]}")
print(f"Email: {row[1]}")

conn.close()
