from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
from services.test_request_schedule_service import (
    TestRequestScheduleService,
)

router = APIRouter(
    prefix="/test-register/schedules",
    tags=["test_request_schedules"],
    dependencies=[Depends(get_current_user)],
)


# ─────────────────────────────────────────────────────────────
# LIST ALL TEMPLATE SCHEDULES
# ─────────────────────────────────────────────────────────────

@router.get("")
def list_schedules(
    organization_id: Optional[UUID] = Query(None),
    equipment_type_id: Optional[int] = Query(None),
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List template schedules.
    """

    svc = TestRequestScheduleService(db)

    return svc.list_schedules(
        organization_id=organization_id or current_user.organization_id,
        equipment_type_id=equipment_type_id,
        active_only=active_only,
        skip=skip,
        limit=limit,
    )


# ─────────────────────────────────────────────────────────────
# CREATE SCHEDULE
# ─────────────────────────────────────────────────────────────

@router.post(
    "/{test_request_id}",
    response_model=TestRequestScheduleResponse,
    status_code=201,
)
def create_schedule(
    test_request_id: UUID,
    data: TestRequestScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create recurring schedule for template request.
    """

    svc = TestRequestScheduleService(db)

    return svc.create_schedule(
        test_request_id=test_request_id,
        frequency=data.frequency.value,
        end_date=data.end_date,
        advance_days=data.advance_days,
        created_by=current_user.id,
    )


# ─────────────────────────────────────────────────────────────
# GET SINGLE SCHEDULE
# ─────────────────────────────────────────────────────────────

@router.get(
    "/{test_request_id}",
    response_model=TestRequestScheduleResponse,
)
def get_schedule(
    test_request_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Get template schedule.
    """

    svc = TestRequestScheduleService(db)

    return svc.get_schedule(
        test_request_id=test_request_id
    )


# ─────────────────────────────────────────────────────────────
# UPDATE SCHEDULE
# ─────────────────────────────────────────────────────────────

@router.put(
    "/{test_request_id}",
    response_model=TestRequestScheduleResponse,
)
def update_schedule(
    test_request_id: UUID,
    data: TestRequestScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update template schedule.
    """

    svc = TestRequestScheduleService(db)

    return svc.update_schedule(
        test_request_id=test_request_id,
        frequency=data.frequency.value if data.frequency else None,
        end_date=data.end_date,
        advance_days=data.advance_days,
        is_active=data.is_active,
        modified_by=current_user.id,
    )


# ─────────────────────────────────────────────────────────────
# DELETE / DEACTIVATE SCHEDULE
# ─────────────────────────────────────────────────────────────

@router.delete("/{test_request_id}")
def delete_schedule(
    test_request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft delete schedule.
    """

    svc = TestRequestScheduleService(db)

    return svc.delete_schedule(
        test_request_id=test_request_id,
        modified_by=current_user.id,
    )


# ─────────────────────────────────────────────────────────────
# PAUSE SCHEDULE
# ─────────────────────────────────────────────────────────────

@router.patch(
    "/{test_request_id}/pause",
    response_model=TestRequestScheduleResponse,
)
def pause_schedule(
    test_request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Pause schedule.
    """

    svc = TestRequestScheduleService(db)

    return svc.update_schedule(
        test_request_id=test_request_id,
        frequency=None,
        end_date=None,
        advance_days=None,
        is_active=False,
        modified_by=current_user.id,
    )


# ─────────────────────────────────────────────────────────────
# RESUME SCHEDULE
# ─────────────────────────────────────────────────────────────

@router.patch(
    "/{test_request_id}/resume",
    response_model=TestRequestScheduleResponse,
)
def resume_schedule(
    test_request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resume schedule.
    """

    svc = TestRequestScheduleService(db)

    return svc.update_schedule(
        test_request_id=test_request_id,
        frequency=None,
        end_date=None,
        advance_days=None,
        is_active=True,
        modified_by=current_user.id,
    )


# ─────────────────────────────────────────────────────────────
# GET SCHEDULE LOGS
# ─────────────────────────────────────────────────────────────

@router.get(
    "/{test_request_id}/logs",
    response_model=List[TestRequestScheduleLogResponse],
)
def get_schedule_logs(
    test_request_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Get schedule execution logs.
    """

    svc = TestRequestScheduleService(db)

    return svc.get_logs(
        test_request_id=test_request_id,
        skip=skip,
        limit=limit,
    )