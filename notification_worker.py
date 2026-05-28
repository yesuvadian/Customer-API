#!/usr/bin/env python3
"""
Notification Engine Worker

Continuously polls for pending notification events and processes them asynchronously.
Runs as a separate process/service independent from the main FastAPI application.

Features:
- Non-blocking: Doesn't impact API request/response cycle
- Reliable: Events persisted to database, won't lose notifications
- Scalable: Can run multiple worker instances in parallel
- Retry logic: Auto-retry failed notifications with exponential backoff
- Graceful shutdown: Handles SIGTERM/SIGINT signals

Usage:
    # Run directly
    python notification_worker.py

    # Run as systemd service
    systemctl start cogniwatt-notification-worker

    # Run with custom poll interval
    POLL_INTERVAL=10 python notification_worker.py

Environment Variables:
    DATABASE_URL: PostgreSQL connection string (required)
    POLL_INTERVAL: Polling interval in seconds (default: 5)
    BATCH_SIZE: Number of events to process per batch (default: 10)
    LOG_LEVEL: Logging level (default: INFO)
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import NotificationEvent
from services.notification_service import NotificationService

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NotificationWorker:
    """
    Notification event processor worker.

    Polls the notification_events table for pending events and dispatches
    notifications via the NotificationService.
    """

    def __init__(
        self,
        db_url: str,
        poll_interval: int = 5,
        batch_size: int = 10,
    ):
        """
        Initialize the notification worker.

        Args:
            db_url: PostgreSQL connection string
            poll_interval: Seconds to wait between polling cycles
            batch_size: Maximum number of events to process per batch
        """
        self.db_url = db_url
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.running = False

        # Create database engine with connection pooling
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,  # Verify connections before using
            pool_size=5,
            max_overflow=10,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        logger.info(f"Notification Worker initialized (poll_interval={poll_interval}s, batch_size={batch_size})")

    def _shutdown(self, signum, frame):
        """Handle graceful shutdown on SIGTERM/SIGINT."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def start(self):
        """Start the worker polling loop."""
        logger.info("=" * 60)
        logger.info("Notification Worker started")
        logger.info(f"Database: {self.db_url.split('@')[1] if '@' in self.db_url else 'N/A'}")
        logger.info(f"Poll interval: {self.poll_interval}s")
        logger.info(f"Batch size: {self.batch_size}")
        logger.info("=" * 60)

        self.running = True
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self.running:
            try:
                processed = self._process_batch()

                if processed > 0:
                    logger.info(f"Processed {processed} events")
                    consecutive_errors = 0  # Reset error counter on success

                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, shutting down...")
                break

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Worker error ({consecutive_errors}/{max_consecutive_errors}): {e}", exc_info=True)

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
                        f"Too many consecutive errors ({max_consecutive_errors}), shutting down. "
                        f"Please check database connectivity and configuration."
                    )
                    break

                # Exponential backoff on errors
                backoff_time = min(self.poll_interval * (2 ** consecutive_errors), 60)
                logger.info(f"Backing off for {backoff_time}s before retry...")
                time.sleep(backoff_time)

        logger.info("Notification Worker stopped")

    def _process_batch(self) -> int:
        """
        Process a batch of pending notification events.

        Returns:
            Number of events processed
        """
        db = self.SessionLocal()
        try:
            # Fetch pending events with row-level locking
            # SKIP LOCKED ensures multiple workers don't process the same event
            events = (
                db.query(NotificationEvent)
                .filter(NotificationEvent.status == 'pending')
                .filter(NotificationEvent.scheduled_for <= datetime.utcnow())
                .filter(NotificationEvent.attempts < NotificationEvent.max_attempts)
                .order_by(NotificationEvent.created_at)
                .limit(self.batch_size)
                .with_for_update(skip_locked=True)
                .all()
            )

            if not events:
                return 0

            logger.debug(f"Processing {len(events)} notification events...")

            processed_count = 0
            for event in events:
                try:
                    self._process_event(db, event)
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Failed to process event {event.id}: {e}", exc_info=True)
                    # Continue processing other events even if one fails

            db.commit()
            return processed_count

        except Exception as e:
            db.rollback()
            logger.error(f"Batch processing error: {e}", exc_info=True)
            raise

        finally:
            db.close()

    def _process_event(self, db: Session, event: NotificationEvent):
        """
        Process a single notification event.

        Args:
            db: Database session
            event: NotificationEvent to process
        """
        try:
            # Mark as processing
            event.status = 'processing'
            event.attempts += 1
            db.flush()

            logger.info(
                f"Processing event {event.id} (type={event.event_type}, "
                f"workflow={event.workflow_type}, attempt={event.attempts}/{event.max_attempts})"
            )

            # Process the notification using NotificationService
            notification_service = NotificationService(db)

            notification_service.fire(
                event_type=event.event_type,
                workflow_type=event.workflow_type,
                equipment_type=event.equipment_type,
                test_category=event.test_category,
                status_from=event.status_from,
                status_to=event.status_to,
                context=event.payload,
                organization_id=event.organization_id,
            )

            # Mark as sent
            event.status = 'sent'
            event.processed_at = datetime.utcnow()
            event.last_error = None

            logger.info(f"✓ Successfully processed event {event.id}")

        except Exception as e:
            # Record error
            event.last_error = str(e)[:1000]  # Limit error message length

            if event.attempts >= event.max_attempts:
                # Exhausted retries, mark as failed
                event.status = 'failed'
                logger.error(
                    f"✗ Event {event.id} FAILED after {event.attempts} attempts: {e}"
                )
            else:
                # Will retry - schedule with exponential backoff
                event.status = 'pending'
                backoff_minutes = 2 ** event.attempts  # 2, 4, 8 minutes
                event.scheduled_for = datetime.utcnow() + timedelta(minutes=backoff_minutes)

                logger.warning(
                    f"⚠ Event {event.id} failed (attempt {event.attempts}), "
                    f"will retry in {backoff_minutes} minutes: {e}"
                )

            db.flush()


def main():
    """Main entry point for the notification worker."""
    # Get configuration from environment
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    poll_interval = int(os.getenv("POLL_INTERVAL", "5"))
    batch_size = int(os.getenv("BATCH_SIZE", "10"))

    # Validate configuration
    if poll_interval < 1:
        logger.error("ERROR: POLL_INTERVAL must be >= 1")
        sys.exit(1)

    if batch_size < 1:
        logger.error("ERROR: BATCH_SIZE must be >= 1")
        sys.exit(1)

    # Create and start worker
    worker = NotificationWorker(
        db_url=db_url,
        poll_interval=poll_interval,
        batch_size=batch_size,
    )

    try:
        worker.start()
    except Exception as e:
        logger.critical(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
