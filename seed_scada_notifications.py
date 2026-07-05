#!/usr/bin/env python3
"""
Seed SCADA notification event types and default templates.

Events seeded:
  scada_alarm          – tag enters WARNING or ALARM condition
  scada_critical       – tag enters CRITICAL condition
  scada_breach_forecast – analytics predicts threshold breach within 48 h

Context variables available (resolved by notification_service scada_reading branch):
  scada.tag, scada.parameter, scada.value, scada.unit,
  scada.condition, scada.timestamp,
  equipment.name, equipment.ueic, equipment.department
"""

import uuid
from database import get_db
from models import NotificationEventCatalogue, NotificationTemplate

db = next(get_db())

SCADA_VARS = [
    "equipment.name", "equipment.ueic", "equipment.department",
    "scada.tag", "scada.parameter", "scada.value", "scada.unit",
    "scada.condition", "scada.timestamp",
]

# ── Event catalogue entries ───────────────────────────────────────────────────

events = [
    {
        "event_type":    "scada_alarm",
        "label":         "SCADA – Alarm / Warning",
        "description":   "A SCADA tag has entered WARNING or ALARM condition",
        "group_name":    "SCADA",
        "organization_id": None,
        "is_active":     True,
        "context_vars":  SCADA_VARS,
        "default_roles": ["EE TLSS"],
    },
    {
        "event_type":    "scada_critical",
        "label":         "SCADA – Critical Alarm",
        "description":   "A SCADA tag has entered CRITICAL condition",
        "group_name":    "SCADA",
        "organization_id": None,
        "is_active":     True,
        "context_vars":  SCADA_VARS,
        "default_roles": ["EE TLSS", "Department Head"],
    },
    {
        "event_type":    "scada_breach_forecast",
        "label":         "SCADA – Breach Forecast",
        "description":   "Analytics predicts a threshold breach within 48 hours",
        "group_name":    "SCADA",
        "organization_id": None,
        "is_active":     True,
        "context_vars":  SCADA_VARS + [
            "scada.days_to_breach", "scada.breach_date", "scada.trend"
        ],
        "default_roles": ["EE TLSS", "Department Head"],
    },
]

print("Seeding SCADA event catalogue entries...")
for ev in events:
    existing = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.event_type == ev["event_type"],
        NotificationEventCatalogue.organization_id.is_(None),
    ).first()
    if existing:
        print(f"  [SKIP] {ev['event_type']} already exists")
    else:
        db.add(NotificationEventCatalogue(id=uuid.uuid4(), **ev))
        print(f"  [ADD]  {ev['event_type']}")

db.commit()

# ── Default notification templates ───────────────────────────────────────────

