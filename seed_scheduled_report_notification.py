"""
Seed the "scheduled_report_ready" notification event — catalogue entry,
templates (email + inapp), and routing rule. Global defaults
(organization_id=NULL); any org can override via Notification Center's
existing "Update Template" flow (per-org row wins over global — same
mechanism every other event already uses).

Fired by services.reporting_service.fire_report_ready_notification(),
called from both the scheduled report job (run_scheduled_reports) and the
on-demand "Run" endpoint (routers/reporting.py) — same event either way.
Opt-in per ReportDefinition: only fires if that definition's
notification_event field is set to this event_type.

Context variables:
  {{report.name}}          — ReportDefinition.name
  {{report.description}}   — ReportDefinition.description
  {{report.frequency}}     — daily | weekly | monthly
  {{report.format}}        — excel | pdf
  {{report.row_count}}     — rows in the generated report
  {{report.file_name}}     — generated file's name
  {{report.generated_at}}  — completion timestamp (UTC, YYYY-MM-DD HH:MM:SS)

The email template's attachment_vars references the generated file itself
(type "excel") — resolved via _generate_attachment_bytes()'s report_log
branch, which reads the file straight off disk rather than re-running the
report query.

Idempotent: existing global entries for this event_type are replaced on
re-run.
"""

import sys
sys.path.insert(0, ".")

from database import SessionLocal
from models import NotificationEventCatalogue, NotificationTemplate, NotificationRoutingRule

EVENT_TYPE = "scheduled_report_ready"

_CATALOGUE_ENTRY = {
    "event_type": EVENT_TYPE,
    "label": "Scheduled Report Ready",
    "group_name": "Reports",
    "description": "Fired when a Reporting Center report definition finishes generating — scheduled or run on demand.",
    "context_vars": [
        "report.name", "report.description", "report.frequency",
        "report.format", "report.row_count", "report.file_name", "report.generated_at",
    ],
    "default_roles": [],
}

_CELL_LABEL = "padding:8px 0;color:#888;width:160px;font-size:13px;"
_CELL_VALUE = "padding:8px 0;font-weight:600;color:#0F172A;font-size:13px;"
_TABLE_STYLE = "border-collapse:collapse;width:100%;margin-bottom:16px;"


def _row(label, var):
    return (
        f"<tr>"
        f"<td style='{_CELL_LABEL}'>{label}</td>"
        f"<td style='{_CELL_VALUE}'>{{{{{var}}}}}</td>"
        f"</tr>"
    )


TEMPLATES = [
    {
        "event_type": EVENT_TYPE,
        "channel": "inapp",
        "subject_template": "Report Ready — {{report.name}}",
        "body_template": (
            "'{{report.name}}' has finished generating ({{report.row_count}} rows, "
            "{{report.format}}). Available in Reporting Center."
        ),
        "recipient_roles": [],
        "attachment_vars": [],
    },
    {
        "event_type": EVENT_TYPE,
        "channel": "email",
        "subject_template": "[CogniWatt] Report Ready — {{report.name}}",
        "body_template": (
            "<h2 style='color:#2E6FDE;margin-bottom:4px;'>Report Ready</h2>"
            "<p style='color:#555;margin-top:0;'>{{report.description}}</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Report", "report.name")
            + _row("Frequency", "report.frequency")
            + _row("Format", "report.format")
            + _row("Rows", "report.row_count")
            + _row("Generated At (UTC)", "report.generated_at")
            + "</table>"
            "<p style='margin-top:20px;'>The generated file is attached to this email, "
            "and also available in <strong>Reporting Center</strong> under this report's log.</p>"
        ),
        "recipient_roles": [],
        "attachment_vars": [{"var_key": "report_file", "type": "excel"}],
    },
]

ROUTING_RULE = {
    "event_type": EVENT_TYPE,
    "label": "Reports — Scheduled Report Ready",
    "channels_enabled": ["inapp", "email"],
    "priority": 0,
}


def seed_scheduled_report_notification(session=None):
    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        print("\n--- Scheduled Report Ready: Event Catalogue ---")
        existing = session.query(NotificationEventCatalogue).filter(
            NotificationEventCatalogue.event_type == EVENT_TYPE,
            NotificationEventCatalogue.organization_id.is_(None),
        ).first()
        if existing:
            existing.label = _CATALOGUE_ENTRY["label"]
            existing.group_name = _CATALOGUE_ENTRY["group_name"]
            existing.description = _CATALOGUE_ENTRY["description"]
            existing.context_vars = _CATALOGUE_ENTRY["context_vars"]
            existing.default_roles = _CATALOGUE_ENTRY["default_roles"]
            existing.is_active = True
            print(f"  Updated: {EVENT_TYPE}")
        else:
            session.add(NotificationEventCatalogue(
                event_type=EVENT_TYPE,
                label=_CATALOGUE_ENTRY["label"],
                group_name=_CATALOGUE_ENTRY["group_name"],
                description=_CATALOGUE_ENTRY["description"],
                context_vars=_CATALOGUE_ENTRY["context_vars"],
                default_roles=_CATALOGUE_ENTRY["default_roles"],
                organization_id=None,
                is_active=True,
            ))
            print(f"  Inserted: {EVENT_TYPE}")

        print("\n--- Scheduled Report Ready: Templates ---")
        rows = session.query(NotificationTemplate).filter(
            NotificationTemplate.event_type == EVENT_TYPE,
            NotificationTemplate.organization_id.is_(None),
        ).all()
        for r in rows:
            session.delete(r)
        if rows:
            session.flush()
            print(f"  Removed {len(rows)} existing templates")

        for tmpl in TEMPLATES:
            session.add(NotificationTemplate(
                event_type=tmpl["event_type"],
                channel=tmpl["channel"],
                subject_template=tmpl["subject_template"],
                body_template=tmpl["body_template"],
                recipient_roles=tmpl["recipient_roles"],
                attachment_vars=tmpl["attachment_vars"],
                organization_id=None,
                is_active=True,
                org_channel_disabled=False,
            ))
        print(f"  Seeded {len(TEMPLATES)} templates")

        print("\n--- Scheduled Report Ready: Routing Rule ---")
        rule_rows = session.query(NotificationRoutingRule).filter(
            NotificationRoutingRule.event_type == EVENT_TYPE,
            NotificationRoutingRule.organization_id.is_(None),
        ).all()
        for r in rule_rows:
            session.delete(r)
        if rule_rows:
            session.flush()
            print(f"  Removed {len(rule_rows)} existing routing rules")

        session.add(NotificationRoutingRule(
            event_type=ROUTING_RULE["event_type"],
            label=ROUTING_RULE["label"],
            channels_enabled=ROUTING_RULE["channels_enabled"],
            recipient_roles_override=None,
            applicable_workflow_types=[],
            applicable_equipment_types=[],
            applicable_test_types=[],
            applicable_status_from=None,
            applicable_status_to=None,
            priority=ROUTING_RULE["priority"],
            organization_id=None,
            is_active=True,
        ))
        print("  Seeded 1 routing rule")

        session.commit()
        print("\n[OK] scheduled_report_ready notification seed complete.")

    except Exception as e:
        session.rollback()
        print(f"\n[FAILED] Seed failed: {e}")
        raise
    finally:
        if own_session:
            session.close()


if __name__ == "__main__":
    seed_scheduled_report_notification()
