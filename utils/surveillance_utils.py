"""
Surveillance workflow utility functions.
"""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session
from models import RepairWorkflow


def calculate_surveillance_quarter(db: Session, workflow_id: UUID, current_date: datetime) -> int:
    """
    Calculate which surveillance quarter we're in based on workflow start date.

    Args:
        db: Database session
        workflow_id: Surveillance workflow ID
        current_date: Current date/time

    Returns:
        Quarter number (1-4)

    Example:
        Workflow started: 2026-01-01
        Current date: 2026-07-15 (6.5 months elapsed)
        Result: Quarter 2 (6.5 / 6 = 1.08, int(1.08) + 1 = 2)
    """
    workflow = db.query(RepairWorkflow).filter(
        RepairWorkflow.id == workflow_id
    ).first()

    if not workflow or not workflow.started_at:
        return 1  # Default to Q1 if not found

    # Calculate months elapsed since workflow start
    start_date = workflow.started_at

    # Handle timezone-aware vs naive datetimes
    if start_date.tzinfo is None and current_date.tzinfo is not None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    elif start_date.tzinfo is not None and current_date.tzinfo is None:
        current_date = current_date.replace(tzinfo=timezone.utc)

    delta = current_date - start_date
    months_elapsed = delta.days / 30  # Approximate (30 days per month)

    # Each quarter is 6 months (24 months / 4 quarters)
    # Q1: 0-6 months    → months_elapsed/6 = 0.x   → int(0.x) + 1 = 1
    # Q2: 6-12 months   → months_elapsed/6 = 1.x   → int(1.x) + 1 = 2
    # Q3: 12-18 months  → months_elapsed/6 = 2.x   → int(2.x) + 1 = 3
    # Q4: 18-24 months  → months_elapsed/6 = 3.x   → int(3.x) + 1 = 4
    quarter = min(int(months_elapsed / 6) + 1, 4)

    return quarter
