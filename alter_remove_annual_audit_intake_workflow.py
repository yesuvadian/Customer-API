#!/usr/bin/env python3
"""
One-time cleanup: reverses alter_annual_audit_intake_workflow.py (now
deleted) wherever it already ran.

The Annual Audit intake review (ANNUAL_AUDIT_INTAKE, 2-level sign-off
before the real remediation workflow starts) has been removed as a
feature -- TAQC's own upstream approval (the TR-engine's now-dedicated
"TAQC Inspection Workflow", see seed_tr_wf_workflow.py) already gates
the audit visit before any observations can even be logged, so a
second observation-level gate was judged redundant.

Removes, in dependency order:
  1. taqc_observations.intake_workflow_id column
  2. RepairStageRole grants on ANNUAL_AUDIT_INTAKE's stages
  3. RepairStageTransition rows on those stages
  4. RepairStageDefinition rows (the 2 levels)
  5. RepairWorkflowDefinition row itself

Safe against real usage: refuses to touch anything if any
TAQCObservation still references an ANNUAL_AUDIT_INTAKE workflow via
intake_workflow_id (i.e. still mid-review) -- run this only after
confirming (this script checks) there's no such observation, since
those columns are being dropped, not just unlinked.

Idempotent: safe to re-run: if the definition is already gone, this is
a no-op.

Usage:
    python alter_remove_annual_audit_intake_workflow.py
"""
from sqlalchemy import text
from database import VendorSessionLocal
from models import (
    RepairWorkflowDefinition,
    RepairStageDefinition,
    RepairStageTransition,
    RepairStageRole,
)

WORKFLOW_CODE = "ANNUAL_AUDIT_INTAKE"


def main():
    db = VendorSessionLocal()
    try:
        wf_def = db.query(RepairWorkflowDefinition).filter_by(
            workflow_code=WORKFLOW_CODE
        ).first()

        if wf_def:
            stages = db.query(RepairStageDefinition).filter_by(
                workflow_definition_id=wf_def.id
            ).all()
            stage_ids = [s.id for s in stages]

            # Raw SQL: the ORM model no longer declares intake_workflow_id
            # (that's the whole point of this cleanup), but the physical
            # column still exists on this table until the DROP below runs.
            in_use = db.execute(text("""
                SELECT COUNT(*) FROM public.taqc_observations o
                JOIN repair_workflows w ON w.id = o.intake_workflow_id
                WHERE o.workflow_id IS NULL AND w.workflow_code = :code
            """), {"code": WORKFLOW_CODE}).scalar() if stage_ids else 0
            if in_use:
                print(f"[ABORT] {in_use} observation(s) still mid-intake-review "
                      f"(workflow_id IS NULL, intake_workflow_id set) -- resolve "
                      f"those first (approve/reject them) before removing the "
                      f"chain, or their intake progress will be lost.")
                return

            if stage_ids:
                n = db.query(RepairStageRole).filter(
                    RepairStageRole.stage_id.in_(stage_ids)
                ).delete(synchronize_session=False)
                print(f"[OK] Removed {n} RepairStageRole grant(s).")

                n = db.query(RepairStageTransition).filter(
                    RepairStageTransition.from_stage_id.in_(stage_ids)
                ).delete(synchronize_session=False)
                print(f"[OK] Removed {n} RepairStageTransition row(s).")

                n = db.query(RepairStageDefinition).filter(
                    RepairStageDefinition.id.in_(stage_ids)
                ).delete(synchronize_session=False)
                print(f"[OK] Removed {n} RepairStageDefinition row(s).")

            db.delete(wf_def)
            print(f"[OK] Removed RepairWorkflowDefinition {WORKFLOW_CODE}.")
            db.commit()
        else:
            print(f"[OK] RepairWorkflowDefinition {WORKFLOW_CODE} not found -- nothing to remove.")

        db.execute(text(
            "ALTER TABLE public.taqc_observations "
            "DROP COLUMN IF EXISTS intake_workflow_id"
        ))
        db.commit()
        print("[OK] Dropped taqc_observations.intake_workflow_id column.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
