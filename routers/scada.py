"""
SCADA Router
============

POST /scada/readings          — ingest one reading
POST /scada/readings/batch    — ingest up to 200 readings

GET  /scada/readings          — paginated alarm history for an equipment
GET  /scada/fleet             — latest status per equipment (Fleet Overview)
GET  /scada/equipment/{id}/analytics  — analytics summary per tag
GET  /scada/equipment/{id}/trend      — time-series for one tag

GET  /scada/alert-rules               — list alert rules
POST /scada/alert-rules               — create alert rule
PUT  /scada/alert-rules/{id}          — update alert rule
DELETE /scada/alert-rules/{id}        — deactivate alert rule

GET  /scada/tag-map                   — list tag→equipment mappings
POST /scada/tag-map                   — create mapping (resolves unresolved tag)
GET  /scada/unresolved                — list unmapped tags

POST /scada/analytics/run             — trigger analytics run for org (admin)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    Equipment,
    ScadaAlertRule,
    ScadaParameterAnalytics,
    ScadaReading,
    ScadaTagMap,
    ScadaUnresolved,
    User,
)
from services import scada_alarm_evaluator as evaluator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scada", tags=["SCADA"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ReadingIn(BaseModel):
    scada_tag:   str
    value:       float
    unit:        Optional[str] = None
    recorded_at: Optional[datetime] = None  # defaults to server now()


class BatchReadingsIn(BaseModel):
    readings: List[ReadingIn] = Field(..., max_items=200)


class ReadingOut(BaseModel):
    id:              UUID
    equipment_id:    Optional[UUID]
    scada_tag:       str
    parameter_name:  Optional[str]
    value:           float
    unit:            Optional[str]
    alarm_condition: str
    recorded_at:     datetime


class AlertRuleIn(BaseModel):
    scada_tag:         str
    equipment_id:      Optional[UUID]  = None
    equipment_type_id: Optional[int]   = None
    parameter_name:    Optional[str]   = None
    unit:              Optional[str]   = None
    warning_min:       Optional[float] = None
    warning_max:       Optional[float] = None
    alarm_min:         Optional[float] = None
    alarm_max:         Optional[float] = None
    critical_min:      Optional[float] = None
    critical_max:      Optional[float] = None


class TagMapIn(BaseModel):
    scada_tag:      str
    equipment_id:   UUID
    parameter_name: Optional[str] = None
    unit:           Optional[str] = None


# ── Helper ────────────────────────────────────────────────────────────────────

def _ingest_one(
    db: Session,
    org_id: UUID,
    user_id: UUID,
    reading_in: ReadingIn,
    background_tasks: BackgroundTasks,
) -> ScadaReading:
    recorded_at = reading_in.recorded_at or datetime.now(timezone.utc)

    # Resolve tag → equipment
    tag_map = (
        db.query(ScadaTagMap)
        .filter(
            ScadaTagMap.organization_id == org_id,
            ScadaTagMap.scada_tag == reading_in.scada_tag,
            ScadaTagMap.is_active == True,
        )
        .first()
    )

    equipment_id      = tag_map.equipment_id      if tag_map else None
    parameter_name    = tag_map.parameter_name    if tag_map else None
    unit              = reading_in.unit or (tag_map.unit if tag_map else None)
    equipment_type_id = None

    if equipment_id:
        eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if eq:
            equipment_type_id = eq.equipment_type_id
    else:
        # Stage as unresolved
        unresolved = (
            db.query(ScadaUnresolved)
            .filter(
                ScadaUnresolved.organization_id == org_id,
                ScadaUnresolved.scada_tag == reading_in.scada_tag,
            )
            .first()
        )
        payload = {"scada_tag": reading_in.scada_tag, "value": reading_in.value, "unit": unit}
        if unresolved:
            unresolved.last_seen_at   = datetime.now(timezone.utc)
            unresolved.sample_payload = payload
        else:
            db.add(ScadaUnresolved(
                id              = uuid.uuid4(),
                organization_id = org_id,
                scada_tag       = reading_in.scada_tag,
                sample_payload  = payload,
            ))

    # Evaluate alarm condition
    rule = evaluator.resolve_rule(db, org_id, reading_in.scada_tag, equipment_id, equipment_type_id)
    condition = evaluator.evaluate(reading_in.value, rule)

    reading = ScadaReading(
        id              = uuid.uuid4(),
        organization_id = org_id,
        equipment_id    = equipment_id,
        scada_tag       = reading_in.scada_tag,
        parameter_name  = parameter_name,
        value           = reading_in.value,
        unit            = unit,
        alarm_condition = condition,
        recorded_at     = recorded_at,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    # Fire notification async if alarm
    if condition != evaluator.NORMAL and equipment_id:
        background_tasks.add_task(
            _fire_alarm_notification, reading.id, org_id, condition
        )

    return reading


def _fire_alarm_notification(reading_id: UUID, org_id: UUID, condition: str) -> None:
    from database import get_vendor_db
    db = next(get_vendor_db())
    try:
        from services.notification_service import NotificationService
        event_type = "scada_critical" if condition == evaluator.CRITICAL else "scada_alarm"
        svc = NotificationService(db)
        svc.send(
            organization_id = org_id,
            event_type      = event_type,
            source_type     = "scada_reading",
            source_id       = reading_id,
        )
    except Exception as exc:
        logger.warning("[SCADA] notification failed reading=%s: %s", reading_id, exc)
    finally:
        db.close()


# ── Ingestion endpoints ───────────────────────────────────────────────────────

@router.post("/readings", response_model=ReadingOut, status_code=201)
def ingest_reading(
    body:               ReadingIn,
    background_tasks:   BackgroundTasks,
    db:                 Session = Depends(get_db),
    user: User          = Depends(get_current_user),
):
    org_id  = UUID(user.organization_id)
    user_id = UUID(user.id)
    reading = _ingest_one(db, org_id, user_id, body, background_tasks)
    return ReadingOut(
        id              = reading.id,
        equipment_id    = reading.equipment_id,
        scada_tag       = reading.scada_tag,
        parameter_name  = reading.parameter_name,
        value           = float(reading.value),
        unit            = reading.unit,
        alarm_condition = reading.alarm_condition,
        recorded_at     = reading.recorded_at,
    )


@router.post("/readings/batch", status_code=201)
def ingest_readings_batch(
    body:             BatchReadingsIn,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id  = UUID(user.organization_id)
    user_id = UUID(user.id)
    results = []
    for r in body.readings:
        try:
            reading = _ingest_one(db, org_id, user_id, r, background_tasks)
            results.append({"scada_tag": r.scada_tag, "id": str(reading.id), "alarm_condition": reading.alarm_condition})
        except Exception as exc:
            logger.warning("[SCADA batch] tag=%s error=%s", r.scada_tag, exc)
            results.append({"scada_tag": r.scada_tag, "error": str(exc)})
    return {"processed": len(results), "results": results}


# ── Query endpoints ───────────────────────────────────────────────────────────

@router.get("/readings")
def list_readings(
    equipment_id:    Optional[UUID]   = Query(None),
    scada_tag:       Optional[str]    = Query(None),
    alarm_only:      bool             = Query(False),
    limit:           int              = Query(50, le=500),
    offset:          int              = Query(0),
    db:              Session          = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    q = db.query(ScadaReading).filter(ScadaReading.organization_id == org_id)
    if equipment_id:
        q = q.filter(ScadaReading.equipment_id == equipment_id)
    if scada_tag:
        q = q.filter(ScadaReading.scada_tag == scada_tag)
    if alarm_only:
        q = q.filter(ScadaReading.alarm_condition != "NORMAL")
    total = q.count()
    rows  = q.order_by(ScadaReading.recorded_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id":              str(r.id),
                "equipment_id":    str(r.equipment_id) if r.equipment_id else None,
                "scada_tag":       r.scada_tag,
                "parameter_name":  r.parameter_name,
                "value":           float(r.value),
                "unit":            r.unit,
                "alarm_condition": r.alarm_condition,
                "recorded_at":     r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in rows
        ],
    }


@router.get("/fleet")
def fleet_overview(
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    """Latest alarm status per equipment — for Fleet Overview UI."""
    from sqlalchemy import text
    org_id = user.organization_id
    rows = db.execute(text("""
        SELECT DISTINCT ON (equipment_id)
               equipment_id,
               scada_tag,
               parameter_name,
               value,
               unit,
               alarm_condition,
               recorded_at
        FROM   public.scada_readings
        WHERE  organization_id = :org_id
          AND  equipment_id IS NOT NULL
        ORDER  BY equipment_id, recorded_at DESC
    """), {"org_id": org_id}).fetchall()

    # Aggregate worst condition per equipment
    from collections import defaultdict
    _rank = {"NORMAL": 0, "WARNING": 1, "ALARM": 2, "CRITICAL": 3}
    eq_map: dict = defaultdict(lambda: {"tags": [], "worst_condition": "NORMAL"})
    for r in rows:
        eid = str(r.equipment_id)
        eq_map[eid]["equipment_id"] = eid
        eq_map[eid]["tags"].append({
            "scada_tag":       r.scada_tag,
            "parameter_name":  r.parameter_name,
            "value":           float(r.value),
            "unit":            r.unit,
            "alarm_condition": r.alarm_condition,
            "recorded_at":     r.recorded_at.isoformat() if r.recorded_at else None,
        })
        if _rank.get(r.alarm_condition, 0) > _rank.get(eq_map[eid]["worst_condition"], 0):
            eq_map[eid]["worst_condition"] = r.alarm_condition

    return {"items": list(eq_map.values())}


@router.get("/equipment/{equipment_id}/analytics")
def equipment_analytics(
    equipment_id: UUID,
    db:           Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    """Analytics summary for all tags of one equipment."""
    org_id = UUID(user.organization_id)
    rows = (
        db.query(ScadaParameterAnalytics)
        .filter(
            ScadaParameterAnalytics.organization_id == org_id,
            ScadaParameterAnalytics.equipment_id == equipment_id,
        )
        .all()
    )
    return {
        "equipment_id": str(equipment_id),
        "tags": [
            {
                "scada_tag":           r.scada_tag,
                "parameter_name":      r.parameter_name,
                "computed_at":         r.computed_at.isoformat() if r.computed_at else None,
                "history_count":       r.history_count,
                "trend":               r.trend,
                "annual_change":       float(r.annual_change) if r.annual_change else None,
                "pct_change_annual":   float(r.pct_change_annual) if r.pct_change_annual else None,
                "is_anomaly":          r.is_anomaly,
                "anomaly_type":        r.anomaly_type,
                "days_to_breach":      float(r.days_to_breach) if r.days_to_breach else None,
                "breach_predicted_at": r.breach_predicted_at.isoformat() if r.breach_predicted_at else None,
            }
            for r in rows
        ],
    }


@router.get("/equipment/{equipment_id}/trend")
def equipment_trend(
    equipment_id: UUID,
    scada_tag:    str   = Query(...),
    hours:        int   = Query(168, le=8760),  # default 7 days, max 1 year
    db:           Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    """Raw time-series for one tag — for Equipment Trend View chart."""
    from sqlalchemy import text
    org_id = user.organization_id
    rows = db.execute(text("""
        SELECT recorded_at, value, alarm_condition
        FROM   public.scada_readings
        WHERE  organization_id = :org_id
          AND  equipment_id    = :eid
          AND  scada_tag       = :tag
          AND  recorded_at     > now() - interval ':hours hours'
        ORDER  BY recorded_at ASC
    """), {"org_id": org_id, "eid": str(equipment_id), "tag": scada_tag, "hours": hours}).fetchall()

    return {
        "equipment_id": str(equipment_id),
        "scada_tag":    scada_tag,
        "points": [
            {
                "ts":              r.recorded_at.isoformat(),
                "value":           float(r.value),
                "alarm_condition": r.alarm_condition,
            }
            for r in rows
        ],
    }


# ── Alert Rules ───────────────────────────────────────────────────────────────

@router.get("/alert-rules")
def list_alert_rules(
    equipment_id: Optional[UUID] = Query(None),
    db:           Session        = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    q = db.query(ScadaAlertRule).filter(
        ScadaAlertRule.organization_id == org_id,
        ScadaAlertRule.is_active == True,
    )
    if equipment_id:
        q = q.filter(ScadaAlertRule.equipment_id == equipment_id)
    return [
        {
            "id":                str(r.id),
            "scada_tag":         r.scada_tag,
            "equipment_id":      str(r.equipment_id) if r.equipment_id else None,
            "equipment_type_id": r.equipment_type_id,
            "parameter_name":    r.parameter_name,
            "unit":              r.unit,
            "warning_min":       float(r.warning_min)  if r.warning_min  else None,
            "warning_max":       float(r.warning_max)  if r.warning_max  else None,
            "alarm_min":         float(r.alarm_min)    if r.alarm_min    else None,
            "alarm_max":         float(r.alarm_max)    if r.alarm_max    else None,
            "critical_min":      float(r.critical_min) if r.critical_min else None,
            "critical_max":      float(r.critical_max) if r.critical_max else None,
        }
        for r in q.all()
    ]


@router.post("/alert-rules", status_code=201)
def create_alert_rule(
    body:      AlertRuleIn,
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    if not body.equipment_id and not body.equipment_type_id:
        raise HTTPException(400, "Provide equipment_id or equipment_type_id")
    rule = ScadaAlertRule(
        id                = uuid.uuid4(),
        organization_id   = org_id,
        equipment_id      = body.equipment_id,
        equipment_type_id = body.equipment_type_id,
        scada_tag         = body.scada_tag,
        parameter_name    = body.parameter_name,
        unit              = body.unit,
        warning_min       = body.warning_min,
        warning_max       = body.warning_max,
        alarm_min         = body.alarm_min,
        alarm_max         = body.alarm_max,
        critical_min      = body.critical_min,
        critical_max      = body.critical_max,
        created_by        = UUID(user.id),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": str(rule.id), "message": "Alert rule created"}


@router.put("/alert-rules/{rule_id}")
def update_alert_rule(
    rule_id:   UUID,
    body:      AlertRuleIn,
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    rule = db.query(ScadaAlertRule).filter(
        ScadaAlertRule.id == rule_id,
        ScadaAlertRule.organization_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    for field in ["warning_min", "warning_max", "alarm_min", "alarm_max", "critical_min", "critical_max", "parameter_name", "unit"]:
        val = getattr(body, field, None)
        if val is not None:
            setattr(rule, field, val)
    db.commit()
    return {"id": str(rule.id), "message": "Updated"}


@router.delete("/alert-rules/{rule_id}")
def deactivate_alert_rule(
    rule_id:   UUID,
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    rule = db.query(ScadaAlertRule).filter(
        ScadaAlertRule.id == rule_id,
        ScadaAlertRule.organization_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    rule.is_active = False
    db.commit()
    return {"message": "Deactivated"}


# ── Tag Map ───────────────────────────────────────────────────────────────────

@router.get("/tag-map")
def list_tag_map(
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    rows = db.query(ScadaTagMap).filter(
        ScadaTagMap.organization_id == org_id,
        ScadaTagMap.is_active == True,
    ).all()
    return [
        {
            "id":            str(r.id),
            "scada_tag":     r.scada_tag,
            "equipment_id":  str(r.equipment_id),
            "parameter_name": r.parameter_name,
            "unit":          r.unit,
        }
        for r in rows
    ]


@router.post("/tag-map", status_code=201)
def create_tag_mapping(
    body:      TagMapIn,
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id  = UUID(user.organization_id)
    user_id = UUID(user.id)

    existing = db.query(ScadaTagMap).filter(
        ScadaTagMap.organization_id == org_id,
        ScadaTagMap.scada_tag == body.scada_tag,
    ).first()
    if existing:
        existing.equipment_id  = body.equipment_id
        existing.parameter_name = body.parameter_name
        existing.unit          = body.unit
        existing.is_active     = True
    else:
        db.add(ScadaTagMap(
            id              = uuid.uuid4(),
            organization_id = org_id,
            scada_tag       = body.scada_tag,
            equipment_id    = body.equipment_id,
            parameter_name  = body.parameter_name,
            unit            = body.unit,
            created_by      = user_id,
        ))

    # Mark unresolved as resolved
    unresolved = db.query(ScadaUnresolved).filter(
        ScadaUnresolved.organization_id == org_id,
        ScadaUnresolved.scada_tag == body.scada_tag,
    ).first()
    if unresolved:
        unresolved.resolved    = True
        unresolved.resolved_at = datetime.now(timezone.utc)
        unresolved.resolved_by = user_id

    # Back-fill equipment_id on recent unresolved readings
    from sqlalchemy import text
    db.execute(text("""
        UPDATE public.scada_readings
        SET    equipment_id = :eid
        WHERE  organization_id = :org_id
          AND  scada_tag       = :tag
          AND  equipment_id IS NULL
          AND  recorded_at    > now() - interval '7 days'
    """), {"eid": str(body.equipment_id), "org_id": str(org_id), "tag": body.scada_tag})

    db.commit()
    return {"message": "Tag mapping created", "scada_tag": body.scada_tag}


@router.get("/unresolved")
def list_unresolved(
    db:        Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    org_id = UUID(user.organization_id)
    rows = db.query(ScadaUnresolved).filter(
        ScadaUnresolved.organization_id == org_id,
        ScadaUnresolved.resolved == False,
    ).order_by(ScadaUnresolved.last_seen_at.desc()).all()
    return [
        {
            "id":            str(r.id),
            "scada_tag":     r.scada_tag,
            "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at":  r.last_seen_at.isoformat()  if r.last_seen_at  else None,
            "sample_payload": r.sample_payload,
        }
        for r in rows
    ]


# ── Admin: trigger analytics run ──────────────────────────────────────────────

@router.post("/analytics/run")
def trigger_analytics_run(
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    """Manually trigger the scheduled analytics runner for this org."""
    org_id = UUID(user.organization_id)

    def _run():
        from database import get_vendor_db
        _db = next(get_vendor_db())
        try:
            from services.scada_analytics_runner import run_for_organization
            run_for_organization(_db, org_id)
        finally:
            _db.close()

    background_tasks.add_task(_run)
    return {"message": "Analytics run queued"}
