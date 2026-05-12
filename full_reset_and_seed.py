"""
Full Database Reset and Reseed Script
Drops all tables, recreates schema, and runs seed.py
"""
import subprocess
import sys
import io

# Set UTF-8 encoding for stdout/stderr to handle Unicode characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from database import engine, Base
import models  # ← MUST import so all models register with Base.metadata

def drop_all_tables():
    """Drop all tables in the public schema using CASCADE to handle FK cycles"""
    print("=" * 80)
    print("STEP 1: DROPPING ALL TABLES")
    print("=" * 80)

    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        # Get all table names in public schema
        insp = inspect(engine)
        tables = insp.get_table_names(schema="public")
        if tables:
            tables_sql = ", ".join(f'public."{t}"' for t in tables)
            conn.execute(text(f"DROP TABLE IF EXISTS {tables_sql} CASCADE"))
            conn.commit()
            print(f"[OK] Dropped {len(tables)} tables with CASCADE")

        # Drop all custom enum types
        result = conn.execute(text("""
            SELECT t.typname
            FROM pg_type t
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
              AND t.typtype = 'e'
        """))
        enums = [row[0] for row in result]
        for enum in enums:
            conn.execute(text(f'DROP TYPE IF EXISTS public."{enum}" CASCADE'))
        if enums:
            conn.commit()
            print(f"[OK] Dropped {len(enums)} enum types: {', '.join(enums)}")

    print("[OK] All tables dropped successfully\n")

def create_all_tables():
    """Create all tables from models"""
    print("=" * 80)
    print("STEP 2: CREATING ALL TABLES")
    print("=" * 80)

    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("[OK] All tables created successfully\n")

def run_seed():
    """Run seed.py to populate initial data"""
    print("=" * 80)
    print("STEP 3: RUNNING SEED SCRIPT")
    print("=" * 80)

    # Run seed.py as a subprocess
    result = subprocess.run(
        [sys.executable, "seed.py"],
        capture_output=False,
        text=True
    )

    if result.returncode == 0:
        print("\n[OK] Seed completed successfully")
    else:
        print(f"\n[ERROR] Seed failed with exit code {result.returncode}")
        sys.exit(1)

def main():
    print("\n")
    print("=" * 80)
    print("         FULL DATABASE RESET & SEED")
    print("=" * 80)
    print()

    try:
        drop_all_tables()
        create_all_tables()
        run_seed()

        print("\n")
        print("=" * 80)
        print("SUCCESS: Database reset and seed completed")
        print("=" * 80)
        print()
        print("Next steps:")
        print("  1. Restart the API server")
        print("  2. Login with KPTCL user credentials")
        print("  3. Testing Request Approvals module should now be visible")
        print()

    except Exception as e:
        print(f"\n\nERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
