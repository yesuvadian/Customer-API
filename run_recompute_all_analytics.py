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
from services.evaluation_service import EvaluationService


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
        template_cache: dict = {}
        done, failed = 0, 0
        for tr in results:
            try:
                cache_key = (tr.template_key, tr.organization_id)
                if cache_key not in template_cache:
                    template_cache[cache_key] = EvaluationService.get_template_data(
                        tr.template_key, db, org_id=tr.organization_id
                    )
                template_data = template_cache[cache_key]
                if template_data:
                    tr.evaluation_result = EvaluationService.evaluate_test_data(
                        template_data, tr.test_data or {}, db
                    )
                    db.flush()

                engine.run_for_test(tr.id)
                done += 1
            except Exception as exc:
                failed += 1
                print(f"  FAILED for test_result {tr.id}: {exc}")
        # Second pass: re-aggregate EVERY equipment that has a health row.
        # The loop above only reaches equipment with an eligible result, so
        # a stale EquipmentAnalytics row with no accepted result behind it
        # (e.g. its only request was rejected / cancelled / reopened) kept
        # its old score - the dashboards showed HEALTH 0 while the Test
        # Results dialog was empty. run_for_equipment() resets such rows.
        from models import EquipmentAnalytics
        eq_ids = [row[0] for row in db.query(EquipmentAnalytics.equipment_id).all()]
        for eq_id in eq_ids:
            try:
                engine.run_for_equipment(eq_id)
            except Exception as exc:
                failed += 1
                print(f"  FAILED equipment re-aggregation {eq_id}: {exc}")
        db.commit()
        print(f"Recompute complete: {done} recomputed, {failed} failed, {len(results)} total eligible, "
              f"{len(eq_ids)} equipment re-aggregated")
    finally:
        db.close()


if __name__ == "__main__":
    run_recompute_all()
