"""
SCADA Alarm Evaluator
=====================
Stateless — compares a single reading value against the configured
scada_alert_rules thresholds and returns an alarm condition string.

Runs inline on every POST /scada/readings — no history query needed.

Resolution order for rules:
  1. equipment-level rule   (most specific)
  2. equipment-type-level rule
  3. no rule → NORMAL
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

NORMAL   = "NORMAL"
WARNING  = "WARNING"
ALARM    = "ALARM"
CRITICAL = "CRITICAL"


def evaluate(value: float, rule) -> str:
    """Return alarm condition for *value* given *rule* (ScadaAlertRule ORM row or None)."""
    if rule is None:
        return NORMAL

    v = float(value)

    if rule.critical_min is not None and v < float(rule.critical_min):
        return CRITICAL
    if rule.critical_max is not None and v > float(rule.critical_max):
        return CRITICAL

    if rule.alarm_min is not None and v < float(rule.alarm_min):
        return ALARM
    if rule.alarm_max is not None and v > float(rule.alarm_max):
        return ALARM

    if rule.warning_min is not None and v < float(rule.warning_min):
        return WARNING
    if rule.warning_max is not None and v > float(rule.warning_max):
        return WARNING

    return NORMAL


def resolve_rule(
    db: Session,
    organization_id: UUID,
    scada_tag: str,
    equipment_id: Optional[UUID],
    equipment_type_id: Optional[int],
):
    """
    Return the best-matching ScadaAlertRule for this tag, or None.
    Equipment-level rule takes priority over equipment-type-level rule.
    """
    from models import ScadaAlertRule

    if equipment_id:
        rule = (
            db.query(ScadaAlertRule)
            .filter(
                ScadaAlertRule.organization_id == organization_id,
                ScadaAlertRule.equipment_id == equipment_id,
                ScadaAlertRule.scada_tag == scada_tag,
                ScadaAlertRule.is_active == True,
            )
            .first()
        )
        if rule:
            return rule

    if equipment_type_id:
        rule = (
            db.query(ScadaAlertRule)
            .filter(
                ScadaAlertRule.organization_id == organization_id,
                ScadaAlertRule.equipment_id == None,
                ScadaAlertRule.equipment_type_id == equipment_type_id,
                ScadaAlertRule.scada_tag == scada_tag,
                ScadaAlertRule.is_active == True,
            )
            .first()
        )
        if rule:
            return rule

    return None
