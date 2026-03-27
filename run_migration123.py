import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Database connection
conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    database=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD")
)

# Read SQL file
with open('create_bills_table.sql', 'r') as f:
    sql = f.read()

# Execute SQL
cursor = conn.cursor()
cursor.execute(sql)
conn.commit()

print("✅ Bills table created successfully!")

cursor.close()
conn.close()