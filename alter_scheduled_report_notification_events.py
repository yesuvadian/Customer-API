"""
ALTER: email every scheduled report when it is generated.

Scheduled report definitions with no notification_event (e.g. Tester
Performance, Maintenance Overdue, Active Alerts, Monthly KPI Summary, Test
Results Summary, Procurement Pipeline) were generated on schedule but never
emailed — services.reporting_service.fire_report_ready() skips notifying when
notification_event is empty.

This points every active, scheduled (not on_demand) definition that has no
event at the generic "scheduled_report_ready" event, and makes sure that
event's email template attaches the generated file instead of the old
unusable {{download_url}} link.

Same rule seed.seed_report_definitions() now applies on every API startup —
this script just applies it immediately, without a restart.

Recipients come from each definition's Recipient Roles (Reporting Center →
edit). A definition with none set resolves to nobody and is skipped.

Safe to run multiple times.

Usage:
    python alter_scheduled_report_notification_events.py --check   # report only
    python alter_scheduled_report_notification_events.py           # apply
"""

from __future__ import annotations

import sys

from database import SessionLocal
from models import NotificationTemplate, OrgRole, ReportDefinition

EVENT = "scheduled_report_ready"
ATTACHMENT_VARS = [{"var_key": "report_attachment", "type": "excel", "source_type": "report_log"}]
OLD_LINK = "<p><a href='{{download_url}}'>Download the report</a> from SEACMS (login required).</p>"
NEW_TEXT = ("<p>The report is attached to this email. It is also available in "
            "SEACMS under Reporting Center &rarr; Log.</p>")


def _role_names(db, roles) -> str:
    names = []
    for r in roles or []:
        try:
            role = db.get(OrgRole, r)
            names.append(role.name if role else str(r))
        except Exception:
            names.append(str(r))  # already a role name
    return ", ".join(names) or "NONE (will be skipped)"


def main(check_only: bool) -> None:
    db = SessionLocal()
    try:
        defs = (
            db.query(ReportDefinition)
            .filter(
                ReportDefinition.is_active.is_(True),
                ReportDefinition.frequency != "on_demand",
                ReportDefinition.notification_event.is_(None),
            )
            .order_by(ReportDefinition.name)
            .all()
        )
        templates = (
            db.query(NotificationTemplate)
            .filter(NotificationTemplate.event_type == EVENT,
                    NotificationTemplate.channel == "email")
            .all()
        )

        print("=" * 70)
        print("  Scheduled reports -> email on generation")
        print("=" * 70)
        print(f"  Scheduled reports with no email event: {len(defs)}")
        for d in defs:
            print(f"    - {d.name:32} {d.frequency:8} recipients: {_role_names(db, d.recipient_roles)}")

        tmpl_fixes = [t for t in templates
                      if t.attachment_vars != ATTACHMENT_VARS or OLD_LINK in (t.body_template or "")]
        if not templates:
            print(f"\n  [WARN] no '{EVENT}' email template found — reports will be marked but "
                  f"no email can be rendered until it exists (restart the API to seed it).")
        print(f"  '{EVENT}' email templates needing the attachment fix: {len(tmpl_fixes)}")

        if check_only:
            print("\n  --check: nothing changed.")
            return

        for d in defs:
            d.notification_event = EVENT
        for t in tmpl_fixes:
            t.attachment_vars = ATTACHMENT_VARS
            if t.body_template and OLD_LINK in t.body_template:
                t.body_template = t.body_template.replace(OLD_LINK, NEW_TEXT)
        db.commit()

        print(f"\n  [OK] {len(defs)} report(s) now email via '{EVENT}'.")
        print(f"  [OK] {len(tmpl_fixes)} template(s) fixed.")
    finally:
        db.close()


if __name__ == "__main__":
    main(check_only="--check" in sys.argv)
