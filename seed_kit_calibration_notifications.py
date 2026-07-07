"""
seed_kit_calibration_notifications.py
──────────────────────────────────────
Seeds notification variables, event catalogue entries, and templates
for test kit calibration due / overdue events.

Call from seed.py after _seed_notification_variables and
_seed_notification_event_catalogue have run.
"""

from __future__ import annotations

from models import (
    NotificationEventCatalogue,
    NotificationRoutingRule,
    NotificationTemplate,
    NotificationVariable,
)


# ── Variables ─────────────────────────────────────────────────────────────────

_KIT_VARIABLES = [
    dict(var_key="kit.ueic",
         label="Kit UEIC",
         group_name="Testing Kit",
         resolver_key="kit.ueic",
         fallback_keys=["kit.ueic"],
         description="Unique Equipment Identity Code of the testing kit.",
         sample_value="KIT-IR-001"),
    dict(var_key="kit.name",
         label="Kit Name",
         group_name="Testing Kit",
         resolver_key="kit.name",
         fallback_keys=["kit.name"],
         description="Name / description of the testing kit.",
         sample_value="Insulation Resistance Tester"),
    dict(var_key="kit.department",
         label="Kit Department",
         group_name="Testing Kit",
         resolver_key="kit.department",
         fallback_keys=["kit.department"],
         description="Department or substation where the testing kit is based.",
         sample_value="Bangalore Zone"),
    dict(var_key="kit.calibration_due_date",
         label="Calibration Due Date",
         group_name="Testing Kit",
         resolver_key="kit.calibration_due_date",
         fallback_keys=["kit.calibration_due_date"],
         description="Date on which the kit's calibration certificate expires.",
         sample_value="2025-06-30"),
    dict(var_key="kit.days_remaining",
         label="Days Until Calibration Due",
         group_name="Testing Kit",
         resolver_key="kit.days_remaining",
         fallback_keys=["kit.days_remaining"],
         description="Number of days remaining before calibration is due.",
         sample_value="14"),
    dict(var_key="kit.days_overdue",
         label="Days Overdue (Calibration)",
         group_name="Testing Kit",
         resolver_key="kit.days_overdue",
         fallback_keys=["kit.days_overdue"],
         description="Number of days the calibration certificate has been expired.",
         sample_value="5"),
]


# ── Event catalogue ───────────────────────────────────────────────────────────

_KIT_EVENTS = [
    dict(
        event_type="kit_calibration_due",
        label="Test Kit Calibration Due Soon",
        group_name="Testing Kit",
        description="Fired when a testing kit's calibration is due within the lead-day window.",
        context_vars=["kit.ueic", "kit.name", "kit.department",
                      "kit.calibration_due_date", "kit.days_remaining"],
        default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        is_active=True,
    ),
    dict(
        event_type="kit_calibration_overdue",
        label="Test Kit Calibration Overdue",
        group_name="Testing Kit",
        description="Fired when a testing kit's calibration certificate has expired.",
        context_vars=["kit.ueic", "kit.name", "kit.department",
                      "kit.calibration_due_date", "kit.days_overdue"],
        default_roles=["EE_TLSS", "AEE_MAINTENANCE", "SEE_WM"],
        is_active=True,
    ),
]


# ── Templates ─────────────────────────────────────────────────────────────────

_KIT_TEMPLATES = [
    # kit_calibration_due — email
    dict(
        event_type="kit_calibration_due",
        channel="email",
        subject_template="Calibration Due in {{kit.days_remaining}} days — {{kit.ueic}}",
        body_template="""<p>Dear Team,</p>
<p>The calibration certificate for testing kit <strong>{{kit.ueic}}</strong> ({{kit.name}}) is due for renewal.</p>
<table style="border-collapse:collapse;font-size:13px;">
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Kit</td><td><strong>{{kit.ueic}}</strong> — {{kit.name}}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Department</td><td>{{kit.department}}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Calibration Due</td><td>{{kit.calibration_due_date}}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Days Remaining</td><td><strong>{{kit.days_remaining}} days</strong></td></tr>
</table>
<p>Please arrange for recalibration before the due date to ensure continued test accuracy.</p>""",
        recipient_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        organization_id=None,
    ),
    # kit_calibration_due — inapp
    dict(
        event_type="kit_calibration_due",
        channel="inapp",
        subject_template="Kit {{kit.ueic}} calibration due in {{kit.days_remaining}} days",
        body_template="{{kit.ueic}} ({{kit.name}}) at {{kit.department}} — calibration due {{kit.calibration_due_date}}.",
        recipient_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        organization_id=None,
    ),
    # kit_calibration_overdue — email
    dict(
        event_type="kit_calibration_overdue",
        channel="email",
        subject_template="OVERDUE: Calibration Expired {{kit.days_overdue}} days ago — {{kit.ueic}}",
        body_template="""<p>Dear Team,</p>
<p>The calibration certificate for testing kit <strong>{{kit.ueic}}</strong> ({{kit.name}}) has <strong style="color:#dc2626;">expired</strong>.</p>
<table style="border-collapse:collapse;font-size:13px;">
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Kit</td><td><strong>{{kit.ueic}}</strong> — {{kit.name}}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Department</td><td>{{kit.department}}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Calibration Was Due</td><td>{{kit.calibration_due_date}}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666;">Days Overdue</td><td><strong style="color:#dc2626;">{{kit.days_overdue}} days</strong></td></tr>
</table>
<p><strong>This kit must not be used for testing until recalibrated.</strong> Please arrange for recalibration immediately.</p>""",
        recipient_roles=["EE_TLSS", "AEE_MAINTENANCE", "SEE_WM"],
        organization_id=None,
    ),
    # kit_calibration_overdue — inapp
    dict(
        event_type="kit_calibration_overdue",
        channel="inapp",
        subject_template="OVERDUE: Kit {{kit.ueic}} calibration expired {{kit.days_overdue}} days ago",
        body_template="{{kit.ueic}} ({{kit.name}}) at {{kit.department}} — calibration expired {{kit.days_overdue}} days ago. Do not use until recalibrated.",
        recipient_roles=["EE_TLSS", "AEE_MAINTENANCE", "SEE_WM"],
        organization_id=None,
    ),
]


