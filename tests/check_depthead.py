import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()
cur.execute("SELECT id, email, organization_id FROM users WHERE email = 'depthead@kptcl.com'")
row = cur.fetchone()
print(f'User ID: {row[0]}')
print(f'Email: {row[1]}')
print(f'Organization ID: {row[2]}')
conn.close()
