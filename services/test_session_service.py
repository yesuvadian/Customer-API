"""
Test Session Service - Manage multi-day, multi-session testing with multiple readings.

Supports:
- Creating test sessions for a testing request
- Recording multiple readings per session
- Tracking session status and progress
- Environmental conditions and witness information
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    TestingRequest,
    TestSession,
    TestSessionReading,
    TestSessionReadingImage,
    User,
)
from utils.common_service import UTCDateTimeMixin


class TestSessionService(UTCDateTimeMixin):

    def __init__(self, db: Session):
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # TEST SESSION CRUD
    # ═══════════════════════════════════════════════════════════

    def create_session(
        self,
        testing_request_id: UUID,
        session_number: int,
        session_name: Optional[str],
        session_date: datetime,
        scheduled_date: Optional[datetime],
        template_key: Optional[str],
        notes: Optional[str],
        weather_conditions: Optional[str],
        environmental_factors: Optional[str],
        organization_id: Optional[UUID],
        created_by: UUID,
    ) -> TestSession:
        """Create a new test session for a testing request."""
        # Validate testing request exists
        testing_request = self.db.query(TestingRequest).filter(
            TestingRequest.id == testing_request_id
        ).first()
        if not testing_request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Testing request not found"
            )

        # Check if session number already exists
        existing = self.db.query(TestSession).filter(
            TestSession.testing_request_id == testing_request_id,
            TestSession.session_number == session_number,
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session number {session_number} already exists for this testing request"
            )

        session = TestSession(
            testing_request_id=testing_request_id,
            organization_id=organization_id or testing_request.organization_id,
            session_number=session_number,
            session_name=session_name,
            session_date=session_date,
            scheduled_date=scheduled_date,
            template_key=template_key,
            notes=notes,
            weather_conditions=weather_conditions,
            environmental_factors=environmental_factors,
            status="scheduled",
            created_by=created_by,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, session_id: UUID) -> TestSession:
        """Get a test session by ID."""
        session = self.db.query(TestSession).filter(
            TestSession.id == session_id
        ).first()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test session not found"
            )
        return session

    def list_sessions(
        self,
        testing_request_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[TestSession]:
        """List all sessions for a testing request."""
        return (
            self.db.query(TestSession)
            .filter(TestSession.testing_request_id == testing_request_id)
            .order_by(TestSession.session_number)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def update_session(
        self,
        session_id: UUID,
        session_name: Optional[str] = None,
        session_date: Optional[datetime] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        weather_conditions: Optional[str] = None,
        environmental_factors: Optional[str] = None,
        conducted_by: Optional[UUID] = None,
        witnessed_by: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        modified_by: Optional[UUID] = None,
    ) -> TestSession:
        """Update a test session."""
        session = self.get_session(session_id)

        if session_name is not None:
            session.session_name = session_name
        if session_date is not None:
            session.session_date = session_date
        if status is not None:
            session.status = status
        if notes is not None:
            session.notes = notes
        if weather_conditions is not None:
            session.weather_conditions = weather_conditions
        if environmental_factors is not None:
            session.environmental_factors = environmental_factors
        if conducted_by is not None:
            session.conducted_by = conducted_by
        if witnessed_by is not None:
            session.witnessed_by = witnessed_by
        if started_at is not None:
            session.started_at = started_at
        if completed_at is not None:
            session.completed_at = completed_at

        session.modified_by = modified_by
        session.mts = self._utc_now()

        self.db.commit()
        self.db.refresh(session)
        return session

    def delete_session(self, session_id: UUID) -> bool:
        """Delete a test session and all its readings."""
        session = self.get_session(session_id)
        self.db.delete(session)
        self.db.commit()
        return True

    def start_session(self, session_id: UUID, conducted_by: UUID) -> TestSession:
        """Mark a session as in progress."""
        return self.update_session(
            session_id=session_id,
            status="in_progress",
            conducted_by=conducted_by,
            started_at=self._utc_now(),
        )

    def complete_session(self, session_id: UUID) -> TestSession:
        """Mark a session as completed and check for auto-transition."""
        session = self.update_session(
            session_id=session_id,
            status="completed",
            completed_at=self._utc_now(),
        )

        # Auto-transition to test_submitted if all sessions are complete
        from services.auto_status_transition_service import AutoStatusTransitionService
        auto_transition = AutoStatusTransitionService(self.db)
        auto_transition.check_and_transition_if_all_sessions_complete(session.testing_request_id)

        return session

    # ═══════════════════════════════════════════════════════════
    # TEST SESSION READING CRUD
    # ═══════════════════════════════════════════════════════════

    def create_reading(
        self,
        session_id: UUID,
        reading_number: int,
        reading_time: datetime,
        reading_data: dict,
        equipment_serial: Optional[str],
        calibration_date: Optional[datetime],
        remarks: Optional[str],
        result_status: Optional[str],
        recorded_by: UUID,
    ) -> TestSessionReading:
        """Create a new reading for a test session."""
        # Validate session exists
        session = self.get_session(session_id)

        # Check if reading number already exists
        existing = self.db.query(TestSessionReading).filter(
            TestSessionReading.test_session_id == session_id,
            TestSessionReading.reading_number == reading_number,
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Reading number {reading_number} already exists for this session"
            )

        reading = TestSessionReading(
            test_session_id=session_id,
            reading_number=reading_number,
            reading_time=reading_time,
            reading_data=reading_data,
            equipment_serial=equipment_serial,
            calibration_date=calibration_date,
            remarks=remarks,
            result_status=result_status,
            recorded_by=recorded_by,
        )
        self.db.add(reading)
        self.db.commit()
        self.db.refresh(reading)
        return reading

    def get_reading(self, reading_id: UUID) -> TestSessionReading:
        """Get a reading by ID."""
        reading = self.db.query(TestSessionReading).filter(
            TestSessionReading.id == reading_id
        ).first()
        if not reading:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reading not found"
            )
        return reading

    def list_readings(
        self,
        session_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[TestSessionReading]:
        """List all readings for a session."""
        return (
            self.db.query(TestSessionReading)
            .filter(TestSessionReading.test_session_id == session_id)
            .order_by(TestSessionReading.reading_number)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def update_reading(
        self,
        reading_id: UUID,
        reading_time: Optional[datetime] = None,
        reading_data: Optional[dict] = None,
        equipment_serial: Optional[str] = None,
        calibration_date: Optional[datetime] = None,
        remarks: Optional[str] = None,
        result_status: Optional[str] = None,
    ) -> TestSessionReading:
        """Update a reading."""
        reading = self.get_reading(reading_id)

        if reading_time is not None:
            reading.reading_time = reading_time
        if reading_data is not None:
            reading.reading_data = reading_data
        if equipment_serial is not None:
            reading.equipment_serial = equipment_serial
        if calibration_date is not None:
            reading.calibration_date = calibration_date
        if remarks is not None:
            reading.remarks = remarks
        if result_status is not None:
            reading.result_status = result_status

        reading.mts = self._utc_now()
        self.db.commit()
        self.db.refresh(reading)
        return reading

    def delete_reading(self, reading_id: UUID) -> bool:
        """Delete a reading."""
        reading = self.get_reading(reading_id)
        self.db.delete(reading)
        self.db.commit()
        return True

    # ═══════════════════════════════════════════════════════════
    # AUTO-GENERATE SESSIONS
    # ═══════════════════════════════════════════════════════════

    def auto_generate_sessions(
        self,
        testing_request_id: UUID,
        created_by: UUID,
    ) -> List[TestSession]:
        """
        Auto-generate sessions based on the testing request's multi-session config.
        Creates sessions at scheduled intervals.
        """
        testing_request = self.db.query(TestingRequest).filter(
            TestingRequest.id == testing_request_id
        ).first()
        if not testing_request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Testing request not found"
            )

        if not testing_request.is_multi_session:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This testing request is not configured for multi-session testing"
            )

        total_sessions = testing_request.total_sessions_planned or 1
        interval_days = testing_request.session_interval_days or 1
        start_date = testing_request.scheduled_start_date or self._utc_now()

        sessions = []
        for session_num in range(1, total_sessions + 1):
            # Calculate session date
            session_date = start_date + timedelta(days=(session_num - 1) * interval_days)

            session_name = f"Session {session_num}"
            if session_num == 1:
                session_name = "Initial Session"
            elif session_num == total_sessions:
                session_name = "Final Session"

            session = self.create_session(
                testing_request_id=testing_request_id,
                session_number=session_num,
                session_name=session_name,
                session_date=session_date,
                scheduled_date=session_date,
                template_key=None,
                notes=f"Auto-generated session {session_num} of {total_sessions}",
                weather_conditions=None,
                environmental_factors=None,
                organization_id=testing_request.organization_id,
                created_by=created_by,
            )
            sessions.append(session)

        return sessions

    # ═══════════════════════════════════════════════════════════
    # STATISTICS
    # ═══════════════════════════════════════════════════════════

    def get_session_statistics(self, session_id: UUID) -> dict:
        """Get statistics for a session."""
        from models import SessionComment

        session = self.get_session(session_id)

        reading_count = self.db.query(func.count(TestSessionReading.id)).filter(
            TestSessionReading.test_session_id == session_id
        ).scalar()

        pass_count = self.db.query(func.count(TestSessionReading.id)).filter(
            TestSessionReading.test_session_id == session_id,
            TestSessionReading.result_status == "pass"
        ).scalar()

        fail_count = self.db.query(func.count(TestSessionReading.id)).filter(
            TestSessionReading.test_session_id == session_id,
            TestSessionReading.result_status == "fail"
        ).scalar()

        comment_count = self.db.query(func.count(SessionComment.id)).filter(
            SessionComment.session_id == session_id
        ).scalar()

        return {
            "session_id": session_id,
            "session_number": session.session_number,
            "status": session.status,
            "reading_count": reading_count,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "comment_count": comment_count or 0,
            "duration_minutes": (
                int((session.completed_at - session.started_at).total_seconds() / 60)
                if session.started_at and session.completed_at else None
            ),
        }
