#!/usr/bin/env python3
"""
Migration 044: Create dpr_projects table (Detailed Project Report projects).

Run once:
    python run_migration_044.py

After this, run seed_dpr_workflow.py to seed the DPR_APPROVAL
RepairWorkflowDefinition / stages / templates the table's workflow_id links to.
"""
import os
import sys
from database import VendorSessionLocal
from sqlalchemy import text


def run_migration():
    migration_file = "migrations/044_dpr_projects.sql"

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
    print("  Migration 044: dpr_projects table")
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
            WHERE table_name = 'dpr_projects'
            ORDER BY ordinal_position;
        """))
        rows = result.fetchall()
        if rows:
            print(f"[OK] Table dpr_projects created with {len(rows)} columns:")
            for r in rows:
                print(f"       {r[0]} ({r[1]}) nullable={r[2]}")
        else:
            print("[WARN] Table not found — check the SQL manually.")

        result = session.execute(text("""
            SELECT indexname FROM pg_indexes WHERE tablename = 'dpr_projects';
        """))
        idx_rows = result.fetchall()
        for r in idx_rows:
            print(f"[OK] Index: {r[0]}")

        print("\n" + "=" * 70)
        print("  [SUCCESS] Migration 044 complete.")
        print("  Next: run  python seed_dpr_workflow.py")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_migration()
