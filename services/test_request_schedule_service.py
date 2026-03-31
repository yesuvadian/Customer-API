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
    elif frequency == ScheduleFrequency.yearly:
        return current + relativedelta(years=1)
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
        schedule = self.db.query(TestRequestSchedule).filter(
            TestRequestSchedule.test_request_id == test_request_id
        ).first()
        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No schedule found for this test request"
            )
        return schedule

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

    # ── Delete ───────────────────────────────────────────────────────────────
    def delete_schedule(self, test_request_id: UUID) -> bool:
        schedule = self.get_schedule(test_request_id)
        self.db.delete(schedule)
        self.db.commit()
        return True

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

    # ── Scheduler job (called daily by APScheduler) ───────────────────────────
    @staticmethod
    def run_daily_scheduler(db: Session) -> dict:
        """
        Called once daily. For every active schedule where today >= next_run_date - advance_days,
        clone the template test request and advance next_run_date.
        """
        from sqlalchemy import func as sqlfunc
        from services.testing_request_service import TestingRequestService

        now = datetime.now(timezone.utc)
        created_count = 0
        failed_count = 0

        due_schedules = (
            db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.is_active == True,
                TestRequestSchedule.next_run_date <= now + timedelta(
                    days=1  # handled per-schedule below using advance_days
                ),
            )
            .all()
        )

        for schedule in due_schedules:
            # Check if today >= next_run_date - advance_days
            trigger_date = schedule.next_run_date - timedelta(days=schedule.advance_days)
            if now.date() < trigger_date.date():
                continue

            # Check end_date
            if schedule.end_date and now > schedule.end_date:
                schedule.is_active = False
                db.commit()
                continue

            log_entry = TestRequestScheduleLog(
                schedule_id=schedule.id,
                run_date=now,
                status=ScheduleLogStatus.failed,  # optimistic default; updated on success
            )

            try:
                # Clone the template request
                template: TestingRequest = schedule.test_request
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

                # Set status to submitted (same as manual flow)
                new_request.status = TestingRequestStatus.submitted
                db.commit()

                log_entry.generated_request_id = new_request.id
                log_entry.status = ScheduleLogStatus.success

                # Advance next_run_date
                schedule.next_run_date = _advance_date(schedule.next_run_date, schedule.frequency)
                schedule.last_run_date = now

                # Deactivate if past end_date
                if schedule.end_date and schedule.next_run_date > schedule.end_date:
                    schedule.is_active = False

                db.add(log_entry)
                db.commit()
                created_count += 1

            except Exception as e:
                db.rollback()
                log_entry.error_message = str(e)
                log_entry.status = ScheduleLogStatus.failed
                db.add(log_entry)
                db.commit()
                failed_count += 1

        return {"created": created_count, "failed": failed_count}
