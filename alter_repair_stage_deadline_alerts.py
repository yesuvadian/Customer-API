#!/usr/bin/env python3
"""
One-time setup for Repair-family stage deadline alerts (main.py's hourly
_check_repair_stage_deadlines):

  1. Adds repair_stage_instances.due_at and the three one-shot alert guards
     (due_soon_notified_at, overdue_notified_at, escalation_notified_at).
  2. Backfills due_at = started_at + default_duration_days for existing
     stage instances. From here on models._sync_repair_stage_due_at keeps it
     in step with started_at.

The repair_stage_due_soon / _overdue / _escalation catalogue entries,
templates and routing rules live in seed.py and are created by
seed_notification_defaults(), which main.py runs on every startup.

Re-running is safe: columns use ADD COLUMN IF NOT EXISTS and the backfill
only fills NULLs.

Existing stages that are already past their deadline get one alert on the
job's first run (the highest level reached - escalation if more than
STAGE_ESCALATION_DAYS late), not one per level.

Usage:
    python alter_repair_stage_deadline_alerts.py
"""
from sqlalchemy import text

from database import VendorSessionLocal


def add_columns(db):
    for col in ("due_at", "due_soon_notified_at", "overdue_notified_at", "escalation_notified_at"):
        db.execute(text(
            f"ALTER TABLE repair_stage_instances ADD COLUMN IF NOT EXISTS {col} TIMESTAMP"
        ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_repair_stage_instances_due_at "
        "ON repair_stage_instances (due_at)"
    ))
    filled = db.execute(text(
        """
        UPDATE repair_stage_instances si
           SET due_at = si.started_at + make_interval(days => d.default_duration_days)
          FROM repair_stage_definitions d
         WHERE d.id = si.stage_id
           AND si.due_at IS NULL
           AND si.started_at IS NOT NULL
           AND d.default_duration_days IS NOT NULL
        """
    )).rowcount
    db.commit()
    print(f"Columns ensured; due_at backfilled on {filled} stage instance(s).")


def main():
    db = VendorSessionLocal()
    try:
        add_columns(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
