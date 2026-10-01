"""
Corrective Action Request (CAR) service
=========================================
A CAR is the persistent corrective-action issue behind one or more failed
tests on one piece of equipment. It has no manual workflow: it is created,
reopened and closed only from Test Request results (and an approved
Procurement), and all work on it happens inside each linked TR's workflow.

    Result -> EvaluationService -> ALERT / CRITICAL -> process_evaluation_for_car()
        CarTriggerConfig (equipment type / test type / severity; ALERT + CRITICAL
        default) decides whether it raises a CAR, only its follow-ups, or nothing.
        Open CAR on this equipment's chain already -> the result joins it.
    Result -> NORMAL -> close_car_if_verified()

  * Every test type that failed in the chain at a CAR-triggering severity
    needs its own passing retest (unresolved_test_types); the CAR CLOSES when
    none is left. The TR that raised the CAR always counts; a NORMAL from the
    TR that first failed for a type isn't an independent retest.
  * Retests (_ensure_active_followup): held while corrective work (a
    maintenance / inspection / repair follow-up) is still expecting a result;
    otherwise one per failed type with no request of its own type in flight.
  * Procurement chosen: no retests while it awaits approval; approval CLOSES
    every open CAR on the equipment (close_cars_for_replacement).
  * Results from TRs whose workflow was genuinely cancelled / rejected (last
    audit action, not the status code) don't count.
  * A daily job (heal_idle_cars) picks up CARs nothing is moving; the CAR
    screen shows the same state (car_drive_state).
  * All decisions for one equipment run under one lock (equipment_lock_key).

Follow-up fan-out (CarTriggerConfig -> CarTriggerFollowup) mirrors the "New
Testing Request" form's multi-select pattern: a test / maintenance /
inspection follow-up becomes a TestingRequest (create_request +
submit_request), a repair_lifecycle one starts RepairWorkflowService.
"""
from __future__ import annotations

import logging
import re
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, text
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
    ProcurementRequest,
    Recommendation,
    RepairWorkflow,
    TestingRequest,
    NextActionType,
    TestingRequestStatus,
    TestResult,
    TestSession,
    TrWfAuditLog,
    TrWfInstance,
    TrWfStageInstance,
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
# /severity: every ALERT or CRITICAL result raises a CAR, on any equipment and
# test. A rule can still turn "Trigger a CAR" off for a severity, or add
# follow-up actions - with no rule, the CAR is driven by a same-type retest.
DEFAULT_CAR_TRIGGER_SEVERITIES = {"CRITICAL", "ALERT"}


@contextmanager
def car_lock(db: Session, key: str, *, wait: bool = True):
    """Postgres session-level advisory lock held on a DEDICATED connection.

    Not on the Session's own connection: the work done under this lock
    (retest creation) commits several times, and after each commit the
    Session hands its connection back to the pool and may continue on a
    different one - an unlock issued there is a silent no-op, leaving the
    lock held forever by an idle pooled connection (the next result for
    that CAR would then wait on it indefinitely). A connection of its own
    keeps lock and unlock on the same backend.

    Yields True when held. wait=False tries once and yields False if another
    process holds it (used so only one worker runs the daily idle check)."""
    conn = db.get_bind().connect()
    got = False
    try:
        if wait:
            conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": key})
            got = True
        else:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": key}).scalar())
        conn.commit()  # end the implicit transaction; the session-level lock stays held
        yield got
    finally:
        try:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
                conn.commit()
        finally:
            conn.close()


def equipment_lock_key(equipment_id, fallback_id) -> str:
    """Lock key for every CAR decision on one piece of equipment. A CAR's
    whole chain is on one equipment, so serialising per equipment covers
    everything that can conflict: two first results creating two CARs, a
    NORMAL closing a CAR while a CRITICAL attaches to it, the daily idle job
    raising a retest for a CAR a result has just closed. fallback_id (the
    TR or CAR id) for the rare request with no equipment."""
    return f"car-equipment:{equipment_id}" if equipment_id else f"car-item:{fallback_id}"


# What _find_trigger_config returns for a rule an org switched off.
_RULE_SWITCHED_OFF = SimpleNamespace(id=None, car_trigger=False, followups=[], is_active=False)


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
        )
    )

    for org_filter in ([organization_id] if organization_id else []) + [None]:
        for tt_filter in ([test_type_id] if test_type_id else []) + [None]:
            row = base.filter(
                CarTriggerConfig.organization_id == org_filter,
                CarTriggerConfig.test_type_id == tt_filter,
            ).first()
            if row is None:
                continue
            if row.is_active:
                return row
            if org_filter is not None:
                # This org switched the rule off (its own rule, or its
                # override of a global one - CAR Trigger Config's deactivate):
                # no CAR and no follow-ups here, rather than falling through
                # to the global rule / ALERT+CRITICAL default.
                return _RULE_SWITCHED_OFF
            # an inactive GLOBAL row just isn't a rule - keep looking
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


_SUMMARY_MAX_FINDINGS = 6
_SUMMARY_MAX_ACTIONS = 3


def _fmt_num(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def summary_tables(ev_result: Optional[dict]) -> list:
    """The CAR's findings as tables for the CAR screen - one per table field
    of the evaluation (e.g. "Test Results as per IS 1866:2017", "Dissolved
    Gas Analysis Results (ppm)"), each with its out-of-range readings
    (ALERT / CRITICAL: parameter, value, unit, breached limit, severity) and
    its remedial actions (deduplicated). Non-table fields that aren't NORMAL
    are grouped as "Other readings". Same source as build_car_summary, which
    stays the plain-text version (lists, notifications)."""
    tables, other = [], {"name": "Other readings", "rows": [], "actions": []}
    for f in (ev_result or {}).get("fields") or []:
        if not isinstance(f, dict):
            continue
        label = f.get("label") or f.get("key") or "Reading"
        cells = (f.get("row_results") or []) + (f.get("column_results") or [])
        if cells:
            rows, actions = [], []
            for c in cells:
                if not isinstance(c, dict) or c.get("status") not in ("ALERT", "CRITICAL"):
                    continue
                name = c.get("row_id") or c.get("row_label") or ""
                if c.get("column") and c.get("row_label"):
                    name = f"{c['row_label']} {str(c['column']).replace('_', ' ')}"
                rows.append({
                    "parameter": name or label,
                    "value": _fmt_num(c.get("value")) if c.get("value") is not None else None,
                    "unit": c.get("unit"),
                    "limit": _fmt_num(c["breach_limit"]) if c.get("breach_limit") is not None else None,
                    "status": c.get("status"),
                })
                if c.get("remedial_action_text"):
                    actions.append(c["remedial_action_text"])
            if f.get("remedial_action_text") and f.get("status") in ("ALERT", "CRITICAL"):
                actions.append(f["remedial_action_text"])
            if rows or actions:
                tables.append({"name": label, "rows": rows, "actions": list(dict.fromkeys(actions))})
        elif f.get("status") in ("ALERT", "CRITICAL"):
            other["rows"].append({
                "parameter": label,
                "value": _fmt_num(f.get("value")) if f.get("value") is not None else None,
                "unit": f.get("unit"),
                "limit": None,
                "status": f.get("status"),
            })
            if f.get("remedial_action_text"):
                other["actions"].append(f["remedial_action_text"])
    if other["rows"]:
        other["actions"] = list(dict.fromkeys(other["actions"]))
        tables.append(other)
    return tables


def build_car_summary(ev_result: Optional[dict], severity: str, request_title: str = "") -> str:
    """CAR summary from the evaluation that raised it. Never empty.

    EvaluationService.build_remedial_summary() only reads remedial text set
    on the field itself, but table templates (DGA, oil, tan delta) carry it
    per row / per cell (row_results / column_results) and number templates
    often have none at all - so on its own it returned None for most CARs.
    This lists the out-of-range readings (value, unit, breached limit) at
    the CAR's own severity - ALERT readings only when nothing is CRITICAL -
    plus any remedial text found at field, row or cell level.
    """
    fields = (ev_result or {}).get("fields") or []
    wanted = ["CRITICAL", "ALERT"] if severity == "CRITICAL" else ["ALERT"]

    def collect(status: str):
        findings, actions = [], []
        for f in fields:
            if not isinstance(f, dict):
                continue
            label = f.get("label") or f.get("key") or "Reading"
            cells = (f.get("row_results") or []) + (f.get("column_results") or [])
            if cells:
                for c in cells:
                    if not isinstance(c, dict) or c.get("status") != status:
                        continue
                    name = c.get("row_id") or c.get("row_label") or ""
                    if c.get("column") and c.get("row_label"):
                        name = f"{c['row_label']} {str(c['column']).replace('_', ' ')}"
                    text_ = f"{label} / {name}: {_fmt_num(c.get('value'))}" if name else f"{label}: {_fmt_num(c.get('value'))}"
                    if c.get("unit"):
                        text_ += f" {c['unit']}"
                    if c.get("breach_limit") is not None:
                        text_ += f" (limit {_fmt_num(c['breach_limit'])})"
                    findings.append(text_)
                    if c.get("remedial_action_text"):
                        actions.append(c["remedial_action_text"])
            elif f.get("status") == status:
                text_ = f"{label}: {_fmt_num(f.get('value'))}" if f.get("value") is not None else label
                if f.get("unit"):
                    text_ += f" {f['unit']}"
                findings.append(text_)
            if f.get("status") == status and f.get("remedial_action_text"):
                actions.append(f["remedial_action_text"])
        return findings, actions

    findings, actions = [], []
    for status in wanted:
        findings, actions = collect(status)
        if findings or actions:
            break

    request_title = (request_title or "").strip(" -")
    header = f"[AUTO-EVAL {severity}] {request_title} - " if request_title else f"[AUTO-EVAL {severity}] "
    if not findings and not actions:
        return header + f"{severity} result - see the source test result for details."

    shown = findings[:_SUMMARY_MAX_FINDINGS]
    body = "; ".join(shown)
    if len(findings) > len(shown):
        body += f"; +{len(findings) - len(shown)} more"
    unique_actions = list(dict.fromkeys(actions))  # same advice repeats per row - keep once, in order
    if unique_actions:
        body += (" | Action: " if body else "Action: ") + " ".join(unique_actions[:_SUMMARY_MAX_ACTIONS])
        if len(unique_actions) > _SUMMARY_MAX_ACTIONS:
            body += f" (+{len(unique_actions) - _SUMMARY_MAX_ACTIONS} more - see the test result)"
    return header + body


def _car_number(db: Session) -> str:
    """CAR-YYYY-NNNN, sequential within the year — mirrors the request_number
    style already used for TestingRequest (e.g. TR-KP-2026-0656)."""
    # Transaction-scoped lock: two CARs raised at the same moment would both
    # count N and both take N+1 (unique violation -> CAR lost). Released at
    # the commit that saves the CAR.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('corrective_action_requests.car_number'))"))
    year = datetime.now(timezone.utc).year
    prefix = f"CAR-{year}-"
    # Highest number used this year + 1 - not count + 1, which collides with
    # an existing number (and silently stops CARs being raised) as soon as
    # any CAR row is ever deleted.
    highest = 0
    for (number,) in db.query(CorrectiveActionRequest.car_number).filter(
        CorrectiveActionRequest.car_number.like(f"{prefix}%")
    ):
        tail = number[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:04d}"


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
                # System-raised only - a manually raised TR of the same
                # equipment+type is its own independent request, not this
                # TR's lineage, even if nobody's submitted it yet.
                TestingRequest.test_request_type != "ORIGINAL",
            )
            .all()
        )
        for (sid,) in siblings:
            if sid not in seen:
                ids.append(sid)
                seen.add(sid)

    return ids


