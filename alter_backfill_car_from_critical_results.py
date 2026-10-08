#!/usr/bin/env python3
"""
One-time backfill: create Corrective Action Requests for equipment whose
CURRENT test condition is CRITICAL (or ALERT, when opted in and a CAR
Trigger Config rule says ALERT triggers) but that never got a CAR - results
submitted before the CAR module existed, or ALERT results from before the
ALERT hook was wired in.

CARs only. Unlike the live hook (services/car_service.process_evaluation_for_car)
this does NOT:
  - raise follow-up / retest Testing Requests (they would all be due within
    days of running this, in bulk),
  - fire car_created notifications.
Each backfilled CAR is created OPEN with its source request linked as
ORIGINATING, for an admin to assign from the Corrective Action Requests
screen. From then on the live hook takes over: the next same-test-type
result on that equipment links to it (non-NORMAL -> retest raised) or
closes it (NORMAL).

Which results count - "current condition", not every CRITICAL ever:
  - only ACCEPTED results (analytics_engine.accepted_test_result_ids - the
    same rule health scores use; in-review / rejected / cancelled excluded),
  - only the LATEST accepted result per (equipment, test type) - a CRITICAL
    that a later NORMAL superseded is already resolved,
  - the latest result's request must not be a historical data import
    (notes start "[IMP-") unless --include-imported,
  - the CAR Trigger Config rule for (org, equipment type, test type,
    severity) must trigger - same lookup and ALERT + CRITICAL default as the
    live hook,
  - skipped when an open CAR already covers that request's lineage, or any
    CAR (open or closed) was already raised from that exact result - so
    re-running is safe.

Dry run by default - prints what it would create and writes nothing.

Usage:
    python alter_backfill_car_from_critical_results.py                  # dry run
    python alter_backfill_car_from_critical_results.py --apply          # write
    python alter_backfill_car_from_critical_results.py --include-alert  # also ALERT
    python alter_backfill_car_from_critical_results.py --org-id <uuid> --verbose
"""
import argparse
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from database import VendorSessionLocal
from config import CAR_DUE_DAYS_ALERT, CAR_DUE_DAYS_CRITICAL
from models import (
    CarRelationshipType,
    CarStatus,
    CarTestRequest,
    CorrectiveActionRequest,
    TestingRequest,
    TestResult,
)
from services.analytics_engine import accepted_test_result_ids
from services.car_service import (
    DEFAULT_CAR_TRIGGER_SEVERITIES,
    _car_number,
    _find_trigger_config,
    build_car_summary,
    find_open_car_for_lineage,
)


def _triggers(db, tr: TestingRequest, severity: str) -> bool:
    """Same decision process_evaluation_for_car makes for a NEW CAR."""
    config = _find_trigger_config(
        db,
        organization_id=tr.organization_id,
        equipment_type_id=tr.equipment_type_id,
        test_type_id=tr.test_type_id,
        severity=severity,
    )
    if config is not None:
        return bool(config.car_trigger)
    return severity in DEFAULT_CAR_TRIGGER_SEVERITIES


def _latest_accepted_results(db, org_id):
    """(TestResult, TestingRequest) for the latest accepted result per
    (equipment_id, test_type_id), newest first."""
    q = (
        db.query(TestResult, TestingRequest)
        .join(TestingRequest, TestingRequest.id == TestResult.testing_request_id)
        .filter(
            TestResult.id.in_(accepted_test_result_ids(db)),
            TestResult.evaluation_result.isnot(None),
            TestingRequest.equipment_id.isnot(None),
            TestingRequest.test_type_id.isnot(None),
        )
    )
    if org_id:
        q = q.filter(TestingRequest.organization_id == org_id)
    q = q.order_by(
        TestResult.tested_at.desc().nullslast(),
        TestResult.cts.desc().nullslast(),
    )

    seen = set()
    for result, tr in q.yield_per(500):
        key = (tr.equipment_id, tr.test_type_id)
        if key in seen:
            continue
        seen.add(key)
        yield result, tr


