"""
Automatic Status Transition Service

Handles automatic status changes for multi-session testing requests.
When all sessions are completed, automatically moves the testing request
to "test_submitted" status and notifies approvers.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import TestingRequest, TestSession, TestingRequestStatus
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


class AutoStatusTransitionService:
    def __init__(self, db: Session):
        self.db = db

    def check_and_transition_if_all_sessions_complete(self, testing_request_id: uuid.UUID) -> bool:
        """
        Check if all sessions for a multi-session test are completed.
        If yes, automatically transition status to test_submitted.

        Returns:
            bool: True if status was transitioned, False otherwise
        """
        try:
            # Get testing request
            testing_request = (
                self.db.query(TestingRequest)
                .filter(TestingRequest.id == testing_request_id)
                .first()
            )

            if not testing_request:
                logger.warning(f"Testing request {testing_request_id} not found")
                return False

            # Only auto-transition if:
            # 1. It's a multi-session test
            # 2. Current status is 'in_progress'
            if not testing_request.is_multi_session:
                logger.debug(f"Request {testing_request_id} is not multi-session, skipping")
                return False

            if testing_request.status != TestingRequestStatus.in_progress:
                logger.debug(
                    f"Request {testing_request_id} status is {testing_request.status}, "
                    f"not in_progress, skipping"
                )
                return False

            # Get all sessions for this request
            sessions = (
                self.db.query(TestSession)
                .filter(TestSession.testing_request_id == testing_request_id)
                .all()
            )

            if not sessions:
                logger.warning(f"No sessions found for request {testing_request_id}")
                return False

            # Check if all sessions are completed
            all_completed = all(session.status == "completed" for session in sessions)

            if all_completed:
                logger.info(
                    f"All {len(sessions)} sessions completed for request {testing_request_id}. "
                    f"Auto-transitioning to test_submitted"
                )

                # Transition status
                testing_request.status = TestingRequestStatus.test_submitted
                testing_request.submitted_at = datetime.now(timezone.utc)

                self.db.commit()

                self._notify_approvers(testing_request)

                return True
            else:
                completed_count = sum(1 for s in sessions if s.status == "completed")
                logger.debug(
                    f"Request {testing_request_id}: {completed_count}/{len(sessions)} "
                    f"sessions completed. Waiting for all to complete."
                )
                return False

        except Exception as e:
            logger.error(f"Error in auto status transition: {e}", exc_info=True)
            self.db.rollback()
            return False

    def check_all_pending_multi_session_tests(self) -> int:
        """
        Scheduled job to check all in_progress multi-session tests:
        1. Check if all sessions completed → auto-submit
        2. Check if end date elapsed → mark incomplete sessions as skipped, auto-submit

        Returns:
            int: Number of tests that were transitioned
        """
        try:
            # Find all in_progress multi-session tests
            in_progress_tests = (
                self.db.query(TestingRequest)
                .filter(
                    TestingRequest.status == TestingRequestStatus.in_progress,
                    TestingRequest.is_multi_session == True,
                )
                .all()
            )

            transitioned_count = 0

            for test in in_progress_tests:
                # Check if all sessions completed (normal completion)
                if self.check_and_transition_if_all_sessions_complete(test.id):
                    transitioned_count += 1
                    continue

                # Check if end date elapsed (forced completion)
                if self._check_and_transition_if_end_date_elapsed(test):
                    transitioned_count += 1

            if transitioned_count > 0:
                logger.info(
                    f"Auto-transitioned {transitioned_count} multi-session tests to test_submitted"
                )

            return transitioned_count

        except Exception as e:
            logger.error(f"Error in scheduled auto transition check: {e}", exc_info=True)
            return 0

    def _check_and_transition_if_end_date_elapsed(self, testing_request: TestingRequest) -> bool:
        """
        Check if the scheduled end date for a multi-session test has passed.
        If yes, mark all incomplete sessions as 'skipped' and auto-submit.

        Returns:
            bool: True if status was transitioned, False otherwise
        """
        from datetime import timedelta

        try:
            # Calculate end date
            if not testing_request.scheduled_start_date:
                return False

            # End date = start_date + ((total_sessions - 1) * interval_days)
            days_needed = (
                (testing_request.total_sessions_planned - 1)
                * testing_request.session_interval_days
            )
            end_date = testing_request.scheduled_start_date + timedelta(days=days_needed)
            # Normalise: make end_date timezone-aware so it can be compared with now
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)

            # Check if end date has passed
            now = datetime.now(timezone.utc)
            if now <= end_date:
                return False  # End date not yet reached

            logger.info(
                f"End date elapsed for request {testing_request.id}. "
                f"End date: {end_date}, Now: {now}"
            )

            # Get all sessions
            sessions = (
                self.db.query(TestSession)
                .filter(TestSession.testing_request_id == testing_request.id)
                .all()
            )

            # Mark incomplete sessions as 'skipped'
            skipped_count = 0
            completed_count = 0

            for session in sessions:
                if session.status == "completed":
                    completed_count += 1
                elif session.status in ("scheduled", "in_progress"):
                    session.status = "skipped"
                    skipped_count += 1

            # Auto-submit test
            testing_request.status = TestingRequestStatus.test_submitted
            testing_request.submitted_at = datetime.now(timezone.utc)

            self.db.commit()

            logger.warning(
                f"Auto-submitted request {testing_request.id} due to elapsed end date. "
                f"Completed: {completed_count}/{len(sessions)}, "
                f"Skipped: {skipped_count}"
            )

            # TODO: Send notification to approvers with warning
            # self._notify_approvers_partial_completion(
            #     testing_request, completed_count, len(sessions), skipped_count
            # )

            return True

        except Exception as e:
            logger.error(
                f"Error checking end date for request {testing_request.id}: {e}",
                exc_info=True,
            )
            self.db.rollback()
            return False

    def _notify_approvers(self, testing_request: TestingRequest):
        """Notify approvers that all sessions are complete and test is ready for review."""
        try:
            from services.notification_service import NotificationService
            NotificationService(self.db).notify_test_submitted(testing_request)
        except Exception as _n:
            logger.warning(f"[Notif] auto-transition notify_approvers failed: {_n}")
