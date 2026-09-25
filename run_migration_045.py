#!/usr/bin/env python3
"""
Migration 045: Create corrective_action_requests + car_test_requests tables.

Run once:
    python run_migration_045.py

After this, the CAR auto-creation hook in services/car_service.py (wired
into services/testing_service.py's evaluation block) starts creating CARs
automatically whenever a test result evaluates CRITICAL.
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/045_corrective_action_requests.sql"

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
    print("  Migration 045: corrective_action_requests + car_test_requests")
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
        for table in ("corrective_action_requests", "car_test_requests"):
            result = session.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :t
                ORDER BY ordinal_position
            """), {"t": table})
            rows = result.fetchall()
            if rows:
                print(f"[OK] Table {table} created with {len(rows)} columns:")
                for r in rows:
                    print(f"       {r[0]} ({r[1]}) nullable={r[2]}")
            else:
                print(f"[WARN] Table {table} not found — check the SQL manually.")

            idx_rows = session.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = :t"
            ), {"t": table}).fetchall()
            for r in idx_rows:
                print(f"[OK] Index: {r[0]}")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 045 complete.")
        print("  Next: run  python seed_test_request_type_master.py  (if not already done)")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
