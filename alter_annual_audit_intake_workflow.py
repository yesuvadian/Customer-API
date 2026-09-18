#!/usr/bin/env python3
"""
One-time setup: add taqc_observations.intake_workflow_id and seed the
ANNUAL_AUDIT_INTAKE RepairWorkflowDefinition (2 stages by default).

Mirrors alter_precommission_intake_workflow.py / alter_dpr_intake_
workflow.py exactly. Before this, AnnualAuditService.create_observation()
started the full ANNUAL_AUDIT remediation workflow immediately when an
observation was logged, with no screening step -- any observation an
inspector logs instantly kicks off the formal remediation workflow. It
now starts this 2-stage intake chain first; only once it completes does
the real ANNUAL_AUDIT workflow (workflow_id) get created. 2 stages is
just the seeded starting point; an admin can add more later purely
through the existing Workflow Configuration screen.

No 'reject' RepairStageTransition is seeded here deliberately -- same
reasoning as the other two intake chains: RepairWorkflowService.
reject_stage()'s "no transition" branch means "re-queue this stage", not
"end the workflow", and changing that shared method's behavior would
affect every other Repair-engine workflow type relying on its current
semantics. AnnualAuditService.reject_stage() handles intake rejection
directly instead when observation.workflow_id is still unset (see that
file), leaving reject_stage() itself untouched.

Idempotent: get-or-create throughout, safe to re-run.

seed_annual_audit_intake_stages(db) is also called from seed.py (org-
agnostic -- these tables have no organization_id -- so a brand-new
deployment gets this workflow definition for free, same as
seed_precommission_stages/seed_dpr_stages/seed_annual_audit_stages).
This script's own main() is for upgrading an EXISTING database that
predates this feature.

Usage:
    python alter_annual_audit_intake_workflow.py
"""
import uuid

from sqlalchemy import text
from models import RepairWorkflowDefinition, RepairStageDefinition, RepairStageTransition

WORKFLOW_CODE = "ANNUAL_AUDIT_INTAKE"

STAGES = [
    {"code": "ANNUAL_AUDIT_INTAKE_LEVEL_1", "name": "Level 1 Review", "sequence": 1},
    {"code": "ANNUAL_AUDIT_INTAKE_LEVEL_2", "name": "Level 2 Review", "sequence": 2},
]

# (from_code, to_code | None for terminal) -- action is always "approve";
# reject is handled directly by AnnualAuditService, not via this table.
TRANSITIONS = [
    ("ANNUAL_AUDIT_INTAKE_LEVEL_1", "ANNUAL_AUDIT_INTAKE_LEVEL_2"),
    ("ANNUAL_AUDIT_INTAKE_LEVEL_2", None),
]


def seed_annual_audit_intake_stages(db) -> None:
    wf_def = db.query(RepairWorkflowDefinition).filter_by(
        workflow_code=WORKFLOW_CODE
    ).first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code=WORKFLOW_CODE,
            name="Annual Audit Intake",
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
    print(f"[OK] Annual Audit Intake stages: {inserted} inserted ({len(code_map)} total)")

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
    print(f"[OK] Annual Audit Intake workflow seeded ({len(TRANSITIONS)} transitions). "
          f"No roles assigned yet -- add them via Workflow Configuration > Annual Audit Intake > Roles.")


def main():
    from database import VendorSessionLocal
    db = VendorSessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE public.taqc_observations "
            "ADD COLUMN IF NOT EXISTS intake_workflow_id UUID "
            "REFERENCES repair_workflows(id) ON DELETE SET NULL"
        ))
        db.commit()
        print("Ensured taqc_observations.intake_workflow_id column exists.")
        seed_annual_audit_intake_stages(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
