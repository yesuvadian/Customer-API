"""
Service layer: Condition Monitoring Recommendations

All DB operations for recommendation configs, evaluation, and schedule activation
live here. The router delegates to this service — no SQLAlchemy in router handlers.
"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import (
    ConditionMonitoringRecommendation,
    ConditionRecommendationActivation,
    Equipment,
    EquipmentAnalytics,
    ScheduleFrequency,
    TestRequestSchedule,
)
from services.test_request_schedule_service import (
    TestRequestScheduleService,
    _advance_date,
)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _schedule_ref(schedule: TestRequestSchedule) -> str:
    return f"SCH-{str(schedule.id)[:8].upper()}"


def _next_date_str(schedule: TestRequestSchedule) -> Optional[str]:
    nd = schedule.next_run_date or schedule.start_date
    return str(nd)[:10] if nd else None


def _parse_frequency(value: str) -> ScheduleFrequency:
    try:
        return ScheduleFrequency(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown frequency: {value!r}. "
                   f"Valid: {[f.value for f in ScheduleFrequency]}",
        )


# ── Config CRUD ──────────────────────────────────────────────────────────────

def list_configs(
    db: Session,
    equipment_type_id: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> List[ConditionMonitoringRecommendation]:
    q = db.query(ConditionMonitoringRecommendation)
    if equipment_type_id is not None:
        q = q.filter(ConditionMonitoringRecommendation.equipment_type_id == equipment_type_id)
    if is_active is not None:
        q = q.filter(ConditionMonitoringRecommendation.is_active == is_active)
    return q.order_by(
        ConditionMonitoringRecommendation.equipment_type_id,
        ConditionMonitoringRecommendation.score_from,
        ConditionMonitoringRecommendation.display_order,
    ).all()


def create_config(
    db: Session,
    *,
    organization_id: Optional[UUID],
    equipment_type_id: int,
    score_from: float,
    score_to: float,
    test_type_id: int,
    frequency: str,
    display_order: int,
    is_active: bool,
    created_by: Optional[UUID],
) -> ConditionMonitoringRecommendation:
    freq = _parse_frequency(frequency)
    rec  = ConditionMonitoringRecommendation(
        organization_id   = organization_id,
        equipment_type_id = equipment_type_id,
        score_from        = score_from,
        score_to          = score_to,
        test_type_id      = test_type_id,
        frequency         = freq,
        is_active         = is_active,
        display_order     = display_order,
        created_by        = created_by,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def update_config(
    db: Session,
    rec_id: UUID,
    *,
    score_from: Optional[float] = None,
    score_to: Optional[float] = None,
    frequency: Optional[str] = None,
    display_order: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> ConditionMonitoringRecommendation:
    rec = db.query(ConditionMonitoringRecommendation).filter(
        ConditionMonitoringRecommendation.id == rec_id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation config not found")

    if score_from    is not None: rec.score_from    = score_from
    if score_to      is not None: rec.score_to      = score_to
    if frequency     is not None: rec.frequency     = _parse_frequency(frequency)
    if display_order is not None: rec.display_order = display_order
    if is_active     is not None: rec.is_active     = is_active

    db.commit()
    db.refresh(rec)
    return rec


def deactivate_config(db: Session, rec_id: UUID) -> None:
    rec = db.query(ConditionMonitoringRecommendation).filter(
        ConditionMonitoringRecommendation.id == rec_id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation config not found")
    rec.is_active = False
    db.commit()


# ── Evaluation ───────────────────────────────────────────────────────────────

def evaluate_for_equipment(db: Session, equipment_id: UUID) -> dict:
    """
    Returns all score-matched recommendations for the equipment together with
    their current activation/schedule status.
    """
    eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment not found")

    ea = db.query(EquipmentAnalytics).filter(
        EquipmentAnalytics.equipment_id == equipment_id
    ).first()

    if not ea or ea.health_score is None:
        return {
            "equipment_id":    str(equipment_id),
            "health_score":    None,
            "risk_level":      None,
            "recommendations": [],
        }

    health_score = float(ea.health_score)

    configs = (
        db.query(ConditionMonitoringRecommendation)
        .filter(
            ConditionMonitoringRecommendation.is_active        == True,
            ConditionMonitoringRecommendation.equipment_type_id == eq.equipment_type_id,
            ConditionMonitoringRecommendation.score_from        <= health_score,
            ConditionMonitoringRecommendation.score_to          >= health_score,
        )
        .order_by(
            ConditionMonitoringRecommendation.display_order,
            ConditionMonitoringRecommendation.score_from,
        )
        .all()
    )

    items = []
    for cfg in configs:
        # Step 1: check activation tracking record
        activation = db.query(ConditionRecommendationActivation).filter(
            ConditionRecommendationActivation.recommendation_id == cfg.id,
            ConditionRecommendationActivation.equipment_id      == equipment_id,
        ).first()

        schedule = None

        # Step 2: resolve schedule from activation link
        if activation and activation.schedule_id:
            schedule = db.query(TestRequestSchedule).filter(
                TestRequestSchedule.id == activation.schedule_id
            ).first()

        # Step 3: if no activation link, check whether an active schedule already
        # exists for this equipment + test type (e.g. created from master template
        # or a previous condition monitoring run without an activation record)
        if schedule is None:
            schedule = db.query(TestRequestSchedule).filter(
                TestRequestSchedule.equipment_id == equipment_id,
                TestRequestSchedule.test_type_id == cfg.test_type_id,
                TestRequestSchedule.is_active    == True,
            ).first()

        schedule_info = None
        if schedule:
            schedule_info = {
                "schedule_id":   str(schedule.id),
                "schedule_ref":  _schedule_ref(schedule),
                "frequency":     schedule.frequency.value if schedule.frequency else cfg.frequency.value,
                "next_due_date": _next_date_str(schedule),
                "is_active":     schedule.is_active,
            }

        # Derive status: prefer activation record; fall back to schedule existence
        if activation:
            status = activation.status
        elif schedule:
            status = "activated"
        else:
            status = "recommended"

        items.append({
            "recommendation_id": str(cfg.id),
            "test_type_id":      cfg.test_type_id,
            "test_name":         cfg.test_type.name if cfg.test_type else "",
            "frequency":         cfg.frequency.value,
            "frequency_label":   cfg.frequency.value.replace("_", "-").capitalize(),
            "status":            status,
            "schedule":          schedule_info,
        })

    return {
        "equipment_id":    str(equipment_id),
        "health_score":    health_score,
        "risk_level":      ea.risk_level,
        "recommendations": items,
    }


# ── Activation ───────────────────────────────────────────────────────────────

def activate(
    db: Session,
    rec_id: UUID,
    equipment_id: UUID,
    start_date_str: str,
    activated_by: Optional[UUID],
) -> dict:
    """
    Activates a recommendation for a specific equipment:
      - Active schedule exists   → raise 409 with schedule details
      - Dormant schedule exists  → reactivate
      - No schedule              → create new operational TestRequestSchedule
    Returns dict with created=True and schedule info on success.
    """
    rec = db.query(ConditionMonitoringRecommendation).filter(
        ConditionMonitoringRecommendation.id       == rec_id,
        ConditionMonitoringRecommendation.is_active == True,
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation config not found or inactive")

    eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment not found")

    try:
        start = datetime.fromisoformat(start_date_str).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid start_date — expected YYYY-MM-DD")

    # Duplicate check — unique constraint covers one row per (equipment, test_type)
    existing = db.query(TestRequestSchedule).filter(
        TestRequestSchedule.equipment_id == equipment_id,
        TestRequestSchedule.test_type_id == rec.test_type_id,
    ).first()

    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code":          "SCHEDULE_EXISTS",
                    "schedule_id":   str(existing.id),
                    "schedule_ref":  _schedule_ref(existing),
                    "test_name":     rec.test_type.name if rec.test_type else "",
                    "frequency":     existing.frequency.value if existing.frequency else rec.frequency.value,
                    "next_due_date": _next_date_str(existing),
                },
            )
        # Reactivate dormant schedule
        existing.is_active     = True
        existing.start_date    = start
        existing.next_run_date = _advance_date(start, rec.frequency)
        existing.frequency     = rec.frequency
        schedule = existing
    else:
        # Try to find a master template to copy fields (request_category, priority,
        # assigned_tester_id, zone fields, etc.) rather than creating a bare record.
        master_template = db.query(TestRequestSchedule).filter(
            TestRequestSchedule.equipment_id.is_(None),
            TestRequestSchedule.equipment_type_id == eq.equipment_type_id,
            TestRequestSchedule.test_type_id      == rec.test_type_id,
            TestRequestSchedule.is_active         == True,
        ).first()

        test_type     = rec.test_type
        next_run_date = _advance_date(start, rec.frequency)

        if master_template:
            schedule = TestRequestSchedule(
                organization_id          = eq.organization_id,
                equipment_id             = equipment_id,
                equipment_type_id        = eq.equipment_type_id,
                department_id            = eq.department_id,
                test_type_id             = rec.test_type_id,
                title                    = master_template.title,
                description              = master_template.description,
                request_category         = master_template.request_category,
                priority                 = master_template.priority,
                notes                    = master_template.notes,
                assigned_tester_id       = master_template.assigned_tester_id,
                transformer_type         = master_template.transformer_type,
                transformer_rating       = master_template.transformer_rating,
                zone                     = master_template.zone,
                ce_circle                = master_template.ce_circle,
                se_division              = master_template.se_division,
                ee_subdivision           = master_template.ee_subdivision,
                aee_section              = master_template.aee_section,
                ae_je                    = master_template.ae_je,
                frequency                = rec.frequency,
                start_date               = start,
                next_run_date            = next_run_date,
                advance_days             = master_template.advance_days or 15,
                revised_periodicity_days = master_template.revised_periodicity_days,
                oem_reference            = master_template.oem_reference,
                is_active                = True,
                created_by               = activated_by,
            )
        else:
            schedule = TestRequestSchedule(
                organization_id   = eq.organization_id,
                equipment_id      = equipment_id,
                equipment_type_id = eq.equipment_type_id,
                department_id     = eq.department_id,
                test_type_id      = rec.test_type_id,
                title             = f"Condition Monitoring — {test_type.name if test_type else 'Test'}",
                frequency         = rec.frequency,
                start_date        = start,
                next_run_date     = next_run_date,
                is_active         = True,
                advance_days      = 15,
                created_by        = activated_by,
            )
        db.add(schedule)

    db.flush()

    # Upsert activation tracking
    activation = db.query(ConditionRecommendationActivation).filter(
        ConditionRecommendationActivation.recommendation_id == rec_id,
        ConditionRecommendationActivation.equipment_id      == equipment_id,
    ).first()

    now = datetime.now(timezone.utc)
    if activation:
        activation.schedule_id  = schedule.id
        activation.status       = "activated"
        activation.activated_by = activated_by
        activation.activated_at = now
    else:
        db.add(ConditionRecommendationActivation(
            recommendation_id = rec_id,
            equipment_id      = equipment_id,
            schedule_id       = schedule.id,
            status            = "activated",
            activated_by      = activated_by,
            activated_at      = now,
            organization_id   = eq.organization_id,
        ))

    db.commit()
    db.refresh(schedule)

    # Trigger immediate ticket creation following the same pattern as
    # TestRequestScheduleService.instantiate_equipment_schedules()
    now = datetime.now(timezone.utc)
    try:
        TestRequestScheduleService.create_one_ticket(db, schedule, now)
    except Exception as e:
        print(f"[WARN] condition monitoring create_one_ticket failed for schedule {schedule.id}: {e}")

    return {
        "created":  True,
        "schedule": {
            "schedule_id":   str(schedule.id),
            "schedule_ref":  _schedule_ref(schedule),
            "frequency":     schedule.frequency.value,
            "next_due_date": _next_date_str(schedule),
            "is_active":     schedule.is_active,
        },
    }
