#!/usr/bin/env python3
"""
One-time setup: seed the 15 "*_report_ready" notification templates (email +
in-app) so ReportDefinition.notification_event actually delivers something.

The notification_event_catalogue entries for all 15 events (overdue_report_ready,
result_review_report_ready, etc.) already existed, but had zero NotificationTemplate
rows -- NotificationService.fire() looks templates up by event_type and silently
returns early when none exist, so every scheduled report finished generating
without notifying anyone. See seed.py's _seed_notification_templates()
"Report-Ready events" block for the templates themselves, and
services/reporting_service.py's run_scheduled_reports() /
_fire_report_ready() for the code that now actually calls fire().

Purely data seeding -- no schema migration needed. _seed_notification_templates()
is an idempotent, self-contained function (upsert by event_type + channel) --
this script just calls it directly with a fresh session, exactly as seed.py's
own seed_all() does, but scoped to only this one seeder rather than re-running
the entire seed.py (which reseeds the whole platform and isn't something to do
casually against a live dev DB with real data).

Usage:
    python alter_seed_report_ready_templates.py
"""
from database import VendorSessionLocal
from seed import _seed_notification_templates


def main():
    session = VendorSessionLocal()
    try:
        template_count = _seed_notification_templates(session)
        print(f"[OK] Notification templates: {template_count} entries touched.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
