#!/usr/bin/env python3
"""
Migration 007: Repair Timeliness & Delay Attribution.

Adds contractual timeline tracking, delay_days computation, and
delay attribution (vendor vs KPTCL) columns to repair tables.

Run once:
    python run_migration_007.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/007_repair_timeliness.sql"

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
    print("  Migration 007: Repair Timeliness & Delay Attribution")
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
            ("repair_stage_definitions", "default_duration_days"),
            ("repair_workflows", "work_award_at"),
            ("repair_workflows", "vendor_name"),
            ("repair_workflows", "contracted_completion"),
            ("repair_stage_instances", "contracted_date"),
            ("repair_stage_instances", "delay_days"),
            ("repair_stage_instances", "delay_attribution"),
            ("repair_stage_instances", "delay_attributed_by"),
        ]
        all_ok = True
        for table, col in checks:
            result = session.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = :tbl AND column_name = :col
            """), {"tbl": table, "col": col})
            row = result.fetchone()
            if row:
                print(f"[OK] {table}.{col} ({row[1]})")
            else:
                print(f"[WARN] {table}.{col} — NOT FOUND")
                all_ok = False

        print("\n" + "=" * 70)
        if all_ok:
            print("  [SUCCESS] Migration 007 complete.")
        else:
            print("  [PARTIAL] Some columns missing — check SQL manually.")
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