def _trigger_tr_ids(db: Session, car_ids: list) -> dict:
    """car_id -> id of the TR whose result raised the CAR (via
    source_test_result_id). That TR - not the ORIGINATING link, which marks
    the start of the chain (design doc 6/8: TR001 ORIGINATING, TR002
    FOLLOW_UP failed -> CAR) - decides which test type verifies the CAR.
    Falls back to the ORIGINATING link if the source result is gone
    (source_test_result_id is ON DELETE SET NULL)."""
    if not car_ids:
        return {}
    ids = {
        car_id: tr_id for car_id, tr_id in (
            db.query(CorrectiveActionRequest.id, TestResult.testing_request_id)
            .join(TestResult, TestResult.id == CorrectiveActionRequest.source_test_result_id)
            .filter(CorrectiveActionRequest.id.in_(car_ids))
            .all()
        )
    }
    missing = [c for c in car_ids if c not in ids]
    if missing:
        ids.update({
            car_id: tr_id for car_id, tr_id in (
                db.query(CarTestRequest.car_id, CarTestRequest.test_request_id)
                .filter(CarTestRequest.car_id.in_(missing),
                        CarTestRequest.relationship_type == CarRelationshipType.ORIGINATING)
                .all()
            )
        })
    return ids


def trigger_request(db: Session, car: CorrectiveActionRequest) -> Optional[TestingRequest]:
    tr_id = _trigger_tr_ids(db, [car.id]).get(car.id)
    return db.query(TestingRequest).filter(TestingRequest.id == tr_id).first() if tr_id else None


def _trigger_test_type_ids(db: Session, car_ids: list) -> dict:
    """car_id -> test_type_id of the TR that raised it."""
    trigger = _trigger_tr_ids(db, car_ids)
    if not trigger:
        return {}
    tt = dict(
        db.query(TestingRequest.id, TestingRequest.test_type_id)
        .filter(TestingRequest.id.in_(list(trigger.values())))
        .all()
    )
    return {car_id: tt.get(tr_id) for car_id, tr_id in trigger.items()}


def _is_trigger(db: Session, car: CorrectiveActionRequest, testing_request: TestingRequest) -> bool:
    return _trigger_tr_ids(db, [car.id]).get(car.id) == testing_request.id


def _link_chain(db: Session, car: CorrectiveActionRequest, testing_request: TestingRequest) -> None:
    """Link the triggering TR and its parent chain into a new CAR, as in the
    design doc (6/8): the first TR of the chain is ORIGINATING, the rest carry
    their own lineage type - TR001 ORIGINATING -> TR002 FOLLOW_UP (failed,
    raised the CAR). With no parent, the triggering TR itself is ORIGINATING."""
    chain = [testing_request]
    seen = {testing_request.id}
    current = testing_request
    while current.parent_request_id and current.parent_request_id not in seen:
        parent = db.query(TestingRequest).filter(TestingRequest.id == current.parent_request_id).first()
        if not parent:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    chain.reverse()  # root first
    for i, tr in enumerate(chain):
        if i == 0:
            rel = CarRelationshipType.ORIGINATING
        elif tr.test_request_type == "RETEST":
            rel = CarRelationshipType.RETEST
        else:
            rel = CarRelationshipType.FOLLOW_UP
        db.add(CarTestRequest(car_id=car.id, test_request_id=tr.id, relationship_type=rel))


def find_open_cars_for_lineage(db: Session, testing_request: TestingRequest) -> list:
    """Every open CAR covering this TR's lineage, best match first: CARs
    whose triggering test type is this TR's test type, then newest. One
    piece of equipment can carry several CARs (e.g. one from DGA, one from
    an oil test), and a follow-up's parent chain can reach more than one."""
    lineage_ids = _lineage_test_request_ids(db, testing_request)
    if not lineage_ids:
        return []
    car_ids = [
        car_id for (car_id,) in (
            db.query(CarTestRequest.car_id)
            .join(CorrectiveActionRequest, CorrectiveActionRequest.id == CarTestRequest.car_id)
            .filter(
                CarTestRequest.test_request_id.in_(lineage_ids),
                CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
            )
            .distinct()
            .all()
        )
    ]
    if not car_ids:
        return []
    cars = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id.in_(car_ids)).all()
    originating_tt = _trigger_test_type_ids(db, car_ids)
    return sorted(
        cars,
        key=lambda c: (
            0 if testing_request.test_type_id and originating_tt.get(c.id) == testing_request.test_type_id else 1,
            -(c.created_at.timestamp() if c.created_at else 0),
        ),
    )


def find_open_car_for_lineage(db: Session, testing_request: TestingRequest) -> Optional[CorrectiveActionRequest]:
    """The open CAR this TR's result belongs to (best match - see
    find_open_cars_for_lineage), so a failed retest attaches to it instead
    of spawning a new one."""
    cars = find_open_cars_for_lineage(db, testing_request)
    return cars[0] if cars else None


def _tr_label(tr: TestingRequest) -> str:
    """Readable name for a TR in auto-generated titles - many requests have
    an empty or placeholder ("  -  ") title."""
    title = (tr.title or "").strip(" -")
    if title:
        return title
    test_type = getattr(getattr(tr, "test_type", None), "name", None)
    return test_type or tr.request_number or "request"


def unlinked_inflight_requests(db: Session, *, car: CorrectiveActionRequest, testing_request: TestingRequest) -> list:
    """In-flight TRs in this lineage (other than testing_request) that aren't
    linked to the CAR yet - typically a scheduled or manually raised test of
    the same equipment and test type. Read-only."""
    linked = {
        tr_id for (tr_id,) in db.query(CarTestRequest.test_request_id).filter(CarTestRequest.car_id == car.id).all()
    }
    lineage = set(_lineage_test_request_ids(db, testing_request)) - linked - {testing_request.id}
    if not lineage:
        return []
    return (
        db.query(TestingRequest)
        .filter(
            TestingRequest.id.in_(lineage),
            ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
            TestingRequest.status != TestingRequestStatus.draft,  # not in flight - never link a draft
            TestingRequest.is_schedule_template.isnot(True),
        )
        .all()
    )


def link_inflight_requests(db: Session, *, car: CorrectiveActionRequest, testing_request: TestingRequest) -> int:
    """Link unlinked_inflight_requests() to the CAR so its chain shows what is
    actually driving it: such a TR is what stops a duplicate retest being
    raised, and its result will update the CAR. Same test type as the
    triggering TR -> RETEST, otherwise FOLLOW_UP. Returns how many."""
    inflight = unlinked_inflight_requests(db, car=car, testing_request=testing_request)
    if not inflight:
        return 0
    originating = trigger_request(db, car)
    for tr in inflight:
        same_type = originating is not None and tr.test_type_id == originating.test_type_id
        db.add(CarTestRequest(
            car_id=car.id,
            test_request_id=tr.id,
            relationship_type=CarRelationshipType.RETEST if same_type else CarRelationshipType.FOLLOW_UP,
        ))
    db.commit()
    return len(inflight)


_PENDING_SESSION_STATUSES = ("scheduled", "in_progress")


def expecting_result_ids(db: Session, tr_ids) -> set:
    """Which of these TRs is still EXPECTING a result - i.e. still able to
    move a CAR forward. "Not closed" is not enough: a TR whose result is in
    and is only awaiting approval won't produce another result (approval
    doesn't run the CAR hook), so counting it as in progress left CARs idle
    once that approval finished. And a multi-session TR (OLTC count, DFR,
    SFRA) whose first session failed still has sessions to come, so it IS
    in progress. A TR is expecting a result when it isn't terminal and:
      - it has no evaluated result yet, or
      - it is multi-session with sessions still scheduled / in progress
        (or, with no session rows, fewer results than sessions planned).
    A result sent back for rework is not counted: the resubmission runs the
    CAR hook again."""
    tr_ids = list(tr_ids)
    if not tr_ids:
        return set()
    rows = (
        db.query(TestingRequest.id, TestingRequest.is_multi_session, TestingRequest.total_sessions_planned)
        .filter(
            TestingRequest.id.in_(tr_ids),
            ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
            # a never-submitted draft or a schedule-register template will
            # never produce a result - it must not hold back a retest
            TestingRequest.status != TestingRequestStatus.draft,
            TestingRequest.is_schedule_template.isnot(True),
        )
        .all()
    )
    if not rows:
        return set()
    open_ids = [r[0] for r in rows]
    result_counts = dict(
        db.query(TestResult.testing_request_id, func.count(TestResult.id))
        .filter(TestResult.testing_request_id.in_(open_ids), TestResult.evaluation_result.isnot(None))
        .group_by(TestResult.testing_request_id)
        .all()
    )
    multi_ids = [r[0] for r in rows if r[1]]
    with_sessions, pending_sessions = set(), set()
    if multi_ids:
        for tr_id, st in (
            db.query(TestSession.testing_request_id, TestSession.status)
            .filter(TestSession.testing_request_id.in_(multi_ids))
            .all()
        ):
            with_sessions.add(tr_id)
            if st in _PENDING_SESSION_STATUSES:
                pending_sessions.add(tr_id)

    expecting = set()
    for tr_id, is_multi, planned in rows:
        n = result_counts.get(tr_id, 0)
        if n == 0:
            expecting.add(tr_id)
        elif is_multi:
            if tr_id in pending_sessions:
                expecting.add(tr_id)
            elif tr_id not in with_sessions and planned and n < planned:
                expecting.add(tr_id)
    return expecting


