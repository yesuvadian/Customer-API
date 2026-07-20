"""
patch_fr_status_codes.py
─────────────────────────
Backfill current_status_code on FR TestingRequests and their TrWfInstances
where the value is NULL but a wf_instance exists with an active stage.

Looks up: wf_instance.wf_definition_id → first TrWfStatus (by sequence)
Sets it on both TrWfInstance.current_status_code and TestingRequest.current_status_code.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from models import TestingRequest, TrWfInstance, TrWfStatus, RequestCategory

db = SessionLocal()
try:
    frs = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.request_category == RequestCategory.failure_registry,
            TestingRequest.current_status_code == None,
            TestingRequest.wf_instance_id != None,
        )
        .all()
    )
    print(f"Found {len(frs)} FRs with null current_status_code and a wf_instance")

    updated = 0
    for fr in frs:
        instance = db.query(TrWfInstance).filter(TrWfInstance.id == fr.wf_instance_id).first()
        if not instance:
            print(f"  {fr.request_number}: no instance found, skipping")
            continue

        # Already has status code on instance
        code = instance.current_status_code
        if not code:
            # Find first active status for this WF definition
            status_row = (
                db.query(TrWfStatus)
                .filter(
                    TrWfStatus.wf_definition_id == instance.wf_definition_id,
                    TrWfStatus.is_active == True,
                )
                .order_by(TrWfStatus.sequence)
                .first()
            )
            if not status_row:
                # Try terminal statuses for completed instances
                status_row = (
                    db.query(TrWfStatus)
                    .filter(TrWfStatus.wf_definition_id == instance.wf_definition_id)
                    .order_by(TrWfStatus.sequence)
                    .first()
                )
            if status_row:
                code = status_row.status_code
                instance.current_status_code = code
                print(f"  {fr.request_number}: instance status set to '{code}'")
            else:
                print(f"  {fr.request_number}: no TrWfStatus rows found for definition {instance.wf_definition_id}")
                continue

        fr.current_status_code = code
        updated += 1
        print(f"  {fr.request_number}: current_status_code = '{code}'")

    db.commit()
    print(f"\nDone. Updated {updated} FR(s).")
finally:
    db.close()
