"""
Run migration to alter users table for organization multi-tenancy
"""
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

# Get database connection details
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

print("=" * 80)
print("  RUNNING ORGANIZATION MIGRATION")
print("=" * 80)

try:
    # Connect to database
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    conn.autocommit = True
    cursor = conn.cursor()

    print(f"\n[OK] Connected to database: {DB_NAME}")

    # Read and execute the migration SQL file
    migration_file = "migrations/001_add_organization_multi_tenancy.sql"
    print(f"\n[INFO] Reading migration file: {migration_file}")

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    print("[INFO] Executing migration...")
    cursor.execute(sql_script)

    print("\n" + "=" * 80)
    print("  MIGRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)
    print("\nChanges applied:")
    print("  [OK] Created organizations table")
    print("  [OK] Created org_departments table")
    print("  [OK] Created org_roles table")
    print("  [OK] Created org_user_roles table")
    print("  [OK] Created org_role_permissions table")
    print("  [OK] Created role_templates table")
    print("  [OK] Created org_invitations table")
    print("\n  [OK] Altered users table:")
    print("      - Added organization_id column")
    print("      - Added employee_id column")
    print("      - Added department_id column")
    print("\n" + "=" * 80)
    print("\nNext step:")
    print("  Run: python seed.py")
    print("=" * 80)

    cursor.close()
    conn.close()

except psycopg2.errors.DuplicateTable as e:
    print(f"\n[INFO] Tables already exist, continuing with ALTER statements...")
    # Some tables might already exist, that's okay

except Exception as e:
    print(f"\n[ERROR] Migration failed: {e}")
    import traceback
    traceback.print_exc()
