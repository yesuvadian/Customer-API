#!/usr/bin/env python3
"""
Migration 051: drop the CAR overdue notification feature

Run once:
    python run_migration_051.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/051_drop_car_overdue.sql"

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
    print("  Migration 051: drop the CAR overdue notification feature")
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
                print(f"  [ERROR] {exc}")
                session.rollback()
                raise

        print("\n--- Verification ---")
        col_checks = session.execute(text("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (
                (table_name = 'corrective_action_requests' AND column_name = 'overdue_notified_at')
                OR (table_name = 'car_trigger_configs' AND column_name = 'car_due_in_days')
              )
        """)).fetchall()
        print(f"[{'OK' if not col_checks else 'WARN'}] columns dropped "
              f"{'(none remaining)' if not col_checks else f'STILL PRESENT: {col_checks}'}")

        row_checks = session.execute(text("""
            SELECT 'notification_templates' AS t, count(*) FROM public.notification_templates WHERE event_type = 'car_overdue'
            UNION ALL
            SELECT 'notification_event_catalogue', count(*) FROM public.notification_event_catalogue WHERE event_type = 'car_overdue'
        """)).fetchall()
        for table, cnt in row_checks:
            print(f"[{'OK' if cnt == 0 else 'WARN'}] {table}: {cnt} car_overdue row(s) remaining")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 051 complete.")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
