#!/usr/bin/env python3
"""
One-time setup: seed the new "deterioration_watch_escalated" notification
event type (catalogue entry + email/SMS/in-app templates) without re-running
the full seed.py (that file seeds the entire platform — equipment types,
workflows, hundreds of other notification templates, etc.; running it again
against a live dev DB with real data is not something to do casually for one
new event type).

Both _seed_notification_event_catalogue() and _seed_notification_templates()
are idempotent, self-contained functions (upsert by event_type, and by
event_type+channel respectively) — this script just calls them directly with
a fresh session, exactly as seed.py's own seed_all() does, but scoped to
only these two.

Usage:
    python alter_deterioration_notification.py
"""
from database import VendorSessionLocal
from seed import _seed_notification_event_catalogue, _seed_notification_templates


def main():
    session = VendorSessionLocal()
    try:
        catalogue_count = _seed_notification_event_catalogue(session)
        template_count = _seed_notification_templates(session)
        print(f"Notification event catalogue: {catalogue_count} entries touched.")
        print(f"Notification templates: {template_count} entries touched.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
