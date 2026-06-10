"""
Surveillance workflow utility functions.
"""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session
from models import RepairStageInstance, RepairWorkflow


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
