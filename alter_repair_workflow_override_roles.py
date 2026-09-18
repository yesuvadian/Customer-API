#!/usr/bin/env python3
"""
One-time setup: create repair_workflow_override_roles.

Supervisory override with mandatory justification -- one role list per
RepairWorkflowDefinition (not per stage), so a role authorized to
override can force-transition the workflow from whatever stage it's
currently stuck in, without needing to be separately granted on every
one of that workflow type's stages. Applies to all workflow types built
on the generic repair-workflow engine (Annual Audit, Breakdown Repair,
Calibration, Overhaul, Post-Commission Surveillance, DPR Approval) --
same tables, same service, no per-type code.

Re-running this script is safe: create_all only creates a missing
table, it never alters or drops an existing one.

Usage:
    python alter_repair_workflow_override_roles.py
"""
from database import VendorSessionLocal
from models import Base, RepairWorkflowOverrideRole


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[RepairWorkflowOverrideRole.__table__],
    )
    print("Ensured repair_workflow_override_roles table exists.")


if __name__ == "__main__":
    main()
