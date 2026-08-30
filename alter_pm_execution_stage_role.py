#!/usr/bin/env python3
"""
One-time setup: grant the "PM Execution" stage of the PM Workflow (the
workflow Failure Registry tickets run on) a real role, via a TrWfStageRole
row.

Without this row, PM Execution has zero role grants — and the workflow
engine's own rule (services/tr_workflow_routing_service.py's advance_stage:
"if the next stage has zero active TrWfStageRole rows, treat this
transition as terminal") means the engine can never actually land on PM
Execution at all. Approving at "Technical Approval" would fall straight
through to terminal instead, and because the "Technical Approval -> PM
Execution" transition itself has no terminal_status_id configured, the
fallback logic (last TrWfStatus by sequence for the definition) resolves to
'fr_cancelled' rather than 'pm_completed' — silently mis-closing every
Failure Registry ticket that reaches that point as cancelled instead of
completed.

Confirmed live: this org's PM Workflow had exactly this gap before this
script was first run (0 TrWfStageRole rows on PM Execution), discovered
while walking FR-KP-2026-0001 through to completion for the Maintenance
Effectiveness Index report. Every org using this codebase's PM Workflow
needs this row.

Grants AEE_MAINTENANCE can_edit=True on PM Execution — matching the
"execution rights = can_edit" convention used everywhere else in this
workflow engine (e.g. the Standard Test Workflow's L4 Test Execution stage),
and AEE_MAINTENANCE is the role literally named for doing maintenance work.
If your org names its maintenance-execution role differently, edit
EXECUTOR_ROLE_NAME below before running.

Idempotent — checks for an existing (stage, role) row before inserting, so
re-running (or running after a manual fix) is safe.

Usage:
    python alter_pm_execution_stage_role.py
"""
import uuid

from database import VendorSessionLocal
from models import TrWfDefinition, TrWfStage, TrWfStageRole, OrgRole

WF_DEFINITION_NAME = "PM Workflow"
STAGE_NAME = "PM Execution"
EXECUTOR_ROLE_NAME = "AEE_MAINTENANCE"


def main():
    db = VendorSessionLocal()
    try:
        wf = db.query(TrWfDefinition).filter(TrWfDefinition.name == WF_DEFINITION_NAME).first()
        if not wf:
            print(f"WARNING: workflow definition '{WF_DEFINITION_NAME}' not found — nothing to do.")
            return

        stage = (
            db.query(TrWfStage)
            .filter(TrWfStage.wf_definition_id == wf.id, TrWfStage.name == STAGE_NAME)
            .first()
        )
        if not stage:
            print(f"WARNING: stage '{STAGE_NAME}' not found on '{WF_DEFINITION_NAME}' — nothing to do.")
            return

        role = db.query(OrgRole).filter(OrgRole.name == EXECUTOR_ROLE_NAME).first()
        if not role:
            print(f"WARNING: role '{EXECUTOR_ROLE_NAME}' not found — edit EXECUTOR_ROLE_NAME "
                  f"in this script to match your org's maintenance-execution role, then re-run.")
            return

        existing = (
            db.query(TrWfStageRole)
            .filter(TrWfStageRole.stage_id == stage.id, TrWfStageRole.role_id == role.id)
            .first()
        )
        if existing:
            print(f"Already present: {EXECUTOR_ROLE_NAME} on '{STAGE_NAME}' "
                  f"(can_edit={existing.can_edit}) — nothing to do.")
            return

        # Any pre-existing grants at all on this stage (a different role)
        # mean the actual gap this script exists to fix isn't present —
        # still add ours, but flag it so it's not mistaken for the same bug.
        other_grants = db.query(TrWfStageRole).filter(TrWfStageRole.stage_id == stage.id).count()
        if other_grants:
            print(f"NOTE: '{STAGE_NAME}' already has {other_grants} role grant(s) from other "
                  f"role(s) — the zero-grants bug this script targets may not apply here. "
                  f"Adding {EXECUTOR_ROLE_NAME} anyway.")

        row = TrWfStageRole(
            id=uuid.uuid4(),
            stage_id=stage.id,
            role_id=role.id,
            can_approve=False,
            can_assign=False,
            can_edit=True,
            can_act_as_tester=False,
            can_view=False,
        )
        db.add(row)
        db.commit()
        print(f"Inserted TrWfStageRole: {EXECUTOR_ROLE_NAME} can_edit=True on '{STAGE_NAME}' "
              f"({row.id}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
