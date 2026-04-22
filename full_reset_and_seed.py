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

def drop_all_tables():
    """Drop all tables in the public schema"""
    print("=" * 80)
    print("STEP 1: DROPPING ALL TABLES")
    print("=" * 80)

    # Drop all tables
    Base.metadata.drop_all(bind=engine)
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
