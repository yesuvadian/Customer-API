#!/usr/bin/env python3
"""
One-time setup: add tr_wf_stage_instances.sla_breach_notified_at.

Guards the proactive Result Review SLA breach notification (main.py's
_check_review_sla_breaches, run every 15 minutes) so each open stage
instance is alerted on exactly once when it first crosses its configured
deadline -- not re-fired on every subsequent 15-minute pass while it
stays open and unactioned.

Re-running this script is safe: ADD COLUMN IF NOT EXISTS is a no-op if
the column already exists.

Usage:
    python alter_tr_wf_stage_instance_sla_notified.py
"""
from sqlalchemy import text
from database import VendorSessionLocal


def main():
    db = VendorSessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE public.tr_wf_stage_instances "
            "ADD COLUMN IF NOT EXISTS sla_breach_notified_at TIMESTAMP"
        ))
        db.execute(text(
            "COMMENT ON COLUMN public.tr_wf_stage_instances.sla_breach_notified_at "
            "IS 'Set once this stage instance has been flagged as an SLA breach, "
            "so the proactive check never re-notifies for the same breach.'"
        ))
        db.commit()
        print("Ensured tr_wf_stage_instances.sla_breach_notified_at column exists.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
