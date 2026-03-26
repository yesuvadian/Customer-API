import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text("SELECT email FROM users WHERE email LIKE '%sampleorg%' LIMIT 10"))
    users = [row[0] for row in result]
    print("Users in database:")
    for user in users:
        print(f"  - {user}")

    if not users:
        print("No users found! Database might not be seeded.")
