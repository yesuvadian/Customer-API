"""
Surveillance workflow utility functions.
"""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session
from models import RepairStageInstance, RepairWorkflow

# Ticket statuses where the tester's part of a surveillance test is done.
# 'closed', 'outcome_active' and 'commissioned' are terminal states of the
# test workflow and must count too, or a fully closed quarter reads 0 done.
# 'procurement_initiated' / 'finance_pending' follow an approved result that
# triggered replacement - the test itself was carried out.
SURVEILLANCE_DONE_STATUSES = frozenset({
    'test_submitted', 'under_approval', 'approved', 'completed',
    'closed', 'outcome_active', 'commissioned',
    'procurement_initiated', 'finance_pending',
})

# Ticket statuses where the test will never be carried out. These are
# neither done nor pending: they must not hold the quarter open.
SURVEILLANCE_VOID_STATUSES = frozenset({'rejected'})


def _status_value(ticket) -> str:
    """TestingRequest.status is an Enum column; compare its string value."""
    return ticket.status.value if hasattr(ticket.status, 'value') else ticket.status


def is_surveillance_test_done(ticket) -> bool:
    return _status_value(ticket) in SURVEILLANCE_DONE_STATUSES


def is_surveillance_test_void(ticket) -> bool:
    return _status_value(ticket) in SURVEILLANCE_VOID_STATUSES


def calculate_surveillance_quarter(db: Session, workflow_id: UUID, current_date: datetime) -> int:
    """
    Return the quarter number for the surveillance workflow's current active stage.

    Uses the stage's quarter_number field rather than elapsed real-world time so
    that manually-advanced (override) workflows assign tickets to the correct
    quarter even when the calendar hasn't caught up yet.

    Falls back to elapsed-time calculation only when no active stage is found.
    """
    # Primary: derive quarter from the current active stage instance
    workflow = db.query(RepairWorkflow).filter(
        RepairWorkflow.id == workflow_id
    ).first()

    if workflow and workflow.current_stage_instance_id:
        instance = db.query(RepairStageInstance).filter(
            RepairStageInstance.id == workflow.current_stage_instance_id
        ).first()
        if instance and instance.quarter_number:
            return instance.quarter_number

    # Fallback: use elapsed time (original logic) for non-instance workflows
    if not workflow or not workflow.started_at:
        return 1

    start_date = workflow.started_at
    if start_date.tzinfo is None and current_date.tzinfo is not None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    elif start_date.tzinfo is not None and current_date.tzinfo is None:
        current_date = current_date.replace(tzinfo=timezone.utc)

    months_elapsed = (current_date - start_date).days / 30
    return min(int(months_elapsed / 6) + 1, 4)