def _finished_open_ids(db: Session, *, equipment_id, test_type_id) -> set:
    """Same equipment + test type TRs that are not closed but have their
    result in (awaiting approval). The duplicate guard in create_request()
    would count them as an active duplicate of a new retest/follow-up;
    they aren't one - they're what it follows up."""
    if not equipment_id or not test_type_id:
        return set()
    open_ids = [
        tr_id for (tr_id,) in (
            db.query(TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.test_type_id == test_type_id,
                ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
            )
            .all()
        )
    ]
    return set(open_ids) - expecting_result_ids(db, open_ids)


_REPLACEMENT_ACTIONS = ("procurement", "replacement")


def _chose_replacement(test_result: Optional[TestResult]) -> bool:
    """The tester picked "Procurement" (next_action = replacement) in the
    recommendation wizard - it stores that choice in the result's test_data
    (routers/testing.py resolves it the same way when it creates the
    Recommendation)."""
    td = (test_result.test_data if test_result is not None else None) or {}
    return str(td.get("next_action") or "").strip().lower() in _REPLACEMENT_ACTIONS


def replacement_pending_request(db: Session, car: CorrectiveActionRequest) -> Optional[TestingRequest]:
    """A request in this CAR's chain recommending Procurement (replacing the
    equipment) that is still waiting for approval. While one exists the CAR
    gets no retests / follow-ups - the equipment is being replaced; approval
    closes the CAR (close_cars_for_replacement), rejection returns it to
    normal handling."""
    linked = [
        tr_id for (tr_id,) in db.query(CarTestRequest.test_request_id).filter(CarTestRequest.car_id == car.id).all()
    ]
    if not linked:
        return None
    pending = (
        db.query(TestingRequest)
        .join(Recommendation, Recommendation.testing_request_id == TestingRequest.id)
        .filter(
            TestingRequest.id.in_(linked),
            Recommendation.approval_status == "pending",
            Recommendation.next_action == NextActionType.replacement,
            # the request ended (cancelled / rejected / closed) without the
            # recommendation being decided - nothing is waiting on it any more
            ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
        )
        .first()
    )
    if pending is not None:
        return pending
    # Result submitted with Procurement, Recommendation not created yet (the
    # wizard's separate submit step) - not closed, latest result says so.
    for tr in db.query(TestingRequest).filter(
        TestingRequest.id.in_(linked), ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES))
    ).all():
        latest = (
            db.query(TestResult)
            .filter(TestResult.testing_request_id == tr.id)
            .order_by(TestResult.cts.desc().nullslast())
            .first()
        )
        rec_decided = db.query(Recommendation.id).filter(
            Recommendation.testing_request_id == tr.id, Recommendation.approval_status != "pending"
        ).first()
        if latest is not None and _chose_replacement(latest) and not rec_decided:
            return tr
    return None


# corrective_action marker while an approved replacement waits for Finance:
# "REPLACEMENT APPROVED: <notes> (Procurement PR-...)". On Finance approval it
# becomes "REPLACEMENT: <notes>" as the CAR closes (close_reason replacement).
REPLACEMENT_APPROVED_PREFIX = "REPLACEMENT APPROVED: "
_PR_NUMBER_RE = re.compile(r"\(Procurement ([^)]+)\)")


def open_linked_requests(db: Session, car: CorrectiveActionRequest) -> list:
    """Linked requests not finished yet (not in a terminal status) - the CAR
    stays open while any exists (a CAR closes only when every one of its
    requests is finished)."""
    linked = [
        tr_id for (tr_id,) in db.query(CarTestRequest.test_request_id).filter(CarTestRequest.car_id == car.id).all()
    ]
    if not linked:
        return []
    return (
        db.query(TestingRequest)
        .filter(TestingRequest.id.in_(linked), ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)))
        .order_by(TestingRequest.cts)
        .all()
    )


def replacement_approval(db: Session, car: CorrectiveActionRequest) -> Optional[tuple]:
    """(pr_number, pr_status) when an approved replacement is recorded on this
    CAR (REPLACEMENT_APPROVED_PREFIX marker), else None. pr_status is the
    procurement request's status: pending_finance / approved / rejected."""
    note = car.corrective_action or ""
    if not note.startswith(REPLACEMENT_APPROVED_PREFIX):
        return None
    m = _PR_NUMBER_RE.search(note)
    if not m:
        return None
    pr_status = (
        db.query(ProcurementRequest.status)
        .filter(ProcurementRequest.procurement_number == m.group(1))
        .scalar()
    )
    return m.group(1), pr_status


def _close(db: Session, car: CorrectiveActionRequest, note: Optional[str] = None) -> None:
    car.status = CarStatus.CLOSED
    car.closed_at = datetime.now(timezone.utc)
    car.has_closed_once = True
    if note is not None:
        car.corrective_action = note


def maybe_close_car(db: Session, car: CorrectiveActionRequest) -> bool:
    """Close the CAR if it's done - the ONE place a CAR closes (caller holds
    its equipment lock). Never while any linked request is still open:
      - approved replacement (marker, procurement request approved) ->
        CLOSED straight away, reason replacement - the one exception to
        "wait for every linked request": requests a person raised are left
        to run on their own;
      - replacement awaiting CM / Finance -> stays open;
      - every failed type has a passing retest -> CLOSED, reason verified.
    Returns True when it closed. Commits."""
    if car.status not in (CarStatus.OPEN, CarStatus.REOPENED):
        return False
    repl = replacement_approval(db, car)
    if repl is not None:
        pr_number, pr_status = repl
        if pr_status == "approved":
            # The equipment is being replaced: close now. Its system retests
            # were cancelled (close_cars_for_replacement); requests a person
            # raised themselves are left to run on their own - they are no
            # reason to keep the CAR open.
            _close(db, car, "REPLACEMENT: " + car.corrective_action[len(REPLACEMENT_APPROVED_PREFIX):])
            db.commit()
            return True
        if pr_status == "pending_finance":
            return False
    if open_linked_requests(db, car):
        return False  # wait until every linked request is finished
    if replacement_pending_request(db, car) is not None:
        return False
    if unresolved_test_types(db, car):
        return False
    _close(db, car)
    db.commit()
    return True


def recheck_cars_for_request(db: Session, testing_request_id) -> None:
    """A linked request just finished (its workflow ended, Finance decided...):
    re-evaluate every open CAR it belongs to right away - close it if that was
    the last open request, otherwise raise any retests that were waiting (e.g.
    corrective work just finished). Takes each CAR's equipment lock. Best-effort."""
    tr = db.query(TestingRequest).filter(TestingRequest.id == testing_request_id).first()
    if tr is None:
        return
    cars = (
        db.query(CorrectiveActionRequest)
        .join(CarTestRequest, CarTestRequest.car_id == CorrectiveActionRequest.id)
        .filter(CarTestRequest.test_request_id == tr.id, CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES))
        .all()
    )
    for car in cars:
        try:
            with car_lock(db, equipment_lock_key(car.equipment_id, car.id)):
                db.refresh(car)
                if not maybe_close_car(db, car) and car.status in CarStatus.OPEN_STATUSES:
                    _ensure_active_followup(db, car=car, testing_request=tr, created_by=None)
        except Exception as exc:
            db.rollback()
            logger.warning(f"CAR {car.car_number}: re-check after {tr.request_number} finished failed: {exc}")


