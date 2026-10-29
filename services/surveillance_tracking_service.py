"""
surveillance_tracking_service.py
─────────────────────────────────
Tracks surveillance test results and updates RepairSurveillanceTest table.

Called from TestingService when surveillance test results are submitted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from models import (
    RepairSurveillanceTest,
    TestingRequest,
)
from services.surveillance_config_service import SurveillanceConfigService

logger = logging.getLogger(__name__)


class SurveillanceTrackingService:
    """Service for tracking surveillance test completion and results."""

    def __init__(self, db: Session):
        self.db = db

    def ensure_test_row(self, testing_request: TestingRequest) -> Optional[RepairSurveillanceTest]:
        """
        Get or create the tracking row for a surveillance ticket. Doesn't commit.

        The scheduler never created these rows, so update_test_result found
        nothing and Final Evaluation / the surveillance dashboard always read
        0 tests. Called when the scheduler creates the ticket, and as a
        fallback when a result arrives for a ticket that has no row yet.
        """
        if not testing_request.surveillance_workflow_id or not testing_request.surveillance_quarter:
            return None

        row = (
            self.db.query(RepairSurveillanceTest)
            .filter(RepairSurveillanceTest.testing_request_id == testing_request.id)
            .first()
        )
        if row:
            return row

        status = testing_request.status
        row = RepairSurveillanceTest(
            surveillance_workflow_id=testing_request.surveillance_workflow_id,
            testing_request_id=testing_request.id,
            quarter_number=testing_request.surveillance_quarter,
            test_type_id=testing_request.test_type_id,
            test_status=status.value if hasattr(status, 'value') else status,
            is_abnormal=False,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update_test_result(
        self,
        testing_request_id: UUID,
        test_status: str,
        result_status: Optional[str] = None,
        tested_at: Optional[datetime] = None
    ) -> None:
        """
        Update RepairSurveillanceTest when surveillance test completes.

        Should be called from TestingService.submit_test_results() when
        a testing request with surveillance_workflow_id is submitted.

        Args:
            testing_request_id: Testing request ID
            test_status: New test status (e.g., 'completed')
            result_status: Test result (e.g., 'PASS', 'FAIL', 'MARGINAL')
            tested_at: Test completion timestamp
        """
        testing_request = self.db.query(TestingRequest).filter(
            TestingRequest.id == testing_request_id
        ).first()

        if not testing_request:
            logger.warning(
                "[SurveillanceTracking] Testing request %s not found",
                testing_request_id
            )
            return

        # None when the ticket isn't linked to a surveillance quarter
        surveillance_test = self.ensure_test_row(testing_request)
        if not surveillance_test:
            return

        # Callers pass the tester's pass/fail; the evaluated status wins
        from utils.surveillance_utils import latest_result_status
        derived_status, derived_at = latest_result_status(self.db, testing_request_id)
        result_status = derived_status or result_status
        tested_at = tested_at or derived_at

        # Update tracking record
        was_abnormal = bool(surveillance_test.is_abnormal)
        surveillance_test.test_status = test_status
        surveillance_test.result_status = result_status
        surveillance_test.tested_at = tested_at or datetime.now(timezone.utc)

        # Determine if result is abnormal
        if result_status and testing_request:
            surveillance_test.is_abnormal = SurveillanceConfigService.is_result_abnormal(
                self.db,
                result_status,
                organization_id=testing_request.organization_id,
                department_id=testing_request.department_id
            )
        else:
            surveillance_test.is_abnormal = False

        # Flush, not commit: the TR workflow's recommendation_finalize calls
        # this mid-transition, and that transaction is committed by its caller
        self.db.flush()

        logger.info(
            "[SurveillanceTracking] Updated test %s: status=%s, result=%s, abnormal=%s",
            surveillance_test.id, test_status, result_status, surveillance_test.is_abnormal
        )

        # Alert once: this runs on result approval and again when the
        # workflow ends, and the second call must not repeat the alert
        if surveillance_test.is_abnormal and not was_abnormal:
            self._send_abnormal_alert(surveillance_test, testing_request, result_status)

    def _send_abnormal_alert(
        self,
        surveillance_test: RepairSurveillanceTest,
        testing_request: TestingRequest,
        result_status: str
    ) -> None:
        """
        Send notification when surveillance test fails.

        Optional enhancement - can be disabled by commenting out the call above.
        """
        try:
            from services.notification_service import NotificationService

            # Determine severity
            severity = "critical" if result_status in ["FAIL", "CRITICAL"] else "warning"

            # Get test type name
            test_type_name = testing_request.test_type.name if testing_request.test_type else "Unknown"

            # Get equipment name
            equipment_name = testing_request.equipment.ueic if testing_request.equipment else "Unknown"

            NotificationService(self.db).fire(
                event_type="surveillance_test_abnormal",
                context={
                    "test_type": test_type_name,
                    "result": result_status,
                    "quarter": f"Q{surveillance_test.quarter_number}",
                    "equipment": equipment_name,
                },
                severity=severity,
                organization_id=testing_request.organization_id,
                department_id=testing_request.department_id,
                source_id=surveillance_test.surveillance_workflow_id,
                source_type="surveillance_workflow",
            )

            logger.info(
                "[SurveillanceTracking] Sent %s alert for failed %s test (Q%d)",
                severity, test_type_name, surveillance_test.quarter_number
            )

        except Exception as exc:
            logger.warning(
                "[SurveillanceTracking] Failed to send abnormal test alert: %s",
                exc
            )
            # Don't raise - notification failure shouldn't block test submission
