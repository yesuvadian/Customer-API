"""
Post-transition action registry for the TR Workflow Engine.

Adding a new action:
  1. Subclass BaseWfAction
  2. Set `key` and `label` class attributes
  3. Implement `execute()`

That's it — reflection discovers it automatically via __subclasses__().
The module must be imported before registry() is called (handled by the
router importing list_post_actions which imports this module).
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models import TestingRequest


class BaseWfAction:
    key: str    # stored on TrWfStageTransition.post_action in DB
    label: str  # shown in UI dropdown

    def execute(self, db: "Session", testing_request: "TestingRequest", context: dict) -> None:
        raise NotImplementedError

    @classmethod
    def registry(cls) -> dict[str, type["BaseWfAction"]]:
        return {sub.key: sub for sub in cls.__subclasses__()}


def dispatch(post_action: str, db: "Session", testing_request: "TestingRequest", context: dict) -> None:
    """Fire the registered post-action for a transition. Errors are non-fatal (logged, not raised)."""
    import logging
    log = logging.getLogger(__name__)
    cls = BaseWfAction.registry().get(post_action)
    if not cls:
        log.warning("tr_wf post_action '%s' not found in registry", post_action)
        return
    try:
        cls().execute(db, testing_request, context)
        log.info("tr_wf post_action '%s' completed for request %s", post_action, testing_request.id)
    except Exception as exc:
        log.exception("tr_wf post_action '%s' failed for request %s: %s", post_action, testing_request.id, exc)


# ── Concrete actions ────────────────────────────────────────────────────────────

class RecommendationFinalizeAction(BaseWfAction):
    key   = "recommendation_finalize"
    label = "Finalize Recommendation"

    def execute(self, db, testing_request, context):
        """
        Trigger downstream recommendation processing after L3 approves test results:
        - Fires any pending surveillance/schedule updates
        - Notifies relevant parties via NotificationService
        """
        from services.notification_service import NotificationService
        try:
            NotificationService(db).notify_recommendation_approved(testing_request)
        except Exception:
            pass

        # Run analytics engine for the latest test result
        try:
            from models import TestResult
            from services.analytics_engine import AnalyticsEngine
            import logging as _log
            latest = (
                db.query(TestResult)
                .filter(TestResult.testing_request_id == testing_request.id)
                .order_by(TestResult.tested_at.desc())
                .first()
            )
            if latest:
                AnalyticsEngine(db).run_for_test(latest.id)
                _log.getLogger(__name__).info(
                    "recommendation_finalize: analytics run for request %s (result %s)",
                    testing_request.id, latest.id,
                )
        except Exception:
            pass

        # Surveillance tracking update if linked
        if getattr(testing_request, "surveillance_workflow_id", None):
            try:
                from services.surveillance_tracking_service import SurveillanceTrackingService
                from models import TestResult
                latest = (
                    db.query(TestResult)
                    .filter(TestResult.testing_request_id == testing_request.id)
                    .order_by(TestResult.tested_at.desc())
                    .first()
                )
                SurveillanceTrackingService(db).update_test_result(
                    testing_request_id=testing_request.id,
                    test_status="completed",
                    result_status=latest.overall_result if latest else None,
                    tested_at=latest.tested_at if latest else None,
                )
            except Exception:
                pass


class ProcurementInitiateAction(BaseWfAction):
    key   = "procurement_initiate"
    label = "Initiate Procurement"

    def execute(self, db, testing_request, context):
        """
        Trigger procurement workflow when an approved recommendation requires replacement.
        Placeholder — wire to your procurement service when ready.
        """
        import logging
        logging.getLogger(__name__).info(
            "procurement_initiate fired for request %s (not yet implemented)",
            testing_request.id,
        )


class ScheduleCreateAction(BaseWfAction):
    key   = "schedule_create"
    label = "Create Follow-up Schedule"

    def execute(self, db, testing_request, context):
        """
        Auto-create a surveillance/maintenance schedule from the recommendation's
        schedule_frequency and dates. Placeholder — wire to your scheduling service.
        """
        import logging
        logging.getLogger(__name__).info(
            "schedule_create fired for request %s (not yet implemented)",
            testing_request.id,
        )


class TriggerAnalyticsAction(BaseWfAction):
    key   = "trigger_analytics"
    label = "Trigger Analytics Engine"

    def execute(self, db, testing_request, context):
        """
        Run the analytics engine for the latest TestResult on this request.
        Updates ParameterAnalytics, TestAnalytics, EquipmentAnalytics and
        hierarchy aggregates so dashboards reflect the completed test immediately.
        """
        import logging
        from models import TestResult
        from services.analytics_engine import AnalyticsEngine

        log = logging.getLogger(__name__)

        latest = (
            db.query(TestResult)
            .filter(TestResult.testing_request_id == testing_request.id)
            .order_by(TestResult.tested_at.desc())
            .first()
        )
        if not latest:
            log.warning("trigger_analytics: no TestResult for request %s", testing_request.id)
            return

        AnalyticsEngine(db).run_for_test(latest.id)
        log.info("trigger_analytics: analytics completed for request %s (result %s)", testing_request.id, latest.id)