def schedule_recheck_after_commit(db: Session, testing_request_id) -> None:
    """Run recheck_cars_for_request() once the caller's transaction COMMITS
    (in its own session), so the CAR logic - which commits and locks - never
    runs inside a half-done workflow transition. A rollback drops the pending
    re-checks (nothing runs). Pending ids live on the session; the two
    listeners are attached once per session."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _Session

    db.info.setdefault("car_recheck_ids", set()).add(testing_request_id)
    if db.info.get("car_recheck_hooked"):
        return
    db.info["car_recheck_hooked"] = True
    bind = db.get_bind()

    def _after_commit(session):
        ids = session.info.pop("car_recheck_ids", set())
        for tr_id in ids:
            s2 = _Session(bind=bind)
            try:
                recheck_cars_for_request(s2, tr_id)
            except Exception as exc:
                logger.warning(f"CAR re-check for request {tr_id} failed: {exc}")
            finally:
                s2.close()

    def _after_rollback(session):
        session.info.pop("car_recheck_ids", None)

    event.listen(db, "after_commit", _after_commit)
    event.listen(db, "after_soft_rollback", lambda session, previous_transaction: _after_rollback(session))


def withdrawn_request_ids(db: Session, tr_ids) -> set:
    """TRs whose outcome was genuinely withdrawn: status rejected, or ended
    with the workflow's LAST AUDIT ACTION a cancel / reject (the same ground
    truth analytics_engine.accepted_test_result_ids uses). Their results
    don't count for a CAR - neither as a failure needing a retest nor as a
    passing one.

    Deliberately NOT the status code: when a terminal transition has no
    status configured, tr_workflow_routing_service falls back to the
    workflow's last status by sequence, which in the seeded workflow is
    "wf_cancelled" - so normally completed requests carry wf_cancelled."""
    tr_ids = list(tr_ids)
    if not tr_ids:
        return set()
    ended = {
        tr_id: status for tr_id, status in (
            db.query(TestingRequest.id, TestingRequest.status)
            .filter(TestingRequest.id.in_(tr_ids), TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)))
            .all()
        )
    }
    out = {tr_id for tr_id, st in ended.items() if st == TestingRequestStatus.rejected}
    rest = [tr_id for tr_id in ended if tr_id not in out]
    if rest:
        last_action = (
            db.query(TrWfAuditLog.action_code)
            .filter(TrWfAuditLog.wf_instance_id == TrWfInstance.id)
            .order_by(TrWfAuditLog.created_at.desc(), TrWfAuditLog.is_terminal.desc().nullslast())
            .limit(1)
            .correlate(TrWfInstance)
            .scalar_subquery()
        )
        for tr_id, code in (
            db.query(TrWfInstance.testing_request_id, last_action)
            .filter(TrWfInstance.testing_request_id.in_(rest))
            .all()
        ):
            if code and ("cancel" in code.lower() or "reject" in code.lower()):
                out.add(tr_id)
    return out


def unresolved_test_types(db: Session, car: CorrectiveActionRequest) -> list:
    """Test types that failed in this CAR's chain and don't have a passing
    retest yet - the CAR closes only when this is empty ("retest every
    failed type": an oil-test CAR whose tan-delta follow-up also failed needs
    a passing tan-delta retest too, not just a passing oil test).

    A type only enters the set by failing at a severity that TRIGGERS a CAR
    for it (CarTriggerConfig for that equipment type / test type / severity,
    ALERT + CRITICAL by default) - e.g. an ALERT that started the chain under a
    "follow-ups only, no CAR" rule doesn't demand its own retest. The TR that
    raised the CAR always counts. Once in, only a NORMAL clears it: a later
    ALERT (or CRITICAL) keeps it unresolved.

    Results from genuinely cancelled / rejected TRs (withdrawn_request_ids)
    are ignored, except the TR that raised the CAR.

    Per test type, over the linked TRs' evaluated results in time order:
    unresolved when the latest result isn't NORMAL, or when the latest
    NORMAL came from the same TR that first failed for that type (a
    corrected entry / later session isn't an independent retest). Returns
    [{"test_type_id", "failing": TR to retest from}], the trigger's type first.
    """
    linked = [
        tr_id for (tr_id,) in db.query(CarTestRequest.test_request_id).filter(CarTestRequest.car_id == car.id).all()
    ]
    if not linked:
        return []
    rows = (
        db.query(TestingRequest, TestResult)
        .join(TestResult, TestResult.testing_request_id == TestingRequest.id)
        .filter(TestingRequest.id.in_(linked), TestResult.evaluation_result.isnot(None))
        .all()
    )
    trig = trigger_request(db, car)
    # Genuinely cancelled / rejected requests don't count - except the one
    # that raised the CAR (the CAR stays until voided; the screen flags it).
    withdrawn = withdrawn_request_ids(db, linked) - ({trig.id} if trig is not None else set())
    by_type: dict = {}
    for tr, res in rows:
        if tr.test_type_id is None or tr.id in withdrawn:
            continue
        at = res.tested_at or res.cts
        overall = (res.evaluation_result or {}).get("overall") if isinstance(res.evaluation_result, dict) else None
        by_type.setdefault(tr.test_type_id, []).append((at.timestamp() if at else 0, tr, overall))

    triggers_cache: dict = {}

    def _triggers(tr: TestingRequest, overall: str) -> bool:
        if trig is not None and tr.id == trig.id:
            return True  # raised the CAR
        key = (tr.organization_id, tr.equipment_type_id, tr.test_type_id, overall)
        if key not in triggers_cache:
            cfg = _find_trigger_config(
                db,
                organization_id=tr.organization_id,
                equipment_type_id=tr.equipment_type_id,
                test_type_id=tr.test_type_id,
                severity=overall,
            )
            triggers_cache[key] = cfg.car_trigger if cfg is not None else overall in DEFAULT_CAR_TRIGGER_SEVERITIES
        return triggers_cache[key]

    out = []
    for tt, events in by_type.items():
        events.sort(key=lambda e: e[0])
        failures = [e for e in events if e[2] in ("ALERT", "CRITICAL") and _triggers(e[1], e[2])]
        if not failures:
            continue  # never failed - not part of the corrective action
        origin = trig if (trig is not None and trig.test_type_id == tt) else failures[0][1]
        latest_at, latest_tr, latest_overall = events[-1]
        resolved = latest_overall == "NORMAL" and latest_tr.id != origin.id
        if not resolved:
            out.append({"test_type_id": tt, "failing": failures[-1][1]})
    out.sort(key=lambda u: 0 if trig is not None and u["test_type_id"] == trig.test_type_id else 1)
    return out


_CORRECTIVE_CATEGORIES = ("maintenance", "inspection", "repair_lifecycle")
# repair_workflows types that are corrective work on the equipment (a repair
# follow-up starts BREAKDOWN) - not "surveillance" / "CALIBRATION"
_CORRECTIVE_WORKFLOW_TYPES = ("BREAKDOWN", "OVERHAUL")


def _corrective_work_pending(
    db: Session, car: CorrectiveActionRequest, failed_type_ids: Optional[set] = None
) -> Optional[str]:
    """Corrective work still under way - retests wait for it, so they verify
    the fix rather than the unfixed condition. Returns what it is (a request
    number, or "repair workflow"), None when nothing is:
      - a linked maintenance / inspection / repair follow-up request still
        expecting a result, or
      - an ACTIVE BREAKDOWN / OVERHAUL repair workflow on the CAR's
        equipment (not surveillance / calibration) - a repair follow-up
        starts one (RepairWorkflowService) without any linked request, so it
        would otherwise not hold retests back at all."""
    linked = [
        tr_id for (tr_id,) in db.query(CarTestRequest.test_request_id).filter(CarTestRequest.car_id == car.id).all()
    ]
    if linked:
        # A request of one of the CAR's own failed test types is a retest,
        # not corrective work - even when that test is filed under a
        # corrective category (e.g. OLTC operations count = maintenance).
        failed = failed_type_ids if failed_type_ids is not None else {
            u["test_type_id"] for u in unresolved_test_types(db, car)
        }
        work = [
            tr for tr in db.query(TestingRequest).filter(TestingRequest.id.in_(linked)).all()
            if tr.request_category is not None and tr.request_category.value in _CORRECTIVE_CATEGORIES
            and tr.test_type_id not in failed
        ]
        expecting = expecting_result_ids(db, [t.id for t in work])
        pending = next((t for t in work if t.id in expecting), None)
        if pending is not None:
            return pending.request_number
    if car.equipment_id:
        repair = (
            db.query(RepairWorkflow.workflow_number, RepairWorkflow.workflow_type)
            .filter(
                RepairWorkflow.equipment_id == car.equipment_id,
                RepairWorkflow.status == "active",
                # corrective work only - the same table also carries routine
                # surveillance programmes and calibrations, which must not
                # hold a CAR's retests
                func.upper(func.coalesce(RepairWorkflow.workflow_type, RepairWorkflow.workflow_code))
                .in_(_CORRECTIVE_WORKFLOW_TYPES),
            )
            .first()
        )
        if repair:
            return f"{(repair[1] or 'repair').lower()} workflow {repair[0]}"
    return None


def _type_in_flight(db: Session, car: CorrectiveActionRequest, base: TestingRequest) -> bool:
    """Is a request of base's test type (a retest already raised, a scheduled
    test, a multi-session request with sessions left) still expecting a
    result - linked to the CAR, on base's lineage (same equipment + type,
    system-raised), or a manually raised TR of the same equipment + type
    that's simply never been linked? A manual TR isn't pulled into the CAR's
    lineage (it's independent, not the CAR's), but its result would still
    cover this type, so raising a retest in parallel would just duplicate
    it - hold back until it resolves."""
    candidates = set(_lineage_test_request_ids(db, base))
    candidates.update(
        tr_id for (tr_id,) in (
            db.query(CarTestRequest.test_request_id)
            .join(TestingRequest, TestingRequest.id == CarTestRequest.test_request_id)
            .filter(CarTestRequest.car_id == car.id, TestingRequest.test_type_id == base.test_type_id)
            .all()
        )
    )
    if bool(expecting_result_ids(db, candidates)):
        return True
    if not base.equipment_id or not base.test_type_id:
        return False
    manual_ids = [
        tr_id for (tr_id,) in (
            db.query(TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == base.equipment_id,
                TestingRequest.test_type_id == base.test_type_id,
                TestingRequest.id != base.id,
                ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
                TestingRequest.status != TestingRequestStatus.draft,
                TestingRequest.is_schedule_template.isnot(True),
            )
            .all()
        )
    ]
    return bool(expecting_result_ids(db, manual_ids))


def in_flight_request_number(db: Session, car: CorrectiveActionRequest, base: TestingRequest) -> Optional[str]:
    """Request number of a request of base's test type still expecting a
    result (the one _type_in_flight finds - including an unlinked manual TR
    covering it), for the CAR screen - None when that type is waiting for a
    retest to be raised."""
    candidates = set(_lineage_test_request_ids(db, base))
    candidates.update(
        tr_id for (tr_id,) in (
            db.query(CarTestRequest.test_request_id)
            .join(TestingRequest, TestingRequest.id == CarTestRequest.test_request_id)
            .filter(CarTestRequest.car_id == car.id, TestingRequest.test_type_id == base.test_type_id)
            .all()
        )
    )
    if base.equipment_id and base.test_type_id:
        candidates.update(
            tr_id for (tr_id,) in (
                db.query(TestingRequest.id)
                .filter(
                    TestingRequest.equipment_id == base.equipment_id,
                    TestingRequest.test_type_id == base.test_type_id,
                    TestingRequest.id != base.id,
                    ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
                    TestingRequest.status != TestingRequestStatus.draft,
                    TestingRequest.is_schedule_template.isnot(True),
                )
                .all()
            )
        )
    expecting = expecting_result_ids(db, candidates)
    if not expecting:
        return None
    return (
        db.query(TestingRequest.request_number)
        .filter(TestingRequest.id.in_(list(expecting)))
        .order_by(TestingRequest.cts.desc())
        .limit(1)
        .scalar()
    )


def _ensure_active_followup(
    db: Session,
    *,
    car: CorrectiveActionRequest,
    testing_request: TestingRequest,
    created_by: Optional[uuid.UUID],
) -> None:
    """Called whenever a TR in an open CAR's chain has just produced a result
    that doesn't close it (a new CAR, a failed retest / follow-up, a pass that
    leaves another failed type open) and by the daily idle check.

    Every test type that failed in the chain needs a passing retest before
    the CAR can close (unresolved_test_types). All retests are held while
    CORRECTIVE WORK (a maintenance / inspection / repair follow-up) is still
    expecting a result, so they verify the fix. Otherwise each failed type
    gets its own retest unless a request of that type is already in flight -
    one type's running retest doesn't hold back another's (the full
    CarTriggerConfig fan-out only runs once, at CAR creation). Each retest's
    parent is the latest failing TR of its type.

    "In flight" means still expecting a result (expecting_result_ids): TRs
    whose result is in don't hold retests back even while under review -
    unless multi-session with sessions left, in which case those sessions
    are the retest.
    """
    if car.status == CarStatus.REPLACEMENT_RECOMMENDED:
        return  # legacy: retests stopped for a recommended replacement
    if replacement_pending_request(db, car) is not None:
        return  # equipment replacement recommended, awaiting approval - no retest
    repl = replacement_approval(db, car)
    if repl is not None and repl[1] in ("pending_finance", "approved"):
        return  # replacement approved - awaiting / done by Finance, nothing to retest

    unresolved = unresolved_test_types(db, car)
    if not unresolved:
        return
    bases = [u["failing"] for u in unresolved]

    # Link in-flight requests of the reporting TR's type and of every failed
    # type (e.g. a scheduled oil test) - they are already driving the CAR.
    link_inflight_requests(db, car=car, testing_request=testing_request)
    for base in bases:
        if base.id != testing_request.id:
            link_inflight_requests(db, car=car, testing_request=base)
    if _corrective_work_pending(db, car, {u["test_type_id"] for u in unresolved}) is not None:
        return  # corrective work still running - retests come after it

    from services.testing_request_service import TestingRequestService

    originator_id = created_by or testing_request.originator_id
    due_days = CAR_DUE_DAYS_CRITICAL if car.severity == "CRITICAL" else CAR_DUE_DAYS_ALERT
    tr_service = TestingRequestService(db)
    for base in bases:
        if not base.equipment_id or not base.test_type_id:
            continue  # not enough to raise a retest against
        if _type_in_flight(db, car, base):
            continue  # this type already has a request expecting a result
        stopped = _type_stopped_by_person(db, car, base.test_type_id)
        if stopped is not None:
            logger.info(
                f"CAR {car.car_number}: not re-raising {_tr_label(base)} - "
                f"{stopped.request_number} was ended without a result by a person"
            )
            continue
        try:
            new_request = tr_service.create_request(
                {
                    "title": f"{car.car_number} retest: {_tr_label(base)}",
                    "due_date": datetime.now(timezone.utc) + timedelta(days=due_days),
                    "equipment_id": base.equipment_id,
                    "equipment_type_id": base.equipment_type_id,
                    "test_type_id": base.test_type_id,
                    "request_category": base.request_category.value
                        if base.request_category else "test",
                    "organization_id": base.organization_id,
                    "department_id": base.department_id,
                    "priority": "high",
                    "notes": f"Auto-created retest - {car.car_number} is still open: "
                             f"{base.request_number} failed and has no passing retest yet",
                },
                originator_id=originator_id,
                # results already in (possibly still in review) - they are
                # what this retest follows up, not duplicates of it
                duplicate_check_ignore_ids={testing_request.id, base.id}
                | _finished_open_ids(db, equipment_id=base.equipment_id, test_type_id=base.test_type_id),
            )
            new_request.parent_request_id = base.id
            new_request.test_request_type = "RETEST"
            db.commit()

            if not _submit_or_withdraw(db, tr_service, new_request, originator_id, car.car_number):
                continue

            db.add(CarTestRequest(
                car_id=car.id,
                test_request_id=new_request.id,
                relationship_type=CarRelationshipType.RETEST,
            ))
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(f"CAR {car.car_number}: auto-retest creation failed for {base.request_number}: {exc}")


def _submit_or_withdraw(db: Session, tr_service, new_request: TestingRequest, originator_id, label: str) -> bool:
    """Submit an auto-created retest / follow-up into its workflow. If that
    fails, the just-created request is closed as cancelled (with a note)
    instead of being left as an unlinked draft that nobody can action and
    that would hold the CAR - True when submitted."""
    try:
        tr_service.submit_request(new_request.id, modified_by=originator_id)
        return True
    except Exception as exc:
        db.rollback()
        tr = db.query(TestingRequest).filter(TestingRequest.id == new_request.id).first()
        if tr is not None:
            tr.status = TestingRequestStatus.closed
            tr.current_status_code = "wf_cancelled"
            tr.notes = f"{tr.notes or ''}\n[CAR] Not submitted ({exc}); withdrawn automatically.".strip()
            db.commit()
        logger.warning(f"{label}: {new_request.request_number} could not be submitted, withdrawn: {exc}")
        return False


def _latest_reported_request(db: Session, car: CorrectiveActionRequest) -> Optional[TestingRequest]:
    """The most recent TR in the CAR's chain that has an evaluated result -
    the parent for a retest raised by heal_idle_cars(), so the lineage
    continues from the last actual result."""
    return (
        db.query(TestingRequest)
        .join(CarTestRequest, CarTestRequest.test_request_id == TestingRequest.id)
        .join(TestResult, TestResult.testing_request_id == TestingRequest.id)
        .filter(CarTestRequest.car_id == car.id, TestResult.evaluation_result.isnot(None))
        .order_by(TestResult.tested_at.desc().nullslast(), TestResult.cts.desc().nullslast())
        .first()
    )


def heal_idle_cars(db: Session, *, apply: bool, exclude: Optional[set] = None) -> list:
    """Find open CARs with nothing in their chain still expecting a result -
    e.g. the only pending retest was rejected / cancelled in its workflow,
    which closes it with no result, so the result-driven hook never runs
    again for that CAR - and put them back in motion: link any in-flight
    same-equipment/test request, else raise one retest of the trigger test
    type (the same thing the live hook does after a result).

    Does NOT re-raise when the CAR's most recent system-raised request
    (retest / follow-up) was rejected or cancelled without a result and
    nothing has reported since: that is a person's decision (equipment
    replaced, test not possible...) and the job must not overrule it every
    night - the CAR is reported as "attention" (void it, or raise a request
    by hand).

    Returns one dict per CAR: {car_number, action: link|retest|attention|
    ok|skip|failed, detail}. apply=False only reports. Used by the daily job
    in main.py and by alter_raise_retests_for_idle_cars.py. Each CAR is
    handled under the same equipment lock as the live hook."""
    excluded = {c.upper() for c in (exclude or ())}
    report = []
    cars = (
        db.query(CorrectiveActionRequest)
        .filter(CorrectiveActionRequest.status.in_([CarStatus.OPEN, CarStatus.REOPENED]))
        .order_by(CorrectiveActionRequest.car_number)
        .all()
    )
    for car in cars:
        entry = {"car_number": car.car_number, "action": "ok", "detail": ""}
        report.append(entry)
        with car_lock(db, equipment_lock_key(car.equipment_id, car.id)):
            # Listed before the lock - a result may have closed / voided it
            # since. Reload and skip unless it is still open.
            db.refresh(car)
            if car.status not in (CarStatus.OPEN, CarStatus.REOPENED):
                entry.update(action="skip", detail=f"{car.status} meanwhile")
                continue
            try:
                _heal_one(db, car, entry, apply=apply, excluded=excluded)
            except Exception as exc:
                # one bad CAR must not stop the check for every CAR after it
                db.rollback()
                entry.update(action="failed", detail=f"error: {exc}")
                logger.exception(f"CAR {car.car_number}: idle check failed")
    return report


def _type_stopped_by_person(db: Session, car: CorrectiveActionRequest, test_type_id) -> Optional[TestingRequest]:
    """For ONE failed test type: its most recently linked system-raised
    request (test_request_type RETEST / FOLLOW_UP) if that ended (rejected,
    cancelled, closed) without a result and no result of this type has come
    in since it was linked. That is a person's decision (equipment replaced,
    test not possible...) - neither the nightly job nor the live hook raises
    this type's retest again; the CAR asks for attention (void it, or raise
    a request by hand). Other failed types carry on normally."""
    row = (
        db.query(TestingRequest, CarTestRequest.created_at)
        .join(CarTestRequest, CarTestRequest.test_request_id == TestingRequest.id)
        .filter(
            CarTestRequest.car_id == car.id,
            TestingRequest.test_type_id == test_type_id,
            TestingRequest.test_request_type.in_(["RETEST", "FOLLOW_UP"]),
        )
        .order_by(CarTestRequest.created_at.desc())
        .first()
    )
    if not row:
        return None
    tr, linked_at = row
    if tr.status not in _TERMINAL_TR_STATUSES:
        return None
    if db.query(TestResult.id).filter(
        TestResult.testing_request_id == tr.id, TestResult.evaluation_result.isnot(None)
    ).first():
        return None  # it did report
    last_action = (
        db.query(TrWfAuditLog.action_code)
        .filter(TrWfAuditLog.testing_request_id == tr.id)
        .order_by(TrWfAuditLog.created_at.desc())
        .limit(1)
        .scalar()
    )
    if last_action == CAR_CANCEL_ACTION:
        return None  # cancelled by the CAR logic itself (void / replacement), not a person
    latest_of_type = (
        db.query(func.max(func.coalesce(TestResult.tested_at, TestResult.cts)))
        .join(CarTestRequest, CarTestRequest.test_request_id == TestResult.testing_request_id)
        .join(TestingRequest, TestingRequest.id == TestResult.testing_request_id)
        .filter(
            CarTestRequest.car_id == car.id,
            TestingRequest.test_type_id == test_type_id,
            TestResult.evaluation_result.isnot(None),
        )
        .scalar()
    )
    if latest_of_type and linked_at and latest_of_type > linked_at:
        return None  # a result of this type came in after it - not the last word
    return tr


def classify_pending_types(db: Session, car: CorrectiveActionRequest, unresolved: list) -> list:
    """Each unresolved failed type with its status:
       in_flight  - request number of a request of that type expecting a result
       stopped    - the system retest a person ended without a result (see
                    _type_stopped_by_person) - not re-raised automatically
       neither    - needs a retest raised (by the live hook / nightly job)"""
    out = []
    for u in unresolved:
        base = u["failing"]
        in_flight = in_flight_request_number(db, car, base)
        stopped = None if in_flight else _type_stopped_by_person(db, car, u["test_type_id"])
        out.append({**u, "in_flight": in_flight, "stopped": stopped})
    return out


def car_drive_state(db: Session, car: CorrectiveActionRequest) -> dict:
    """What is moving this CAR forward right now. The single answer used by
    the daily idle check (heal_idle_cars) AND shown on the CAR screen
    (routers/car.py), so the screen can never contradict what the job does.

    state:
      replacement_pending  a request recommends Procurement (replace the
                   equipment), awaiting approval - no retests; approval closes it
      in_progress  corrective work (incl. an active repair workflow) is under
                   way, or every failed type is in flight / stopped by a person
      attention    every remaining failed type's last system retest was ended
                   by a person without a result - not re-raised; void the CAR
                   or raise a request
      idle         some failed type has nothing in flight - the job raises
                   its retest
      resolved     every failed type has a passing retest (or Finance approved
                   the replacement) and every linked request is finished - the
                   job closes it
      finishing    the same, but a linked request is still open - closes
                   when it finishes
      replacement_finance  replacement approved by CM, procurement request
                   waiting for Finance - no retests; Finance approval closes it
      replacement  (legacy) REPLACEMENT_RECOMMENDED - retests stopped
      no_trigger   trigger request missing / has no equipment or test type
      None         CLOSED / VOIDED
    Also: trigger, latest (latest request with a result, else the trigger),
    unlinked (in-flight requests not linked yet), stopped, replacement, and
    pending_types - the failed test types still needing a passing retest."""
    out = {"state": None, "trigger": None, "latest": None, "unlinked": [], "stopped": None,
           "replacement": None, "pending_types": [], "trigger_withdrawn": False, "corrective_work": None,
           "open_requests": [], "replacement_pr": None}
    if car.status == CarStatus.REPLACEMENT_RECOMMENDED:
        out["state"] = "replacement"
        return out
    if car.status not in (CarStatus.OPEN, CarStatus.REOPENED):
        return out
    trig = trigger_request(db, car)
    out["trigger"] = trig
    if trig is None or not trig.equipment_id or not trig.test_type_id:
        out["state"] = "no_trigger"
        return out
    latest = _latest_reported_request(db, car) or trig
    out["latest"] = latest

    pending_repl = replacement_pending_request(db, car)
    if pending_repl is not None:
        out.update(state="replacement_pending", replacement=pending_repl)
        return out
    open_reqs = open_linked_requests(db, car)
    out["open_requests"] = open_reqs
    repl = replacement_approval(db, car)
    if repl is not None and repl[1] in ("pending_finance", "approved"):
        out["replacement_pr"] = repl[0]
        out["state"] = "replacement_finance" if repl[1] == "pending_finance" else (
            "finishing" if open_reqs else "resolved"
        )
        return out

    unresolved = unresolved_test_types(db, car)
    out["pending_types"] = unresolved
    bases = [latest] + [u["failing"] for u in unresolved if u["failing"].id != latest.id]

    unlinked: dict = {}
    for base in bases:
        unlinked.update({t.id: t for t in unlinked_inflight_requests(db, car=car, testing_request=base)})
    out["unlinked"] = list(unlinked.values())

    out["trigger_withdrawn"] = trig.id in withdrawn_request_ids(db, [trig.id])
    if not unresolved:
        # every failed type passed - closes once the linked requests finish
        out["state"] = "finishing" if open_reqs else "resolved"
        return out
    # Same rules as _ensure_active_followup, per failed type.
    classified = classify_pending_types(db, car, unresolved)
    out["pending_types"] = classified
    out["corrective_work"] = _corrective_work_pending(db, car, {u["test_type_id"] for u in unresolved})
    if out["corrective_work"] is not None:
        out["state"] = "in_progress"  # retests wait for the fix
        return out
    if any(not c["in_flight"] and c["stopped"] is None for c in classified):
        out["state"] = "idle"  # some type needs its retest raised
    elif any(c["in_flight"] for c in classified):
        out["state"] = "in_progress"  # the rest are in flight (a stopped one is shown per type)
    else:
        first = next(c["stopped"] for c in classified if c["stopped"] is not None)
        out.update(state="attention", stopped=first)  # every remaining type was stopped by a person
    return out


def reopen_closed_with_unresolved(db: Session, *, apply: bool) -> list:
    """CARs CLOSED by a passing retest of their trigger test while another
    test type that failed in the chain still has no passing retest - closed
    under the old "trigger test only" rule, before every failed type had to
    pass. Reopens them (REOPENED) so heal_idle_cars raises the missing
    retests. CARs closed by an approved replacement, and VOIDED ones, are
    left alone. Returns [{car_number, pending: [test type names]}]."""
    found = []
    for car in (
        db.query(CorrectiveActionRequest)
        .filter(CorrectiveActionRequest.status == CarStatus.CLOSED)
        .order_by(CorrectiveActionRequest.car_number)
        .all()
    ):
        if (car.corrective_action or "").startswith("REPLACEMENT: "):
            continue
        unresolved = unresolved_test_types(db, car)
        if not unresolved:
            continue
        found.append({
            "car_number": car.car_number,
            "pending": [getattr(getattr(u["failing"], "test_type", None), "name", None) or str(u["test_type_id"])
                        for u in unresolved],
        })
        if apply:
            with car_lock(db, equipment_lock_key(car.equipment_id, car.id)):
                db.refresh(car)
                if car.status == CarStatus.CLOSED:
                    car.status = CarStatus.REOPENED
                    car.closed_at = None
                    db.commit()
    return found


def _heal_one(db: Session, car: CorrectiveActionRequest, entry: dict, *, apply: bool, excluded: set) -> None:
    """One CAR of heal_idle_cars(); caller holds its equipment lock. Acts on
    car_drive_state() - the same state the CAR screen shows."""
    if car.car_number.upper() in excluded:
        entry.update(action="skip", detail="excluded")
        return
    st = car_drive_state(db, car)
    trig, latest = st["trigger"], st["latest"]
    if st["state"] == "no_trigger":
        entry.update(action="skip", detail="trigger request missing / has no equipment or test type")
        return
    if st["state"] in (None, "replacement"):
        entry.update(action="skip", detail=f"{car.status}")
        return
    if st["state"] == "replacement_pending":
        entry.update(detail=f"replacement recommended on {st['replacement'].request_number} - awaiting approval")
        return
    if st["state"] == "resolved":
        entry.update(action="close", detail="done - every linked request finished")
        if apply and not maybe_close_car(db, car):
            entry.update(action="ok", detail="not closable yet")
        return
    if st["state"] in ("finishing", "replacement_finance"):
        waiting = ", ".join(t.request_number for t in st["open_requests"]) or "-"
        entry.update(detail=(
            f"replacement {st['replacement_pr']} waiting for Finance" if st["state"] == "replacement_finance"
            else f"closes when these finish: {waiting}"
        ))
        return

    if st["unlinked"]:
        entry.update(action="link", detail=", ".join(
            f"{t.request_number} ({t.status.value if t.status else '?'})" for t in st["unlinked"]
        ))
        if apply:
            link_inflight_requests(db, car=car, testing_request=latest)
            if trig.id != latest.id:
                link_inflight_requests(db, car=car, testing_request=trig)

    if st["state"] == "in_progress":
        if entry["action"] == "ok":
            entry["detail"] = "a request in the chain is still expecting a result"
        return
    if st["state"] == "attention":
        stopped = st["stopped"]
        entry.update(action="attention", detail=(
            f"last system-raised request {stopped.request_number} was "
            f"{stopped.status.value if stopped.status else 'closed'} without a result - "
            f"not re-raised; void the CAR or raise a request manually"
        ))
        return

    # idle: one retest per failed type that has nothing of its own in flight
    names = [getattr(getattr(u["failing"], "test_type", None), "name", None) or f"test_type_id={u['test_type_id']}"
             for u in st["pending_types"] if not u.get("in_flight") and u.get("stopped") is None]
    entry.update(action="retest", detail=", ".join(names))
    if apply:
        before = db.query(CarTestRequest.id).filter(CarTestRequest.car_id == car.id).count()
        _ensure_active_followup(db, car=car, testing_request=latest, created_by=None)
        if db.query(CarTestRequest.id).filter(CarTestRequest.car_id == car.id).count() == before:
            entry.update(action="failed", detail=entry["detail"] + " - not raised, see log")


def process_evaluation_for_car(
    db: Session,
    *,
    test_result: TestResult,
    testing_request: TestingRequest,
    evaluation_overall: str,
    summary: Optional[str],
    created_by: Optional[uuid.UUID] = None,
) -> Optional[CorrectiveActionRequest]:
    """Entry point from testing_service.py. The whole decision - is there an
    open CAR, create / attach, follow-ups, retest - runs under the equipment
    lock, so two results on the same equipment at the same moment can't both
    create a CAR, and the open-CAR lookup is always current (done after the
    lock, not before it)."""
    with car_lock(db, equipment_lock_key(testing_request.equipment_id, testing_request.id)):
        return _process_evaluation_for_car(
            db,
            test_result=test_result,
            testing_request=testing_request,
            evaluation_overall=evaluation_overall,
            summary=summary,
            created_by=created_by,
        )


def _process_evaluation_for_car(
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
      and its parent chain (root = ORIGINATING, see _link_chain), and fan out
      any configured follow-up actions.
    - An open CAR already exists for this lineage -> link this TR to it as
      RETEST instead of creating a duplicate CAR (design doc section 6).
      This applies to any non-NORMAL result, including an ALERT whose rule
      doesn't trigger a new CAR: the retest still didn't come back clean, so
      the CAR stays open and keeps a retest in flight.
    """
    config = _find_trigger_config(
        db,
        organization_id=testing_request.organization_id,
        equipment_type_id=testing_request.equipment_type_id,
        test_type_id=testing_request.test_type_id,
        severity=evaluation_overall,
    )

    if config is not None:
        triggers = config.car_trigger
    else:
        triggers = evaluation_overall in DEFAULT_CAR_TRIGGER_SEVERITIES

    # Tester recommended Procurement (replace the equipment): the result is
    # still recorded on the CAR, but no retest / follow-ups are raised for
    # equipment that is being replaced. Approval of the recommendation closes
    # the CAR (close_cars_for_replacement); rejection returns it to normal.
    replacement = _chose_replacement(test_result)

    existing_car = find_open_car_for_lineage(db, testing_request)
    if not triggers and not existing_car:
        # "Trigger a CAR" is off for this severity, but the rule may still
        # schedule follow-up actions (e.g. ALERT -> a follow-up oil test in
        # 30 days) - raise them as plain TRs, no CAR (design doc 5 and 8).
        if not replacement and config is not None and any(f.is_active for f in config.followups):
            _create_followups(db, car=None, config=config, source_request=testing_request, created_by=created_by)
        return None

    if existing_car:
        # Caller holds the equipment lock (process_evaluation_for_car).
        db.refresh(existing_car)
        already_linked = (
            db.query(CarTestRequest)
            .filter(
                CarTestRequest.car_id == existing_car.id,
                CarTestRequest.test_request_id == testing_request.id,
            )
            .first()
        )
        # Only the link itself is conditional. Retests/follow-ups raised by
        # this service are linked the moment they're created, so their
        # own failing result arrives already linked - the reopen + next
        # retest below must still run for them. Both are idempotent: a
        # re-saved result finds its earlier retest in flight and no-ops.
        if not already_linked:
            trigger_tt = _trigger_test_type_ids(db, [existing_car.id]).get(existing_car.id)
            db.add(CarTestRequest(
                car_id=existing_car.id,
                test_request_id=testing_request.id,
                relationship_type=CarRelationshipType.RETEST
                if testing_request.test_type_id == trigger_tt else CarRelationshipType.FOLLOW_UP,
            ))
            db.flush()  # the reopen check below reads the chain including this TR
        # A later TR in the chain (retest / follow-up) came back non-NORMAL
        # again, at a severity that needs a retest -> REOPENED. The
        # triggering TR re-saving its own result isn't a new failure.
        if (
            existing_car.status == CarStatus.OPEN
            and not _is_trigger(db, existing_car, testing_request)
            and testing_request.test_type_id in {
                u["test_type_id"] for u in unresolved_test_types(db, existing_car)
            }
        ):
            # only a failure that needs a retest (triggering severity, or a
            # type already failed) reopens it
            existing_car.status = CarStatus.REOPENED
        # Escalation: a CAR raised on ALERT whose chain has now come back
        # CRITICAL is handled as a CRITICAL one from here on - CRITICAL
        # severity, the CRITICAL due date (never later than it already is),
        # and the CRITICAL rule's follow-up actions (below).
        escalated = (
            evaluation_overall == "CRITICAL"
            and (existing_car.severity or "").upper() == "ALERT"
            and triggers
        )
        if escalated:
            existing_car.severity = "CRITICAL"
            critical_due = (datetime.now(timezone.utc) + timedelta(days=CAR_DUE_DAYS_CRITICAL)).date()
            if existing_car.due_date is None or existing_car.due_date > critical_due:
                existing_car.due_date = critical_due
            logger.info(
                f"CAR {existing_car.car_number}: escalated ALERT -> CRITICAL by "
                f"{testing_request.request_number or testing_request.id}"
            )
        db.commit()
        if escalated:
            _fire_car_notification(db, event_type="car_escalated", car=existing_car)
            # the CRITICAL rule's follow-ups (e.g. oil + tan delta in 1 day);
            # _create_followups reuses a request of that type already in
            # flight, so nothing is duplicated. Not while replacing the
            # equipment.
            if not replacement and config is not None and any(f.is_active for f in config.followups):
                _create_followups(
                    db, car=existing_car, config=config, source_request=testing_request, created_by=created_by
                )

        # This CAR just got another non-NORMAL result (CRITICAL, or an
        # ALERT - triggering or not). Keep exactly one active TR driving it
        # forward - unless this result (or another in the chain) recommends
        # replacing the equipment, which stops retests until it's decided.
        if not replacement:
            _ensure_active_followup(db, car=existing_car, testing_request=testing_request, created_by=created_by)

        return existing_car

    due_days = CAR_DUE_DAYS_CRITICAL if evaluation_overall == "CRITICAL" else CAR_DUE_DAYS_ALERT
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

    _link_chain(db, car, testing_request)
    db.commit()
    db.refresh(car)
    _fire_car_notification(db, event_type="car_created", car=car)

    if replacement:
        return car  # Procurement recommended - no follow-ups / retest; approval closes it

    if config is not None and config.followups:
        _create_followups(db, car=car, config=config, source_request=testing_request, created_by=created_by)

    # No rule for this equipment type (the ALERT + CRITICAL default), a rule
    # with no active follow-ups, or every follow-up failing to create would
    # otherwise leave the new CAR open with nothing driving it - fall back to
    # a single same-test-type retest. No-op when a follow-up is in flight.
    _ensure_active_followup(db, car=car, testing_request=testing_request, created_by=created_by)

    return car


