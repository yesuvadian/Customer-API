#!/usr/bin/env python3
"""
One-time setup: add tr_wf_stages.default_duration_hours.

Lets a stage's SLA be configured in hours (e.g. a 2-hour CRITICAL
result-review turnaround) instead of only whole days. When a stage has
both default_duration_hours and default_duration_days set, application
code uses hours and ignores days.

Every existing stage predates SLA support and has both columns NULL, so
this script only adds the column — it does not backfill a value or add
a NOT-NULL/CHECK constraint. "At least one of the two required" is
enforced at the API layer (routers/tr_workflow_config.py), not in the
database.

Re-running this script is safe: ADD COLUMN IF NOT EXISTS is a no-op if
the column already exists.

Usage:
    python alter_tr_wf_stage_duration_hours.py
"""
from sqlalchemy import text
from database import VendorSessionLocal


def main():
    db = VendorSessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE public.tr_wf_stages "
            "ADD COLUMN IF NOT EXISTS default_duration_hours INTEGER"
        ))
        db.execute(text(
            "COMMENT ON COLUMN public.tr_wf_stages.default_duration_hours "
            "IS 'SLA duration in hours for this stage. Takes precedence "
            "over default_duration_days when both are set.'"
        ))
        db.commit()
        print("Ensured tr_wf_stages.default_duration_hours column exists.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
