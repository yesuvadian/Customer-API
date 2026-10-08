#!/usr/bin/env python3
"""
Migration 052: testing_requests.test_request_type (ORIGINAL / FOLLOW_UP / RETEST).

Run once:
    python run_migration_052.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/052_test_request_type.sql"

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
    print("  Migration 052: testing_requests.test_request_type")
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
        rows = session.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'testing_requests'
              AND column_name = 'test_request_type'
        """)).fetchall()
        if rows:
            for r in rows:
                print(f"[OK] test_request_type ({r[1]}) nullable={r[2]} default={r[3]}")
            for t, n in session.execute(text(
                "SELECT test_request_type, count(*) FROM public.testing_requests GROUP BY 1 ORDER BY 1"
            )).fetchall():
                print(f"     {t:<10} {n}")
        else:
            print("[WARN] Column not found - check the SQL manually.")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 052 complete.")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
