from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

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

    # ============================================================
    # CREATE TEMPLATE SCHEDULE
    # ============================================================

    def create_schedule(
        self,
        test_request_id: UUID,
        frequency: str,
        end_date: Optional[datetime],
        advance_days: int,
        created_by: UUID,
    ) -> TestRequestSchedule:

        req = (
            self.db.query(TestingRequest)
            .filter(
                TestingRequest.id == test_request_id
            )
            .first()
        )
        if req.equipment_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Operational requests "
                    "cannot have schedules."
                ),
            )
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test request not found",
            )

        if not req.is_schedule_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Schedules can only be created "
                    "for template requests."
                ),
            )

        # prevent operational requests
        if req.equipment_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Schedules cannot be created "
                    "for operational equipment requests."
                ),
            )

        # only one TEMPLATE schedule
        existing = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.test_request_id
                    == test_request_id,

                TestRequestSchedule.equipment_id.is_(None),
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Template schedule already exists."
                ),
            )

        freq_enum = ScheduleFrequency(frequency)

        start_date = req.due_date or self._utc_now()

        next_run_date = _advance_date(
            start_date,
            freq_enum,
        )

        schedule = TestRequestSchedule(
            test_request_id=test_request_id,
            equipment_id=None,
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

    # ============================================================
    # GET TEMPLATE SCHEDULE
    # ============================================================

    def get_schedule(
        self,
        test_request_id: UUID,
    ) -> TestRequestSchedule:

        schedule = (
            self.db.query(TestRequestSchedule)
            .join(TestingRequest)
            .filter(
                TestRequestSchedule.test_request_id
                    == test_request_id,

                TestRequestSchedule.equipment_id.is_(None),

                TestingRequest.is_schedule_template.is_(True),
            )
            .first()
        )

        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No template schedule found",
            )

        return schedule

    # ============================================================
    # LIST SCHEDULES
    # ============================================================

    def list_schedules(
        self,
        organization_id: Optional[UUID] = None,
        equipment_type_id: Optional[int] = None,
        equipment_id: Optional[UUID] = None,
        templates_only: bool = False,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[dict]:

        query = (
            self.db.query(
                TestRequestSchedule,
                TestingRequest,
            )
            .join(
                TestingRequest,
                TestingRequest.id
                    == TestRequestSchedule.test_request_id,
            )
        )

        if organization_id:
            query = query.filter(
                TestRequestSchedule.organization_id
                    == organization_id
            )

        if equipment_type_id:
            query = query.filter(
                TestingRequest.equipment_type_id
                    == equipment_type_id
            )

        if templates_only:
            query = query.filter(
                TestRequestSchedule.equipment_id.is_(None)
            )

        if equipment_id:
            query = query.filter(
                TestRequestSchedule.equipment_id
                    == equipment_id
            )

        if active_only:
            query = query.filter(
                TestRequestSchedule.is_active.is_(True)
            )

        rows = (
            query
            .order_by(
                TestRequestSchedule.next_run_date.asc()
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

        results = []

        for schedule, request in rows:

            results.append({
                "schedule_id": str(schedule.id),

                "test_request_id": str(request.id),

                "equipment_id": (
                    str(schedule.equipment_id)
                    if schedule.equipment_id else None
                ),

                "is_template_schedule": (
                    schedule.equipment_id is None
                ),

                "request_number": request.request_number,

                "title": request.title,

                "equipment_type_id": (
                    request.equipment_type_id
                ),

                "frequency": (
                    schedule.frequency.value
                    if schedule.frequency else None
                ),

                "next_run_date": (
                    schedule.next_run_date.isoformat()
                    if schedule.next_run_date else None
                ),

                "advance_days": (
                    schedule.advance_days
                ),

                "is_active": (
                    schedule.is_active
                ),
            })

        return results

    # ============================================================
    # INSTANTIATE OPERATIONAL SCHEDULES
    # ============================================================

    # ============================================================
# CHANGE 11
# FILE:
# services/test_request_schedule_service.py
# ADD NEW METHOD
# ============================================================

    @staticmethod
    def instantiate_equipment_schedules(
        db: Session,
        equipment,
        user_id: UUID,
    ):

        templates = (
            db.query(TestRequestSchedule)
            .join(TestingRequest)
            .options(
                joinedload(
                    TestRequestSchedule.test_request
                )
            )
            .filter(
                TestRequestSchedule.is_active.is_(True),

                TestRequestSchedule.equipment_id.is_(None),

                TestingRequest.is_schedule_template.is_(True),

                TestingRequest.equipment_type_id
                    == equipment.equipment_type_id,
            )
            .all()
        )

        for template in templates:

            existing = (
                db.query(TestRequestSchedule)
                .filter(
                    TestRequestSchedule.test_request_id
                        == template.test_request_id,

                    TestRequestSchedule.equipment_id
                        == equipment.id,
                )
                .first()
            )

            if existing:
                continue

            operational_schedule = TestRequestSchedule(
                test_request_id=template.test_request_id,

                equipment_id=equipment.id,

                organization_id=equipment.organization_id,

                frequency=template.frequency,

                start_date=datetime.now(timezone.utc),

                next_run_date=template.next_run_date,

                end_date=template.end_date,

                advance_days=template.advance_days,

                revised_periodicity_days=(
                    template.revised_periodicity_days
                ),

                oem_reference=template.oem_reference,

                responsible_role_id=(
                    template.responsible_role_id
                ),

                reviewing_role_id=(
                    template.reviewing_role_id
                ),

                is_active=True,

                created_by=user_id,
            )

            db.add(operational_schedule)

        db.commit()

    # ============================================================
    # CREATE OPERATIONAL REQUEST
    # ============================================================

    @staticmethod
    def create_one_ticket(
        db: Session,
        schedule: "TestRequestSchedule",
        template: "TestingRequest",
        now: datetime,
    ) -> bool:

        from services.testing_request_service import (
            TestingRequestService
        )

        try:

            schedule = (
                db.query(TestRequestSchedule)
                .options(
                    joinedload(
                        TestRequestSchedule.equipment
                    ),
                    joinedload(
                        TestRequestSchedule.test_request
                    ),
                )
                .filter(
                    TestRequestSchedule.id == schedule.id
                )
                .with_for_update()
                .first()
            )
            equipment = schedule.equipment

            if not equipment:
                raise Exception(
                    "Equipment not found."
                )
            if not schedule:
                return False

            if not schedule.is_active:
                return False

            if not schedule.equipment_id:
                raise Exception(
                    "Template schedules cannot execute."
                )

            if (
                schedule.end_date
                and now > schedule.end_date
            ):
                schedule.is_active = False
                schedule.last_success_at = now

                schedule.consecutive_failures = 0
                db.commit()
                return False

            equipment = schedule.equipment

            if not equipment:
                raise Exception(
                    "Equipment not found."
                )

            trigger_date = (
                schedule.next_run_date
                - timedelta(days=schedule.advance_days)
            )

            if now.date() < trigger_date.date():
                return False



            existing_generated = (
                db.query(TestingRequest)
                .filter(
                    TestingRequest.source_schedule_id
                        == schedule.id,

                    TestingRequest.due_date
                        == schedule.next_run_date,
                )
                .first()
            )

            if existing_generated:
                return True

            if existing_generated:
                return True

            svc = TestingRequestService(db)

          

            new_data = {

                "title": template.title,

                "description": template.description,

                "request_category": (
                    template.request_category
                ),

                "test_type_id": (
                    template.test_type_id
                ),

                "priority": template.priority,

                "notes": template.notes,

                "assigned_tester_id": (
                    template.assigned_tester_id
                ),

                "equipment_id": equipment.id,

                "equipment_type_id": (
                    equipment.equipment_type_id
                ),

                "manufacturer": (
                    equipment.manufacturer
                ),

                "serial_number": (
                    equipment.factory_serial_number
                ),

                "transformer_type": (
                    template.transformer_type
                ),

                "transformer_rating": (
                    template.transformer_rating
                ),

                "organization_id": (
                    equipment.organization_id
                ),

                "department_id": (
                    equipment.department_id
                ),

                "zone": template.zone,

                "ce_circle": template.ce_circle,

                "se_division": template.se_division,

                "ee_subdivision": template.ee_subdivision,

                "aee_section": template.aee_section,

                "ae_je": template.ae_je,

                "requested_date": now,

                "due_date": (
                    schedule.next_run_date
                ),

                "is_schedule_template": False,

                "source_schedule_id": (
                    schedule.id
                ),
            }

            new_request = svc.create_request(
                new_data,
                originator_id=template.originator_id,
            )

            new_request.status = (
                TestingRequestStatus.submitted
            )

            db.flush()

            log_entry = TestRequestScheduleLog(
                schedule_id=schedule.id,
                run_date=now,
                status=ScheduleLogStatus.success,
                generated_request_id=new_request.id,
            )

            db.add(log_entry)

            schedule.next_run_date = _advance_date(
                schedule.next_run_date,
                schedule.frequency,
            )

            schedule.last_run_date = now

            if (
                schedule.end_date
                and schedule.next_run_date
                    > schedule.end_date
            ):
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
            schedule.last_failure_at = now

            schedule.consecutive_failures += 1

            if schedule.consecutive_failures >= 5:
                schedule.is_active = False
            db.commit()

            return False
        # ============================================================
    # FILE:
    # services/test_request_schedule_service.py
    # METHOD:
    # delete_schedule()
    # ADD THIS METHOD BACK
    # ============================================================

    def delete_schedule(
        self,
        test_request_id: UUID,
        modified_by: UUID,
    ) -> dict:

        schedule = (
            self.db.query(TestRequestSchedule)
            .join(
                TestingRequest,
                TestingRequest.id
                    == TestRequestSchedule.test_request_id,
            )
            .filter(
                TestRequestSchedule.test_request_id
                    == test_request_id,

                TestRequestSchedule.equipment_id.is_(None),

                TestRequestSchedule.is_deleted == False,

                TestingRequest.is_schedule_template.is_(True),
            )
            .first()
        )

        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template schedule not found",
            )

        schedule.is_deleted = True

        schedule.deleted_at = self._utc_now()

        schedule.deleted_by = modified_by

        schedule.modified_by = modified_by

        schedule.mts = self._utc_now()

        schedule.is_active = False

        self.db.commit()

        return {
            "message": "Schedule deleted successfully",
            "schedule_id": str(schedule.id),
        }
    # ============================================================
    # DAILY SCHEDULER
    # ============================================================

    @staticmethod
    def run_daily_scheduler(
        db: Session,
    ) -> dict:

        try:
            from config import (
                SCHEDULE_ADVANCE_DAYS as _adv
            )
        except Exception:
            _adv = 15

        now = datetime.now(timezone.utc)

        created_count = 0
        failed_count = 0

 

        due_schedules = (
            db.query(TestRequestSchedule)
            .options(
                joinedload(
                    TestRequestSchedule.test_request
                ),
                joinedload(
                    TestRequestSchedule.equipment
                ),
            )
            .filter(
                TestRequestSchedule.is_active == True,

                TestRequestSchedule.is_deleted == False,

                TestRequestSchedule.equipment_id.isnot(None),

                TestRequestSchedule.next_run_date
                    <= now + timedelta(days=_adv + 1),
            )
            .all()
        )

        for schedule in due_schedules:

            trigger_date = (
                schedule.next_run_date
                - timedelta(days=schedule.advance_days)
            )

            if now.date() < trigger_date.date():
                continue

            template = schedule.test_request

            success = (
                TestRequestScheduleService.create_one_ticket(
                    db=db,
                    schedule=schedule,
                    template=template,
                    now=now,
                )
            )

            if success:
                created_count += 1
            else:
                failed_count += 1

        return {
            "created": created_count,
            "failed": failed_count,
        }