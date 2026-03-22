#!/usr/bin/env python3
"""
Run migration 002: Testing Request Department Hierarchy
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text

def run_migration():
    """Run the migration SQL file."""
    migration_file = "migrations/002_testing_request_department_hierarchy.sql"

    if not os.path.exists(migration_file):
        print(f"[ERROR] Migration file not found: {migration_file}")
        sys.exit(1)

    # Read migration SQL
    with open(migration_file, 'r') as f:
        sql_content = f.read()

    # Split by semicolons and filter out comments/empty lines
    statements = []
    for statement in sql_content.split(';'):
        # Remove comments
        lines = []
        for line in statement.split('\n'):
            line = line.split('--')[0].strip()  # Remove inline comments
            if line:
                lines.append(line)

        clean_statement = '\n'.join(lines).strip()
        if clean_statement and not clean_statement.startswith('--'):
            statements.append(clean_statement)

    print("=" * 80)
    print("  Running Migration 002: Testing Request Department Hierarchy")
    print("=" * 80)
    print(f"\nFound {len(statements)} SQL statements to execute\n")

    # Execute migration
    session = VendorSessionLocal()
    try:
        for i, statement in enumerate(statements, 1):
            print(f"[{i}/{len(statements)}] Executing statement...")
            try:
                session.execute(text(statement))
                session.commit()
                print(f"  [OK] Success")
            except Exception as e:
                # Some statements might fail if already applied (like DROP IF EXISTS)
                # Check if it's a benign error
                error_msg = str(e).lower()
                if 'already exists' in error_msg or 'does not exist' in error_msg:
                    print(f"  [WARN] Warning: {e}")
                    session.rollback()
                else:
                    print(f"  [ERROR] Error: {e}")
                    session.rollback()
                    raise

        print("\n" + "=" * 80)
        print("  [SUCCESS] Migration 002 completed successfully!")
        print("=" * 80)

        # Verify the changes
        print("\n--- Verification ---")
        result = session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'testing_requests'
            AND column_name IN ('organization_id', 'department_id')
            ORDER BY column_name;
        """))

        columns = result.fetchall()
        if columns:
            print("\n[OK] New columns added to testing_requests:")
            for col in columns:
                print(f"  • {col[0]} ({col[1]}) - Nullable: {col[2]}")
        else:
            print("\n[WARN] Warning: Could not verify new columns")

        # Check indexes
        result = session.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'testing_requests'
            AND indexname LIKE 'idx_testing_requests_%department%';
        """))

        indexes = result.fetchall()
        if indexes:
            print("\n[OK] Indexes created:")
            for idx in indexes:
                print(f"  • {idx[0]}")

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        print(f"\n[FAILED] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
