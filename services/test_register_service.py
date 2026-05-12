"""
test_register_service.py
────────────────────────
Service layer for the Test Register module.

Responsibilities
────────────────
• CRUD on register templates (TestingRequest with is_schedule_template=True)
• Commissioning: when a new Equipment is saved, auto-clone template rows into
  live TestingRequest + TestRequestSchedule records for that UEIC.
• ALERT reschedule: after EvaluationService returns ALERT, update the live
  schedule's next_run_date using revised_periodicity_days (if set).

Template data shape
───────────────────
  TestingRequest (is_schedule_template=True)
    equipment_type_id   ← CategoryMaster PK  (not equipment_id — that stays NULL)
    organization_id     ← org this template belongs to
    title               ← e.g. "DGA — Power Transformer"
    template_key        ← matches OrgTestTemplate key (e.g. "transformer_dga")
    priority            ← "normal" | "high"
    notes               ← any admin notes about this test requirement

  TestRequestSchedule  (linked by test_request_id)
    frequency           ← ScheduleFrequency enum
    start_date          ← set to now() during template creation (placeholder)
    next_run_date       ← same (overwritten on commission)
    advance_days        ← how many days before due_date to trigger a live clone
    responsible_role_id ← OrgRole that performs the test
    reviewing_role_id   ← OrgRole that approves the result
    revised_periodicity_days ← override interval when evaluation = ALERT
    oem_reference       ← IS / OEM standard clause
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from models import (
    CategoryMaster,
    Equipment,
    OrgRole,
    RequestCategory,
    ScheduleFrequency,
    TestingRequest,
    TestingRequestStatus,
    TestRequestSchedule,
    User,
)

# ── frequency → calendar delta ────────────────────────────────────────────────
_FREQ_DELTA = {
    ScheduleFrequency.daily:       relativedelta(days=1),
    ScheduleFrequency.weekly:      relativedelta(weeks=1),
    ScheduleFrequency.biweekly:    relativedelta(weeks=2),
    ScheduleFrequency.monthly:     relativedelta(months=1),
    ScheduleFrequency.quarterly:   relativedelta(months=3),
    ScheduleFrequency.semi_annual: relativedelta(months=6),
    ScheduleFrequency.yearly:      relativedelta(years=1),
    ScheduleFrequency.triennial:   relativedelta(years=3),
}

# ── roles allowed to create / edit templates ──────────────────────────────────
_WRITE_ROLES = {"Admin", "SuperAdmin", "EE TLSS", "Department Head"}


# ─────────────────────────────────────────────────────────────────────────────
class TestRegisterService:

    def __init__(self, db: Session):
        self.db = db

    # ── helpers ───────────────────────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _require_write_access(self, user: User) -> None:
        """Raise 403 if user cannot create / edit register templates."""
        from models import Role, UserRole, OrgUserRole

        global_roles = (
            self.db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == user.id)
            .all()
        )
        org_roles = (
            self.db.query(OrgRole.name)
            .join(OrgUserRole, OrgUserRole.org_role_id == OrgRole.id)
            .filter(OrgUserRole.user_id == user.id)
            .all()
        )
        names = {r[0] for r in global_roles} | {r[0] for r in org_roles}
        if not names.intersection(_WRITE_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only EE TLSS, Department Head, or Admin can manage the Test Register.",
            )

    @staticmethod
    def _freq_delta(freq: ScheduleFrequency) -> relativedelta:
        return _FREQ_DELTA.get(freq, relativedelta(years=1))

    @staticmethod
    def _serialize_template(req: TestingRequest, schedule: Optional[TestRequestSchedule]) -> dict:
        eq_type = req.equipment_type
        return {
            "id": str(req.id),
            "request_number": req.request_number,
            "title": req.title,
            "notes": req.notes,
            "priority": req.priority,
            "equipment_type_id": req.equipment_type_id,
            "equipment_type_name": getattr(eq_type, "name", None),
            "organization_id": str(req.organization_id) if req.organization_id else None,
            "template_key": (
                req.test_results[0].template_key
                if req.test_results else None
            ),
            "schedule": (
                {
                    "id": str(schedule.id),
                    "frequency": schedule.frequency.value if schedule.frequency else None,
                    "advance_days": schedule.advance_days,
                    "revised_periodicity_days": schedule.revised_periodicity_days,
                    "oem_reference": schedule.oem_reference,
                    "responsible_role_id": str(schedule.responsible_role_id) if schedule.responsible_role_id else None,
                    "responsible_role_name": getattr(schedule.responsible_role, "name", None),
                    "reviewing_role_id": str(schedule.reviewing_role_id) if schedule.reviewing_role_id else None,
                    "reviewing_role_name": getattr(schedule.reviewing_role, "name", None),
                    "is_active": schedule.is_active,
                }
                if schedule else None
            ),
            "cts": req.cts.isoformat() if req.cts else None,
        }

    def _get_template_or_404(self, template_id: UUID) -> TestingRequest:
        req = (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.equipment_type),
                joinedload(TestingRequest.test_results),
            )
            .filter(
                TestingRequest.id == template_id,
                TestingRequest.is_schedule_template.is_(True),
            )
            .first()
        )
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test register template not found.",
            )
        return req

    def _get_schedule_for(self, req_id: UUID) -> Optional[TestRequestSchedule]:
        return (
            self.db.query(TestRequestSchedule)
            .options(
                joinedload(TestRequestSchedule.responsible_role),
                joinedload(TestRequestSchedule.reviewing_role),
            )
            .filter(TestRequestSchedule.test_request_id == req_id)
            .first()
        )

    def _gen_request_number(self) -> str:
        today = self._now().strftime("%Y%m%d")
        count = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.request_number.like(f"TR-REG-{today}-%"))
            .scalar()
        )
        return f"TR-REG-{today}-{(count + 1):04d}"

    # ── List ──────────────────────────────────────────────────────────────────

    def list_templates(
        self,
        organization_id: Optional[UUID] = None,
        equipment_type_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list:
        q = (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.equipment_type),
                joinedload(TestingRequest.test_results),
            )
            .filter(TestingRequest.is_schedule_template.is_(True))
            .order_by(TestingRequest.cts.desc())
        )
        if organization_id:
            q = q.filter(TestingRequest.organization_id == organization_id)
        if equipment_type_id:
            q = q.filter(TestingRequest.equipment_type_id == equipment_type_id)

        rows = q.offset(skip).limit(limit).all()
        results = []
        for row in rows:
            sched = self._get_schedule_for(row.id)
            results.append(self._serialize_template(row, sched))
        return results

    # ── Get single ────────────────────────────────────────────────────────────

    def get_template(self, template_id: UUID) -> dict:
        req = self._get_template_or_404(template_id)
        sched = self._get_schedule_for(req.id)
        return self._serialize_template(req, sched)

    # ── Create ────────────────────────────────────────────────────────────────

    def create_template(self, data: dict, creator: User) -> dict:
        """
        Required keys: title, equipment_type_id, organization_id, frequency
        Optional keys: template_key, priority, notes, advance_days,
                       responsible_role_id, reviewing_role_id,
                       revised_periodicity_days, oem_reference
        """
        self._require_write_access(creator)

        try:
            freq = ScheduleFrequency(data["frequency"])
        except (KeyError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid frequency. Accepted: {[f.value for f in ScheduleFrequency]}",
            )

        now = self._now()
        req = TestingRequest(
            id=uuid4(),
            request_number=self._gen_request_number(),
            title=data["title"],
            description=data.get("description"),
            equipment_type_id=data["equipment_type_id"],
            organization_id=data["organization_id"],
            department_id=data.get("department_id"),
            request_category=RequestCategory.test,
            priority=data.get("priority", "normal"),
            notes=data.get("notes"),
            status=TestingRequestStatus.draft,
            is_schedule_template=True,
            is_direct_submission=False,
            originator_id=creator.id,
            created_by=creator.id,
            requested_date=now,
        )
        self.db.add(req)
        self.db.flush()

        sched = TestRequestSchedule(
            id=uuid4(),
            test_request_id=req.id,
            organization_id=data["organization_id"],
            frequency=freq,
            start_date=now,
            next_run_date=now + self._freq_delta(freq),
            advance_days=data.get("advance_days", 15),
            is_active=True,
            responsible_role_id=data.get("responsible_role_id"),
            reviewing_role_id=data.get("reviewing_role_id"),
            revised_periodicity_days=data.get("revised_periodicity_days"),
            oem_reference=data.get("oem_reference"),
            created_by=creator.id,
        )
        self.db.add(sched)
        self.db.commit()
        self.db.refresh(req)
        self.db.refresh(sched)

        return self._serialize_template(req, sched)

    # ── Update ────────────────────────────────────────────────────────────────

    def update_template(self, template_id: UUID, data: dict, editor: User) -> dict:
        self._require_write_access(editor)

        req = self._get_template_or_404(template_id)
        sched = self._get_schedule_for(req.id)

        # Request-level fields
        for field in ("title", "description", "priority", "notes", "equipment_type_id", "department_id"):
            if field in data:
                setattr(req, field, data[field])
        req.modified_by = editor.id

        # Schedule-level fields
        if sched and any(k in data for k in (
            "frequency", "advance_days", "responsible_role_id", "reviewing_role_id",
            "revised_periodicity_days", "oem_reference", "is_active",
        )):
            if "frequency" in data:
                try:
                    sched.frequency = ScheduleFrequency(data["frequency"])
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid frequency '{data['frequency']}'.",
                    )
            for field in ("advance_days", "responsible_role_id", "reviewing_role_id",
                          "revised_periodicity_days", "oem_reference", "is_active"):
                if field in data:
                    setattr(sched, field, data[field])
            sched.modified_by = editor.id

        self.db.commit()
        self.db.refresh(req)
        if sched:
            self.db.refresh(sched)
        return self._serialize_template(req, sched)

    # ── Deactivate ────────────────────────────────────────────────────────────

    def deactivate_template(self, template_id: UUID, editor: User) -> dict:
        self._require_write_access(editor)

        req = self._get_template_or_404(template_id)
        sched = self._get_schedule_for(req.id)

        if sched:
            sched.is_active = False
            sched.modified_by = editor.id

        self.db.commit()
        if sched:
            self.db.refresh(sched)
        return self._serialize_template(req, sched)

    # ── Commission equipment ──────────────────────────────────────────────────

    def commission_equipment(self, equipment_id: UUID, triggered_by: User) -> dict:
        """
        Clone all active register templates matching equipment.equipment_type_id
        into live TestingRequest + TestRequestSchedule records.

        Returns a summary dict with the count and IDs of created requests.
        """
        equipment = (
            self.db.query(Equipment)
            .filter(Equipment.id == equipment_id)
            .first()
        )
        if not equipment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Equipment not found.",
            )

        org_id = equipment.organization_id or getattr(triggered_by, "organization_id", None)

        templates = (
            self.db.query(TestingRequest)
            .join(
                TestRequestSchedule,
                TestRequestSchedule.test_request_id == TestingRequest.id,
            )
            .filter(
                TestingRequest.is_schedule_template.is_(True),
                TestingRequest.equipment_type_id == equipment.equipment_type_id,
                TestingRequest.organization_id == org_id,
                TestRequestSchedule.is_active.is_(True),
            )
            .options(joinedload(TestingRequest.test_results))
            .all()
        )

        now = self._now()
        created_ids = []

        for tmpl in templates:
            tmpl_sched = self._get_schedule_for(tmpl.id)
            if not tmpl_sched:
                continue

            # Derive due_date from frequency
            due_date = now + self._freq_delta(tmpl_sched.frequency)

            today_str = now.strftime("%Y%m%d")
            count = (
                self.db.query(func.count(TestingRequest.id))
                .filter(TestingRequest.request_number.like(f"TR-{today_str}-%"))
                .scalar()
            )
            req_number = f"TR-{today_str}-{(count + 1):04d}"

            live_req = TestingRequest(
                id=uuid4(),
                request_number=req_number,
                title=tmpl.title,
                description=tmpl.description,
                equipment_type_id=tmpl.equipment_type_id,
                equipment_id=equipment.id,
                organization_id=org_id,
                department_id=tmpl.department_id or equipment.department_id,
                request_category=RequestCategory.test,
                priority=tmpl.priority,
                notes=tmpl.notes,
                status=TestingRequestStatus.submitted,
                is_schedule_template=False,
                is_direct_submission=False,
                originator_id=triggered_by.id,
                created_by=triggered_by.id,
                requested_date=now,
                due_date=due_date,
            )
            self.db.add(live_req)
            self.db.flush()

            live_sched = TestRequestSchedule(
                id=uuid4(),
                test_request_id=live_req.id,
                organization_id=org_id,
                frequency=tmpl_sched.frequency,
                start_date=now,
                next_run_date=due_date,
                advance_days=tmpl_sched.advance_days,
                is_active=True,
                responsible_role_id=tmpl_sched.responsible_role_id,
                reviewing_role_id=tmpl_sched.reviewing_role_id,
                revised_periodicity_days=tmpl_sched.revised_periodicity_days,
                oem_reference=tmpl_sched.oem_reference,
                created_by=triggered_by.id,
            )
            self.db.add(live_sched)
            created_ids.append(str(live_req.id))

        self.db.commit()

        return {
            "equipment_id": str(equipment_id),
            "equipment_ueic": getattr(equipment, "ueic", None),
            "templates_matched": len(templates),
            "requests_created": len(created_ids),
            "created_request_ids": created_ids,
        }

    # ── ALERT reschedule ──────────────────────────────────────────────────────

    def apply_alert_reschedule(self, schedule_id: UUID) -> dict:
        """
        Called after EvaluationService returns ALERT for a testing request.
        If the schedule has revised_periodicity_days, update next_run_date.
        Returns updated next_run_date (ISO) or None if no override.
        """
        sched = (
            self.db.query(TestRequestSchedule)
            .filter(TestRequestSchedule.id == schedule_id)
            .first()
        )
        if not sched:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule not found.",
            )

        now = self._now()
        if sched.revised_periodicity_days:
            from datetime import timedelta
            sched.next_run_date = now + timedelta(days=sched.revised_periodicity_days)
            sched.last_run_date = now
            self.db.commit()
            self.db.refresh(sched)
            return {
                "schedule_id": str(schedule_id),
                "rescheduled": True,
                "next_run_date": sched.next_run_date.isoformat(),
                "revised_periodicity_days": sched.revised_periodicity_days,
            }

        # fallback: advance by normal frequency
        sched.next_run_date = now + self._freq_delta(sched.frequency)
        sched.last_run_date = now
        self.db.commit()
        self.db.refresh(sched)
        return {
            "schedule_id": str(schedule_id),
            "rescheduled": True,
            "next_run_date": sched.next_run_date.isoformat(),
            "revised_periodicity_days": None,
        }

    # ── Equipment schedule view ───────────────────────────────────────────────

    def list_equipment_schedules(self, equipment_id: UUID) -> list:
        """List all live test schedules for a specific equipment unit."""
        rows = (
            self.db.query(TestRequestSchedule)
            .join(
                TestingRequest,
                TestingRequest.id == TestRequestSchedule.test_request_id,
            )
            .options(
                joinedload(TestRequestSchedule.responsible_role),
                joinedload(TestRequestSchedule.reviewing_role),
                joinedload(TestRequestSchedule.test_request).joinedload(TestingRequest.equipment_type),
            )
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.is_schedule_template.is_(False),
                TestRequestSchedule.is_active.is_(True),
            )
            .order_by(TestRequestSchedule.next_run_date.asc())
            .all()
        )

        def _s(row: TestRequestSchedule) -> dict:
            req = row.test_request
            return {
                "schedule_id": str(row.id),
                "request_id": str(req.id),
                "request_number": req.request_number,
                "title": req.title,
                "equipment_type_name": getattr(req.equipment_type, "name", None),
                "frequency": row.frequency.value if row.frequency else None,
                "next_run_date": row.next_run_date.isoformat() if row.next_run_date else None,
                "advance_days": row.advance_days,
                "last_run_date": row.last_run_date.isoformat() if row.last_run_date else None,
                "responsible_role": getattr(row.responsible_role, "name", None),
                "reviewing_role": getattr(row.reviewing_role, "name", None),
                "oem_reference": row.oem_reference,
                "revised_periodicity_days": row.revised_periodicity_days,
                "is_active": row.is_active,
            }

        return [_s(r) for r in rows]
