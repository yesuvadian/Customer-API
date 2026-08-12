#!/usr/bin/env python3
"""
Recompute analytics for every submitted TestResult in the DB.

Standalone equivalent of POST /analytics/recompute-all (routers/analytics.py),
run directly against the DB so it doesn't need an authenticated admin session.
Re-runs score_test + equipment aggregation for every TestResult whose testing
request is in a terminal/submitted state, backfilling trend/annual_change AND
current_value/last_tested_at so they stay consistent with each other.

Run once:
    python run_recompute_all_analytics.py
"""
from database import VendorSessionLocal
from models import TestResult, TestingRequest, TestingRequestStatus, TrWfInstance
from services.analytics_engine import AnalyticsEngine


def run_recompute_all():
    db = VendorSessionLocal()
    try:
        _SKIP_STATUSES = {
            TestingRequestStatus.draft,
            TestingRequestStatus.submitted,
            TestingRequestStatus.assigned,
            TestingRequestStatus.accepted,
            TestingRequestStatus.in_progress,
        }

        wf_active_ids = {
            row.testing_request_id
            for row in db.query(TrWfInstance.testing_request_id).filter(
                TrWfInstance.status == "active"
            ).all()
        }

        results = db.query(TestResult).all()
        results = [
            r for r in results
            if r.testing_request
            and r.testing_request.status not in _SKIP_STATUSES
            and r.testing_request_id not in wf_active_ids
        ]

        engine = AnalyticsEngine(db)
        done, failed = 0, 0
        for tr in results:
            try:
                engine.run_for_test(tr.id)
                done += 1
            except Exception as exc:
                failed += 1
                print(f"  FAILED for test_result {tr.id}: {exc}")
        db.commit()
        print(f"Recompute complete: {done} recomputed, {failed} failed, {len(results)} total eligible")
    finally:
        db.close()


if __name__ == "__main__":
    run_recompute_all()