def main():
    parser = argparse.ArgumentParser(description="Backfill CARs for current CRITICAL test results (CARs only).")
    parser.add_argument("--apply", action="store_true", help="Write the CARs (default: dry run)")
    parser.add_argument("--include-alert", action="store_true",
                        help="Also consider ALERT results (only where a CAR Trigger Config rule triggers on ALERT)")
    parser.add_argument("--include-imported", action="store_true",
                        help="Also consider results from historical data imports")
    parser.add_argument("--org-id", type=uuid.UUID, help="Limit to one organization")
    parser.add_argument("--verbose", action="store_true", help="Also list skipped results and why")
    args = parser.parse_args()

    severities = {"CRITICAL", "ALERT"} if args.include_alert else {"CRITICAL"}
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== CAR backfill ({mode}) - severities: {', '.join(sorted(severities))} ===")

    db = VendorSessionLocal()
    skipped = Counter()
    planned = []
    try:
        for result, tr in _latest_accepted_results(db, args.org_id):
            ev = result.evaluation_result or {}
            severity = ev.get("overall") if isinstance(ev, dict) else None
            label = f"{tr.request_number or tr.id} (result {result.id})"

            if severity not in ("ALERT", "CRITICAL"):
                skipped["latest result is NORMAL / no severity"] += 1  # the common case - never listed
                continue

            reason = None
            if severity not in severities:
                reason = f"latest result is {severity} (pass --include-alert)"
            elif not args.include_imported and (tr.notes or "").startswith("[IMP-"):
                reason = "historical data import"
            elif db.query(CorrectiveActionRequest.id).filter(
                CorrectiveActionRequest.source_test_result_id == result.id
            ).first():
                reason = "CAR already raised from this result"
            elif db.query(CarTestRequest.id).filter(CarTestRequest.test_request_id == tr.id).first():
                # already part of a CAR (open, closed or voided) - that CAR
                # handled this result, e.g. closed on an approved replacement
                reason = "request already linked to a CAR"
            elif find_open_car_for_lineage(db, tr):
                reason = "open CAR already covers this lineage"
            elif not _triggers(db, tr, severity):
                reason = f"CAR Trigger Config does not trigger on {severity}"

            if reason:
                skipped[reason] += 1
                if args.verbose:
                    print(f"  skip  {label}: {reason}")
                continue

            planned.append((result, tr, severity, ev))

        print(f"\nCandidates: {len(planned)}")
        for result, tr, severity, _ev in planned:
            tested = result.tested_at.date().isoformat() if result.tested_at else "?"
            equipment = getattr(tr.equipment, "ueic", None) or tr.equipment_id
            test_type = getattr(tr.test_type, "name", None) or f"test_type_id={tr.test_type_id}"
            print(f"  {severity:8} {tr.request_number or tr.id}  {equipment}  {test_type}  tested={tested}")

        if skipped:
            print("\nSkipped:")
            for reason, n in skipped.most_common():
                print(f"  {n:5}  {reason}")

        if not args.apply:
            print("\nDry run - nothing written. Re-run with --apply to create these CARs.")
            return 0

        today = datetime.now(timezone.utc)
        created = []
        for result, tr, severity, ev in planned:
            due_days = CAR_DUE_DAYS_CRITICAL if severity == "CRITICAL" else CAR_DUE_DAYS_ALERT
            car = CorrectiveActionRequest(
                car_number=_car_number(db),
                equipment_id=tr.equipment_id,
                organization_id=tr.organization_id,
                department_id=tr.department_id,
                source_test_result_id=result.id,
                template_key=result.template_key,
                severity=severity,
                summary=build_car_summary(ev, severity, request_title=tr.title or ""),
                status=CarStatus.OPEN,
                due_date=(today + timedelta(days=due_days)).date(),
            )
            db.add(car)
            db.flush()  # so the next _car_number() count sees this one
            db.add(CarTestRequest(
                car_id=car.id,
                test_request_id=tr.id,
                relationship_type=CarRelationshipType.ORIGINATING,
            ))
            db.flush()
            created.append((car.car_number, tr.request_number or str(tr.id)))

        db.commit()
        print(f"\n[OK] Created {len(created)} CAR(s):")
        for car_number, request_number in created:
            print(f"  {car_number}  <- {request_number}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] {exc} - rolled back, nothing written.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