def _inflight_request(db: Session, *, equipment_id, test_type_id, exclude_id) -> Optional[TestingRequest]:
    """A TR for this equipment + test type (other than exclude_id) that is
    still expecting a result - reusable as the follow-up instead of raising
    a duplicate. One whose result is already in doesn't count: it can't
    produce the follow-up's result. System-raised only (RETEST/FOLLOW_UP) -
    a manually raised TR of the same equipment+type is its own independent
    request and is never silently repurposed as a CAR follow-up."""
    if not equipment_id or not test_type_id:
        return None
    open_trs = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.equipment_id == equipment_id,
            TestingRequest.test_type_id == test_type_id,
            TestingRequest.id != exclude_id,
            ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
            TestingRequest.test_request_type != "ORIGINAL",
        )
        .all()
    )
    expecting = expecting_result_ids(db, [t.id for t in open_trs])
    return next((t for t in open_trs if t.id in expecting), None)


def _create_followups(
    db: Session,
    *,
    car: Optional[CorrectiveActionRequest],
    config: CarTriggerConfig,
    source_request: TestingRequest,
    created_by: Optional[uuid.UUID],
) -> None:
    """Auto-create a retest of the SAME test type that failed - never a
    different one. A CarTriggerFollowup configured for a different test type
    (e.g. a Tan Delta test on an oil-test rule) is intentionally not acted on
    here: a CRITICAL/ALERT on one test type only auto-raises a retest of that
    test type, nothing else. Only the repair_lifecycle branch is exempt (it's
    the corrective action itself, not a measurement, and doesn't get raised
    on its own type since it has none). Best-effort: one failing (e.g. a
    repair workflow already active for this equipment) never blocks the
    others or the CAR itself.

    The retest is due on the CAR default for its severity (3 days CRITICAL,
    7 days ALERT - config.py), not the rule row's due_in_days.

    car=None: "Trigger a CAR" is off for this rule - a same-type follow-up is
    raised as a plain retest with no CAR. An in-flight system retest of the
    same type is reused instead of raising a duplicate (linked to the CAR
    when there is one).
    """
    from services.testing_request_service import TestingRequestService
    from services.repair_workflow_service import RepairWorkflowService

    candidate_followups = [f for f in config.followups if f.is_active]
    if not candidate_followups:
        return

    followup_type_ids = [f.follow_up_test_type_id for f in candidate_followups]
    category_by_type_id = {
        row.id: row.category_type
        for row in db.query(CategoryDetails).filter(CategoryDetails.id.in_(followup_type_ids)).all()
    }
    active_followups = [
        f for f in candidate_followups
        if f.follow_up_test_type_id == source_request.test_type_id
        or category_by_type_id.get(f.follow_up_test_type_id) == "repair_lifecycle"
    ]
    if not active_followups:
        return

    tr_service = TestingRequestService(db)
    repair_service = RepairWorkflowService(db)
    originator_id = created_by or source_request.originator_id
    label = car.car_number if car is not None else source_request.request_number

    for followup in active_followups:
        category = category_by_type_id.get(followup.follow_up_test_type_id)
        try:
            if category == "repair_lifecycle":
                result = repair_service.start_workflow(
                    equipment_id=source_request.equipment_id,
                    user_id=originator_id,
                    source_failure_id=source_request.id,
                )
                logger.info(f"{label}: started repair workflow {result.get('id') if result else '?'}")
                continue

            is_retest = followup.follow_up_test_type_id == source_request.test_type_id
            relationship = CarRelationshipType.RETEST if is_retest else CarRelationshipType.FOLLOW_UP

            # A multi-session source (OLTC count, DFR, SFRA) with sessions
            # still to run IS the same-type follow-up - raising another
            # request of that type now would duplicate its remaining sessions.
            if is_retest and source_request.id in expecting_result_ids(db, [source_request.id]):
                logger.info(
                    f"{label}: no same-type follow-up for test_type_id={followup.follow_up_test_type_id} - "
                    f"{source_request.request_number} still has sessions to run"
                )
                continue

            existing = _inflight_request(
                db,
                equipment_id=source_request.equipment_id,
                test_type_id=followup.follow_up_test_type_id,
                exclude_id=source_request.id,
            )
            if existing is not None:
                if car is not None and not db.query(CarTestRequest.id).filter(
                    CarTestRequest.car_id == car.id, CarTestRequest.test_request_id == existing.id
                ).first():
                    db.add(CarTestRequest(car_id=car.id, test_request_id=existing.id, relationship_type=relationship))
                    db.commit()
                logger.info(f"{label}: reusing in-flight {existing.request_number} for test_type_id={followup.follow_up_test_type_id}")
                continue

            # Same deadline as every other retest of a CAR - the CAR default
            # for its severity (CAR_DUE_DAYS_CRITICAL / _ALERT) - not the
            # rule row's due_in_days, so a retest's due date never depends
            # on whether its test happens to be listed in the rule.
            severity = (car.severity if car is not None else config.severity) or "CRITICAL"
            due_days = CAR_DUE_DAYS_CRITICAL if severity == "CRITICAL" else CAR_DUE_DAYS_ALERT
            due_date = datetime.now(timezone.utc) + timedelta(days=due_days)
            new_request = tr_service.create_request(
                {
                    "title": f"{label} follow-up: {_tr_label(source_request)}",
                    "equipment_id": source_request.equipment_id,
                    "equipment_type_id": source_request.equipment_type_id,
                    "test_type_id": followup.follow_up_test_type_id,
                    "request_category": category or "test",
                    "organization_id": source_request.organization_id,
                    "department_id": source_request.department_id,
                    "priority": "high",
                    "due_date": due_date,
                    "notes": (
                        f"Auto-created from {car.car_number} (source: {source_request.request_number})"
                        if car is not None else
                        f"Auto-created follow-up (source: {source_request.request_number}, "
                        f"{config.severity}) - CAR Trigger Config schedules it without raising a CAR"
                    ),
                },
                originator_id=originator_id,
                # the source's result is in (it's what raised this follow-up)
                # but it may still be under review, i.e. "active"; same for
                # any other same-type TR whose result is in
                duplicate_check_ignore_ids={source_request.id}
                | _finished_open_ids(
                    db, equipment_id=source_request.equipment_id, test_type_id=followup.follow_up_test_type_id
                ),
            )
            new_request.parent_request_id = source_request.id
            new_request.source_failure_id = None
            new_request.test_request_type = "RETEST" if is_retest else "FOLLOW_UP"
            db.commit()

            if not _submit_or_withdraw(db, tr_service, new_request, originator_id, label):
                continue

            if car is not None:
                db.add(CarTestRequest(
                    car_id=car.id,
                    test_request_id=new_request.id,
                    relationship_type=relationship,
                ))
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(f"{label}: follow-up creation failed for test_type_id={followup.follow_up_test_type_id}: {exc}")


