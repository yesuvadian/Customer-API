#!/usr/bin/env python3
"""
One-time data fix: backfill a default SLA duration onto existing Result
Review stages (TrWfStage.is_result_stage = True) so the Overall Dashboard's
"Result Review SLA" tile and the proactive breach check
(main.py's _check_review_sla_breaches) have real data to work with,
instead of every org showing "no SLA configured yet".

Sets default_duration_hours = 24 (the spec's ALERT-tier target, used as a
single blended default since severity-split SLA isn't built yet) on every
Result Review stage that is still fully unconfigured (both
default_duration_days and default_duration_hours NULL).

Only touches unconfigured rows -- if an admin has already set either
field on a stage (via the Add Stage / Settings UI), this script leaves it
untouched. Re-running is safe for the same reason: once a row has a value,
it's no longer a backfill target.

Usage:
    python backfill_review_sla_duration.py
"""
from database import VendorSessionLocal
from models import TrWfStage

DEFAULT_HOURS = 24


def main():
    db = VendorSessionLocal()
    try:
        targets = (
            db.query(TrWfStage)
            .filter(
                TrWfStage.is_result_stage.is_(True),
                TrWfStage.default_duration_days.is_(None),
                TrWfStage.default_duration_hours.is_(None),
            )
            .all()
        )
        for stage in targets:
            stage.default_duration_hours = DEFAULT_HOURS
        db.commit()
        print(f"Backfilled default_duration_hours={DEFAULT_HOURS} on {len(targets)} Result Review stage(s):")
        for stage in targets:
            print(f"  - {stage.name!r} (code={stage.code!r}, wf_definition_id={stage.wf_definition_id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
