#!/usr/bin/env python3
"""
Migration 050: car_trigger_configs.car_due_in_days

Run once:
    python run_migration_050.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/050_car_trigger_due_days.sql"

    if not os.path.exists(migration_file):
        print(f"[ERROR] Migration file not found: {migration_file}")
        sys.exit(1)

    with open(migration_file) as fh:
        sql_content = fh.read()

    statements = []
    for raw in sql_content.split(";"):
        lines = [l.split("--")[0].strip() for l in raw.split("\n")]
        clean = "\n".join(l for l in lines if l).strip()
        if clean:
            statements.append(clean)

    print("=" * 70)
    print("  Migration 050: car_trigger_configs.car_due_in_days")
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
                if "already exists" in msg:
                    print(f"  [WARN] {exc}")
                    session.rollback()
                else:
                    print(f"  [ERROR] {exc}")
                    session.rollback()
                    raise

        print("\n--- Verification ---")
        col_check = session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'car_trigger_configs'
              AND column_name = 'car_due_in_days'
        """)).fetchall()
        print(f"[{'OK' if col_check else 'WARN'}] car_trigger_configs.car_due_in_days "
              f"{'present' if col_check else 'MISSING'}")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 050 complete.")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
