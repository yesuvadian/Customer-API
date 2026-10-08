#!/usr/bin/env python3
"""
Migration 047: car_trigger_followups (multi follow-up support) +
drop the singular follow_up_test_type_id columns from migration 046.

Run once:
    python run_migration_047.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/047_car_trigger_followups.sql"

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
    print("  Migration 047: car_trigger_followups")
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
            WHERE table_schema = 'public' AND table_name = 'car_trigger_followups'
            ORDER BY ordinal_position
        """))
        rows = result.fetchall()
        if rows:
            print(f"[OK] Table car_trigger_followups created with {len(rows)} columns:")
            for r in rows:
                print(f"       {r[0]} ({r[1]}) nullable={r[2]}")
        else:
            print("[WARN] Table not found - check the SQL manually.")

        for tbl in ("car_trigger_configs", "corrective_action_requests"):
            col_check = session.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = '{tbl}'
                  AND column_name = 'follow_up_test_type_id'
            """)).fetchall()
            print(f"[{'OK' if not col_check else 'WARN'}] {tbl}.follow_up_test_type_id "
                  f"{'dropped' if not col_check else 'STILL PRESENT'}")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 047 complete.")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
