#!/usr/bin/env python3
"""
One-time backfill: populate repair_stage_definitions.workflow_definition_id
for rows that existed before migration 004.

Run AFTER run_migration_004.py:
    python backfill_workflow_definition_id.py

Safe to run multiple times (skips rows that already have a value).
"""
import sys
from database import VendorSessionLocal
from models import RepairStageDefinition, RepairWorkflowDefinition

# Stage codes that belong to each workflow type.
# These match the seed files exactly.
REPAIR_STAGE_CODES = [
    "FAILURE_REPORT",
    "COMMITTEE_REVIEW",
    "VENDOR_ASSIGNMENT",
    "LIFTING",
    "JOINT_INSPECTION",
    "ESTIMATE",
    "QA",
    "FINAL_INSPECTION",
    "DISPATCH",
    "COMMISSIONING",
]

ANNUAL_AUDIT_STAGE_CODES = [
    "OBSERVATION_REPORTING",
    "OBSERVATION_ASSIGNMENT",
    "COMPLIANCE_SUBMISSION",
    "COMPLIANCE_REVIEW",
    "OBSERVATION_CLOSURE",
]


def backfill(db):
    mapping = [
        ("BREAKDOWN",    REPAIR_STAGE_CODES),
        ("ANNUAL_AUDIT", ANNUAL_AUDIT_STAGE_CODES),
    ]

    total_updated = 0

    for wf_code, stage_codes in mapping:
        wf_def = (
            db.query(RepairWorkflowDefinition)
            .filter_by(workflow_code=wf_code, is_active=True)
            .first()
        )
        if not wf_def:
            print(f"[WARN] WorkflowDefinition '{wf_code}' not found — "
                  "run run_migration_004.py first, then re-run this script.")
            continue

        stages = (
            db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.code.in_(stage_codes))
            .all()
        )

        updated = 0
        for stage in stages:
            if stage.workflow_definition_id != wf_def.id:
                stage.workflow_definition_id = wf_def.id
                updated += 1

        db.flush()
        total_updated += updated
        print(f"[OK] {wf_code}: {updated} stage(s) updated "
              f"(definition id={wf_def.id})")

    db.commit()
    print(f"\n[DONE] Total stages updated: {total_updated}")

    # Verify: show any stages still missing a definition
    orphans = (
        db.query(RepairStageDefinition)
        .filter(RepairStageDefinition.workflow_definition_id.is_(None))
        .all()
    )
    if orphans:
        print(f"\n[WARN] {len(orphans)} stage(s) still have no workflow_definition_id:")
        for s in orphans:
            print(f"  - {s.code} ({s.name})")
    else:
        print("[OK] All stage definitions have a workflow_definition_id.")


if __name__ == "__main__":
    db = VendorSessionLocal()
    try:
        backfill(db)
    except Exception as exc:
        db.rollback()
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()
