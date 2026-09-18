#!/usr/bin/env python3
"""
One-time setup: grant System Administrator supervisory-override access by
default, on every active repair-workflow definition (Annual Audit,
Breakdown Repair, Calibration, DPR Approval, Overhaul, Post-Commission
Surveillance, ...).

Without this, RepairWorkflowOverrideRole starts empty and the override
feature is unreachable by anyone until an org admin manually visits each
workflow's "Override Roles" menu -- KPTCL's own System Administrator role
should have it out of the box, matching how the role's name already
implies system-wide authority elsewhere in the app.

Seeds by NAME ("System Administrator"), not by a single org's OrgRole.id:
RepairWorkflowDefinition has no organization_id (it's shared across every
org), and the authorization check itself
(RepairWorkflowService._user_org_role_ids) already expands a caller's own
role name to every OrgRole.id sharing that name across all orgs -- so one
seeded row per (workflow_definition, name-matching OrgRole) is enough for
every org's own System Administrator to be covered, present or future.

Idempotent: only inserts a (workflow_definition_id, role_id) pair that
doesn't already exist, so re-running after an admin has already
customized a workflow's override roles never overwrites their choice --
it only fills in ones still missing entirely.

Usage:
    python alter_seed_default_override_roles.py
"""
from database import VendorSessionLocal
from models import RepairWorkflowDefinition, RepairWorkflowOverrideRole, OrgRole

DEFAULT_OVERRIDE_ROLE_NAME = "System Administrator"


def main():
    db = VendorSessionLocal()
    try:
        workflows = db.query(RepairWorkflowDefinition).filter(
            RepairWorkflowDefinition.is_active.is_(True)
        ).all()
        if not workflows:
            print("No active workflow definitions found -- nothing to seed.")
            return

        admin_roles = db.query(OrgRole).filter(
            OrgRole.name == DEFAULT_OVERRIDE_ROLE_NAME,
        ).all()
        if not admin_roles:
            print(f"No OrgRole named '{DEFAULT_OVERRIDE_ROLE_NAME}' found -- nothing to seed.")
            return

        existing = {
            (r.workflow_definition_id, r.role_id)
            for r in db.query(RepairWorkflowOverrideRole).all()
        }

        inserted = 0
        for wf in workflows:
            for role in admin_roles:
                key = (wf.id, role.id)
                if key in existing:
                    continue
                db.add(RepairWorkflowOverrideRole(
                    workflow_definition_id=wf.id,
                    role_id=role.id,
                ))
                existing.add(key)
                inserted += 1

        db.commit()
        print(
            f"Seeded {inserted} default override-role grant(s) across "
            f"{len(workflows)} workflow(s) and {len(admin_roles)} "
            f"'{DEFAULT_OVERRIDE_ROLE_NAME}' role(s) (already-covered pairs skipped)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
