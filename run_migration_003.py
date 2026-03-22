#!/usr/bin/env python3
"""
Run migration 003: Add organization_id to Testing Tables
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text

def run_migration():
    """Run the migration SQL file."""
    migration_file = "migrations/003_add_org_id_to_testing_tables.sql"

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
    print("  Running Migration 003: Add organization_id to Testing Tables")
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
                # Some statements might fail if already applied
                error_msg = str(e).lower()
                if 'already exists' in error_msg or 'does not exist' in error_msg:
                    print(f"  [WARN] Warning: {e}")
                    session.rollback()
                else:
                    print(f"  [ERROR] Error: {e}")
                    session.rollback()
                    raise

        print("\n" + "=" * 80)
        print("  [SUCCESS] Migration 003 completed successfully!")
        print("=" * 80)

        # Verify the changes
        print("\n--- Verification ---")

        tables = ['tester_locations', 'test_results', 'recommendations', 'procurement_requests']
        for table in tables:
            result = session.execute(text(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = '{table}'
                AND column_name = 'organization_id';
            """))

            columns = result.fetchall()
            if columns:
                print(f"\n[OK] {table} has organization_id:")
                for col in columns:
                    print(f"  - {col[0]} ({col[1]}) - Nullable: {col[2]}")
            else:
                print(f"\n[WARN] {table} missing organization_id column")

        # Check indexes
        result = session.execute(text("""
            SELECT tablename, indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            AND indexname LIKE '%organization%'
            AND tablename IN ('tester_locations', 'test_results', 'recommendations', 'procurement_requests')
            ORDER BY tablename;
        """))

        indexes = result.fetchall()
        if indexes:
            print("\n[OK] Indexes created:")
            for idx in indexes:
                print(f"  - {idx[0]}.{idx[1]}")

        # Check data migration
        print("\n--- Data Migration Status ---")
        result = session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM test_results WHERE organization_id IS NOT NULL) as test_results_migrated,
                (SELECT COUNT(*) FROM test_results) as test_results_total,
                (SELECT COUNT(*) FROM recommendations WHERE organization_id IS NOT NULL) as recommendations_migrated,
                (SELECT COUNT(*) FROM recommendations) as recommendations_total,
                (SELECT COUNT(*) FROM procurement_requests WHERE organization_id IS NOT NULL) as procurement_migrated,
                (SELECT COUNT(*) FROM procurement_requests) as procurement_total;
        """))

        stats = result.fetchone()
        if stats:
            print(f"\n[OK] Test Results: {stats[0]} of {stats[1]} have organization_id")
            print(f"[OK] Recommendations: {stats[2]} of {stats[3]} have organization_id")
            print(f"[OK] Procurement Requests: {stats[4]} of {stats[5]} have organization_id")

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
