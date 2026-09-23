#!/usr/bin/env python3
"""
One-time setup: add precommission_requests.intake_workflow_id and seed the
PRECOMMISSION_INTAKE RepairWorkflowDefinition (2 stages by default).

Replaces PreCommissionRequest.approval_status as a manually-set flat field
with a real, N-stage, role-gated review chain on the same
RepairWorkflowService engine already powering the QAP workflow (workflow_id)
-- same admin-configurable stages/roles UI, no new abstraction. 2 stages is
just the seeded starting point; an admin can add more later purely through
the existing Workflow Configuration screen (see seed_precommission_workflow.
py's PRE_COMMISSION QAP definition for the same idiom at larger scale).

No 'reject' RepairStageTransition is seeded here deliberately -- unlike the
QAP workflow's "reject loops back to the same stage" semantics (a real
re-inspection cycle), a rejected intake request should end the whole
review, not send it back for rework. RepairWorkflowService.reject_stage()
doesn't cleanly support "terminal reject" (its own "no transition" branch
means "re-queue this stage", not "end the workflow") without changing
behavior for the 5 other workflow types already relying on it -- so
PrecommissionService.reject_request() handles rejection directly instead
(see that file), leaving reject_stage() itself untouched.

Idempotent: get-or-create throughout, safe to re-run.

seed_precommission_intake_stages(db) is also called from seed.py (org-
agnostic — these tables have no organization_id — so a brand-new
deployment gets this workflow definition for free, same as
seed_precommission_stages/seed_dpr_stages/seed_annual_audit_stages).
This script's own main() is for upgrading an EXISTING database that
predates this feature.

Usage:
    python alter_precommission_intake_workflow.py
"""
import uuid

from sqlalchemy import text
from models import RepairWorkflowDefinition, RepairStageDefinition, RepairStageTransition

WORKFLOW_CODE = "PRECOMMISSION_INTAKE"

STAGES = [
    {"code": "PCI_LEVEL_1", "name": "Level 1 Review", "sequence": 1},
    {"code": "PCI_LEVEL_2", "name": "Level 2 Review", "sequence": 2},
]

# (from_code, to_code | None for terminal) -- action is always "approve";
# reject is handled directly by PrecommissionService, not via this table.
TRANSITIONS = [
    ("PCI_LEVEL_1", "PCI_LEVEL_2"),
    ("PCI_LEVEL_2", None),
]


def seed_precommission_intake_stages(db) -> None:
    wf_def = db.query(RepairWorkflowDefinition).filter_by(
        workflow_code=WORKFLOW_CODE
    ).first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code=WORKFLOW_CODE,
            name="Precommission Intake",
            is_active=True,
        )
        db.add(wf_def)
        db.flush()
    print(f"[OK] RepairWorkflowDefinition {WORKFLOW_CODE}: {wf_def.id}")

    code_map = {}
    inserted = 0
    for s in STAGES:
        existing = db.query(RepairStageDefinition).filter_by(
            workflow_definition_id=wf_def.id, code=s["code"]
        ).first()
        if existing:
            existing.name = s["name"]
            existing.sequence = s["sequence"]
            code_map[s["code"]] = existing.id
            continue
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            workflow_definition_id=wf_def.id,
            name=s["name"],
            code=s["code"],
            sequence=s["sequence"],
            weight=round(100 / len(STAGES)),
            is_active=True,
            is_mandatory=True,
        )
        db.add(stage)
        db.flush()
        code_map[s["code"]] = stage.id
        inserted += 1
    print(f"[OK] Precommission Intake stages: {inserted} inserted ({len(code_map)} total)")

    for from_code, to_code in TRANSITIONS:
        from_id = code_map.get(from_code)
        to_id = code_map.get(to_code) if to_code else None
        if not from_id:
            continue
        exists = db.query(RepairStageTransition).filter_by(
            from_stage_id=from_id, action="approve"
        ).first()
        if not exists:
            db.add(RepairStageTransition(
                id=uuid.uuid4(),
                from_stage_id=from_id,
                to_stage_id=to_id,
                action="approve",
            ))
        else:
            exists.to_stage_id = to_id

    db.commit()
    print(f"[OK] Precommission Intake workflow seeded ({len(TRANSITIONS)} transitions). "
          f"No roles assigned yet -- add them via Workflow Configuration > Precommission Intake > Roles.")


def main():
    from database import VendorSessionLocal
    db = VendorSessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE public.precommission_requests "
            "ADD COLUMN IF NOT EXISTS intake_workflow_id UUID "
            "REFERENCES repair_workflows(id) ON DELETE SET NULL"
        ))
        db.commit()
        print("Ensured precommission_requests.intake_workflow_id column exists.")
        seed_precommission_intake_stages(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
