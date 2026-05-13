"""
outcome_service.py
──────────────────
Triggered after a Failure Registry TestingRequest is approved.
Routes to the correct existing service based on next_action and
the 15-day rule.

Flow:
  next_action = None / "None"  → stop
  next_action = "Procurement"  → ProcurementService
  start_date > today + 15 days → create schedule template + TestRequestSchedule
                                  (cron handles future ticket creation)
  start_date ≤ today + 15 days → create schedule template + TestRequestSchedule
                                  + immediately call create_one_ticket()
"""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import (
    FROutcomeLog,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    ScheduleFrequency,
)
from services.test_request_schedule_service import TestRequestScheduleService
from services.procurement_service import ProcurementService

THRESHOLD_DAYS = 15

# ── next_action → RequestCategory ─────────────────────────────────────────────
ACTION_TO_CATEGORY: dict[str, RequestCategory] = {
    "Test":        RequestCategory.test,
    "Maintenance": RequestCategory.maintenance,
    "Repair":      RequestCategory.repair_lifecycle,
    "Inspection":  RequestCategory.inspection,
}

# ── scheduling_gap string → ScheduleFrequency enum ───────────────────────────
# Flutter sends these exact lowercase strings
GAP_TO_FREQUENCY: dict[str, ScheduleFrequency] = {
    "monthly":     ScheduleFrequency.monthly,
    "quarterly":   ScheduleFrequency.quarterly,
    "semi_annual": ScheduleFrequency.semi_annual,
    "yearly":      ScheduleFrequency.yearly,
    "triennial":   ScheduleFrequency.triennial,
}


