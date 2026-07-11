# ============================================================
# services/test_request_schedule_service.py
# ============================================================

from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from typing import Optional, List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from models import (
    Equipment,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    TestRequestSchedule,
    TestRequestScheduleLog,
    ScheduleFrequency,
    ScheduleLogStatus,
)

from utils.common_service import UTCDateTimeMixin
import logging

logger = logging.getLogger(__name__)


# ============================================================
# DATE ADVANCE
# ============================================================

def _advance_date(
    current: datetime,
    frequency: ScheduleFrequency,
) -> datetime:

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


# ============================================================
# SERVICE
# ============================================================

class TestRequestScheduleService(UTCDateTimeMixin):

    def __init__(self, db: Session):
        self.db = db

    # ============================================================
    # CREATE MASTER SCHEDULE
    # equipment_id = NULL
    # ============================================================

    def create_master_schedule(
        self,
        organization_id: UUID,
        equipment_type_id: int,
        test_type_id: int,
        title: str,
        description: Optional[str],
        frequency: str,
        advance_days: int,
        created_by: UUID,
        request_category=None,
        priority=None,
        notes=None,
        assigned_tester_id=None,
        transformer_type=None,
        transformer_rating=None,
        zone=None,
        ce_circle=None,
        se_division=None,
        ee_subdivision=None,
        aee_section=None,
        ae_je=None,
        revised_periodicity_days=None,
        oem_reference=None,
        end_date=None,
    ):

        existing = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.equipment_id.is_(None),

                TestRequestSchedule.organization_id
                    == organization_id,

                TestRequestSchedule.equipment_type_id
                    == equipment_type_id,

                TestRequestSchedule.test_type_id
                    == test_type_id,

                TestRequestSchedule.is_deleted == False,
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Master schedule already exists "
                    "for this test type."
                ),
            )

        freq_enum = ScheduleFrequency(frequency)

        now = self._utc_now()

        schedule = TestRequestSchedule(

            # MASTER
            equipment_id=None,

            organization_id=organization_id,

            equipment_type_id=equipment_type_id,

            test_type_id=test_type_id,

            title=title,

            description=description,

            request_category=request_category,

            priority=priority,

            notes=notes,

            assigned_tester_id=assigned_tester_id,

            transformer_type=transformer_type,

            transformer_rating=transformer_rating,

            zone=zone,

            ce_circle=ce_circle,

            se_division=se_division,

            ee_subdivision=ee_subdivision,

            aee_section=aee_section,

            ae_je=ae_je,

            frequency=freq_enum,

            start_date=now,

            next_run_date=_advance_date(
                now,
                freq_enum,
            ),

            end_date=end_date,

            advance_days=advance_days,

            revised_periodicity_days=(
                revised_periodicity_days
            ),

            oem_reference=oem_reference,

            is_active=True,

            created_by=created_by,
        )

        self.db.add(schedule)

        self.db.commit()

        self.db.refresh(schedule)

        return schedule

    # ============================================================
    # ONBOARD EQUIPMENT SCHEDULES
    # ============================================================

    @staticmethod
    def instantiate_equipment_schedules(
        db: Session,
        equipment,
        user_id: UUID,
    ):

        templates = (
            db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.is_active.is_(True),
                TestRequestSchedule.is_deleted == False,
                TestRequestSchedule.equipment_id.is_(None),  # MASTER ONLY
                TestRequestSchedule.equipment_type_id == equipment.equipment_type_id,
            )
            .all()
        )

        now = datetime.now(timezone.utc)
        new_schedules = []

        for template in templates:

            existing = (
                db.query(TestRequestSchedule)
                .filter(
                    TestRequestSchedule.equipment_id == equipment.id,
                    TestRequestSchedule.test_type_id == template.test_type_id,
                    TestRequestSchedule.is_deleted == False,
                )
                .first()
            )

            if existing:
                continue

            # Calculate appropriate next_run_date based on frequency
            # For monthly/yearly, use the advanced date; for immediate, use now
            if template.frequency in [
                ScheduleFrequency.monthly,
                ScheduleFrequency.quarterly,
                ScheduleFrequency.semi_annual,
                ScheduleFrequency.yearly,
                ScheduleFrequency.triennial,
            ]:
                # For longer frequencies, set next_run_date to the advanced date
                # This prevents immediate ticket creation
                next_run_date = _advance_date(now, template.frequency)
            else:
                # For daily/weekly/biweekly, set to now for immediate ticket
                next_run_date = now

            operational_schedule = TestRequestSchedule(
                equipment_id=equipment.id,
                organization_id=equipment.organization_id,
                equipment_type_id=template.equipment_type_id,
                test_type_id=template.test_type_id,
                title=template.title,
                description=template.description,
                request_category=template.request_category,
                priority=template.priority,
                notes=template.notes,
                assigned_tester_id=template.assigned_tester_id,
                transformer_type=template.transformer_type,
                transformer_rating=template.transformer_rating,
                zone=template.zone,
                ce_circle=template.ce_circle,
                se_division=template.se_division,
                ee_subdivision=template.ee_subdivision,
                aee_section=template.aee_section,
                ae_je=template.ae_je,
                frequency=template.frequency,
                start_date=now,
                next_run_date=next_run_date,  # Now properly set based on frequency
                end_date=template.end_date,
                advance_days=template.advance_days,
                revised_periodicity_days=template.revised_periodicity_days,
                oem_reference=template.oem_reference,
                is_active=True,
                created_by=user_id,
            )

            db.add(operational_schedule)
            new_schedules.append(operational_schedule)

        db.commit()

        # Apply same trigger check as daily scheduler
        for sched in new_schedules:
            db.refresh(sched)
            try:
                # This will now properly check based on the next_run_date
                TestRequestScheduleService.create_one_ticket(db, sched, now)
            except Exception as e:
                print(f"[WARN] create_one_ticket on onboard failed for schedule {sched.id}: {e}")

    # ============================================================
    # CREATE ONE TICKET
    # ============================================================

    @staticmethod
    def create_one_ticket(
        db: Session,
        schedule: TestRequestSchedule,
        now: datetime,
        force_run: bool = False,
    ) -> bool:

        from services.testing_request_service import (
            TestingRequestService
        )

        try:

            schedule = (
                db.query(TestRequestSchedule)
                .filter(
                    TestRequestSchedule.id
                        == schedule.id
                )
                .with_for_update()
                .first()
            )

            if not schedule:
                return False

            if not schedule.is_active:
                return False

            # Site-level schedules (e.g. taqc_inspection) have no equipment_id.
            # Equipment-bound schedules require a valid Equipment record.
            from models import Equipment
            if schedule.equipment_id:
                equipment = (
                    db.query(Equipment)
                    .filter(Equipment.id == schedule.equipment_id)
                    .first()
                )
                if not equipment:
                    raise Exception("Equipment not found.")
            else:
                equipment = None

            trigger_date = (
                schedule.next_run_date
                - timedelta(
                    days=schedule.advance_days
                )
            )
            if not force_run:
             if now.date() < trigger_date.date():
                return False

            # ── Cross-path dedup ─────────────────────────────────────────────
            # Multiple paths can create a follow-up for the same equipment+test
            # (threshold-alert followup on save AND recommendation dispatch on
            # approval). Guard here — the single chokepoint for ALL generated
            # tickets — so only ONE open ticket exists per equipment+test_type.
            if schedule.equipment_id and schedule.test_type_id:
                from models import TestingRequestStatus as _TRS
                _open = [
                    _TRS.draft, _TRS.submitted, _TRS.assigned, _TRS.accepted,
                    _TRS.in_progress, _TRS.test_submitted, _TRS.under_approval,
                    _TRS.under_review,
                ]
                _dup = (
                    db.query(TestingRequest)
                    .filter(
                        TestingRequest.equipment_id == schedule.equipment_id,
                        TestingRequest.test_type_id == schedule.test_type_id,
                        TestingRequest.status.in_(_open),
                        TestingRequest.is_schedule_template.is_(False),
                        # Only consider already-generated follow-up tickets — NOT
                        # the manually-created test that triggered this. The
                        # original test has source_schedule_id = NULL, so it
                        # won't block its own follow-up.
                        TestingRequest.source_schedule_id.isnot(None),
                    )
                    .first()
                )
                if _dup:
                    logger.info(
                        "[ScheduleService] Skipping ticket — open request %s already "
                        "exists for equipment %s test_type %s",
                        _dup.request_number, schedule.equipment_id, schedule.test_type_id,
                    )
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
                # Patch missing surveillance linkage on existing ticket
                if (
                    schedule.surveillance_workflow_id
                    and not existing_generated.surveillance_workflow_id
                ):
                    from utils.surveillance_utils import calculate_surveillance_quarter
                    existing_generated.surveillance_workflow_id = schedule.surveillance_workflow_id
                    existing_generated.surveillance_quarter = calculate_surveillance_quarter(
                        db, schedule.surveillance_workflow_id, now
                    )
                    db.commit()
                    logger.info(
                        "[ScheduleService] Patched surveillance linkage on existing ticket %s",
                        existing_generated.id,
                    )
                return True

            # Check if schedule has ended (for surveillance workflows with end_date)
            if schedule.end_date and now > schedule.end_date:
                # Schedule has expired, mark as inactive
                schedule.is_active = False
                db.commit()
                return False

            # Calculate surveillance quarter dynamically (if this is a surveillance schedule)
            surveillance_quarter = None
            if schedule.surveillance_workflow_id:
                from utils.surveillance_utils import calculate_surveillance_quarter
                surveillance_quarter = calculate_surveillance_quarter(
                    db,
                    schedule.surveillance_workflow_id,
                    now
                )

            svc = TestingRequestService(db)

            new_data = {

                "title": schedule.title,

                "description": (
                    schedule.description
                ),

                "request_category": (
                    schedule.request_category
                ),

                "test_type_id": (
                    schedule.test_type_id
                ),

                "priority": (
                    schedule.priority
                ),

                "notes": schedule.notes,

                "assigned_tester_id": (
                    schedule.assigned_tester_id
                ),

                "equipment_id": equipment.id if equipment else None,

                "equipment_type_id": (
                    equipment.equipment_type_id if equipment else None
                ),

                "manufacturer": (
                    equipment.manufacturer if equipment else None
                ),

                "serial_number": (
                    equipment.factory_serial_number if equipment else None
                ),

                "transformer_type": (
                    schedule.transformer_type
                ),

                "transformer_rating": (
                    schedule.transformer_rating
                ),

                "organization_id": (
                    equipment.organization_id if equipment else schedule.organization_id
                ),

                "department_id": (
                    equipment.department_id if equipment else schedule.department_id
                ),

                "zone": schedule.zone,

                "ce_circle": (
                    schedule.ce_circle
                ),

                "se_division": (
                    schedule.se_division
                ),

                "ee_subdivision": (
                    schedule.ee_subdivision
                ),

                "aee_section": (
                    schedule.aee_section
                ),

                "ae_je": schedule.ae_je,

                "requested_date": now,

                "due_date": (
                    schedule.next_run_date
                ),

                "is_schedule_template": False,

                "source_schedule_id": (
                    schedule.id
                ),

                # Surveillance workflow linkage (if applicable)
                # surveillance_quarter is calculated dynamically above (not from schedule)
                "surveillance_workflow_id": (
                    schedule.surveillance_workflow_id if hasattr(schedule, 'surveillance_workflow_id') else None
                ),

                "surveillance_quarter": surveillance_quarter,  # Calculated dynamically for surveillance schedules
            }

            new_request = svc.create_request(
                new_data,
                originator_id=(
                    schedule.created_by
                ),
            )

            new_request.status = (
                TestingRequestStatus.submitted
            )

            # Maintenance schedules route to PM Workflow
            if str(getattr(schedule, "request_category", "") or "").lower() == "maintenance":
                new_request.request_type = "pm"

            db.flush()

            # Enroll in TR workflow engine so the ticket enters the L2→L3→L4
            # approval/assignment/test flow instead of the old direct-approval path.
            try:
                from services.tr_workflow_routing_service import WorkflowRoutingService
                WorkflowRoutingService(db).instantiate_workflow(
                    new_request,
                    performed_by_id=schedule.created_by,
                )
                db.flush()
                logger.info(
                    "[ScheduleService] WF instance created for new ticket %s",
                    new_request.request_number,
                )
            except Exception as _wf_err:
                logger.error(
                    "[ScheduleService] WF enrollment FAILED for ticket %s: %s",
                    new_request.request_number, _wf_err, exc_info=True,
                )

            log_entry = TestRequestScheduleLog(
                schedule_id=schedule.id,
                run_date=now,
                status=ScheduleLogStatus.success,
                generated_request_id=(
                    new_request.id
                ),
            )

            db.add(log_entry)

            schedule.next_run_date = (
                _advance_date(
                    schedule.next_run_date,
                    schedule.frequency,
                )
            )

            schedule.last_run_date = now

            schedule.last_success_at = now

            schedule.consecutive_failures = 0

            db.commit()

            return True

        except Exception as e:

            db.rollback()
            print("RUN NOW ERROR:", str(e))

            log_entry = TestRequestScheduleLog(
                schedule_id=schedule.id,
                run_date=now,
                status=ScheduleLogStatus.failed,
                error_message=str(e),
            )

            db.add(log_entry)

            schedule.last_failure_at = now

            schedule.consecutive_failures += 1

            if (
                schedule.consecutive_failures
                >= 5
            ):
                schedule.is_active = False

            db.commit()

            return False

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
                    TestRequestSchedule.equipment
                )
            )
            .filter(
                TestRequestSchedule.is_active == True,

                TestRequestSchedule.is_deleted == False,

                # OPERATIONAL ONLY
                TestRequestSchedule.equipment_id
                    .isnot(None),

                TestRequestSchedule.next_run_date
                    <= now + timedelta(
                        days=_adv + 1
                    ),
            )
            .all()
        )

        for schedule in due_schedules:

            success = (
                TestRequestScheduleService
                .create_one_ticket(
                    db=db,
                    schedule=schedule,
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
    

    # ============================================================
    # MASTER SCHEDULES
    # equipment_id = NULL
    # ============================================================

    def create_master_schedule(
        self,
        data: dict,
        user_id: UUID,
    ):

        existing = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.equipment_id.is_(None),

                TestRequestSchedule.organization_id
                    == data["organization_id"],

                TestRequestSchedule.equipment_type_id
                    == data["equipment_type_id"],

                TestRequestSchedule.test_type_id
                    == data["test_type_id"],

                TestRequestSchedule.is_deleted == False,
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Master schedule already exists."
                ),
            )

        schedule = TestRequestSchedule(

            # MASTER
            equipment_id=None,

            organization_id=(
                data["organization_id"]
            ),

            equipment_type_id=(
                data["equipment_type_id"]
            ),

            test_type_id=(
                data["test_type_id"]
            ),

            title=data["title"],

            description=data.get(
                "description"
            ),

            request_category=data.get(
                "request_category"
            ),

            priority=data.get(
                "priority"
            ),

            notes=data.get(
                "notes"
            ),

            assigned_tester_id=data.get(
                "assigned_tester_id"
            ),

            transformer_type=data.get(
                "transformer_type"
            ),

            transformer_rating=data.get(
                "transformer_rating"
            ),

            zone=data.get("zone"),

            ce_circle=data.get(
                "ce_circle"
            ),

            se_division=data.get(
                "se_division"
            ),

            ee_subdivision=data.get(
                "ee_subdivision"
            ),

            aee_section=data.get(
                "aee_section"
            ),

            ae_je=data.get("ae_je"),

            frequency=data["frequency"],

            start_date=datetime.now(timezone.utc),

            next_run_date=_advance_date(
                datetime.now(timezone.utc),
                ScheduleFrequency(data["frequency"]),
            ),

            end_date=data.get(
                "end_date"
            ),

            advance_days=data.get(
                "advance_days",
                1,
            ),

            revised_periodicity_days=(
                data.get(
                    "revised_periodicity_days"
                )
            ),

            oem_reference=data.get(
                "oem_reference"
            ),

            is_active=True,

            created_by=user_id,
        )

        self.db.add(schedule)

        self.db.commit()

        self.db.refresh(schedule)

        return schedule

    # ============================================================
    # LIST MASTER SCHEDULES
    # ============================================================

    def list_master_schedules(
        self,
        organization_id: Optional[UUID] = None,
        equipment_type_id: Optional[int] = None,
        request_category: Optional[str] = None,
    ):

        query = (
            self.db.query(TestRequestSchedule)
            .options(
                joinedload(
                    TestRequestSchedule
                    .equipment_type
                ),
                joinedload(
                    TestRequestSchedule
                    .test_type
                ),
            )
            .filter(
                TestRequestSchedule.equipment_id
                    .is_(None),

                TestRequestSchedule.is_deleted
                    == False,
            )
        )

        if organization_id:
            query = query.filter(
                TestRequestSchedule
                .organization_id
                    == organization_id
            )

        if equipment_type_id:
            query = query.filter(
                TestRequestSchedule
                .equipment_type_id
                    == equipment_type_id
            )

        if request_category:
            try:
                cat_enum = RequestCategory(request_category)
            except ValueError:
                cat_enum = None
            if cat_enum == RequestCategory.test:
                # Legacy rows with NULL category are treated as 'test'
                query = query.filter(
                    or_(
                        TestRequestSchedule.request_category == RequestCategory.test,
                        TestRequestSchedule.request_category.is_(None),
                    )
                )
            elif cat_enum is not None:
                query = query.filter(
                    TestRequestSchedule.request_category == cat_enum
                )

        return query.all()

    # ============================================================
    # LIST EQUIPMENT WITH SCHEDULES
    # ============================================================

    def list_equipment_with_schedules(
        self,
        organization_id: Optional[UUID] = None,
        request_category: Optional[str] = None,
    ):
        """
        Returns list of equipment that have operational schedules.
        Includes schedule counts per equipment.
        """
        from models import Equipment, CategoryMaster
        from sqlalchemy import func, case
        from datetime import datetime, timezone as _tz

        _now = datetime.now(_tz.utc)

        # Build query to group schedules by equipment
        query = (
            self.db.query(
                Equipment.id.label('equipment_id'),
                Equipment.ueic,
                CategoryMaster.name.label('equipment_type_name'),
                Equipment.nameplate_data['substation_name'].astext.label('location'),
                func.count(TestRequestSchedule.id).label('schedule_count'),
                func.sum(
                    case((TestRequestSchedule.is_active == True, 1), else_=0)
                ).label('active_count'),
                func.sum(
                    case((TestRequestSchedule.paused_at.isnot(None), 1), else_=0)
                ).label('paused_count'),
            )
            .join(
                TestRequestSchedule,
                TestRequestSchedule.equipment_id == Equipment.id
            )
            .outerjoin(
                CategoryMaster,
                CategoryMaster.id == Equipment.equipment_type_id
            )
            .filter(
                TestRequestSchedule.is_deleted == False,
                (TestRequestSchedule.end_date.is_(None) | (TestRequestSchedule.end_date > _now)),
            )
            .group_by(
                Equipment.id,
                Equipment.ueic,
                CategoryMaster.name,
                Equipment.nameplate_data['substation_name'].astext,
            )
        )

        if organization_id:
            query = query.filter(Equipment.organization_id == organization_id)

        if request_category:
            try:
                cat_enum = RequestCategory(request_category)
            except ValueError:
                cat_enum = None
            if cat_enum == RequestCategory.test:
                query = query.filter(
                    or_(
                        TestRequestSchedule.request_category == RequestCategory.test,
                        TestRequestSchedule.request_category.is_(None),
                    )
                )
            elif cat_enum is not None:
                query = query.filter(
                    TestRequestSchedule.request_category == cat_enum
                )

        results = query.all()

        # Convert to dict
        return [
            {
                'equipment_id': str(row.equipment_id),
                'ueic': row.ueic or '',
                'equipment_type_name': row.equipment_type_name or '',
                'location': row.location or '',
                'schedule_count': row.schedule_count or 0,
                'active_count': row.active_count or 0,
                'paused_count': row.paused_count or 0,
            }
            for row in results
        ]

    # ============================================================
    # GET MASTER SCHEDULE
    # ============================================================

    def get_master_schedule(
        self,
        schedule_id: UUID,
    ):

        schedule = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.id
                    == schedule_id,

                TestRequestSchedule.equipment_id
                    .is_(None),

                TestRequestSchedule.is_deleted
                    == False,
            )
            .first()
        )

        if not schedule:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Master schedule not found."
                ),
            )

        return schedule

    # ============================================================
    # UPDATE MASTER SCHEDULE
    # ============================================================

    def update_master_schedule(
        self,
        schedule_id: UUID,
        data: dict,
        user_id: UUID,
    ):

        schedule = self.get_master_schedule(
            schedule_id
        )

        for key, value in data.items():

            if hasattr(schedule, key):
                setattr(schedule, key, value)

        schedule.modified_by = user_id

        schedule.mts = self._utc_now()

        self.db.commit()

        self.db.refresh(schedule)

        return schedule

    # ============================================================
    # DELETE MASTER SCHEDULE
    # ============================================================

    def delete_master_schedule(
        self,
        schedule_id: UUID,
        user_id: UUID,
    ):

        schedule = self.get_master_schedule(
            schedule_id
        )

        schedule.is_deleted = True

        schedule.deleted_at = self._utc_now()

        schedule.deleted_by = user_id

        schedule.modified_by = user_id

        schedule.mts = self._utc_now()

        schedule.is_active = False

        self.db.commit()

        return {
            "message": (
                "Master schedule deleted."
            )
        }

    # ============================================================
    # OPERATIONAL SCHEDULES
    # equipment_id != NULL
    # ============================================================

    def list_operational_schedules(
        self,
        equipment_id: UUID,
        request_category: Optional[str] = None,
    ):

        query = (
            self.db.query(TestRequestSchedule)
            .options(
                joinedload(
                    TestRequestSchedule
                    .test_type
                ),
            )
            .filter(
                TestRequestSchedule.equipment_id
                    == equipment_id,

                TestRequestSchedule.is_deleted
                    == False,
            )
        )

        if request_category:
            try:
                cat_enum = RequestCategory(request_category)
            except ValueError:
                cat_enum = None
            if cat_enum == RequestCategory.test:
                # Legacy rows with NULL category are treated as 'test'
                query = query.filter(
                    or_(
                        TestRequestSchedule.request_category == RequestCategory.test,
                        TestRequestSchedule.request_category.is_(None),
                    )
                )
            elif cat_enum is not None:
                query = query.filter(
                    TestRequestSchedule.request_category == cat_enum
                )

        schedules = query.all()
        today = datetime.now(timezone.utc)

        result = []
        for s in schedules:
            # Build base dict from ORM object (scalar columns only)
            s_dict: dict = {
                "id": str(s.id),
                "equipment_id": str(s.equipment_id) if s.equipment_id else None,
                "organization_id": str(s.organization_id) if s.organization_id else None,
                "test_type": (
                    {"id": s.test_type.id, "name": s.test_type.name}
                    if s.test_type else None
                ),
                "title": s.title,
                "frequency": s.frequency.value if s.frequency else None,
                "is_active": s.is_active,
                "is_deleted": s.is_deleted,
                "next_run_date": s.next_run_date.isoformat() if s.next_run_date else None,
                "start_date": s.start_date.isoformat() if s.start_date else None,
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "request_category": s.request_category.value if s.request_category else None,
                "cts": s.cts.isoformat() if s.cts else None,
            }

            # Most recent ticket created from this schedule
            ticket = (
                self.db.query(TestingRequest)
                .filter(
                    TestingRequest.source_schedule_id == s.id,
                    TestingRequest.is_schedule_template == False,
                )
                .order_by(TestingRequest.requested_date.desc())
                .first()
            )

            if ticket:
                is_completed = ticket.status == TestingRequestStatus.completed
                due = ticket.due_date
                if due and due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                is_overdue = bool(due and due < today and not is_completed)

                ref = ticket.assigned_at or ticket.requested_date
                if ref:
                    ref_utc = ref if ref.tzinfo else ref.replace(tzinfo=timezone.utc)
                    days_in_stage = (today - ref_utc).days
                else:
                    days_in_stage = 0

                s_dict["current_ticket"] = {
                    "id": str(ticket.id),
                    "request_number": ticket.request_number,
                    "status": ticket.status.value,
                    "current_status_code": ticket.current_status_code,
                    "due_date": ticket.due_date.isoformat() if ticket.due_date else None,
                    "requested_date": ticket.requested_date.isoformat() if ticket.requested_date else None,
                    "days_in_stage": days_in_stage,
                    "is_overdue": is_overdue,
                    "is_completed": is_completed,
                }
            else:
                s_dict["current_ticket"] = None

            result.append(s_dict)

        return result

    # ============================================================
    # GET OPERATIONAL SCHEDULE
    # ============================================================

    def get_operational_schedule(
        self,
        schedule_id: UUID,
        equipment_id: UUID,
    ):

        schedule = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.id
                    == schedule_id,

                TestRequestSchedule.equipment_id
                    == equipment_id,

                TestRequestSchedule.is_deleted
                    == False,
            )
            .first()
        )

        if not schedule:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Operational schedule "
                    "not found."
                ),
            )

        return schedule

    # ============================================================
    # UPDATE OPERATIONAL SCHEDULE
    # ============================================================

    def update_operational_schedule(
        self,
        schedule_id: UUID,
        equipment_id: UUID,
        data: dict,
        user_id: UUID,
    ):

        schedule = (
            self.get_operational_schedule(
                schedule_id,
                equipment_id,
            )
        )

        protected_fields = [

            "id",

            "equipment_id",

            "organization_id",

            "equipment_type_id",

            "test_type_id",

            "created_by",

            "cts",
        ]

        for key, value in data.items():

            if key in protected_fields:
                continue

            if hasattr(schedule, key):
                setattr(schedule, key, value)

        schedule.modified_by = user_id

        schedule.mts = self._utc_now()

        self.db.commit()

        self.db.refresh(schedule)

        return schedule

    # ============================================================
    # PAUSE OPERATIONAL SCHEDULE
    # ============================================================

    def pause_operational_schedule(
        self,
        schedule_id: UUID,
        equipment_id: UUID,
        user_id: UUID,
        reason: Optional[str] = None,
    ):

        schedule = (
            self.get_operational_schedule(
                schedule_id,
                equipment_id,
            )
        )

        schedule.is_active = False

        schedule.paused_at = self._utc_now()

        schedule.paused_by = user_id

        schedule.pause_reason = reason

        schedule.modified_by = user_id

        self.db.commit()

        return {
            "message": (
                "Operational schedule paused."
            )
        }

    # ============================================================
    # RESUME OPERATIONAL SCHEDULE
    # ============================================================

    def resume_operational_schedule(
        self,
        schedule_id: UUID,
        equipment_id: UUID,
        user_id: UUID,
    ):

        schedule = (
            self.get_operational_schedule(
                schedule_id,
                equipment_id,
            )
        )

        schedule.is_active = True

        schedule.paused_at = None

        schedule.paused_by = None

        schedule.pause_reason = None

        schedule.consecutive_failures = 0

        schedule.modified_by = user_id

        self.db.commit()

        return {
            "message": (
                "Operational schedule resumed."
            )
        }

    # ============================================================
    # DELETE OPERATIONAL SCHEDULE
    # ============================================================

    def delete_operational_schedule(
        self,
        schedule_id: UUID,
        equipment_id: UUID,
        user_id: UUID,
    ):

        schedule = (
            self.get_operational_schedule(
                schedule_id,
                equipment_id,
            )
        )

        schedule.is_deleted = True

        schedule.deleted_at = self._utc_now()

        schedule.deleted_by = user_id

        schedule.modified_by = user_id

        schedule.is_active = False

        self.db.commit()

        return {
            "message": (
                "Operational schedule deleted."
            )
        }