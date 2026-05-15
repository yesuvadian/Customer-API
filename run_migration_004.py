#!/usr/bin/env python3
"""
Migration 004: Add workflow_definition_id to repair_stage_definitions.

Run once:
    python run_migration_004.py

After this, run the backfill to populate the new column for existing rows:
    python backfill_workflow_definition_id.py
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/004_add_workflow_definition_id_to_stages.sql"

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
    print("  Migration 004: workflow_definition_id on repair_stage_definitions")
    print("=" * 70)
    print(f"\n  {len(statements)} statement(s) to execute\n")

    session = VendorSessionLocal()
    try:
        for i, stmt in enumerate(statements, 1):
            print(f"[{i}/{len(statements)}] {stmt[:80].replace(chr(10),' ')} ...")
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

        # Verify
        print("\n--- Verification ---")
        result = session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'repair_stage_definitions'
              AND column_name = 'workflow_definition_id';
        """))
        row = result.fetchone()
        if row:
            print(f"[OK] Column added: {row[0]} ({row[1]}) nullable={row[2]}")
        else:
            print("[WARN] Column not found — check the SQL manually.")

        result = session.execute(text("""
            SELECT workflow_code, name FROM repair_workflow_definitions
            WHERE workflow_code IN ('BREAKDOWN', 'ANNUAL_AUDIT');
        """))
        rows = result.fetchall()
        for r in rows:
            print(f"[OK] WorkflowDefinition: {r[0]} — {r[1]}")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 004 complete.")
        print("  Next: run  python backfill_workflow_definition_id.py")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
