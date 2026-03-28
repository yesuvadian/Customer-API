"""
Clean database and run seed - Non-interactive version
"""
import psycopg2
import subprocess
import sys
import os

def drop_all_tables():
    """Drop all tables using psycopg2"""
    # Get database credentials from environment or use defaults
    db_name = os.getenv('DB_NAME', 'Relu_Vendor2')
    db_user = os.getenv('DB_USER', 'relu_user')
    db_password = os.getenv('DB_PASSWORD', 'StrongPassword123!')
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')

    try:
        print("=" * 80)
        print("  DROPPING ALL TABLES")
        print("=" * 80)
        print()

        conn = psycopg2.connect(
            database=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        cur = conn.cursor()

        # Get all table names
        cur.execute("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)

        all_tables = [row[0] for row in cur.fetchall()]
        print(f"Found {len(all_tables)} tables to drop")
        print()

        # Drop each table with CASCADE (foreign keys are handled automatically)
        for table_name in all_tables:
            try:
                cur.execute(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE;')
                print(f"  Dropped: {table_name}")
            except Exception as e:
                print(f"  Error dropping {table_name}: {e}")

        conn.commit()
        cur.close()
        conn.close()

        print()
        print("[OK] All tables dropped successfully")
        return True

    except Exception as e:
        print(f"[ERROR] {e}")
        return False

def run_seed():
    """Run seed.py"""
    print()
    print("=" * 80)
    print("  RUNNING SEED.PY")
    print("=" * 80)
    print()

    try:
        result = subprocess.run(
            [sys.executable, "seed.py"],
            capture_output=False,
            text=True,
            timeout=300
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    print()
    print("*" * 80)
    print("  CLEAN DATABASE AND RUN SEED")
    print("*" * 80)
    print()

    # Step 1: Drop all tables
    if not drop_all_tables():
        print("\n[FAILED] Could not drop tables")
        sys.exit(1)

    # Step 2: Run seed
    if not run_seed():
        print("\n[FAILED] Seed script failed")
        sys.exit(1)

    print()
    print("*" * 80)
    print("  SUCCESS - DATABASE READY FOR TESTING")
    print("*" * 80)
