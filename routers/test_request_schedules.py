from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import (
    TestRequestScheduleCreate,
    TestRequestScheduleUpdate,
    TestRequestScheduleResponse,
    TestRequestScheduleLogResponse,
)
from services.test_request_schedule_service import TestRequestScheduleService

router = APIRouter(
    prefix="/testing_requests/{request_id}/schedule",
    tags=["test_request_schedules"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/", response_model=TestRequestScheduleResponse, status_code=201)
def create_schedule(
    request_id: UUID,
    data: TestRequestScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable recurring schedule for a test request."""
    svc = TestRequestScheduleService(db)
    return svc.create_schedule(
        test_request_id=request_id,
        frequency=data.frequency.value,
        end_date=data.end_date,
        advance_days=data.advance_days,
        created_by=current_user.id,
    )


@router.get("/", response_model=TestRequestScheduleResponse)
def get_schedule(
    request_id: UUID,
    db: Session = Depends(get_db),
):
    """Get the schedule for a test request."""
    svc = TestRequestScheduleService(db)
    return svc.get_schedule(test_request_id=request_id)


@router.put("/", response_model=TestRequestScheduleResponse)
def update_schedule(
    request_id: UUID,
    data: TestRequestScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update frequency, end date, advance days, or pause/resume."""
    svc = TestRequestScheduleService(db)
    return svc.update_schedule(
        test_request_id=request_id,
        frequency=data.frequency.value if data.frequency else None,
        end_date=data.end_date,
        advance_days=data.advance_days,
        is_active=data.is_active,
        modified_by=current_user.id,
    )


@router.delete("/", status_code=204)
def delete_schedule(
    request_id: UUID,
    db: Session = Depends(get_db),
):
    """Remove the schedule from a test request."""
    svc = TestRequestScheduleService(db)
    svc.delete_schedule(test_request_id=request_id)


@router.patch("/pause", response_model=TestRequestScheduleResponse)
def pause_schedule(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pause the schedule."""
    svc = TestRequestScheduleService(db)
    return svc.update_schedule(
        test_request_id=request_id,
        frequency=None, end_date=None, advance_days=None,
        is_active=False,
        modified_by=current_user.id,
    )


@router.patch("/resume", response_model=TestRequestScheduleResponse)
def resume_schedule(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resume a paused schedule."""
    svc = TestRequestScheduleService(db)
    return svc.update_schedule(
        test_request_id=request_id,
        frequency=None, end_date=None, advance_days=None,
        is_active=True,
        modified_by=current_user.id,
    )


@router.get("/logs", response_model=List[TestRequestScheduleLogResponse])
def get_schedule_logs(
    request_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get auto-generation history for a scheduled test request."""
    svc = TestRequestScheduleService(db)
    return svc.get_logs(test_request_id=request_id, skip=skip, limit=limit)
