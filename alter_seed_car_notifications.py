#!/usr/bin/env python3
"""
One-time setup: register the three Corrective Action Request notification
events -- car_created, car_assigned, car_overdue -- so they're fully
leverage-able from the existing Notification Center screen (Organisation ->
Notification Center), same as every other event in the system. Adds:
  1. NotificationEventCatalogue rows (event_type, label, group_name,
     description, context_vars, default_roles)
  2. NotificationTemplate rows (email/sms/inapp subject+body per event)

These come from seed.py's own _seed_notification_event_catalogue() and
_seed_notification_templates() lists, so this script just re-runs the same
idempotent seed_notification_defaults() wrapper seed.py itself calls during
a full run -- safe to run standalone without re-running the entire seed.py.

Requires migrations 049 and 050 (corrective_action_requests.overdue_
notified_at, car_trigger_configs.car_due_in_days) to already be applied --
run run_migration_049.py / run_migration_050.py first on a fresh
environment.

Idempotent: get-or-create / update-existing throughout (seed_notification_
defaults()'s own convention), safe to re-run.

Usage:
    python alter_seed_car_notifications.py
"""
from database import VendorSessionLocal
from seed import seed_notification_defaults


def main():
    db = VendorSessionLocal()
    try:
        result = seed_notification_defaults(db)
        db.commit()
        print(f"[OK] Notification defaults seeded: {result}")

        from models import NotificationEventCatalogue
        for event_type in ("car_created", "car_assigned", "car_overdue"):
            row = db.query(NotificationEventCatalogue).filter(
                NotificationEventCatalogue.event_type == event_type
            ).first()
            status = f"OK ({row.label})" if row else "MISSING"
            print(f"  {event_type}: {status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
