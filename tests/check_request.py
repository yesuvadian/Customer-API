import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()
cur.execute('SELECT id, request_number, status, organization_id, originator_id FROM testing_requests ORDER BY cts DESC LIMIT 1')
row = cur.fetchone()
print(f'ID: {row[0]}')
print(f'Request Number: {row[1]}')
print(f'Status: {row[2]}')
print(f'Organization ID: {row[3]}')
print(f'Originator ID: {row[4]}')
conn.close()
