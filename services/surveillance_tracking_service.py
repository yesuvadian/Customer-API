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
        # Find surveillance test tracking record
        surveillance_test = (
            self.db.query(RepairSurveillanceTest)
            .filter(RepairSurveillanceTest.testing_request_id == testing_request_id)
            .first()
        )

        if not surveillance_test:
            # Not a surveillance test - silently return
            return

        # Get testing request for config lookup
        testing_request = self.db.query(TestingRequest).filter(
            TestingRequest.id == testing_request_id
        ).first()

        if not testing_request:
            logger.warning(
                "[SurveillanceTracking] Testing request %s not found",
                testing_request_id
            )
            return

        # Update tracking record
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

        self.db.commit()

        logger.info(
            "[SurveillanceTracking] Updated test %s: status=%s, result=%s, abnormal=%s",
            surveillance_test.id, test_status, result_status, surveillance_test.is_abnormal
        )

        # Send alert if abnormal (optional enhancement)
        if surveillance_test.is_abnormal:
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
            equipment_name = testing_request.equipment.name if testing_request.equipment else "Unknown"

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
