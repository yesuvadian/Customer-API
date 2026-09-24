"""
Corrective Action Request (CAR) service
=========================================
Implements the auto-creation hook from the CM Recommendation -> Test Request
-> Evaluation -> CAR design:

    Test Result -> Evaluation Engine -> NORMAL      -> no CAR (closes an open one)
                                      -> ALERT       -> per CarTriggerConfig (may or may not trigger)
                                      -> CRITICAL    -> CAR created/linked, per CarTriggerConfig
                                                         (falls back to CRITICAL-only, single
                                                         same-test-type retest, when no config row
                                                         exists for this equipment_type/test_type)

A CAR is never created by a user action — only by process_evaluation_for_car(),
called from testing_service.py right after EvaluationService.run() produces a
result. Lineage is walked via TestingRequest.parent_request_id (already used
today for Failure Request -> child Test Request creation) plus equipment_id +
test_type_id as a fallback, so a retest that isn't a direct parent/child but
targets the same equipment+test still finds the right open CAR.

Follow-up fan-out (CarTriggerConfig -> CarTriggerFollowup) mirrors the "New
Testing Request" form's own multi-select-test-types pattern
(create_testing_request_form.dart): one CRITICAL/ALERT rule can raise several
follow-up actions in one shot — a retest (category=test), a maintenance work
order (category=maintenance), a physical inspection (category=inspection),
or a repair workflow (category=repair_lifecycle), each via the exact same
TestingRequestService calls (create_request + submit_request) the manual
form uses, or RepairWorkflowService.start_workflow() for repair_lifecycle.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from config import CAR_DUE_DAYS_ALERT, CAR_DUE_DAYS_CRITICAL
from models import (
    CarRelationshipType,
    CarStatus,
    CarTestRequest,
    CarTriggerConfig,
    CarTriggerFollowup,
    CategoryDetails,
    CorrectiveActionRequest,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
)

# TR statuses that mean "this TR is done, it's not driving anything forward
# anymore" - anything not in this set counts as an active/in-flight TR for
# the "does this CAR still have a live TR" check below.
_TERMINAL_TR_STATUSES = {
    TestingRequestStatus.completed,
    TestingRequestStatus.rejected,
    TestingRequestStatus.outcome_active,
    TestingRequestStatus.commissioned,
    TestingRequestStatus.closed,
}

logger = logging.getLogger(__name__)

# Fallback when no CarTriggerConfig row matches this equipment_type/test_type
# at all — keeps existing deployments working unchanged until an admin
# configures rules for that equipment type.
DEFAULT_CAR_TRIGGER_SEVERITIES = {"CRITICAL"}


def _find_trigger_config(
    db: Session,
    *,
    organization_id: Optional[uuid.UUID],
    equipment_type_id: Optional[int],
    test_type_id: Optional[int],
    severity: str,
) -> Optional[CarTriggerConfig]:
    """Most specific match wins: org+test_type > org+wildcard >
    global+test_type > global+wildcard. Returns None if nothing configured
    for this equipment_type at all (caller falls back to the hardcoded
    default rather than treating "no config" as "never trigger")."""
    if not equipment_type_id:
        return None

    base = (
        db.query(CarTriggerConfig)
        .options(joinedload(CarTriggerConfig.followups))
        .filter(
            CarTriggerConfig.equipment_type_id == equipment_type_id,
            CarTriggerConfig.severity == severity,
            CarTriggerConfig.is_active.is_(True),
        )
    )

    for org_filter in ([organization_id] if organization_id else []) + [None]:
        for tt_filter in ([test_type_id] if test_type_id else []) + [None]:
            row = base.filter(
                CarTriggerConfig.organization_id == org_filter,
                CarTriggerConfig.test_type_id == tt_filter,
            ).first()
            if row:
                return row
    return None


def _has_any_config_for_equipment_type(db: Session, equipment_type_id: Optional[int]) -> bool:
    if not equipment_type_id:
        return False
    return (
        db.query(CarTriggerConfig.id)
        .filter(CarTriggerConfig.equipment_type_id == equipment_type_id, CarTriggerConfig.is_active.is_(True))
        .first()
        is not None
    )


def _car_number(db: Session) -> str:
    """CAR-YYYY-NNNN, sequential within the year — mirrors the request_number
    style already used for TestingRequest (e.g. TR-KP-2026-0656)."""
    year = datetime.now(timezone.utc).year
    prefix = f"CAR-{year}-"
    count = (
        db.query(CorrectiveActionRequest)
        .filter(CorrectiveActionRequest.car_number.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count + 1:04d}"


def _lineage_test_request_ids(db: Session, testing_request: TestingRequest) -> list[uuid.UUID]:
    """Walk the parent_request_id chain upward from this TR, plus sibling
    TRs sharing the same equipment+test_type as a fallback for lineages that
    aren't strictly parent/child (e.g. a manually re-raised retest)."""
    ids: list[uuid.UUID] = [testing_request.id]
    current = testing_request
    seen = {testing_request.id}
    while current.parent_request_id and current.parent_request_id not in seen:
        parent = db.query(TestingRequest).filter(TestingRequest.id == current.parent_request_id).first()
        if not parent:
            break
        ids.append(parent.id)
        seen.add(parent.id)
        current = parent

    if testing_request.equipment_id and testing_request.test_type_id:
        siblings = (
            db.query(TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == testing_request.equipment_id,
                TestingRequest.test_type_id == testing_request.test_type_id,
                TestingRequest.id != testing_request.id,
            )
            .all()
        )
        for (sid,) in siblings:
            if sid not in seen:
                ids.append(sid)
                seen.add(sid)

    return ids


