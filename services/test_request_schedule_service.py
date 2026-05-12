from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import (
    TestingRequest,
    TestingRequestStatus,
    TestRequestSchedule,
    TestRequestScheduleLog,
    ScheduleFrequency,
    ScheduleLogStatus,
)
from utils.common_service import UTCDateTimeMixin


def _advance_date(current: datetime, frequency: ScheduleFrequency) -> datetime:
    """Return the next run date based on frequency."""
    if frequency == ScheduleFrequency.daily:
        return current + timedelta(days=1)
    elif frequency == ScheduleFrequency.weekly:
        return current + timedelta(weeks=1)
    elif frequency == ScheduleFrequency.biweekly:
        return current + timedelta(weeks=2)
    elif frequency == ScheduleFrequency.monthly:
        return current + relativedelta(months=1)
    elif frequency == ScheduleFrequency.quarterly:
        return current + relativedelta(months=3)
    elif frequency == ScheduleFrequency.semi_annual:
        return current + relativedelta(months=6)
    elif frequency == ScheduleFrequency.yearly:
        return current + relativedelta(years=1)
    elif frequency == ScheduleFrequency.triennial:
        return current + relativedelta(years=3)
    return current


class TestRequestScheduleService(UTCDateTimeMixin):

    def __init__(self, db: Session):
        self.db = db

    # ── Create ───────────────────────────────────────────────────────────────
    def create_schedule(
        self,
        test_request_id: UUID,
        frequency: str,
        end_date: Optional[datetime],
        advance_days: int,
        created_by: UUID,
    ) -> TestRequestSchedule:
        # Validate the test request exists
        req = self.db.query(TestingRequest).filter(
            TestingRequest.id == test_request_id
        ).first()
        if not req.is_schedule_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Schedules can only be created for template requests."
    )
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test request not found"
            )

        # Only one schedule per request
        existing = self.db.query(TestRequestSchedule).filter(
            TestRequestSchedule.test_request_id == test_request_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A schedule already exists for this test request. Use update to modify it."
            )

        freq_enum = ScheduleFrequency(frequency)

        # start_date = the original request's due_date (or today if not set)
        start_date = req.due_date or self._utc_now()

        # next_run_date = start_date advanced by one frequency period
        next_run_date = _advance_date(start_date, freq_enum)

        schedule = TestRequestSchedule(
            test_request_id=test_request_id,
            organization_id=req.organization_id,
            frequency=freq_enum,
            start_date=start_date,
            end_date=end_date,
            next_run_date=next_run_date,
            advance_days=advance_days,
            is_active=True,
            created_by=created_by,
        )
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    # ── Get ──────────────────────────────────────────────────────────────────
    def get_schedule(self, test_request_id: UUID) -> TestRequestSchedule:
        schedule = (
            self.db.query(TestRequestSchedule)
            .join(TestingRequest)
            .filter(
                TestRequestSchedule.test_request_id == test_request_id,
                TestingRequest.is_schedule_template.is_(True),
            )
            .first()
        )
        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No schedule found for this test request"
            )
        return schedule
    # ── List Schedules ──────────────────────────────────────────────────────────
    def list_schedules(
        self,
        organization_id: Optional[UUID] = None,
        equipment_type_id: Optional[int] = None,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[dict]:

        query = (
            self.db.query(TestRequestSchedule, TestingRequest)
            .join(
                TestingRequest,
                TestingRequest.id == TestRequestSchedule.test_request_id,
            )
            .filter(
                TestingRequest.is_schedule_template.is_(True)
            )
        )

        if organization_id:
            query = query.filter(
                TestRequestSchedule.organization_id == organization_id
            )

        if equipment_type_id:
            query = query.filter(
                TestingRequest.equipment_type_id == equipment_type_id
            )

        if active_only:
            query = query.filter(
                TestRequestSchedule.is_active.is_(True)
            )

        rows = (
            query
            .order_by(TestRequestSchedule.next_run_date.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        results = []

        for schedule, request in rows:
            results.append({
                "schedule_id": str(schedule.id),
                "test_request_id": str(request.id),
                "request_number": request.request_number,
                "title": request.title,
                "description": request.description,
                "equipment_type_id": request.equipment_type_id,
                "organization_id": str(schedule.organization_id),

                "frequency": (
                    schedule.frequency.value
                    if schedule.frequency else None
                ),

                "start_date": (
                    schedule.start_date.isoformat()
                    if schedule.start_date else None
                ),

                "next_run_date": (
                    schedule.next_run_date.isoformat()
                    if schedule.next_run_date else None
                ),

                "last_run_date": (
                    schedule.last_run_date.isoformat()
                    if schedule.last_run_date else None
                ),

                "end_date": (
                    schedule.end_date.isoformat()
                    if schedule.end_date else None
                ),

                "advance_days": schedule.advance_days,
                "revised_periodicity_days": schedule.revised_periodicity_days,
                "oem_reference": schedule.oem_reference,
                "responsible_role_id": (
                    str(schedule.responsible_role_id)
                    if schedule.responsible_role_id else None
                ),
                "reviewing_role_id": (
                    str(schedule.reviewing_role_id)
                    if schedule.reviewing_role_id else None
                ),
                "is_active": schedule.is_active,

                "created_at": (
                    schedule.cts.isoformat()
                    if schedule.cts else None
                ),
            })

        return results


    # ── Soft Delete Schedule ────────────────────────────────────────────────────
    def delete_schedule(
        self,
        test_request_id: UUID,
        modified_by: UUID,
    ) -> dict:

        schedule = (
            self.db.query(TestRequestSchedule)
            .join(
                TestingRequest,
                TestingRequest.id == TestRequestSchedule.test_request_id,
            )
            .filter(
                TestRequestSchedule.test_request_id == test_request_id,
                TestingRequest.is_schedule_template.is_(True),
            )
            .first()
        )

        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template schedule not found"
            )

        schedule.is_active = False
        schedule.modified_by = modified_by
        schedule.mts = self._utc_now()

        self.db.commit()

        return {
            "message": "Schedule deactivated successfully",
            "schedule_id": str(schedule.id),
            "is_active": schedule.is_active,
        }
    # ── Update ───────────────────────────────────────────────────────────────
    def update_schedule(
        self,
        test_request_id: UUID,
        frequency: Optional[str],
        end_date: Optional[datetime],
        advance_days: Optional[int],
        is_active: Optional[bool],
        modified_by: UUID,
    ) -> TestRequestSchedule:
        schedule = self.get_schedule(test_request_id)

        if frequency is not None:
            schedule.frequency = ScheduleFrequency(frequency)
            # Recalculate next_run_date from start_date with new frequency
            schedule.next_run_date = _advance_date(schedule.start_date, schedule.frequency)

        if end_date is not None:
            schedule.end_date = end_date

        if advance_days is not None:
            schedule.advance_days = advance_days

        if is_active is not None:
            schedule.is_active = is_active

        schedule.modified_by = modified_by
        schedule.mts = self._utc_now()

        self.db.commit()
        self.db.refresh(schedule)
        return schedule

   
    # ── Logs ─────────────────────────────────────────────────────────────────
    def get_logs(
        self,
        test_request_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[TestRequestScheduleLog]:
        schedule = self.get_schedule(test_request_id)
        return (
            self.db.query(TestRequestScheduleLog)
            .filter(TestRequestScheduleLog.schedule_id == schedule.id)
            .order_by(TestRequestScheduleLog.run_date.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    # ── Shared ticket-creation logic ─────────────────────────────────────────
    @staticmethod
    def create_one_ticket(
        db: Session,
        schedule: "TestRequestSchedule",
        template: "TestingRequest",
        now: datetime,
    ) -> bool:
        """
        Clone a schedule template into a real submitted TestingRequest and advance
        next_run_date.  Returns True on success, False on failure.

        Called by both run_daily_scheduler() and workflow_dispatch_service when the
        start date is already within advance_days (immediate first-ticket creation).
        """
        from services.testing_request_service import TestingRequestService

        try:
            svc = TestingRequestService(db)
            new_data = {
                "title": template.title,
                "description": template.description,
                "transformer_type": template.transformer_type,
                "transformer_rating": template.transformer_rating,
                "manufacturer": template.manufacturer,
                "serial_number": template.serial_number,
                "equipment_type_id": template.equipment_type_id,
                "test_type_id": template.test_type_id,
                "organization_id": template.organization_id,
                "department_id": template.department_id,
                "zone": template.zone,
                "ce_circle": template.ce_circle,
                "se_division": template.se_division,
                "ee_subdivision": template.ee_subdivision,
                "aee_section": template.aee_section,
                "ae_je": template.ae_je,
                "assigned_tester_id": template.assigned_tester_id,
                "priority": template.priority,
                "notes": template.notes,
                "requested_date": now,
                "due_date": schedule.next_run_date,
            }
            new_request = svc.create_request(new_data, originator_id=template.originator_id)

            # Mark as submitted (same as manual flow)
            new_request.status = TestingRequestStatus.submitted
            db.flush()

            log_entry = TestRequestScheduleLog(
                schedule_id=schedule.id,
                run_date=now,
                status=ScheduleLogStatus.success,
                generated_request_id=new_request.id,
            )
            db.add(log_entry)

            # Advance next_run_date
            schedule.next_run_date = _advance_date(schedule.next_run_date, schedule.frequency)
            schedule.last_run_date = now

            # Deactivate if past end_date
            if schedule.end_date and schedule.next_run_date > schedule.end_date:
                schedule.is_active = False

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            log_entry = TestRequestScheduleLog(
                schedule_id=schedule.id,
                run_date=now,
                status=ScheduleLogStatus.failed,
                error_message=str(e),
            )
            db.add(log_entry)
            db.commit()
            return False

    # ── Scheduler job (called daily by APScheduler) ───────────────────────────
    @staticmethod
    def run_daily_scheduler(db: Session) -> dict:
        """
        Called once daily. For every active schedule where today >= next_run_date - advance_days,
        clone the template test request and advance next_run_date.
        """
        try:
            from config import SCHEDULE_ADVANCE_DAYS as _adv
        except Exception:
            _adv = 15

        now = datetime.now(timezone.utc)
        created_count = 0
        failed_count = 0

        # Fetch schedules whose next_run_date falls within the maximum advance window.
        # The per-schedule trigger check below refines this to the actual advance_days value.
        due_schedules = (
            db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.is_active == True,
                TestRequestSchedule.next_run_date <= now + timedelta(days=_adv + 1),
            )
            .all()
        )

        for schedule in due_schedules:
            # Check if today >= next_run_date - advance_days (per-schedule granularity)
            trigger_date = schedule.next_run_date - timedelta(days=schedule.advance_days)
            if now.date() < trigger_date.date():
                continue

            # Deactivate expired schedules
            if schedule.end_date and now > schedule.end_date:
                schedule.is_active = False
                db.commit()
                continue

            template: TestingRequest = schedule.test_request
            success = TestRequestScheduleService.create_one_ticket(db, schedule, template, now)
            if success:
                created_count += 1
            else:
                failed_count += 1

        return {"created": created_count, "failed": failed_count}
