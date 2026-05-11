"""One-shot cleanup: delete all repair workflow data so seed.py can re-run cleanly."""
from database import ErpSessionLocal
from sqlalchemy import text

db = ErpSessionLocal()
try:
    # Check what repair tables exist
    result = db.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'repair%' "
        "ORDER BY table_name"
    ))
    tables = [r[0] for r in result.fetchall()]
    print(f"[INFO] Repair tables found: {tables}")

    # Delete in FK-safe order
    for tbl in [
        "repair_stage_audit_logs",
        "repair_stage_documents",
        "repair_stage_data",
        "repair_assignment_queue",
        "repair_stage_instances",
        "repair_workflows",
        "repair_stage_transitions",
        "repair_stage_templates",
        "repair_stage_roles",
        "repair_stage_definitions",
    ]:
        if tbl in tables:
            db.execute(text(f"DELETE FROM {tbl}"))
            print(f"[OK] Cleared {tbl}")
        else:
            print(f"[SKIP] {tbl} — not found")

    db.commit()
    print("[DONE] All repair tables cleared.")
except Exception as e:
    db.rollback()
    print(f"[ERROR] {e}")
finally:
    db.close()
