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


def confirm():
    print("\n" + "=" * 80)
    print("  ⚠️  WARNING: THIS WILL DELETE ALL DATA ⚠️")
    print("=" * 80)
    response = input("\nType 'DELETE ALL DATA' to confirm: ")
    return response == "DELETE ALL DATA"


def drop_all_tables_schema():
    """
    Best method: Drop entire schema (fast + clean)
    """
    session = SessionLocal()

    try:
        if not confirm():
            print("\n[ABORTED] Operation cancelled.")
            return

        print("\n[INFO] Dropping entire schema...")

        session.execute(text("DROP SCHEMA public CASCADE;"))
        session.execute(text("CREATE SCHEMA public;"))
        session.commit()

        print("\n" + "=" * 80)
        print("[SUCCESS] Database reset complete (schema dropped)")
        print("=" * 80)

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed to reset schema: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


def drop_all_tables_manual():
    """
    Fallback method: Drop tables one by one
    """
    session = SessionLocal()

    try:
        print("\n[INFO] Fetching list of all tables...")

        inspector = inspect(engine)
        all_tables = inspector.get_table_names(schema="public")

        if not all_tables:
            print("[INFO] No tables found.")
            return

        print(f"[INFO] Found {len(all_tables)} tables:")
        for table in all_tables:
            print(f"  - {table}")

        if not confirm():
            print("\n[ABORTED] Operation cancelled.")
            return

        print("\n[INFO] Dropping tables...")

        dropped_count = 0
        for table_name in all_tables:
            try:
                session.execute(
                    text(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE;')
                )
                print(f"  [OK] Dropped: {table_name}")
                dropped_count += 1
            except Exception as e:
                print(f"  [ERROR] Failed: {table_name} → {e}")

        session.commit()

        print("\n" + "=" * 80)
        print(f"[SUCCESS] Dropped {dropped_count} tables")
        print("=" * 80)

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed to drop tables: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


def drop_tables_sqlalchemy():
    """
    Drop tables using SQLAlchemy metadata
    (only tables defined in models)
    """
    try:
        if not confirm():
            print("\n[ABORTED] Operation cancelled.")
            return

        print("\n[INFO] Dropping tables using SQLAlchemy metadata...")
        Base.metadata.drop_all(bind=engine)

        print("\n[SUCCESS] All tables dropped (SQLAlchemy metadata)")

    except Exception as e:
        print(f"[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 80)
    print("  DROP ALL DATABASE TABLES")
    print("  ⚠️  DESTRUCTIVE OPERATION - ALL DATA WILL BE LOST ⚠️")
    print("=" * 80)

    print("\nChoose method:")
    print("  1. Drop entire schema (BEST & FASTEST)")
    print("  2. Drop tables manually (CASCADE)")
    print("  3. Drop using SQLAlchemy metadata")
    print("  4. Cancel")

    choice = input("\nEnter choice (1/2/3/4): ")

    if choice == "1":
        drop_all_tables_schema()
    elif choice == "2":
        drop_all_tables_manual()
    elif choice == "3":
        drop_tables_sqlalchemy()
    else:
        print("\n[ABORTED] Operation cancelled.")

    print("\n📌 Next steps:")
    print("  1. Run migrations:  alembic upgrade head")
    print("  2. Or recreate tables:")
    print('     python -c "from database import Base, engine; Base.metadata.create_all(bind=engine)"')
    print("  3. Seed data if needed: python seed.py")