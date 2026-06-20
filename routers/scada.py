"""
SCADA Integration Router
========================
POST  /scada/readings           – ingest single reading
POST  /scada/readings/batch     – ingest up to 500 readings
GET   /scada/readings           – paginated reading list (optional equipment/tag filter)
GET   /scada/fleet              – per-equipment worst alarm condition summary
GET   /scada/equipment/{id}/analytics  – SCADA parameter analytics for an equipment
GET   /scada/equipment/{id}/trend      – time-series data for a single tag
GET   /scada/alert-rules        – list alert rules
POST  /scada/alert-rules        – create alert rule
PUT   /scada/alert-rules/{id}   – update alert rule
DELETE /scada/alert-rules/{id}  – delete alert rule
GET   /scada/tag-map            – list tag mappings (+ unresolved)
POST  /scada/tag-map            – create tag mapping
GET   /scada/unresolved         – list unresolved tags
POST  /scada/analytics/run      – trigger analytics run (admin)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    ScadaAlertRule,
    ScadaParameterAnalytics,
    ScadaReading,
    ScadaTagMap,
    ScadaUnresolved,
)
from services.scada_alarm_evaluator import evaluate as _evaluate, resolve_rule

router = APIRouter(prefix="/scada", tags=["SCADA"])


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class ReadingIn(BaseModel):
    scada_tag: str
    value: float
    unit: Optional[str] = None
    parameter_name: Optional[str] = None
    recorded_at: Optional[datetime] = None


class BatchReadingsIn(BaseModel):
    readings: List[ReadingIn]


class ReadingOut(BaseModel):
    id: UUID
    scada_tag: str
    parameter_name: Optional[str]
    value: float
    unit: Optional[str]
    alarm_condition: str
    recorded_at: datetime
    equipment_id: Optional[UUID]

    class Config:
        from_attributes = True


class AlertRuleIn(BaseModel):
    scada_tag: str
    parameter_name: Optional[str] = None
    unit: Optional[str] = None
    equipment_id: Optional[UUID] = None
    equipment_type_id: Optional[int] = None
    warning_min: Optional[float] = None
    warning_max: Optional[float] = None
    alarm_min: Optional[float] = None
    alarm_max: Optional[float] = None
    critical_min: Optional[float] = None
    critical_max: Optional[float] = None


class TagMapIn(BaseModel):
    scada_tag: str
    equipment_id: UUID
    parameter_name: Optional[str] = None
    unit: Optional[str] = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_equipment(db: Session, organization_id: UUID, scada_tag: str):
    """Return (equipment_id, equipment_type_id) or (None, None)."""
    mapping = db.query(ScadaTagMap).filter(
        ScadaTagMap.organization_id == organization_id,
        ScadaTagMap.scada_tag == scada_tag,
        ScadaTagMap.is_active == True,
    ).first()
    if not mapping:
        return None, None
    from models import Equipment
    eq = db.query(Equipment).filter(Equipment.id == mapping.equipment_id).first()
    equipment_type_id = getattr(eq, "equipment_type_id", None) if eq else None
    return mapping.equipment_id, equipment_type_id


def _stage_unresolved(db: Session, organization_id: UUID, scada_tag: str, payload: dict):
    existing = db.query(ScadaUnresolved).filter(
        ScadaUnresolved.organization_id == organization_id,
        ScadaUnresolved.scada_tag == scada_tag,
    ).first()
    if existing:
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.resolved = False
    else:
        db.add(ScadaUnresolved(
            id=uuid.uuid4(),
            organization_id=organization_id,
            scada_tag=scada_tag,
            sample_payload=payload,
        ))


def _ingest_one(
    db: Session,
    organization_id: UUID,
    reading_in: ReadingIn,
    background_tasks: BackgroundTasks,
    current_user,
) -> ScadaReading:
    equipment_id, equipment_type_id = _resolve_equipment(db, organization_id, reading_in.scada_tag)
    if equipment_id is None:
        _stage_unresolved(db, organization_id, reading_in.scada_tag, reading_in.model_dump())

    rule = resolve_rule(db, organization_id, reading_in.scada_tag, equipment_id, equipment_type_id)
    condition = _evaluate(reading_in.value, rule)

    reading = ScadaReading(
        id=uuid.uuid4(),
        organization_id=organization_id,
        equipment_id=equipment_id,
        scada_tag=reading_in.scada_tag,
        parameter_name=reading_in.parameter_name,
        value=reading_in.value,
        unit=reading_in.unit,
        alarm_condition=condition,
        recorded_at=reading_in.recorded_at or datetime.now(timezone.utc),
    )
    db.add(reading)
    db.flush()  # get reading.id before commit

    if condition != "NORMAL":
        reading_id = reading.id

        def _fire(rid: UUID, cond: str, org_id: UUID):
            from database import VendorSessionLocal as SessionLocal
            _db = SessionLocal()
            try:
                from services.notification_service import NotificationService
                event_type = "scada_critical" if cond == "CRITICAL" else "scada_alarm"
                NotificationService(_db).send(
                    organization_id=org_id,
                    event_type=event_type,
                    source_type="scada_reading",
                    source_id=rid,
                )
                _db.commit()
            except Exception:
                pass
            finally:
                _db.close()

        background_tasks.add_task(_fire, reading_id, condition, organization_id)

    return reading


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/readings", response_model=ReadingOut, status_code=201)
def ingest_reading(
    payload: ReadingIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    org_id = current_user.organization_id
    reading = _ingest_one(db, org_id, payload, background_tasks, current_user)
    db.commit()
    db.refresh(reading)
    return reading


@router.post("/readings/batch", status_code=201)
def ingest_readings_batch(
    payload: BatchReadingsIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if len(payload.readings) > 500:
        raise HTTPException(400, "Batch limit is 500 readings")
    org_id = current_user.organization_id
    ids = []
    for r in payload.readings:
        reading = _ingest_one(db, org_id, r, background_tasks, current_user)
        ids.append(str(reading.id))
    db.commit()
    return {"inserted": len(ids), "ids": ids}


@router.get("/readings", response_model=List[ReadingOut])
def list_readings(
    equipment_id: Optional[UUID] = None,
    scada_tag: Optional[str] = None,
    alarm_only: bool = False,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(ScadaReading).filter(ScadaReading.organization_id == current_user.organization_id)
    if equipment_id:
        q = q.filter(ScadaReading.equipment_id == equipment_id)
    if scada_tag:
        q = q.filter(ScadaReading.scada_tag == scada_tag)
    if alarm_only:
        q = q.filter(ScadaReading.alarm_condition != "NORMAL")
    return q.order_by(ScadaReading.recorded_at.desc()).offset(offset).limit(limit).all()


@router.get("/fleet")
def fleet_overview(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Latest reading per (equipment, tag) — then aggregate tags per equipment
    rows = db.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (equipment_id, scada_tag)
                   equipment_id, scada_tag, parameter_name,
                   value, unit, alarm_condition, recorded_at
            FROM   public.scada_readings
            WHERE  organization_id = :org_id
              AND  equipment_id IS NOT NULL
            ORDER  BY equipment_id, scada_tag, recorded_at DESC
        )
        SELECT
            l.equipment_id::text,
            COALESCE(cm.name || ' — ' || e.ueic, e.ueic) AS equipment_name,
            e.ueic,
            (
                SELECT alarm_condition
                FROM   latest l2
                WHERE  l2.equipment_id = l.equipment_id
                ORDER  BY CASE alarm_condition
                              WHEN 'CRITICAL' THEN 1
                              WHEN 'ALARM'    THEN 2
                              WHEN 'WARNING'  THEN 3
                              ELSE 4 END
                LIMIT 1
            ) AS worst_condition,
            json_agg(
                json_build_object(
                    'scada_tag',       l.scada_tag,
                    'parameter_name',  l.parameter_name,
                    'value',           l.value::float8,
                    'unit',            l.unit,
                    'alarm_condition', l.alarm_condition,
                    'recorded_at',     l.recorded_at
                )
                ORDER BY l.scada_tag
            ) AS tags
        FROM   latest l
        JOIN   public.equipment e  ON e.id = l.equipment_id
        LEFT   JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        GROUP  BY l.equipment_id, e.ueic, cm.name
        ORDER  BY equipment_name
    """), {"org_id": str(current_user.organization_id)}).fetchall()

    return [dict(r._mapping) for r in rows]


