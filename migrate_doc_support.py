"""
DDL migration for Document Support Workflow (Option B+).
- tr_wf_instances: add entity_type, entity_id; make testing_request_id nullable
- tr_wf_audit_logs: make testing_request_id nullable
Idempotent — safe to re-run.
"""
from database import vendor_engine
from sqlalchemy import text

STEPS = [
    # tr_wf_instances — add entity_type
    (
        "entity_type on tr_wf_instances",
        "SELECT 1 FROM information_schema.columns WHERE table_name='tr_wf_instances' AND column_name='entity_type'",
        "ALTER TABLE tr_wf_instances ADD COLUMN entity_type VARCHAR(50)",
    ),
    # tr_wf_instances — add entity_id
    (
        "entity_id on tr_wf_instances",
        "SELECT 1 FROM information_schema.columns WHERE table_name='tr_wf_instances' AND column_name='entity_id'",
        "ALTER TABLE tr_wf_instances ADD COLUMN entity_id UUID",
    ),
    # tr_wf_instances — make testing_request_id nullable
    (
        "testing_request_id nullable on tr_wf_instances",
        "SELECT 1 FROM information_schema.columns WHERE table_name='tr_wf_instances' AND column_name='testing_request_id' AND is_nullable='YES'",
        "ALTER TABLE tr_wf_instances ALTER COLUMN testing_request_id DROP NOT NULL",
    ),
    # tr_wf_audit_logs — make testing_request_id nullable
    (
        "testing_request_id nullable on tr_wf_audit_logs",
        "SELECT 1 FROM information_schema.columns WHERE table_name='tr_wf_audit_logs' AND column_name='testing_request_id' AND is_nullable='YES'",
        "ALTER TABLE tr_wf_audit_logs ALTER COLUMN testing_request_id DROP NOT NULL",
    ),
]

with vendor_engine.connect() as conn:
    for label, check_sql, alter_sql in STEPS:
        exists = conn.execute(text(check_sql)).fetchone()
        if exists:
            print(f"  [SKIP]  {label} — already done")
        else:
            conn.execute(text(alter_sql))
            conn.commit()
            print(f"  [DONE]  {label}")

print("Migration complete.")
