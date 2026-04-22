"""
Test Session Router - API endpoints for multi-day, multi-session testing.

Endpoints:
- Create/update/delete test sessions
- Record multiple readings per session
- Start/complete sessions
- Auto-generate sessions based on schedule
- Get session statistics
"""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import (
    TestSessionCreate,
    TestSessionUpdate,
    TestSessionResponse,
    TestSessionReadingCreate,
    TestSessionReadingUpdate,
    TestSessionReadingResponse,
)
from services.test_session_service import TestSessionService

router = APIRouter(
    prefix="/testing_requests/{request_id}/sessions",
    tags=["test_sessions"],
    dependencies=[Depends(get_current_user)],
)


# ═══════════════════════════════════════════════════════════
# TEST SESSION ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.post("/", response_model=TestSessionResponse, status_code=201)
def create_session(
    request_id: UUID,
    data: TestSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new test session for a testing request."""
    svc = TestSessionService(db)
    return svc.create_session(
        testing_request_id=request_id,
        session_number=data.session_number,
        session_name=data.session_name,
        session_date=data.session_date,
        scheduled_date=data.scheduled_date,
        template_key=data.template_key,
        notes=data.notes,
        weather_conditions=data.weather_conditions,
        environmental_factors=data.environmental_factors,
        organization_id=data.organization_id,
        created_by=current_user.id,
    )


@router.post("/auto-generate", response_model=List[TestSessionResponse], status_code=201)
def auto_generate_sessions(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Auto-generate all sessions for a multi-session testing request.
    Creates sessions based on total_sessions_planned and session_interval_days.
    """
    svc = TestSessionService(db)
    return svc.auto_generate_sessions(
        testing_request_id=request_id,
        created_by=current_user.id,
    )


@router.get("/", response_model=List[TestSessionResponse])
def list_sessions(
    request_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all sessions for a testing request."""
    svc = TestSessionService(db)
    return svc.list_sessions(
        testing_request_id=request_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{session_id}", response_model=TestSessionResponse)
def get_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Get a specific test session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return session


@router.put("/{session_id}", response_model=TestSessionResponse)
def update_session(
    request_id: UUID,
    session_id: UUID,
    data: TestSessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a test session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")

    return svc.update_session(
        session_id=session_id,
        session_name=data.session_name,
        session_date=data.session_date,
        status=data.status,
        notes=data.notes,
        weather_conditions=data.weather_conditions,
        environmental_factors=data.environmental_factors,
        conducted_by=data.conducted_by,
        witnessed_by=data.witnessed_by,
        started_at=data.started_at,
        completed_at=data.completed_at,
        modified_by=current_user.id,
    )


@router.delete("/{session_id}", status_code=204)
def delete_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a test session and all its readings."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    svc.delete_session(session_id)


@router.post("/{session_id}/start", response_model=TestSessionResponse)
def start_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a session as in progress and set start time."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return svc.start_session(session_id, conducted_by=current_user.id)


@router.post("/{session_id}/complete", response_model=TestSessionResponse)
def complete_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Mark a session as completed and set completion time."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return svc.complete_session(session_id)


@router.get("/{session_id}/statistics")
def get_session_statistics(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Get statistics for a session (reading count, pass/fail, duration)."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return svc.get_session_statistics(session_id)


# ═══════════════════════════════════════════════════════════
# TEST SESSION READING ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.post("/{session_id}/readings", response_model=TestSessionReadingResponse, status_code=201)
def create_reading(
    request_id: UUID,
    session_id: UUID,
    data: TestSessionReadingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new reading for a test session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")

    return svc.create_reading(
        session_id=session_id,
        reading_number=data.reading_number,
        reading_time=data.reading_time,
        reading_data=data.reading_data,
        equipment_serial=data.equipment_serial,
        calibration_date=data.calibration_date,
        remarks=data.remarks,
        result_status=data.result_status,
        recorded_by=current_user.id,
    )


@router.get("/{session_id}/readings", response_model=List[TestSessionReadingResponse])
def list_readings(
    request_id: UUID,
    session_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all readings for a session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")

    return svc.list_readings(
        session_id=session_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{session_id}/readings/{reading_id}", response_model=TestSessionReadingResponse)
def get_reading(
    request_id: UUID,
    session_id: UUID,
    reading_id: UUID,
    db: Session = Depends(get_db),
):
    """Get a specific reading."""
    svc = TestSessionService(db)
    reading = svc.get_reading(reading_id)
    if reading.test_session_id != session_id:
        raise HTTPException(status_code=404, detail="Reading not found for this session")
    return reading


@router.put("/{session_id}/readings/{reading_id}", response_model=TestSessionReadingResponse)
def update_reading(
    request_id: UUID,
    session_id: UUID,
    reading_id: UUID,
    data: TestSessionReadingUpdate,
    db: Session = Depends(get_db),
):
    """Update a reading."""
    svc = TestSessionService(db)
    reading = svc.get_reading(reading_id)
    if reading.test_session_id != session_id:
        raise HTTPException(status_code=404, detail="Reading not found for this session")

    return svc.update_reading(
        reading_id=reading_id,
        reading_time=data.reading_time,
        reading_data=data.reading_data,
        equipment_serial=data.equipment_serial,
        calibration_date=data.calibration_date,
        remarks=data.remarks,
        result_status=data.result_status,
    )


@router.delete("/{session_id}/readings/{reading_id}", status_code=204)
def delete_reading(
    request_id: UUID,
    session_id: UUID,
    reading_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a reading."""
    svc = TestSessionService(db)
    reading = svc.get_reading(reading_id)
    if reading.test_session_id != session_id:
        raise HTTPException(status_code=404, detail="Reading not found for this session")
    svc.delete_reading(reading_id)
