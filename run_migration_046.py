#!/usr/bin/env python3
"""
Migration 046: Create car_trigger_configs table + add
corrective_action_requests.follow_up_test_type_id.

Run once:
    python run_migration_046.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/046_car_trigger_config.sql"

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
    print("  Migration 046: car_trigger_configs")
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
        result = session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'car_trigger_configs'
            ORDER BY ordinal_position
        """))
        rows = result.fetchall()
        if rows:
            print(f"[OK] Table car_trigger_configs created with {len(rows)} columns:")
            for r in rows:
                print(f"       {r[0]} ({r[1]}) nullable={r[2]}")
        else:
            print("[WARN] Table not found — check the SQL manually.")

        col_check = session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'corrective_action_requests'
              AND column_name = 'follow_up_test_type_id'
        """)).fetchall()
        print(f"[{'OK' if col_check else 'WARN'}] corrective_action_requests.follow_up_test_type_id "
              f"{'present' if col_check else 'MISSING'}")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 046 complete.")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
