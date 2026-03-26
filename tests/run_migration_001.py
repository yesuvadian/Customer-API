"""
Run migration: Create tester role module requirements table
"""
import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

# Read migration SQL
with open('migrations/001_create_tester_role_config.sql', 'r') as f:
    migration_sql = f.read()

cur = conn.cursor()

try:
    print("Running migration...")
    cur.execute(migration_sql)
    conn.commit()
    print("✓ Migration completed successfully!")

    # Verify
    print("\nVerifying table created...")
    cur.execute("""
        SELECT
            id,
            organization_id,
            required_module_ids,
            array_length(required_module_ids, 1) as module_count,
            description,
            is_active
        FROM public.tester_role_module_requirements
    """)

    rows = cur.fetchall()
    print(f"✓ Found {len(rows)} configuration(s):")
    for row in rows:
        print(f"\n  ID: {row[0]}")
        print(f"  Organization: {'Global Default' if row[1] is None else row[1]}")
        print(f"  Required Modules: {row[2]}")
        print(f"  Module Count: {row[3]}")
        print(f"  Description: {row[4]}")
        print(f"  Active: {row[5]}")

except Exception as e:
    conn.rollback()
    print(f"✗ Migration failed: {e}")
    raise
finally:
    cur.close()
    conn.close()
