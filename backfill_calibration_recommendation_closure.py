"""
backfill_calibration_recommendation_closure.py
────────────────────────────────────────────────
One-time backfill: run this once, right after deploying the
close_open_recommendation() fix (services/calibration_service.py +
calibration_hooks.py).

Problem it fixes
-----------------
Before that fix, a CALIBRATION repair workflow never closed its
CalibrationRepairRecommendation on completion. Any equipment whose CALIBRATION
workflow completed *before* this deploy is left with a permanently OPEN
recommendation, which silently blocks every future Fail from ever creating a
new workflow for that equipment. New completions are handled automatically
by the fixed hook going forward — this script sweeps up the pre-existing
stuck cases across the whole database in one pass.

What it does
------------
For every equipment with an OPEN CalibrationRepairRecommendation whose most
recent CALIBRATION RepairWorkflow has already reached status='completed':
  1. Close the stale OPEN recommendation (status=CLOSED, closed_at=now).
  2. If a calibration Fail TestResult exists that is newer than that
     completed workflow (i.e. a Fail that never got a workflow because of
     this bug), re-run CalibrationService._handle_fail() to create the
     missing CAL- workflow now.

Recommendations still OPEN behind a workflow that is NOT yet completed are
left untouched — those are legitimately active and not stuck.

Idempotent — safe to run more than once. Once there's nothing stuck, it's a
no-op. No need to stop the app or the database to run it.

Usage
-----
    python backfill_calibration_recommendation_closure.py            # apply
    python backfill_calibration_recommendation_closure.py --dry-run  # inspect only, write nothing
"""
import argparse

from sqlalchemy import func

from database import get_vendor_session
from models import (
    Equipment,
    CalibrationRepairRecommendation,
    RepairWorkflow,
    TestingRequest,
    TestResult,
)
from services.calibration_service import CalibrationService

CALIBRATION_WORKFLOW_CODE = "CALIBRATION"


def _latest_calibration_workflow(db, equipment_id):
    return (
        db.query(RepairWorkflow)
        .filter(
            RepairWorkflow.equipment_id == equipment_id,
            RepairWorkflow.workflow_code == CALIBRATION_WORKFLOW_CODE,
        )
        .order_by(RepairWorkflow.created_at.desc())
        .first()
    )


def _latest_fail_result(db, equipment_id):
    return (
        db.query(TestResult)
        .join(TestingRequest, TestingRequest.id == TestResult.testing_request_id)
        .filter(
            TestingRequest.equipment_id == equipment_id,
            TestResult.overall_result == "fail",
        )
        .order_by(func.coalesce(TestResult.tested_at, TestResult.cts).desc())
        .first()
    )


def main():
    parser = argparse.ArgumentParser(
        description="Backfill: close stale OPEN calibration recommendations left by "
        "workflows that completed before the auto-close fix was deployed."
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report, write nothing")
    args = parser.parse_args()

    with get_vendor_session() as db:
        svc = CalibrationService(db)

        open_recs = (
            db.query(CalibrationRepairRecommendation)
            .filter(CalibrationRepairRecommendation.status == "OPEN")
            .all()
        )
        print(f"Found {len(open_recs)} OPEN recommendation(s) across the database.\n")

        closed_count = 0
        triggered_count = 0

        for rec in open_recs:
            equipment = db.query(Equipment).filter(Equipment.id == rec.equipment_id).first()
            label = equipment.ueic if equipment else str(rec.equipment_id)

            latest_wf = _latest_calibration_workflow(db, rec.equipment_id)
            if not latest_wf or latest_wf.status != "completed":
                print(
                    f"  SKIP  {label}: OPEN recommendation but its workflow "
                    f"({latest_wf.workflow_number if latest_wf else 'none'}) isn't "
                    f"completed yet — legitimately active, leaving it alone."
                )
                continue

            print(
                f"  STUCK {label}: recommendation {rec.id} is OPEN but workflow "
                f"{latest_wf.workflow_number} already completed at {latest_wf.created_at}."
            )

            if args.dry_run:
                continue

            svc.close_open_recommendation(equipment_id=rec.equipment_id, user_id=None)
            closed_count += 1
            print("        -> closed.")

            latest_fail = _latest_fail_result(db, rec.equipment_id)
            fail_time = latest_fail and (latest_fail.tested_at or latest_fail.cts)
            if latest_fail and fail_time and fail_time > latest_wf.created_at:
                svc._handle_fail(equipment_id=rec.equipment_id, user_id=None)
                triggered_count += 1
                print(
                    "        -> a Fail result newer than the completed workflow was "
                    "found — created the missing CAL- workflow."
                )

        print(
            f"\nDone. Closed {closed_count} stale recommendation(s), "
            f"triggered {triggered_count} new workflow(s)."
        )
        if args.dry_run:
            print("(--dry-run set — nothing was written.)")


if __name__ == "__main__":
    main()
