"""
SCADA Analytics Runner
======================
Scheduled (hourly / daily) — NOT called on every reading insert.

For each (equipment, scada_tag) pair:
  1. Fetch last 90 days of readings from scada_readings
  2. Downsample to hourly averages (keeps point count manageable)
  3. Build evaluation dict from scada_alert_rules thresholds
  4. Delegate to existing ParameterAnalyzer.analyse() — unchanged
  5. Upsert scada_parameter_analytics
  6. If days_to_breach < 48h → fire breach forecast notification

Call run_for_organization(db, org_id) from a Celery beat task or cron.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.analytics_engine import ParameterAnalyzer

logger = logging.getLogger(__name__)

HISTORY_DAYS            = 90
BREACH_ALERT_HOURS      = 48


def run_for_organization(db: Session, organization_id: UUID) -> None:
    """Run analytics for every active (equipment, tag) pair in the org."""
    rows = db.execute(text("""
        SELECT DISTINCT equipment_id, scada_tag
        FROM   public.scada_readings
        WHERE  organization_id = :org_id
          AND  equipment_id IS NOT NULL
          AND  recorded_at > now() - interval '90 days'
    """), {"org_id": str(organization_id)}).fetchall()

    for row in rows:
        try:
            run_for_equipment_tag(db, organization_id, row.equipment_id, row.scada_tag)
        except Exception as exc:
            logger.warning(
                "[SCADA Analytics] equipment=%s tag=%s error=%s",
                row.equipment_id, row.scada_tag, exc,
            )


def run_for_equipment_tag(
    db: Session,
    organization_id: UUID,
    equipment_id: UUID,
    scada_tag: str,
) -> None:
    """Run analytics for one (equipment, scada_tag) pair."""
    # 1. Downsample to hourly averages
    rows = db.execute(text("""
        SELECT date_trunc('hour', recorded_at) AS hour,
               AVG(value)                      AS avg_val
        FROM   public.scada_readings
        WHERE  equipment_id = :eid
          AND  scada_tag    = :tag
          AND  recorded_at  > now() - interval ':days days'
        GROUP  BY 1
        ORDER  BY 1
    """), {
        "eid":  str(equipment_id),
        "tag":  scada_tag,
        "days": HISTORY_DAYS,
    }).fetchall()

    if not rows:
        return

    history = [(r.hour, float(r.avg_val)) for r in rows]

    # 2. Get threshold bounds from alert rules
    from models import ScadaAlertRule, Equipment
    eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    equipment_type_id = eq.equipment_type_id if eq else None

    from services.scada_alarm_evaluator import resolve_rule
    rule = resolve_rule(db, organization_id, scada_tag, equipment_id, equipment_type_id)

    evaluation = {}
    if rule:
        if rule.alarm_min is not None:
            evaluation["alert_min"] = float(rule.alarm_min)
        if rule.alarm_max is not None:
            evaluation["alert_max"] = float(rule.alarm_max)
        if rule.critical_min is not None:
            evaluation["critical_below"] = float(rule.critical_min)
        if rule.critical_max is not None:
            evaluation["critical_above"] = float(rule.critical_max)

    # 3. Run existing ParameterAnalyzer — zero changes to analytics_engine.py
    result = ParameterAnalyzer.analyse(history, evaluation)

    # 4. Upsert scada_parameter_analytics
    _upsert_analytics(db, organization_id, equipment_id, scada_tag, rule, result)

    # 5. Breach forecast notification
    dtb = result.get("days_to_breach")
    if dtb is not None and dtb <= (BREACH_ALERT_HOURS / 24):
        _fire_breach_notification(db, organization_id, equipment_id, scada_tag, result)

    db.commit()


def _upsert_analytics(
    db: Session,
    organization_id: UUID,
    equipment_id: UUID,
    scada_tag: str,
    rule,
    result: dict,
) -> None:
    from models import ScadaParameterAnalytics

    parameter_name = rule.parameter_name if rule else None

    existing = (
        db.query(ScadaParameterAnalytics)
        .filter(
            ScadaParameterAnalytics.equipment_id == equipment_id,
            ScadaParameterAnalytics.scada_tag == scada_tag,
        )
        .first()
    )

    if existing:
        existing.computed_at         = datetime.now(timezone.utc)
        existing.history_count       = result.get("history_count")
        existing.trend               = result.get("trend")
        existing.trend_slope         = result.get("trend_slope")
        existing.trend_r_squared     = result.get("trend_r_squared")
        existing.annual_change       = result.get("annual_change")
        existing.pct_change_annual   = result.get("pct_change_annual")
        existing.is_anomaly          = result.get("is_anomaly", False)
        existing.anomaly_type        = result.get("anomaly_type")
        existing.anomaly_detail      = result.get("anomaly_detail")
        existing.breach_threshold    = result.get("breach_threshold")
        existing.breach_predicted_at = result.get("breach_predicted_at")
        existing.days_to_breach      = result.get("days_to_breach")
        if parameter_name:
            existing.parameter_name  = parameter_name
    else:
        analytics = ScadaParameterAnalytics(
            id                  = uuid.uuid4(),
            organization_id     = organization_id,
            equipment_id        = equipment_id,
            scada_tag           = scada_tag,
            parameter_name      = parameter_name,
            history_count       = result.get("history_count"),
            trend               = result.get("trend"),
            trend_slope         = result.get("trend_slope"),
            trend_r_squared     = result.get("trend_r_squared"),
            annual_change       = result.get("annual_change"),
            pct_change_annual   = result.get("pct_change_annual"),
            is_anomaly          = result.get("is_anomaly", False),
            anomaly_type        = result.get("anomaly_type"),
            anomaly_detail      = result.get("anomaly_detail"),
            breach_threshold    = result.get("breach_threshold"),
            breach_predicted_at = result.get("breach_predicted_at"),
            days_to_breach      = result.get("days_to_breach"),
        )
        db.add(analytics)


def _fire_breach_notification(
    db: Session,
    organization_id: UUID,
    equipment_id: UUID,
    scada_tag: str,
    result: dict,
) -> None:
    try:
        from models import ScadaReading
        latest = (
            db.query(ScadaReading)
            .filter(
                ScadaReading.equipment_id == equipment_id,
                ScadaReading.scada_tag == scada_tag,
            )
            .order_by(ScadaReading.recorded_at.desc())
            .first()
        )
        if not latest:
            return

        from services.notification_service import NotificationService
        svc = NotificationService(db)
        svc.send(
            organization_id = organization_id,
            event_type      = "scada_breach_forecast",
            source_type     = "scada_reading",
            source_id       = latest.id,
            extra_ctx       = {
                "scada.days_to_breach": str(round(result.get("days_to_breach", 0), 1)),
                "scada.breach_date":    str(result.get("breach_predicted_at", ""))[:10],
                "scada.trend":          result.get("trend", ""),
            },
        )
    except Exception as exc:
        logger.warning("[SCADA Analytics] breach notification failed: %s", exc)