class OutcomeService:

    def __init__(self, db: Session):
        self.db = db

    # ── Public entry point ────────────────────────────────────────────────────

    def handle_fr_approval(self, request_id: UUID, approver_id: UUID) -> dict:
        """
        Call this immediately after an FR is moved to `approved`.
        Returns a summary dict for logging/response.
        """
        req = (
            self.db.query(TestingRequest)
            .filter_by(id=request_id)
            .first()
        )
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")

        result = (
            self.db.query(TestResult)
            .filter_by(testing_request_id=request_id)
            .order_by(TestResult.tested_at.desc())
            .first()
        )

        if not result:
            self._log(request_id, None, "none", approver_id,
                      error="No TestResult found")
            return {"action": "none", "reason": "no_test_result"}

        next_action    = (result.next_action    or "").strip()
        scheduling_gap = (result.scheduling_gap or "").strip()
        start_date     = result.schedule_start_date    # type: date | None
        end_date       = result.schedule_end_date      # type: date | None
        test_type_str  = (result.test_type      or "").strip()

        # ── 1. Flow ends ──────────────────────────────────────────────────────
        if not next_action or next_action.lower() == "none":
            self._log(request_id, next_action, "none", approver_id)
            return {"action": "none"}

        # ── 2. Procurement branch ─────────────────────────────────────────────
        if next_action == "Procurement":
            return self._handle_procurement(
                req, result, approver_id, test_type_str
            )

        # ── 3. Test / Maintenance / Repair / Inspection ───────────────────────
        category = ACTION_TO_CATEGORY.get(next_action)
        if not category:
            self._log(request_id, next_action, "none", approver_id,
                      error=f"Unknown next_action: {next_action}")
            return {"action": "none", "reason": "unknown_next_action"}

        return self._handle_scheduled_action(
            req          = req,
            result       = result,
            approver_id  = approver_id,
            next_action  = next_action,
            category     = category,
            test_type_str= test_type_str,
            start_date   = start_date,
            end_date     = end_date,
            scheduling_gap = scheduling_gap,
        )

    # ── Procurement ───────────────────────────────────────────────────────────

    def _handle_procurement(
        self,
        req,
        result,
        approver_id: UUID,
        test_type_str: str,
    ) -> dict:
        try:
            svc = ProcurementService(self.db)
            proc = svc.create_procurement(
                data={
                    "testing_request_id": req.id,
                    "title": (
                        f"Procurement — {test_type_str or 'Equipment'} "
                        f"({req.request_number})"
                    ),
                    "description": result.summary,
                    "recommendation_id": None,
                },
                raised_by=approver_id,
            )
            self._log(
                req.id, "Procurement", "procurement",
                approver_id, procurement_id=proc.id
            )
            return {
                "action":         "procurement",
                "procurement_id": str(proc.id),
                "procurement_number": proc.procurement_number,
            }
        except Exception as e:
            self._log(req.id, "Procurement", "procurement",
                      approver_id, error=str(e))
            raise

    # ── Scheduled / Immediate ticket ──────────────────────────────────────────

    def _handle_scheduled_action(
        self,
        req,
        result,
        approver_id: UUID,
        next_action: str,
        category,
        test_type_str: str,
        start_date,
        end_date,
        scheduling_gap: str,
    ) -> dict:
        
        today    = date.today()
        if not start_date:
            raise HTTPException(
                status_code=400,
                detail="schedule_start_date missing"
            )
        is_future = (
            start_date is not None
            and start_date > today + timedelta(days=THRESHOLD_DAYS)
        )

        freq = GAP_TO_FREQUENCY.get(scheduling_gap, ScheduleFrequency.yearly)

        # ── Build schedule template TestingRequest ────────────────────────────
        template = self._create_schedule_template(
            parent_req    = req,
            category      = category,
            test_type_str = test_type_str,
            start_date    = start_date,
            end_date      = end_date,
            approver_id   = approver_id,
        )

        # ── Register schedule ─────────────────────────────────────────────────
        end_dt = (
            datetime.combine(end_date, datetime.min.time())
            .replace(tzinfo=timezone.utc)
            if end_date else None
        )
        schedule_svc = TestRequestScheduleService(self.db)
        schedule = schedule_svc.create_schedule(
            test_request_id = template.id,
            frequency       = freq.value,
            end_date        = end_dt,
            advance_days    = THRESHOLD_DAYS,
            created_by      = approver_id,
        )

        if is_future:
            # Cron will pick this up when start_date falls within advance window
            self._log(
                req.id, next_action, "scheduled",
                approver_id, schedule_id=schedule.id,
                child_request_id=template.id,
            )
            return {
                "action":       "scheduled",
                "schedule_id":  str(schedule.id),
                "template_id":  str(template.id),
                "first_ticket": start_date.isoformat() if start_date else None,
                "frequency":    freq.value,
            }
        else:
            # Immediate: create first ticket right now
            now = datetime.now(timezone.utc)
            success = TestRequestScheduleService.create_one_ticket(
                db       = self.db,
                schedule = schedule,
                template = template,
                now      = now,
            )
            # Retrieve the generated child request from the log
            from models import TestRequestScheduleLog, ScheduleLogStatus
            last_log = (
                self.db.query(TestRequestScheduleLog)
                .filter_by(schedule_id=schedule.id)
                .order_by(TestRequestScheduleLog.run_date.desc())
                .first()
            )
            child_id = last_log.generated_request_id if last_log else None

            self._log(
                req.id, next_action,
                "immediate_ticket" if success else "immediate_ticket_failed",
                approver_id,
                schedule_id      = schedule.id,
                child_request_id = child_id,
                error            = None if success else "create_one_ticket returned False",
            )
            return {
                "action":           "immediate_ticket",
                "schedule_id":      str(schedule.id),
                "child_request_id": str(child_id) if child_id else None,
                "success":          success,
            }

    # ── Schedule template ─────────────────────────────────────────────────────

    def _create_schedule_template(
        self,
        parent_req,
        category,
        test_type_str: str,
        start_date,
        end_date,
        approver_id: UUID,
    ) -> TestingRequest:
        """
        Creates an is_schedule_template=True TestingRequest that
        TestRequestScheduleService.create_one_ticket() will clone.
        """
        test_type_id = self._resolve_test_type_id(test_type_str)

        eq_ueic = (
            parent_req.equipment.ueic
            if parent_req.equipment else ""
        )
        due_dt = (
            datetime.combine(start_date, datetime.min.time())
            .replace(tzinfo=timezone.utc)
            if start_date else None
        )

        template = TestingRequest(
            title                = f"{test_type_str} — {eq_ueic}".strip(" —"),
            description          = f"Auto-generated from FR {parent_req.request_number}",
            request_category     = category,
            test_type_id         = test_type_id,
            equipment_id         = parent_req.equipment_id,
            organization_id      = parent_req.organization_id,
            department_id        = parent_req.department_id,
            priority             = parent_req.priority or "normal",
            notes                = parent_req.notes,
            status               = TestingRequestStatus.submitted,
            is_schedule_template = True,
            originator_id        = approver_id,
            created_by           = approver_id,
            due_date             = due_dt,
            source_failure_id = parent_req.id   # links child back to FR
        )
        self.db.add(template)
        self.db.flush()   # get template.id without committing
        return template

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_test_type_id(self, test_type_str: str):
        """DB lookup: TestType.name → TestType.id. Returns None if not found."""
        from models import TestType
        if not test_type_str:
            return None
        tt = self.db.query(TestType).filter(
            TestType.name == test_type_str
        ).first()
        return tt.id if tt else None

    def _log(
    self,
    testing_request_id,
    next_action,
    action_taken,
    processed_by,
    schedule_id=None,
    child_request_id=None,
    procurement_id=None,
    error=None,
):
        entry = FROutcomeLog(
        id                 = uuid4(),
        testing_request_id = testing_request_id,
        next_action        = next_action,
        action_taken       = action_taken,
        schedule_id        = schedule_id,
        child_request_id   = child_request_id,
        procurement_id     = procurement_id,
        error_message      = error,
        processed_by       = processed_by,
    )

        self.db.add(entry)

        try:
            self.db.commit()      # IMPORTANT
            self.db.refresh(entry)
        except Exception as e:
            self.db.rollback()
            print("FROutcomeLog save failed:", str(e))