#!/usr/bin/env python3
"""
Manually run the due-date / stage-SLA notification checks now, instead of
waiting for the scheduler (12:30 IST daily; Result Review every 15 min).

With request numbers, only those Test Requests are evaluated -- nobody else
gets notified, and the org-wide summaries / schedule-missed passes are
skipped. Without arguments it runs the full scheduled check for every org
(the same as the 12:30 IST run).

The normal duplicate guard still applies: a request already notified for an
event inside that rule's cooldown (e.g. 7 days for the weekly overdue rules)
is not notified again.

Usage:
    python run_notification_check.py TR-KP-2026-1703 [TR-... ...]
    python run_notification_check.py            # everything (careful)
"""
import sys

from database import VendorSessionLocal
from models import TestingRequest


def main(argv):
    only_ids = None
    if argv:
        db = VendorSessionLocal()
        try:
            rows = (
                db.query(TestingRequest.id, TestingRequest.request_number)
                .filter(TestingRequest.request_number.in_(argv))
                .all()
            )
        finally:
            db.close()
        missing = set(argv) - {n for _, n in rows}
        if missing:
            print(f"Not found: {', '.join(sorted(missing))}")
            return 1
        only_ids = {i for i, _ in rows}
        print(f"Checking only: {', '.join(argv)}")
    else:
        print("Checking ALL open requests in every org")

    # Importing main builds the app but does not start its scheduler (that
    # only happens in the FastAPI startup event).
    from main import _check_schedule_notifications, _check_review_sla_breaches

    _check_schedule_notifications(only_request_ids=only_ids)
    _check_review_sla_breaches(only_request_ids=only_ids)
    print("Done -- see Notification Center > Log.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
