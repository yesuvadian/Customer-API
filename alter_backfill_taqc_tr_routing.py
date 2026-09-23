#!/usr/bin/env python3
"""
One-time backfill: run seed_tr_wf_workflow(org=X) for every EXISTING
organization, so each gets the new dedicated "TAQC Inspection Workflow"
TrWfDefinition + explicit request_type='taqc_inspection' TrWfRoutingRule
(see seed_tr_wf_workflow.py's own docstring/comments for why).

Not needed for future orgs -- services/organization_service.py already
calls seed_tr_wf_workflow(session, org=new_org) during new-org
provisioning, so they get this automatically. This script only backfills
orgs that were provisioned before this fix landed.

Idempotent: seed_tr_wf_workflow() itself is entirely get-or-create, so
re-running this (or running it against an org that already has the new
workflow) is a no-op for that org.

Usage:
    python alter_backfill_taqc_tr_routing.py
"""
from database import VendorSessionLocal
from models import Organization
from seed_tr_wf_workflow import seed_tr_wf_workflow


def main():
    db = VendorSessionLocal()
    try:
        orgs = db.query(Organization).all()
        print(f"Backfilling TAQC TR routing for {len(orgs)} organization(s)...")
        for org in orgs:
            try:
                seed_tr_wf_workflow(db, org=org)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"  [WARN] {org.name} ({org.id}): {e}")
        print("[OK] TAQC TR routing backfill complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