templates = [
    # scada_alarm ─────────────────────────────────────────────────────────────
    {
        "event_type": "scada_alarm",
        "channel":    "inapp",
        "subject_template":"SCADA Alarm – {{scada.tag}}",
        "body_template": (
            "⚠️ {{equipment.name}} | Tag: {{scada.tag}} ({{scada.parameter}})\n"
            "Condition: {{scada.condition}}  |  Value: {{scada.value}} {{scada.unit}}\n"
            "Time: {{scada.timestamp}}"
        ),
        "is_active": True,
        "organization_id": None,
    },
    {
        "event_type": "scada_alarm",
        "channel":    "email",
        "subject_template":"[SCADA ALARM] {{equipment.name}} – {{scada.tag}} is {{scada.condition}}",
        "body_template": (
            "<p>An alarm has been triggered on your SCADA system.</p>"
            "<table>"
            "<tr><td><b>Equipment</b></td><td>{{equipment.name}} ({{equipment.ueic}})</td></tr>"
            "<tr><td><b>Department</b></td><td>{{equipment.department}}</td></tr>"
            "<tr><td><b>Tag</b></td><td>{{scada.tag}}</td></tr>"
            "<tr><td><b>Parameter</b></td><td>{{scada.parameter}}</td></tr>"
            "<tr><td><b>Value</b></td><td>{{scada.value}} {{scada.unit}}</td></tr>"
            "<tr><td><b>Condition</b></td><td>{{scada.condition}}</td></tr>"
            "<tr><td><b>Time</b></td><td>{{scada.timestamp}}</td></tr>"
            "</table>"
        ),
        "is_active": True,
        "organization_id": None,
    },
    # scada_critical ──────────────────────────────────────────────────────────
    {
        "event_type": "scada_critical",
        "channel":    "inapp",
        "subject_template":"🔴 SCADA CRITICAL – {{scada.tag}}",
        "body_template": (
            "CRITICAL: {{equipment.name}} | Tag: {{scada.tag}} ({{scada.parameter}})\n"
            "Value: {{scada.value}} {{scada.unit}}  |  Time: {{scada.timestamp}}"
        ),
        "is_active": True,
        "organization_id": None,
    },
    {
        "event_type": "scada_critical",
        "channel":    "email",
        "subject_template":"[SCADA CRITICAL] {{equipment.name}} – {{scada.tag}} exceeded critical threshold",
        "body_template": (
            "<p><b style='color:red'>CRITICAL alarm triggered. Immediate attention required.</b></p>"
            "<table>"
            "<tr><td><b>Equipment</b></td><td>{{equipment.name}} ({{equipment.ueic}})</td></tr>"
            "<tr><td><b>Department</b></td><td>{{equipment.department}}</td></tr>"
            "<tr><td><b>Tag</b></td><td>{{scada.tag}}</td></tr>"
            "<tr><td><b>Parameter</b></td><td>{{scada.parameter}}</td></tr>"
            "<tr><td><b>Value</b></td><td>{{scada.value}} {{scada.unit}}</td></tr>"
            "<tr><td><b>Condition</b></td><td>{{scada.condition}}</td></tr>"
            "<tr><td><b>Time</b></td><td>{{scada.timestamp}}</td></tr>"
            "</table>"
        ),
        "is_active": True,
        "organization_id": None,
    },
    # scada_breach_forecast ───────────────────────────────────────────────────
    {
        "event_type": "scada_breach_forecast",
        "channel":    "inapp",
        "subject_template":"SCADA Breach Forecast – {{scada.tag}}",
        "body_template": (
            "📈 {{equipment.name}} | Tag: {{scada.tag}}\n"
            "Trend: {{scada.trend}}  |  Breach predicted in {{scada.days_to_breach}} days "
            "(~{{scada.breach_date}})"
        ),
        "is_active": True,
        "organization_id": None,
    },
    {
        "event_type": "scada_breach_forecast",
        "channel":    "email",
        "subject_template":"[SCADA Forecast] {{equipment.name}} – {{scada.tag}} breach in {{scada.days_to_breach}} days",
        "body_template": (
            "<p>Predictive analytics has detected that a SCADA parameter is trending "
            "toward a threshold breach.</p>"
            "<table>"
            "<tr><td><b>Equipment</b></td><td>{{equipment.name}} ({{equipment.ueic}})</td></tr>"
            "<tr><td><b>Department</b></td><td>{{equipment.department}}</td></tr>"
            "<tr><td><b>Tag</b></td><td>{{scada.tag}}</td></tr>"
            "<tr><td><b>Parameter</b></td><td>{{scada.parameter}}</td></tr>"
            "<tr><td><b>Trend</b></td><td>{{scada.trend}}</td></tr>"
            "<tr><td><b>Days to Breach</b></td><td>{{scada.days_to_breach}}</td></tr>"
            "<tr><td><b>Estimated Breach Date</b></td><td>{{scada.breach_date}}</td></tr>"
            "</table>"
            "<p>Consider scheduling an inspection or testing request.</p>"
        ),
        "is_active": True,
        "organization_id": None,
    },
]

print("\nSeeding SCADA notification templates...")
for tmpl in templates:
    existing = db.query(NotificationTemplate).filter(
        NotificationTemplate.event_type == tmpl["event_type"],
        NotificationTemplate.channel == tmpl["channel"],
        NotificationTemplate.organization_id.is_(None),
    ).first()
    if existing:
        print(f"  [SKIP] {tmpl['event_type']} / {tmpl['channel']} already exists")
    else:
        db.add(NotificationTemplate(id=uuid.uuid4(), **tmpl))
        print(f"  [ADD]  {tmpl['event_type']} / {tmpl['channel']}")

db.commit()

# ── Verify ────────────────────────────────────────────────────────────────────

print("\nVerification:")
for et in ["scada_alarm", "scada_critical", "scada_breach_forecast"]:
    evt = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.event_type == et
    ).first()
    tmpls = db.query(NotificationTemplate).filter(
        NotificationTemplate.event_type == et
    ).count()
    print(f"  {et}: event={'OK' if evt else 'MISSING'}  templates={tmpls}")

db.close()
print("\n[DONE]")