@router.get("/equipment/{equipment_id}/analytics")
def equipment_analytics(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = db.query(ScadaParameterAnalytics).filter(
        ScadaParameterAnalytics.organization_id == current_user.organization_id,
        ScadaParameterAnalytics.equipment_id == equipment_id,
    ).all()
    # Coerce Decimal columns to float so JSON serialization is numeric not string
    def _row(r):
        return {
            "scada_tag":          r.scada_tag,
            "parameter_name":     r.parameter_name,
            "computed_at":        r.computed_at,
            "trend":              r.trend,
            "trend_slope":        float(r.trend_slope)        if r.trend_slope        is not None else None,
            "trend_r_squared":    float(r.trend_r_squared)    if r.trend_r_squared    is not None else None,
            "annual_change":      float(r.annual_change)      if r.annual_change      is not None else None,
            "pct_change_annual":  float(r.pct_change_annual)  if r.pct_change_annual  is not None else None,
            "is_anomaly":         r.is_anomaly,
            "anomaly_type":       r.anomaly_type,
            "anomaly_detail":     r.anomaly_detail,
            "breach_threshold":   float(r.breach_threshold)   if r.breach_threshold   is not None else None,
            "days_to_breach":     float(r.days_to_breach)     if r.days_to_breach     is not None else None,
            "breach_predicted_at": r.breach_predicted_at,
        }
    return [_row(r) for r in rows]


@router.get("/equipment/{equipment_id}/trend")
def equipment_trend(
    equipment_id: UUID,
    scada_tag: str,
    hours: int = Query(24, ge=1, le=2160),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = db.execute(text("""
        SELECT recorded_at AS ts, value::float8 AS value, alarm_condition
        FROM   public.scada_readings
        WHERE  organization_id = :org_id
          AND  equipment_id    = :eid
          AND  scada_tag       = :tag
          AND  recorded_at     > now() - (:hours || ' hours')::interval
        ORDER  BY recorded_at ASC
    """), {
        "org_id": str(current_user.organization_id),
        "eid":    str(equipment_id),
        "tag":    scada_tag,
        "hours":  hours,
    }).fetchall()
    return [dict(r._mapping) for r in rows]


# ─── Equipment Types (SCADA-instrumented) ────────────────────────────────────

@router.get("/equipment-types")
def list_scada_equipment_types(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return distinct equipment types that have at least one SCADA-tagged equipment."""
    rows = db.execute(text("""
        SELECT DISTINCT cm.id, cm.name
        FROM   public.equipment e
        JOIN   public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        WHERE  e.organization_id = :org
        AND    e.scada_tag IS NOT NULL
        ORDER  BY cm.name
    """), {"org": str(current_user.organization_id)}).fetchall()
    return [{"id": str(r[0]), "name": r[1]} for r in rows]


# ─── Alert Rules ─────────────────────────────────────────────────────────────

@router.get("/alert-rules")
def list_alert_rules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rules = db.query(ScadaAlertRule).filter(
        ScadaAlertRule.organization_id == current_user.organization_id,
        ScadaAlertRule.is_active == True,
    ).all()
    def _f(v):
        return float(v) if v is not None else None
    def _rule(r):
        return {
            "id":                str(r.id),
            "scada_tag":         r.scada_tag,
            "parameter_name":    r.parameter_name,
            "unit":              r.unit,
            "equipment_id":      str(r.equipment_id) if r.equipment_id else None,
            "equipment_type_id": r.equipment_type_id,
            "warning_min":       _f(r.warning_min),
            "warning_max":       _f(r.warning_max),
            "alarm_min":         _f(r.alarm_min),
            "alarm_max":         _f(r.alarm_max),
            "critical_min":      _f(r.critical_min),
            "critical_max":      _f(r.critical_max),
        }
    return [_rule(r) for r in rules]


@router.post("/alert-rules", status_code=201)
def create_alert_rule(
    payload: AlertRuleIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = ScadaAlertRule(
        id=uuid.uuid4(),
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/alert-rules/{rule_id}")
def update_alert_rule(
    rule_id: UUID,
    payload: AlertRuleIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = db.query(ScadaAlertRule).filter(
        ScadaAlertRule.id == rule_id,
        ScadaAlertRule.organization_id == current_user.organization_id,
    ).first()
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = db.query(ScadaAlertRule).filter(
        ScadaAlertRule.id == rule_id,
        ScadaAlertRule.organization_id == current_user.organization_id,
    ).first()
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    rule.is_active = False
    db.commit()


# ─── Tag Mapping ─────────────────────────────────────────────────────────────

@router.get("/tag-map")
def list_tag_map(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    mappings = db.query(ScadaTagMap).filter(
        ScadaTagMap.organization_id == current_user.organization_id,
        ScadaTagMap.is_active == True,
    ).all()
    return mappings


@router.post("/tag-map", status_code=201)
def create_tag_mapping(
    payload: TagMapIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    existing = db.query(ScadaTagMap).filter(
        ScadaTagMap.organization_id == current_user.organization_id,
        ScadaTagMap.scada_tag == payload.scada_tag,
    ).first()
    if existing:
        existing.equipment_id   = payload.equipment_id
        existing.parameter_name = payload.parameter_name
        existing.unit           = payload.unit
        existing.is_active      = True
        db.commit()
        db.refresh(existing)
        # mark unresolved as resolved
        unresolved = db.query(ScadaUnresolved).filter(
            ScadaUnresolved.organization_id == current_user.organization_id,
            ScadaUnresolved.scada_tag == payload.scada_tag,
        ).first()
        if unresolved:
            unresolved.resolved    = True
            unresolved.resolved_at = datetime.now(timezone.utc)
            unresolved.resolved_by = current_user.id
        _backfill_readings(db, current_user.organization_id, payload.scada_tag,
                           payload.equipment_id)
        db.commit()
        return existing

    mapping = ScadaTagMap(
        id=uuid.uuid4(),
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(mapping)

    unresolved = db.query(ScadaUnresolved).filter(
        ScadaUnresolved.organization_id == current_user.organization_id,
        ScadaUnresolved.scada_tag == payload.scada_tag,
    ).first()
    if unresolved:
        unresolved.resolved    = True
        unresolved.resolved_at = datetime.now(timezone.utc)
        unresolved.resolved_by = current_user.id

    db.commit()
    db.refresh(mapping)

    # Back-fill last 7 days of readings that arrived before the mapping existed
    _backfill_readings(db, current_user.organization_id, payload.scada_tag,
                       payload.equipment_id)
    db.commit()
    return mapping


def _backfill_readings(db: Session, organization_id, scada_tag: str, equipment_id) -> None:
    db.execute(text("""
        UPDATE public.scada_readings
        SET    equipment_id = :eid
        WHERE  organization_id = :org_id
          AND  scada_tag       = :tag
          AND  equipment_id IS NULL
          AND  recorded_at     > now() - interval '7 days'
    """), {"eid": str(equipment_id), "org_id": str(organization_id), "tag": scada_tag})


@router.get("/unresolved")
def list_unresolved(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return db.query(ScadaUnresolved).filter(
        ScadaUnresolved.organization_id == current_user.organization_id,
        ScadaUnresolved.resolved == False,
    ).order_by(ScadaUnresolved.last_seen_at.desc()).all()


# ─── Analytics trigger ───────────────────────────────────────────────────────

@router.post("/analytics/run", status_code=202)
def trigger_analytics(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    org_id = current_user.organization_id

    def _run(oid: UUID):
        from database import VendorSessionLocal as SessionLocal
        _db = SessionLocal()
        try:
            from services.scada_analytics_runner import run_for_organization
            run_for_organization(_db, oid)
            _db.commit()
        except Exception:
            pass
        finally:
            _db.close()

    background_tasks.add_task(_run, org_id)
    return {"status": "queued"}
