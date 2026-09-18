#!/usr/bin/env python3
"""
One-time setup: grant System Administrator approve access by default on
every stage of the three intake review chains (Precommission Intake, DPR
Intake, Annual Audit Intake).

Without this, RepairStageRole starts empty for these stages and the
intake chains are unreachable by anyone until an org admin manually
visits each workflow's "Roles" screen -- KPTCL's own System
Administrator role should have it out of the box, same reasoning as
alter_seed_default_override_roles.py for the supervisory-override
feature.

Seeds by NAME ("System Administrator"), not by a single org's OrgRole.id:
RepairStageDefinition has no organization_id (it's shared across every
org), and RepairWorkflowService._user_org_role_ids already expands a
caller's own role name to every OrgRole.id sharing that name across all
orgs -- so one seeded row per (stage, name-matching OrgRole) is enough
for every org's own System Administrator to be covered, present or
future.

Idempotent: only inserts a (stage_id, role_id) pair that doesn't already
exist, so re-running after an admin has already customized a stage's
roles never overwrites their choice -- it only fills in ones still
missing entirely.

Usage:
    python alter_seed_default_intake_approval_roles.py
"""
from database import VendorSessionLocal
from models import RepairWorkflowDefinition, RepairStageDefinition, RepairStageRole, OrgRole

DEFAULT_ROLE_NAME = "System Administrator"

INTAKE_WORKFLOW_CODES = [
    "PRECOMMISSION_INTAKE",
    "DPR_INTAKE",
    "ANNUAL_AUDIT_INTAKE",
]


def seed_default_intake_approval_roles(db) -> int:
    wf_defs = db.query(RepairWorkflowDefinition).filter(
        RepairWorkflowDefinition.workflow_code.in_(INTAKE_WORKFLOW_CODES)
    ).all()
    if not wf_defs:
        print("[WARN] seed_default_intake_approval_roles: no intake workflow definitions found — skipping")
        return 0

    stages = db.query(RepairStageDefinition).filter(
        RepairStageDefinition.workflow_definition_id.in_([w.id for w in wf_defs])
    ).all()
    if not stages:
        print("[WARN] seed_default_intake_approval_roles: no intake stages found — skipping")
        return 0

    admin_roles = db.query(OrgRole).filter(OrgRole.name == DEFAULT_ROLE_NAME).all()
    if not admin_roles:
        print(f"[WARN] seed_default_intake_approval_roles: no OrgRole named '{DEFAULT_ROLE_NAME}' found — skipping")
        return 0

    existing = {
        (r.stage_id, r.role_id)
        for r in db.query(RepairStageRole).filter(
            RepairStageRole.stage_id.in_([s.id for s in stages])
        ).all()
    }

    inserted = 0
    for stage in stages:
        for role in admin_roles:
            key = (stage.id, role.id)
            if key in existing:
                continue
            db.add(RepairStageRole(
                stage_id=stage.id,
                role_id=role.id,
                can_edit=True,
                can_approve=True,
                can_assign=True,
            ))
            existing.add(key)
            inserted += 1

    db.commit()
    print(
        f"[OK] Seeded {inserted} default intake approval-role grant(s) across "
        f"{len(stages)} stage(s) and {len(admin_roles)} '{DEFAULT_ROLE_NAME}' "
        f"role(s) (already-covered pairs skipped)."
    )
    return inserted


def main():
    db = VendorSessionLocal()
    try:
        seed_default_intake_approval_roles(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
