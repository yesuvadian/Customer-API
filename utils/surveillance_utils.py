"""
Surveillance workflow utility functions.
"""
from datetime import datetime, timezone
from typing import Optional
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


def latest_result_status(db: Session, testing_request_id) -> tuple:
    """
    (result_status, tested_at) of a ticket's latest test result.

    The evaluated overall (NORMAL / ALERT / CRITICAL) wins over the tester's
    own pass/fail pick - same precedence as TestingService's
    _derive_recommendation_from_results. Surveillance screens used to read
    form_data['result_status'], which nothing ever writes, so every test
    read as normal.
    """
    from models import TestResult

    latest = (
        db.query(TestResult)
        .filter(TestResult.testing_request_id == testing_request_id)
        .order_by(TestResult.tested_at.desc())
        .first()
    )
    if not latest:
        return None, None
    evaluated = (latest.evaluation_result or {}).get('overall')
    return (evaluated if isinstance(evaluated, str) else None) or latest.overall_result, latest.tested_at


def is_surveillance_test_abnormal(db: Session, ticket) -> bool:
    """A done ticket whose latest result matches the configured abnormal statuses."""
    from services.surveillance_config_service import SurveillanceConfigService

    if not is_surveillance_test_done(ticket):
        return False
    status, _ = latest_result_status(db, ticket.id)
    return bool(status) and SurveillanceConfigService.is_result_abnormal(
        db, status,
        organization_id=ticket.organization_id,
        department_id=ticket.department_id,
    )


def quarter_submit_block_reason(db: Session, workflow_id: UUID, quarter_number: int) -> Optional[str]:
    """
    Why the quarter's review can't be submitted yet, or None if it can.

    Shared by the available-transitions gate (UI) and submit_stage (server)
    so the button and the submit call never disagree.
    """
    from models import TestingRequest, TestRequestSchedule

    tickets = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.surveillance_workflow_id == workflow_id,
            TestingRequest.surveillance_quarter == quarter_number,
        )
        .all()
    )

    if not tickets:
        # Tests are still to come from the schedule - wait for them. With no
        # active schedule nothing will ever arrive, so don't hold the quarter.
        scheduled = (
            db.query(TestRequestSchedule.id)
            .filter(
                TestRequestSchedule.surveillance_workflow_id == workflow_id,
                TestRequestSchedule.is_active.is_(True),
                TestRequestSchedule.is_deleted.is_(False),
            )
            .first()
        )
        return f'No Q{quarter_number} test tickets created yet' if scheduled else None

    # Rejected tickets will never be tested - they don't hold the quarter open
    active = [t for t in tickets if not is_surveillance_test_void(t)]
    pending = sum(1 for t in active if not is_surveillance_test_done(t))
    if pending:
        return (
            f'{pending} of {len(active)} Q{quarter_number} test(s) still pending '
            f'— complete all tests before submitting'
        )
    return None


def calendar_quarter(start_date: datetime, end_date: Optional[datetime], run_date: datetime) -> Optional[int]:
    """
    Quarter of a schedule run, from the schedule's own start/end (end - start
    is the whole surveillance period, split into 4).

    Runs are meant to fire at each quarter's start, but next_run_date drifts
    (time of day, late/catch-up runs), so round to the nearest quarter start
    instead of flooring - a run a day before month 6 is still the Q2 run.
    """
    if not start_date or not end_date or not run_date:
        return None
    quarter_days = (end_date - start_date).days / 4
    if quarter_days <= 0:
        return None
    index = round((run_date - start_date).days / quarter_days)
    return max(1, min(index + 1, 4))


def schedule_run_quarter(db: Session, schedule, now: datetime) -> int:
    """
    Quarter for a ticket generated by a surveillance schedule run.

    The workflow's current stage alone mis-tags late quarters: if Q1 isn't
    approved by the time the month-6 run fires, those Q2 tests would land in
    Q1 and Q2 would never get any. Take the later of the stage quarter (keeps
    override-advanced workflows right) and the run date's calendar quarter.
    """
    stage_quarter = calculate_surveillance_quarter(db, schedule.surveillance_workflow_id, now)
    run_quarter = calendar_quarter(schedule.start_date, schedule.end_date, schedule.next_run_date)
    return max(stage_quarter, run_quarter or 0)


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
