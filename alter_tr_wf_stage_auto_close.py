#!/usr/bin/env python3
"""
One-time setup: add tr_wf_stages.auto_close_normal_after_hours.

Lets a result-review stage (is_result_stage=True) auto-close once every
TestResult on the request evaluated NORMAL and this many hours have
elapsed since the stage opened -- KPTCL spec D.8 "Auto-close NORMAL
results after review period". Deliberately a separate column from
default_duration_hours (the SLA-breach-notification duration): an org
may want a different cadence for "quietly close a clean result" than for
"escalate an overdue one", and either could reasonably outlive the other
on the same stage.

Null (the default) = auto-close disabled for that stage -- opt-in, not a
behavior change for any existing stage. Only meaningful when
is_result_stage is True; enforced at the API layer
(routers/tr_workflow_config.py), not in the database, matching how
"at least one duration required" is already enforced there rather than
with a DB constraint.

Re-running this script is safe: ADD COLUMN IF NOT EXISTS is a no-op if
the column already exists.

Usage:
    python alter_tr_wf_stage_auto_close.py
"""
from sqlalchemy import text
from database import VendorSessionLocal


def main():
    db = VendorSessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE public.tr_wf_stages "
            "ADD COLUMN IF NOT EXISTS auto_close_normal_after_hours INTEGER"
        ))
        db.execute(text(
            "COMMENT ON COLUMN public.tr_wf_stages.auto_close_normal_after_hours "
            "IS 'Hours after which this result-review stage auto-closes if every "
            "TestResult on the request evaluated NORMAL. NULL = disabled.'"
        ))
        db.commit()
        print("Ensured tr_wf_stages.auto_close_normal_after_hours column exists.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
