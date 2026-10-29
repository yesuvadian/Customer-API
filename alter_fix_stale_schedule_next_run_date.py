#!/usr/bin/env python3
"""
One-time repair: roll forward recurring schedules whose next_run_date was
left in the past by a one-period catch-up.

Background
----------
TestRequestScheduleService.create_one_ticket() used to advance a recurring
schedule's next_run_date by exactly ONE period after generating its ticket.
When the daily scheduler had been down for a while (e.g. 22 Oct 2026 run
after weeks without one), that left next_run_date still in the past:

  * the CM Schedules compliance screen kept showing the schedule OVERDUE,
  * main.py Pass 3 skipped it (a success log existed after next_run_date),
    so no schedule_missed / escalation alert went out, and
  * every following daily run would have generated another catch-up ticket.

create_one_ticket() now rolls past the run time (_advance_past). This script
applies the same rule to rows already in that state: any active recurring
schedule whose latest successful run is on/after its next_run_date gets
next_run_date = first period boundary after that run. A schedule that is
still behind after that (scheduler not run since) correctly stays overdue.

Idempotent: a repaired row's next_run_date is after its last success run,
so it no longer matches. Dry run by default.

Usage:
    python alter_fix_stale_schedule_next_run_date.py           # preview
    python alter_fix_stale_schedule_next_run_date.py --apply   # write
"""
import sys

from sqlalchemy import func

from database import VendorSessionLocal
from models import (
    ScheduleLogStatus,
    TestRequestSchedule,
    TestRequestScheduleLog,
)
from services.test_request_schedule_service import _advance_past


def main(apply: bool):
    db = VendorSessionLocal()
    try:
        last_success = (
            db.query(
                TestRequestScheduleLog.schedule_id,
                func.max(TestRequestScheduleLog.run_date).label("run_date"),
            )
            .filter(TestRequestScheduleLog.status == ScheduleLogStatus.success)
            .group_by(TestRequestScheduleLog.schedule_id)
            .subquery()
        )
        rows = (
            db.query(TestRequestSchedule, last_success.c.run_date)
            .join(last_success, last_success.c.schedule_id == TestRequestSchedule.id)
            .filter(
                TestRequestSchedule.is_active.is_(True),
                TestRequestSchedule.is_deleted.is_(False),
                TestRequestSchedule.is_recurring.is_(True),
                TestRequestSchedule.next_run_date <= last_success.c.run_date,
            )
            .all()
        )
        for sch, run_date in rows:
            new_next = _advance_past(sch.next_run_date, sch.frequency, run_date)
            eq = getattr(getattr(sch, "equipment", None), "ueic", "") or "-"
            print(f"  {eq} | {sch.title} | {sch.frequency.value if sch.frequency else None} | "
                  f"{sch.next_run_date.date()} -> {new_next.date()} (last run {run_date.date()})")
            sch.next_run_date = new_next

        if apply:
            db.commit()
            print(f"[OK] Repaired {len(rows)} schedule(s).")
        else:
            db.rollback()
            print(f"[DRY RUN] {len(rows)} schedule(s) would be repaired. Re-run with --apply.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
