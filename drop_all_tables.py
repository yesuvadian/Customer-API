"""
Drop all database tables - DESTRUCTIVE OPERATION
This will delete ALL data in the database.
"""
import sys
import os

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from database import SessionLocal, engine
from models import Base
from sqlalchemy import text, inspect

def drop_all_tables():
    """Drop all tables in the database."""
    session = SessionLocal()

    try:
        print("\n[INFO] Fetching list of all tables...")

        # Get inspector to list all tables
        inspector = inspect(engine)
        all_tables = inspector.get_table_names(schema='public')

        if not all_tables:
            print("[INFO] No tables found in database.")
            return

        print(f"[INFO] Found {len(all_tables)} tables:")
        for table in all_tables:
            print(f"  - {table}")

        print("\n" + "=" * 80)
        print("  WARNING: THIS WILL DELETE ALL DATA")
        print("=" * 80)
        response = input("\nType 'DELETE ALL DATA' to confirm: ")

        if response != 'DELETE ALL DATA':
            print("\n[ABORTED] Operation cancelled.")
            return

        print("\n[INFO] Dropping all tables...")

        # Disable foreign key checks temporarily
        session.execute(text("SET session_replication_role = 'replica';"))

        # Drop all tables
        dropped_count = 0
        for table_name in all_tables:
            try:
                session.execute(text(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE;'))
                print(f"  [OK] Dropped table: {table_name}")
                dropped_count += 1
            except Exception as e:
                print(f"  [ERROR] Failed to drop {table_name}: {e}")

        # Re-enable foreign key checks
        session.execute(text("SET session_replication_role = 'origin';"))

        session.commit()

        print("\n" + "=" * 80)
        print(f"[SUCCESS] Dropped {dropped_count} tables")
        print("=" * 80)
        print("\nDatabase is now empty. Run the following to recreate:")
        print("  1. python -c \"from database import Base, engine; Base.metadata.create_all(bind=engine)\"")
        print("  2. python seed.py")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed to drop tables: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

def drop_tables_sqlalchemy():
    """Alternative method using SQLAlchemy metadata."""
    print("\n[INFO] Using SQLAlchemy metadata to drop tables...")

    try:
        # Drop all tables defined in models
        Base.metadata.drop_all(bind=engine)
        print("[SUCCESS] All tables dropped using SQLAlchemy metadata")
        print("\nTo recreate tables:")
        print("  1. python -c \"from database import Base, engine; Base.metadata.create_all(bind=engine)\"")
        print("  2. python seed.py")
    except Exception as e:
        print(f"[ERROR] Failed to drop tables: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("=" * 80)
    print("  DROP ALL DATABASE TABLES")
    print("  ⚠️  DESTRUCTIVE OPERATION - ALL DATA WILL BE LOST ⚠️")
    print("=" * 80)

    print("\nChoose method:")
    print("  1. Drop using SQL CASCADE (drops everything including orphaned tables)")
    print("  2. Drop using SQLAlchemy metadata (only drops tables defined in models)")
    print("  3. Cancel")

    choice = input("\nEnter choice (1/2/3): ")

    if choice == '1':
        drop_all_tables()
    elif choice == '2':
        print("\n" + "=" * 80)
        print("  WARNING: THIS WILL DELETE ALL DATA")
        print("=" * 80)
        response = input("\nType 'DELETE ALL DATA' to confirm: ")

        if response == 'DELETE ALL DATA':
            drop_tables_sqlalchemy()
        else:
            print("\n[ABORTED] Operation cancelled.")
    else:
        print("\n[ABORTED] Operation cancelled.")
