#!/usr/bin/env python3
"""
Migration 013: Add surveillance workflow linkage to test_request_schedules.

Adds surveillance_workflow_id and surveillance_quarter columns to test_request_schedules
so that schedules can be explicitly linked to surveillance workflows.

Run once:
    python run_migration_013.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/013_add_surveillance_to_schedules.sql"

    if not os.path.exists(migration_file):
        print(f"[ERROR] Migration file not found: {migration_file}")
        sys.exit(1)

    with open(migration_file) as fh:
        sql_content = fh.read()

    # Split on semicolons, skip blank/comment-only chunks
    statements = []
    for raw in sql_content.split(";"):
        lines = [l.split("--")[0].strip() for l in raw.split("\n")]
        clean = "\n".join(l for l in lines if l).strip()
        if clean:
            statements.append(clean)

    print("=" * 70)
    print("  Migration 013: Add Surveillance Linkage to Schedules")
    print("=" * 70)
    print(f"\n  {len(statements)} statement(s) to execute\n")

    session = VendorSessionLocal()
    try:
        for i, stmt in enumerate(statements, 1):
            print(f"[{i}/{len(statements)}] {stmt[:80].replace(chr(10), ' ')} ...")
            try:
                session.execute(text(stmt))
                session.commit()
                print("  [OK]")
            except Exception as exc:
                msg = str(exc).lower()
                if "already exists" in msg or "does not exist" in msg:
                    print(f"  [WARN] {exc}")
                    session.rollback()
                else:
                    print(f"  [ERROR] {exc}")
                    session.rollback()
                    raise

        # Verification
        print("\n--- Verification ---")

        checks = [
            ("test_request_schedules", "surveillance_workflow_id"),
            ("test_request_schedules", "surveillance_quarter"),
        ]
        all_ok = True
        for table, col in checks:
            result = session.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :tbl
                  AND column_name = :col
            """), {"tbl": table, "col": col})
            row = result.fetchone()
            if row:
                print(f"[OK] {table}.{col} ({row[1]})")
            else:
                print(f"[WARN] {table}.{col} — NOT FOUND")
                all_ok = False

        # Check index
        print("\n--- Index Verification ---")
        result = session.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = 'idx_test_request_schedules_surveillance'
        """))
        row = result.fetchone()
        if row:
            print(f"[OK] Index: idx_test_request_schedules_surveillance")
        else:
            print(f"[WARN] Index: idx_test_request_schedules_surveillance — NOT FOUND")
            all_ok = False

        print("\n" + "=" * 70)
        if all_ok:
            print("  [SUCCESS] Migration 013 complete.")
            print("\n  This migration allows surveillance workflows to use the existing")
            print("  test_request_schedules infrastructure instead of a separate scheduler.")
            print("\n  Surveillance hooks will now create schedule records that are")
            print("  automatically processed by TestRequestScheduleService.run_daily_scheduler()")
        else:
            print("  [PARTIAL] Some objects missing — check SQL manually.")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