# ── Routing rules ─────────────────────────────────────────────────────────────

_KIT_ROUTING_RULES = [
    dict(
        event_type="kit_calibration_due",
        label="Test Kit Calibration Due Soon — In-app",
        channels_enabled=["inapp"],
        priority=0,
        is_active=True,
    ),
    dict(
        event_type="kit_calibration_overdue",
        label="Test Kit Calibration Overdue — In-app",
        channels_enabled=["inapp"],
        priority=0,
        is_active=True,
    ),
]


# ── Public entry point ────────────────────────────────────────────────────────

def seed_kit_calibration_notifications(session) -> dict:
    """
    Upsert kit calibration variables, events, templates, and routing rules.
    Returns a summary dict with counts.
    """
    vars_upserted    = _upsert_variables(session)
    events_upserted  = _upsert_events(session)
    tmpls_upserted   = _upsert_templates(session)
    rules_upserted   = _upsert_routing_rules(session)
    session.commit()
    return {
        "variables": vars_upserted,
        "events":    events_upserted,
        "templates": tmpls_upserted,
        "rules":     rules_upserted,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _upsert_variables(session) -> int:
    count = 0
    for v in _KIT_VARIABLES:
        existing = (
            session.query(NotificationVariable)
            .filter(
                NotificationVariable.var_key == v["var_key"],
                NotificationVariable.organization_id.is_(None),
            )
            .first()
        )
        fb = v.pop("fallback_keys", [])
        if existing:
            for k, val in v.items():
                setattr(existing, k, val)
            existing.fallback_keys = fb
        else:
            session.add(NotificationVariable(
                **v,
                fallback_keys=fb,
                role_template_ids=[],
                organization_id=None,
                is_system=True,
                is_active=True,
            ))
        count += 1
    return count


def _upsert_events(session) -> int:
    count = 0
    for e in _KIT_EVENTS:
        existing = (
            session.query(NotificationEventCatalogue)
            .filter(
                NotificationEventCatalogue.event_type == e["event_type"],
                NotificationEventCatalogue.organization_id.is_(None),
            )
            .first()
        )
        if existing:
            for k, val in e.items():
                setattr(existing, k, val)
        else:
            session.add(NotificationEventCatalogue(
                **e,
                organization_id=None,
            ))
        count += 1
    return count


def _upsert_templates(session) -> int:
    count = 0
    for t in _KIT_TEMPLATES:
        existing = (
            session.query(NotificationTemplate)
            .filter(
                NotificationTemplate.event_type == t["event_type"],
                NotificationTemplate.channel    == t["channel"],
                NotificationTemplate.organization_id.is_(None),
            )
            .first()
        )
        if existing:
            for k, val in t.items():
                setattr(existing, k, val)
        else:
            session.add(NotificationTemplate(**t))
        count += 1
    return count


def _upsert_routing_rules(session) -> int:
    count = 0
    for r in _KIT_ROUTING_RULES:
        existing = (
            session.query(NotificationRoutingRule)
            .filter(
                NotificationRoutingRule.event_type == r["event_type"],
                NotificationRoutingRule.organization_id.is_(None),
            )
            .first()
        )
        if existing:
            for k, val in r.items():
                setattr(existing, k, val)
        else:
            session.add(NotificationRoutingRule(
                **r,
                recipient_roles_override=None,
                applicable_workflow_types=[],
                applicable_equipment_types=[],
                organization_id=None,
            ))
        count += 1
    return count


if __name__ == "__main__":
    from database import SessionLocal
    db = SessionLocal()
    try:
        result = seed_kit_calibration_notifications(db)
        print(f"[OK] Kit calibration notifications seeded: {result}")
    finally:
        db.close()
