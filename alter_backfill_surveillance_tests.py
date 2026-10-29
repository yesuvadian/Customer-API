#!/usr/bin/env python3
"""
One-time fix: create the missing repair_surveillance_tests rows.

The surveillance scheduler created testing requests but never their
tracking rows, so SurveillanceTrackingService.update_test_result() found
nothing to update and Final Evaluation / the surveillance dashboard always
read 0 tests. New tickets now get a row when they're created; this adds
rows for the tickets that already exist, and fills in the latest result for
tickets whose test is already done. No notifications are sent.

Dry run by default - prints what it would create and writes nothing.

Usage:
    python alter_backfill_surveillance_tests.py            # dry run
    python alter_backfill_surveillance_tests.py --apply    # write
"""
import argparse

from database import VendorSessionLocal
from models import RepairSurveillanceTest, TestingRequest
from services.surveillance_tracking_service import SurveillanceTrackingService
from utils.surveillance_utils import (
    is_surveillance_test_abnormal,
    is_surveillance_test_done,
    latest_result_status,
)


def main():
    parser = argparse.ArgumentParser(description="Create missing surveillance test tracking rows.")
    parser.add_argument("--apply", action="store_true", help="Write the rows (default: dry run)")
    args = parser.parse_args()

    print(f"=== Surveillance test tracking backfill ({'APPLY' if args.apply else 'DRY RUN'}) ===")
    db = VendorSessionLocal()
    try:
        tracked = {r[0] for r in db.query(RepairSurveillanceTest.testing_request_id).all()}
        tickets = (
            db.query(TestingRequest)
            .filter(
                TestingRequest.surveillance_workflow_id.isnot(None),
                TestingRequest.surveillance_quarter.isnot(None),
            )
            .order_by(TestingRequest.request_number)
            .all()
        )

        tracking = SurveillanceTrackingService(db)
        created = 0
        for tr in tickets:
            if tr.id in tracked:
                continue
            row = tracking.ensure_test_row(tr)

            if is_surveillance_test_done(tr):
                row.test_status = "completed"
                row.result_status, row.tested_at = latest_result_status(db, tr.id)
                row.is_abnormal = is_surveillance_test_abnormal(db, tr)

            print(f"  add   {tr.request_number}: Q{row.quarter_number} status={row.test_status} "
                  f"result={row.result_status} abnormal={row.is_abnormal}")
            created += 1

        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(f"\n{created} row(s) {'created' if args.apply else 'would be created'}, "
              f"{len(tickets) - created} already tracked")
    finally:
        db.close()


if __name__ == "__main__":
    main()