def find_open_car_for_lineage(db: Session, testing_request: TestingRequest) -> Optional[CorrectiveActionRequest]:
    """An open CAR already covering this TR's lineage (same equipment/test
    chain), so a failed retest attaches to it instead of spawning a new one."""
    lineage_ids = _lineage_test_request_ids(db, testing_request)
    if not lineage_ids:
        return None

    link = (
        db.query(CarTestRequest)
        .join(CorrectiveActionRequest, CorrectiveActionRequest.id == CarTestRequest.car_id)
        .filter(
            CarTestRequest.test_request_id.in_(lineage_ids),
            CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
        )
        .order_by(CorrectiveActionRequest.created_at.desc())
        .first()
    )
    if link:
        return db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == link.car_id).first()
    return None


def _ensure_active_followup(
    db: Session,
    *,
    car: CorrectiveActionRequest,
    testing_request: TestingRequest,
    created_by: Optional[uuid.UUID],
) -> None:
    """Called when a CAR just failed another retest (still open). If nothing
    in its lineage is still in-flight, the CAR is an orphan - open, but with
    no live TR anywhere driving it toward resolution, since the full
    CarTriggerConfig fan-out only runs once, at original CAR creation. Raise
    a single same-test-type retest (not the full fan-out again - the
    maintenance/inspection/repair crews from the original trigger don't need
    re-dispatching every time the retest itself fails) so the CAR always has
    exactly one active TR in flight until something finally comes back
    NORMAL.
    """
    lineage_ids = _lineage_test_request_ids(db, testing_request)
    active = (
        db.query(TestingRequest.id)
        .filter(
            TestingRequest.id.in_(lineage_ids),
            ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
        )
        .first()
    )
    if active:
        return  # something's still in flight - nothing to do

    if not testing_request.equipment_id or not testing_request.test_type_id:
        return  # not enough to raise a same-type retest against

    from services.testing_request_service import TestingRequestService

    originator_id = created_by or testing_request.originator_id
    tr_service = TestingRequestService(db)
    try:
        new_request = tr_service.create_request(
            {
                "title": f"{car.car_number} retest: {testing_request.title}",
                "equipment_id": testing_request.equipment_id,
                "equipment_type_id": testing_request.equipment_type_id,
                "test_type_id": testing_request.test_type_id,
                "request_category": testing_request.request_category.value
                    if testing_request.request_category else "test",
                "organization_id": testing_request.organization_id,
                "department_id": testing_request.department_id,
                "priority": "high",
                "notes": f"Auto-created retest - {car.car_number} still open after a repeat failure "
                         f"(source: {testing_request.request_number})",
            },
            originator_id=originator_id,
        )
        new_request.parent_request_id = testing_request.id
        db.commit()

        tr_service.submit_request(new_request.id, modified_by=originator_id)

        db.add(CarTestRequest(
            car_id=car.id,
            test_request_id=new_request.id,
            relationship_type=CarRelationshipType.RETEST,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(f"CAR {car.car_number}: auto-retest creation failed: {exc}")


def process_evaluation_for_car(
    db: Session,
    *,
    test_result: TestResult,
    testing_request: TestingRequest,
    evaluation_overall: str,
    summary: Optional[str],
    created_by: Optional[uuid.UUID] = None,
) -> Optional[CorrectiveActionRequest]:
    """
    The auto-creation hook. Call this right after evaluation produces a
    result (see testing_service.py). Returns the CAR that was created or
    linked to, or None if this severity doesn't trigger one.

    - No open CAR in this TR's lineage yet -> create a new CAR, link this TR
      as ORIGINATING, and fan out any configured follow-up actions.
    - An open CAR already exists for this lineage -> link this TR to it as
      RETEST instead of creating a duplicate CAR (design doc section 6).
    """
    config = _find_trigger_config(
        db,
        organization_id=testing_request.organization_id,
        equipment_type_id=testing_request.equipment_type_id,
        test_type_id=testing_request.test_type_id,
        severity=evaluation_overall,
    )

    if config is not None:
        if not config.car_trigger:
            return None
    elif evaluation_overall not in DEFAULT_CAR_TRIGGER_SEVERITIES:
        return None

    existing_car = find_open_car_for_lineage(db, testing_request)

    if existing_car:
        # Session-level advisory lock, not a row lock: _ensure_active_followup
        # goes through TestingRequestService.create_request(), which commits
        # internally — a plain SELECT ... FOR UPDATE row lock would be
        # released at that first inner commit, well before the "check active
        # -> create retest" sequence finishes, so two near-simultaneous
        # evaluations could still both slip through and double-create. An
        # advisory lock is independent of transaction boundaries and only
        # releases on pg_advisory_unlock (or the connection closing), so it
        # actually serializes the whole sequence for this CAR.
        db.execute(text("SELECT pg_advisory_lock(hashtext(:car_id))"), {"car_id": str(existing_car.id)})
        try:
            already_linked = (
                db.query(CarTestRequest)
                .filter(
                    CarTestRequest.car_id == existing_car.id,
                    CarTestRequest.test_request_id == testing_request.id,
                )
                .first()
            )
            if not already_linked:
                db.add(CarTestRequest(
                    car_id=existing_car.id,
                    test_request_id=testing_request.id,
                    relationship_type=CarRelationshipType.RETEST,
                ))
                # A CAR that failed verification goes back to REOPENED, not
                # stays PENDING_VERIFICATION, since the retest just failed again.
                if existing_car.status == CarStatus.PENDING_VERIFICATION:
                    existing_car.status = CarStatus.REOPENED
                db.commit()

                # We only reach this branch for a triggering severity (see the
                # config/DEFAULT_CAR_TRIGGER_SEVERITIES gate above) - so this
                # CAR just failed another retest. Keep exactly one active TR
                # driving it forward — unless a reviewer has already
                # recommended replacing the equipment instead, which stops
                # the auto-retest loop deliberately.
                if existing_car.status != CarStatus.REPLACEMENT_RECOMMENDED:
                    _ensure_active_followup(db, car=existing_car, testing_request=testing_request, created_by=created_by)
        finally:
            db.execute(text("SELECT pg_advisory_unlock(hashtext(:car_id))"), {"car_id": str(existing_car.id)})
            db.commit()

        return existing_car

    # Per-rule override (car_due_in_days, set on the CarTriggerConfig row
    # itself via the Trigger Config screen) wins over the global .env
    # default for this severity -- same override-falls-back-to-default
    # shape every other config in this fan-out already uses.
    due_days = (
        config.car_due_in_days
        if config is not None and config.car_due_in_days is not None
        else (CAR_DUE_DAYS_CRITICAL if evaluation_overall == "CRITICAL" else CAR_DUE_DAYS_ALERT)
    )
    car = CorrectiveActionRequest(
        car_number=_car_number(db),
        equipment_id=testing_request.equipment_id,
        organization_id=testing_request.organization_id,
        department_id=testing_request.department_id,
        source_test_result_id=test_result.id,
        template_key=test_result.template_key,
        severity=evaluation_overall,
        summary=summary,
        status=CarStatus.OPEN,
        due_date=(datetime.now(timezone.utc) + timedelta(days=due_days)).date(),
        created_by=created_by,
    )
    db.add(car)
    db.flush()

    db.add(CarTestRequest(
        car_id=car.id,
        test_request_id=testing_request.id,
        relationship_type=CarRelationshipType.ORIGINATING,
    ))
    db.commit()
    db.refresh(car)
    _fire_car_notification(db, event_type="car_created", car=car)

    if config is not None and config.followups:
        _create_followups(db, car=car, config=config, source_request=testing_request, created_by=created_by)

    return car


def _create_followups(
    db: Session,
    *,
    car: CorrectiveActionRequest,
    config: CarTriggerConfig,
    source_request: TestingRequest,
    created_by: Optional[uuid.UUID],
) -> None:
    """Fan out CarTriggerFollowup rows into real follow-up actions — same
    branch the "New Testing Request" form takes per selected test type:
    test/maintenance/inspection -> TestingRequestService.create_request() +
    submit_request(); repair_lifecycle -> RepairWorkflowService.start_workflow().
    Best-effort per follow-up: one failing (e.g. a repair workflow already
    active for this equipment) never blocks the others or the CAR itself.
    """
    from services.testing_request_service import TestingRequestService
    from services.repair_workflow_service import RepairWorkflowService

    active_followups = [f for f in config.followups if f.is_active]
    if not active_followups:
        return

    followup_type_ids = [f.follow_up_test_type_id for f in active_followups]
    category_by_type_id = {
        row.id: row.category_type
        for row in db.query(CategoryDetails).filter(CategoryDetails.id.in_(followup_type_ids)).all()
    }

    tr_service = TestingRequestService(db)
    repair_service = RepairWorkflowService(db)
    originator_id = created_by or source_request.originator_id

    for followup in active_followups:
        category = category_by_type_id.get(followup.follow_up_test_type_id)
        try:
            if category == "repair_lifecycle":
                result = repair_service.start_workflow(
                    equipment_id=source_request.equipment_id,
                    user_id=originator_id,
                    source_failure_id=source_request.id,
                )
                logger.info(f"CAR {car.car_number}: started repair workflow {result.get('id') if result else '?'}")
                continue

            due_date = datetime.now(timezone.utc) + timedelta(days=followup.due_in_days)
            new_request = tr_service.create_request(
                {
                    "title": f"{car.car_number} follow-up: {source_request.title}",
                    "equipment_id": source_request.equipment_id,
                    "equipment_type_id": source_request.equipment_type_id,
                    "test_type_id": followup.follow_up_test_type_id,
                    "request_category": category or "test",
                    "organization_id": source_request.organization_id,
                    "department_id": source_request.department_id,
                    "priority": "high",
                    "due_date": due_date,
                    "notes": f"Auto-created from {car.car_number} (source: {source_request.request_number})",
                },
                originator_id=originator_id,
            )
            new_request.parent_request_id = source_request.id
            new_request.source_failure_id = None
            db.commit()

            tr_service.submit_request(new_request.id, modified_by=originator_id)

            relationship = (
                CarRelationshipType.RETEST
                if followup.follow_up_test_type_id == source_request.test_type_id
                else CarRelationshipType.FOLLOW_UP
            )
            db.add(CarTestRequest(
                car_id=car.id,
                test_request_id=new_request.id,
                relationship_type=relationship,
            ))
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(f"CAR {car.car_number}: follow-up creation failed for test_type_id={followup.follow_up_test_type_id}: {exc}")


def close_car_if_verified(
    db: Session,
    *,
    testing_request: TestingRequest,
    evaluation_overall: str,
) -> Optional[CorrectiveActionRequest]:
    """
    Call this after a PASS/NORMAL evaluation to check whether it closes out
    an open CAR in this TR's lineage — e.g. a retest that finally passes.
    No-op if there's no open CAR for this lineage, or the result wasn't
    actually clean.

    Only closes on a NORMAL result of the SAME test_type as the CAR's
    ORIGINATING failure. A CAR's lineage can include several parallel
    follow-ups fanned out from one trigger (an inspection AND a retest,
    say) that all share the same parent_request_id and so all resolve to
    the same open CAR via find_open_car_for_lineage() below — closing on
    ANY of them passing would let an unrelated inspection/maintenance/
    repair ticket close out a CAR whose actual triggering problem (e.g. a
    bad insulation-resistance reading) was never re-verified. A
    non-verifying pass still gets linked into the lineage (so the CAR
    detail sheet shows it happened) but doesn't close anything.
    """
    config = _find_trigger_config(
        db,
        organization_id=testing_request.organization_id,
        equipment_type_id=testing_request.equipment_type_id,
        test_type_id=testing_request.test_type_id,
        severity=evaluation_overall,
    )
    triggers = config.car_trigger if config is not None else (evaluation_overall in DEFAULT_CAR_TRIGGER_SEVERITIES)
    if triggers:
        return None

    car = find_open_car_for_lineage(db, testing_request)
    if not car:
        return None

    originating_link = (
        db.query(CarTestRequest)
        .filter(CarTestRequest.car_id == car.id, CarTestRequest.relationship_type == CarRelationshipType.ORIGINATING)
        .first()
    )
    originating_tr = (
        db.query(TestingRequest).filter(TestingRequest.id == originating_link.test_request_id).first()
        if originating_link else None
    )
    # Missing originating data should never happen (every CAR is created
    # with this link — see process_evaluation_for_car above), but if it
    # somehow did, default to NOT closing: a CAR that stays open in error
    # is recoverable by hand from the CAR management screen; a CAR closed
    # in error hides a real unresolved problem with nothing to flag it.
    is_verifying = (
        originating_tr is not None
        and testing_request.test_type_id is not None
        and testing_request.test_type_id == originating_tr.test_type_id
    )

    already_linked = (
        db.query(CarTestRequest)
        .filter(CarTestRequest.car_id == car.id, CarTestRequest.test_request_id == testing_request.id)
        .first()
    )
    if not already_linked:
        db.add(CarTestRequest(
            car_id=car.id,
            test_request_id=testing_request.id,
            relationship_type=CarRelationshipType.VERIFICATION if is_verifying else CarRelationshipType.FOLLOW_UP,
        ))
        db.commit()

    if not is_verifying:
        return None

    car.status = CarStatus.CLOSED
    car.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(car)
    return car


# ── Status-transition helpers (for the CAR management UI, not the hook) ──────

def _fire_car_notification(db: Session, *, event_type: str, car: CorrectiveActionRequest) -> None:
    """Best-effort — never blocks the CAR action it's attached to. No-ops
    silently if the org hasn't got a NotificationTemplate for event_type
    (same graceful-no-op NotificationService.fire() already gives every
    other event in this codebase — see seed_car_notifications.py for the
    seeded defaults)."""
    try:
        from services.notification_service import NotificationService
        equipment_ueic = getattr(car.equipment, "ueic", None) if car.equipment_id else None
        NotificationService(db).fire(
            event_type=event_type,
            context={
                "car.number": car.car_number,
                "car.severity": car.severity or "",
                "car.status": car.status,
                "car.summary": car.summary or "",
                "car.due_date": car.due_date.isoformat() if car.due_date else "",
                "equipment.ueic": equipment_ueic or "",
            },
            organization_id=car.organization_id,
            department_id=car.department_id,
            source_id=car.id,
            source_type="corrective_action_request",
        )
    except Exception as exc:
        logger.warning(f"CAR {car.car_number}: {event_type} notification failed: {exc}")


def assign_car(db: Session, car: CorrectiveActionRequest, assigned_to: uuid.UUID) -> CorrectiveActionRequest:
    car.assigned_to = assigned_to
    car.status = CarStatus.ASSIGNED
    db.commit()
    db.refresh(car)
    _fire_car_notification(db, event_type="car_assigned", car=car)
    return car


def start_progress(db: Session, car: CorrectiveActionRequest) -> CorrectiveActionRequest:
    car.status = CarStatus.IN_PROGRESS
    db.commit()
    db.refresh(car)
    return car


def submit_for_verification(db: Session, car: CorrectiveActionRequest, corrective_action_text: str) -> CorrectiveActionRequest:
    car.corrective_action = corrective_action_text
    car.status = CarStatus.PENDING_VERIFICATION
    db.commit()
    db.refresh(car)
    return car


def recommend_replacement(
    db: Session,
    car: CorrectiveActionRequest,
    *,
    recommended_by: uuid.UUID,
    notes: Optional[str] = None,
) -> CorrectiveActionRequest:
    """A reviewer has decided the equipment should be replaced rather than
    keep retesting it — stops the auto-retest loop in
    _ensure_active_followup() (checked via CarStatus.REPLACEMENT_RECOMMENDED)
    without closing the CAR, since the underlying issue is still open until
    the replacement actually happens. Best-effort starts the existing repair
    workflow for this equipment (same one the "Repair / Lifecycle" request
    category kicks off) so the replacement itself is tracked; failing to
    start it (e.g. a workflow is already active) never blocks the
    recommendation from being recorded.
    """
    car.status = CarStatus.REPLACEMENT_RECOMMENDED
    if notes:
        car.corrective_action = notes
    db.commit()

    if car.equipment_id:
        try:
            from services.repair_workflow_service import RepairWorkflowService
            RepairWorkflowService(db).start_workflow(
                equipment_id=car.equipment_id,
                user_id=recommended_by,
                source_failure_id=None,
            )
        except Exception as exc:
            logger.warning(f"CAR {car.car_number}: replacement workflow not started: {exc}")

    db.refresh(car)
    return car
