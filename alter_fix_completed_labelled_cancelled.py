#!/usr/bin/env python3
"""
One-time fix: requests whose workflow was COMPLETED (last workflow action a
"complete" / approve - not a cancel or reject) but whose status label was
saved as a cancel status (e.g. wf_cancelled) - the old terminal-status
fallback took the workflow's last status by sequence when the transition had
no end status configured. Sets the request's and its workflow instance's
current_status_code to the workflow's completed status (the same choice
services/tr_workflow_routing_service.py fallback_terminal_status now makes).

Only the label changes - status, results, CARs and audit history are left
as they are. Dry run by default.

    python alter_fix_completed_labelled_cancelled.py           # dry run
    python alter_fix_completed_labelled_cancelled.py --apply   # write
"""
import sys

from sqlalchemy import text

from database import VendorSessionLocal
from models import TestingRequest, TrWfAuditLog, TrWfInstance
from services.tr_workflow_routing_service import fallback_terminal_status

apply = "--apply" in sys.argv
db = VendorSessionLocal()
rows = (
    db.query(TestingRequest, TrWfInstance)
    .join(TrWfInstance, TrWfInstance.id == TestingRequest.wf_instance_id)
    .filter(
        TrWfInstance.status == "completed",
        TestingRequest.current_status_code.ilike("%cancel%"),
    )
    .order_by(TestingRequest.request_number)
    .all()
)
fixed = 0
for tr, inst in rows:
    last = (
        db.query(TrWfAuditLog.action_code)
        .filter(TrWfAuditLog.wf_instance_id == inst.id)
        .order_by(TrWfAuditLog.created_at.desc())
        .first()
    )
    action = (last[0] if last else "") or ""
    if "cancel" in action.lower() or "reject" in action.lower():
        continue  # really cancelled / rejected - label is right
    target = fallback_terminal_status(db, inst.wf_definition_id, action_code=action, is_rejection=False)
    if target is None or "cancel" in (target.status_code or ""):
        continue
    print(f"  {tr.request_number:<20} last action '{action}': {tr.current_status_code} -> {target.status_code}")
    fixed += 1
    if apply:
        tr.current_status_code = target.status_code
        inst.current_status_code = target.status_code
if apply:
    db.commit()
print(f"{fixed} request(s) {'fixed' if apply else 'would be fixed'}." + ("" if apply else " Re-run with --apply."))
