#!/usr/bin/env python3
"""
Migration 008: Post-Commissioning Surveillance Workflow.

Adds surveillance workflow support for 24-month post-commissioning monitoring.
Creates 3 new tables (surveillance_config, surveillance_test_config, repair_surveillance_tests)
and adds linkage columns to existing tables.

Run once:
    python run_migration_008.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/008_surveillance_workflow.sql"

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
    print("  Migration 008: Post-Commissioning Surveillance Workflow")
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
            ("testing_requests", "surveillance_workflow_id"),
            ("testing_requests", "surveillance_quarter"),
            ("repair_stage_instances", "quarter_number"),
            ("surveillance_config", "surveillance_period_months"),
            ("surveillance_config", "frequency_multiplier"),
            ("surveillance_test_config", "equipment_type_id"),
            ("surveillance_test_config", "test_type_id"),
            ("repair_surveillance_tests", "surveillance_workflow_id"),
            ("repair_surveillance_tests", "quarter_number"),
            ("repair_surveillance_tests", "is_abnormal"),
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

        # Check indexes
        print("\n--- Index Verification ---")
        index_checks = [
            "idx_testing_requests_surveillance_workflow",
            "idx_surveillance_config_org",
            "idx_surveillance_test_config_equipment",
            "idx_repair_surveillance_tests_workflow",
            "idx_repair_surveillance_tests_abnormal",
        ]
        for idx in index_checks:
            result = session.execute(text("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = :idx
            """), {"idx": idx})
            row = result.fetchone()
            if row:
                print(f"[OK] Index: {idx}")
            else:
                print(f"[WARN] Index: {idx} — NOT FOUND")
                all_ok = False

        # Check constraints
        print("\n--- Constraint Verification ---")
        constraint_checks = [
            ("surveillance_test_config", "uq_surveillance_equipment_test"),
            ("repair_surveillance_tests", "uq_surveillance_test_link"),
        ]
        for table, constraint in constraint_checks:
            result = session.execute(text("""
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                  AND table_name = :tbl
                  AND constraint_name = :con
            """), {"tbl": table, "con": constraint})
            row = result.fetchone()
            if row:
                print(f"[OK] {table}.{constraint}")
            else:
                print(f"[WARN] {table}.{constraint} — NOT FOUND")
                all_ok = False

        print("\n" + "=" * 70)
        if all_ok:
            print("  [SUCCESS] Migration 008 complete.")
            print("\n  Next step:")
            print("  Run the main seed script to populate surveillance configuration:")
            print("    python seed.py")
            print("\n  The seed script will:")
            print("    • Load surveillance workflow/stage definitions from JSON")
            print("    • Create workflow definition (SURVEILLANCE)")
            print("    • Create 5 stage definitions (Q1-Q4 + Final Evaluation)")
            print("    • Map stages to templates")
            print("    • Set up role permissions")
            print("    • Create stage transitions")
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
