#!/usr/bin/env python3
"""
One-time setup: seed the "Workflow Request Types" CategoryDetails group.

TrWfDefinition.request_type / TrWfRoutingRule.request_type / TestingRequest.
request_type all stay plain strings (they're compared as such in 21+ places
across the routing engine) -- this only supplies the ADMIN-EDITABLE PICKLIST
of valid values for the "New Workflow Definition" dialog, which today
hardcodes exactly four options in Dart. Same category_type-grouping idiom
"Annual Audit Categories" already uses (seed.py's
_get_or_create_category_detail), so adding a new request type later is a
Category Management admin action, not a code change.

Idempotent: get-or-create throughout, safe to re-run.

Usage:
    python alter_seed_workflow_request_types.py
"""
from database import VendorSessionLocal
from models import CategoryMaster
from seed import _get_or_create_category_detail

MASTER_NAME = "Workflow Request Types"
CATEGORY_TYPE = "workflow_request_type"

# (name, description) -- name is the literal string stored on
# TrWfDefinition.request_type / TestingRequest.request_type.
#
# Deliberately does NOT include annual_audit_intake / precommission_intake /
# dpr_intake: Annual Audit, Precommission Intake, and DPR Approval all run
# on RepairWorkflowDefinition/RepairWorkflowService (see
# alter_precommission_intake_workflow.py), never on a TrWfDefinition, so
# they'd never be a valid request_type for a TR workflow to begin with --
# an earlier draft of this seed added them speculatively before that engine
# choice was finalized.
REQUEST_TYPES = [
    ("normal", "Standard equipment test request"),
    ("failure", "Failure Registry-triggered request"),
    ("special", "Special/one-off test request"),
]


def main():
    db = VendorSessionLocal()
    try:
        master = db.query(CategoryMaster).filter(
            CategoryMaster.name == MASTER_NAME
        ).first()
        if not master:
            master = CategoryMaster(
                name=MASTER_NAME,
                description="Valid values for TrWfDefinition/TestingRequest.request_type",
                is_active=True,
            )
            db.add(master)
            db.flush()
            print(f"[NEW] CategoryMaster '{MASTER_NAME}'")

        for name, description in REQUEST_TYPES:
            _get_or_create_category_detail(
                db,
                name=name,
                category_master_id=master.id,
                description=description,
                category_type=CATEGORY_TYPE,
                is_active=True,
            )

        db.commit()
        print(f"[OK] Seeded {len(REQUEST_TYPES)} workflow request type(s) under '{MASTER_NAME}'.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
