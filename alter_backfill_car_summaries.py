#!/usr/bin/env python3
"""
One-time fix: fill in the summary of CARs created without one.

Before services/car_service.build_car_summary() existed, a CAR's summary
came from EvaluationService.build_remedial_summary(), which only reads
remedial text set on a field itself - table templates (DGA, oil, tan delta)
carry it per row / cell, and number templates often have none - so most
CARs were saved with summary NULL. This rebuilds it from the CAR's source
test result's stored evaluation, the same way new CARs now get theirs.

Only touches CARs whose summary is NULL/blank unless --all is given.
Dry run by default - prints the new summaries and writes nothing.

Usage:
    python alter_backfill_car_summaries.py            # dry run
    python alter_backfill_car_summaries.py --apply    # write
    python alter_backfill_car_summaries.py --all      # also rebuild non-empty summaries
"""
import argparse
import sys

from sqlalchemy import or_

from database import VendorSessionLocal
from models import CarRelationshipType, CarTestRequest, CorrectiveActionRequest, TestingRequest, TestResult
from services.car_service import build_car_summary


def main():
    parser = argparse.ArgumentParser(description="Fill in missing CAR summaries from their source test result.")
    parser.add_argument("--apply", action="store_true", help="Write the summaries (default: dry run)")
    parser.add_argument("--all", action="store_true", help="Rebuild every CAR's summary, not just empty ones")
    args = parser.parse_args()

    print(f"=== CAR summary backfill ({'APPLY' if args.apply else 'DRY RUN'}) ===")
    db = VendorSessionLocal()
    try:
        q = db.query(CorrectiveActionRequest)
        if not args.all:
            q = q.filter(or_(CorrectiveActionRequest.summary.is_(None), CorrectiveActionRequest.summary == ""))
        cars = q.order_by(CorrectiveActionRequest.car_number).all()

        updated, skipped = 0, 0
        for car in cars:
            result = (
                db.query(TestResult).filter(TestResult.id == car.source_test_result_id).first()
                if car.source_test_result_id else None
            )
            if result is None or not result.evaluation_result:
                print(f"  skip  {car.car_number}: source test result / evaluation not found")
                skipped += 1
                continue

            link = (
                db.query(CarTestRequest)
                .filter(CarTestRequest.car_id == car.id,
                        CarTestRequest.relationship_type == CarRelationshipType.ORIGINATING)
                .first()
            )
            tr = db.query(TestingRequest).filter(TestingRequest.id == link.test_request_id).first() if link else None

            summary = build_car_summary(result.evaluation_result, car.severity, request_title=(tr.title if tr else "") or "")
            print(f"\n  {car.car_number}:\n    {summary}")
            if args.apply:
                car.summary = summary
            updated += 1

        if args.apply:
            db.commit()
            print(f"\n[OK] Updated {updated} CAR summar{'y' if updated == 1 else 'ies'}; skipped {skipped}.")
        else:
            db.rollback()
            print(f"\nDry run - {updated} would be updated, {skipped} skipped. Re-run with --apply to write.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] {exc} - rolled back, nothing written.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
