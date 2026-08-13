#!/usr/bin/env python3
"""
General-purpose cleanup for orphaned ParameterAnalytics rows - i.e. rows
whose parameter_key is no longer producible from the test_result's current
test_data + template (renamed row-id, removed template field, etc.),
regardless of what caused the staleness.

Detection heuristic: run_for_test() upserts every currently-valid parameter
for a test_result together, in one pass, so they end up with near-identical
calculated_at timestamps. A row whose calculated_at lags meaningfully behind
the newest calculated_at among its own test_result's rows means the most
recent recompute did not regenerate it - it's stale.

This is invocation-independent (unlike the rename-tracking cleanup in
backfill_row_id_normalization.py, which can only clean up renames it
personally witnessed in that same run) - it catches leftover orphans from
ANY prior cause, as long as a full recompute has run since.

Usage:
    python backfill_orphaned_parameter_analytics.py --dry-run   # report only
    python backfill_orphaned_parameter_analytics.py              # delete
    python backfill_orphaned_parameter_analytics.py --gap-minutes 5
        # widen/narrow the staleness gap (default 1 minute)

IMPORTANT: run this only right after a full run_recompute_all_analytics.py
pass - otherwise a test_result that simply hasn't been recomputed recently
(but whose data hasn't changed) would be flagged as if it were orphaned.
"""
import argparse

from database import VendorSessionLocal
from models import ParameterAnalytics
from sqlalchemy import func


def find_orphans(db, gap_minutes: int):
    latest_per_test = (
        db.query(
            ParameterAnalytics.test_result_id.label("trid"),
            func.max(ParameterAnalytics.calculated_at).label("latest"),
        )
        .group_by(ParameterAnalytics.test_result_id)
        .subquery()
    )
    return (
        db.query(ParameterAnalytics)
        .join(latest_per_test, ParameterAnalytics.test_result_id == latest_per_test.c.trid)
        .filter(
            ParameterAnalytics.calculated_at
            < latest_per_test.c.latest - func.make_interval(0, 0, 0, 0, 0, gap_minutes, 0)
        )
        .all()
    )


def run(dry_run: bool, gap_minutes: int):
    db = VendorSessionLocal()
    try:
        orphans = find_orphans(db, gap_minutes)
        print(f"{'[DRY RUN] ' if dry_run else ''}Orphaned ParameterAnalytics rows: {len(orphans)}")
        for r in orphans[:30]:
            print(f"  {r.test_result_id}  {r.parameter_key!r}  calculated_at={r.calculated_at}")
        if len(orphans) > 30:
            print(f"  ... and {len(orphans) - 30} more")

        if not dry_run and orphans:
            for r in orphans:
                db.delete(r)
            db.commit()
            print(f"Deleted {len(orphans)} orphaned row(s).")
        elif dry_run:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gap-minutes", type=int, default=1)
    args = parser.parse_args()
    run(dry_run=args.dry_run, gap_minutes=args.gap_minutes)