def close_car_if_verified(
    db: Session,
    *,
    testing_request: TestingRequest,
    evaluation_overall: str,
) -> Optional[CorrectiveActionRequest]:
    """Entry point from testing_service.py for a NORMAL result; runs under
    the same equipment lock as process_evaluation_for_car()."""
    with car_lock(db, equipment_lock_key(testing_request.equipment_id, testing_request.id)):
        return _close_car_if_verified(db, testing_request=testing_request, evaluation_overall=evaluation_overall)


def _close_car_if_verified(
    db: Session,
    *,
    testing_request: TestingRequest,
    evaluation_overall: str,
) -> Optional[CorrectiveActionRequest]:
    """
    A NORMAL result on a TR in an open CAR's chain. It is linked into the
    chain (VERIFICATION when it resolves a test type that had failed there,
    FOLLOW_UP otherwise). The CAR CLOSES once every test type that failed in
    its chain has a passing retest (unresolved_test_types) AND every linked
    request is finished (maybe_close_car) - e.g. an oil-test CAR whose
    tan-delta follow-up also failed needs both.

    A NORMAL from the TR that first failed for a type (a corrected entry, a
    later session) doesn't resolve it - it isn't an independent retest.
    Every CAR the result resolves closes (one equipment can carry several).
    If something is still unresolved, retests are raised for it.
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

    cars = find_open_cars_for_lineage(db, testing_request)
    if not cars:
        return None

    closed, still_open = [], []
    for car in cars:
        before = {u["test_type_id"] for u in unresolved_test_types(db, car)}
        if not db.query(CarTestRequest.id).filter(
            CarTestRequest.car_id == car.id, CarTestRequest.test_request_id == testing_request.id
        ).first():
            db.add(CarTestRequest(
                car_id=car.id,
                test_request_id=testing_request.id,
                relationship_type=CarRelationshipType.VERIFICATION
                if testing_request.test_type_id in before else CarRelationshipType.FOLLOW_UP,
            ))
            db.commit()
        # Closes only if every failed type passed AND every linked request is
        # finished - usually not yet at result time (this request's own
        # workflow is still running); then it closes when the last one ends
        # (recheck_cars_for_request, fired from the workflow's finish).
        if maybe_close_car(db, car):
            closed.append(car)
        else:
            still_open.append(car)

    for car in still_open:
        _ensure_active_followup(db, car=car, testing_request=testing_request, created_by=None)

    if closed:
        for car in closed:
            db.refresh(car)
        return closed[0]
    return None


# ── Notifications ────────────────────────────────────────────────────────────

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


# Audit action for requests the CAR logic cancels itself (void / replacement).
# Still a cancel for withdrawn_request_ids and the accepted-results rule, but
# not "a person stopped this retest" (_type_stopped_by_person), so a CAR
# reopened after a Finance rejection gets its retests back.
CAR_CANCEL_ACTION = "car_cancel"


def cancel_open_car_requests(
    db: Session,
    car: CorrectiveActionRequest,
    *,
    reason: str,
    cancelled_by: Optional[uuid.UUID],
    apply: bool = True,
) -> list:
    """When a CAR ends without needing its retests (voided, equipment being
    replaced): cancel the SYSTEM-raised retests / follow-ups
    (test_request_type RETEST / FOLLOW_UP) still waiting for a result, so
    they don't linger in approval / testing queues.

    Left alone: requests whose result is already in (e.g. awaiting approval
    or Finance), requests a person raised or a schedule raised (ORIGINAL),
    and anything also linked to another still-open CAR.

    Same shape as RepairWorkflowService.cancel_workflow's closing of its
    requests (status closed + wf_cancelled, instance cancelled), plus a
    "cancel" audit row, so the workflow history shows why and
    withdrawn_request_ids / the accepted-results rule see it as cancelled.
    Returns the request numbers (would be) cancelled; commits when apply."""
    linked = [
        tr_id for (tr_id,) in db.query(CarTestRequest.test_request_id).filter(CarTestRequest.car_id == car.id).all()
    ]
    if not linked:
        return []
    candidates = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.id.in_(linked),
            TestingRequest.test_request_type.in_(["RETEST", "FOLLOW_UP"]),
            ~TestingRequest.status.in_(list(_TERMINAL_TR_STATUSES)),
        )
        .all()
    )
    expecting = expecting_result_ids(db, [t.id for t in candidates])
    shared = {
        tr_id for (tr_id,) in (
            db.query(CarTestRequest.test_request_id)
            .join(CorrectiveActionRequest, CorrectiveActionRequest.id == CarTestRequest.car_id)
            .filter(
                CarTestRequest.test_request_id.in_([t.id for t in candidates]),
                CarTestRequest.car_id != car.id,
                CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
            )
            .all()
        )
    }
    to_cancel = [t for t in candidates if t.id in expecting and t.id not in shared]
    if not apply:
        return [t.request_number for t in to_cancel]

    now = datetime.now(timezone.utc)
    for tr in to_cancel:
        from_code = tr.current_status_code
        tr.status = TestingRequestStatus.closed
        tr.current_status_code = "wf_cancelled"
        tr.completed_at = now
        tr.modified_by = cancelled_by
        instance = (
            db.query(TrWfInstance).filter(TrWfInstance.id == tr.wf_instance_id).first()
            if tr.wf_instance_id else None
        )
        if instance is not None:
            from_stage = instance.current_stage_id
            if instance.status == "active":
                instance.status = "cancelled"
                instance.current_status_code = "wf_cancelled"
                instance.completed_at = now
            # Close its open stage record(s) and clear the current stage, as a
            # normal workflow finish does. Otherwise the stage-SLA / deadline
            # jobs (they filter stage instances "in_progress", not the
            # instance) keep sending overdue alerts for a cancelled request.
            db.query(TrWfStageInstance).filter(
                TrWfStageInstance.wf_instance_id == instance.id,
                TrWfStageInstance.status.in_(["in_progress", "not_started"]),
            ).update(
                {"status": "cancelled", "completed_at": now},
                synchronize_session=False,
            )
            instance.current_stage_id = None
            db.add(TrWfAuditLog(
                wf_instance_id=instance.id,
                testing_request_id=tr.id,
                from_stage_id=from_stage,
                action_code=CAR_CANCEL_ACTION,  # contains "cancel": withdrawn everywhere
                performed_by=cancelled_by,
                from_status_code=from_code,
                to_status_code="wf_cancelled",
                comment=reason,
                is_terminal=True,
            ))
    db.commit()
    for tr in to_cancel:
        logger.info(f"CAR {car.car_number}: cancelled {tr.request_number} - {reason}")
    return [t.request_number for t in to_cancel]


def void_car(db: Session, car: CorrectiveActionRequest, *, reason: str, voided_by: uuid.UUID) -> CorrectiveActionRequest:
    """Admin escape hatch for a CAR raised in error (bad equipment record,
    wrong threshold) - not a workflow step. Its system-raised retests /
    follow-ups still waiting for a result are cancelled
    (cancel_open_car_requests); requests a person raised are left alone."""
    with car_lock(db, equipment_lock_key(car.equipment_id, car.id)):
        # checked by the caller before the lock - a result may have closed it
        # while this waited; never overwrite a closed CAR
        db.refresh(car)
        if car.status not in CarStatus.OPEN_STATUSES:
            raise ValueError(f"CAR {car.car_number} is {car.status} - only an open CAR can be voided")
        car.status = CarStatus.VOIDED
        car.corrective_action = f"VOIDED: {reason.strip()}"
        car.modified_by = voided_by
        db.commit()
        # its retests / follow-ups have nothing left to verify
        cancel_open_car_requests(
            db, car, reason=f"{car.car_number} voided: {reason.strip()}", cancelled_by=voided_by
        )
    db.refresh(car)
    return car


def close_cars_for_replacement(
    db: Session,
    testing_request: TestingRequest,
    *,
    approved_by: Optional[uuid.UUID],
    notes: str,
) -> list:
    """The CM workflow approved a Procurement (replace the equipment)
    recommendation (workflow_dispatch_service). Every open CAR on that
    equipment - the whole asset is being replaced, so e.g. both a DGA and an
    oil-test CAR on it are moot:
      - gets its system-raised retests / follow-ups still waiting for a
        result cancelled (cancel_open_car_requests), and
      - is marked "Replacement approved, waiting for Finance" (marker in
        corrective_action) - it stays OPEN: a CAR closes only when every
        linked request is finished, and the recommending request is
        finance_pending until Finance decides.
    Finance approval closes it (finish_replacement), Finance rejection
    clears the marker (reopen_cars_after_replacement_rejected). Procurement
    tracks the replacement itself - no repair workflow is started. Returns
    the CARs marked."""
    with car_lock(db, equipment_lock_key(testing_request.equipment_id, testing_request.id)):
        if testing_request.equipment_id:
            cars = (
                db.query(CorrectiveActionRequest)
                .filter(
                    CorrectiveActionRequest.equipment_id == testing_request.equipment_id,
                    CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
                )
                .all()
            )
        else:
            cars = find_open_cars_for_lineage(db, testing_request)
        for car in cars:
            car.corrective_action = f"{REPLACEMENT_APPROVED_PREFIX}{notes}"
            car.modified_by = approved_by
        db.commit()
        for car in cars:
            cancel_open_car_requests(
                db, car, reason=f"{car.car_number}: {notes}", cancelled_by=approved_by
            )
        for car in cars:
            db.refresh(car)
            maybe_close_car(db, car)  # no-op until Finance approves
        return cars


def finish_replacement(db: Session, pr_number: str) -> list:
    """Finance approved the procurement request: close every CAR waiting on it
    (maybe_close_car - once all its linked requests are finished; a CAR with
    another request still open closes when that one ends). Returns the CARs
    closed."""
    cars = (
        db.query(CorrectiveActionRequest)
        .filter(
            CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
            CorrectiveActionRequest.corrective_action.like(f"{REPLACEMENT_APPROVED_PREFIX}%"),
            CorrectiveActionRequest.corrective_action.like(f"%(Procurement {pr_number})%"),
        )
        .all()
    )
    closed = []
    for car in cars:
        with car_lock(db, equipment_lock_key(car.equipment_id, car.id)):
            db.refresh(car)
            if maybe_close_car(db, car):
                closed.append(car)
    return closed


def reopen_cars_after_replacement_rejected(
    db: Session,
    testing_request: TestingRequest,
    *,
    pr_number: str,
    rejected_by: Optional[uuid.UUID],
    notes: str,
) -> list:
    """Finance rejected the procurement request (routers/procurement.py
    finance_reject): the replacement isn't happening. CARs waiting on it
    (replacement-approved marker) lose the marker and carry on normally -
    while the recommendation is back to pending for the tester to revise
    they show replacement_pending (no retests), then retests resume. A CAR
    closed early under the old rule (closed at CM approval, "REPLACEMENT:
    ... (Procurement <pr>)") is reopened. Returns the CARs changed."""
    with car_lock(db, equipment_lock_key(testing_request.equipment_id, testing_request.id)):
        cars = (
            db.query(CorrectiveActionRequest)
            .filter(
                CorrectiveActionRequest.corrective_action.like(f"%(Procurement {pr_number})%"),
                or_(
                    CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
                    CorrectiveActionRequest.status == CarStatus.CLOSED,
                ),
            )
            .all()
        )
        changed = []
        for car in cars:
            note = car.corrective_action or ""
            if car.status == CarStatus.CLOSED and not note.startswith("REPLACEMENT: "):
                continue
            if car.status == CarStatus.CLOSED:
                car.status = CarStatus.REOPENED
                car.closed_at = None
            car.corrective_action = f"Replacement rejected by Finance ({pr_number}): {notes}"
            car.modified_by = rejected_by
            changed.append(car)
        db.commit()
        for car in changed:
            logger.info(f"CAR {car.car_number}: replacement {pr_number} rejected by Finance - back to normal handling")
        return changed