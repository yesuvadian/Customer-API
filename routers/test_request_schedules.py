# ============================================================
# routes/test_request_schedule_routes.py
# ============================================================

from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db

from models import User

from schemas import (
    TestRequestScheduleCreate,
    TestRequestScheduleUpdate,
)

from services.test_request_schedule_service import (
    TestRequestScheduleService,
)

router = APIRouter(
    prefix="/test-register/schedules",
    tags=["test_request_schedules"],
    dependencies=[Depends(get_current_user)],
)

# ============================================================
# MASTER SCHEDULES
# equipment_id = NULL
# ============================================================


# ============================================================
# CREATE MASTER SCHEDULE
# ============================================================

@router.post(
    "/master",
    status_code=201,
)
def create_master_schedule(
    data: TestRequestScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    payload = data.dict(exclude_unset=True)

    payload["organization_id"] = (
        current_user.organization_id
    )

    return svc.create_master_schedule(
        data=payload,
        user_id=current_user.id,
    )


# ============================================================
# LIST MASTER SCHEDULES
# ============================================================

@router.get("/master")
def list_master_schedules(
    equipment_type_id: Optional[int] = Query(None),
    request_category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.list_master_schedules(
        organization_id=current_user.organization_id,
        equipment_type_id=equipment_type_id,
        request_category=request_category,
    )


# ============================================================
# GET MASTER SCHEDULE
# ============================================================

@router.get("/master/{schedule_id}")
def get_master_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db),
):

    svc = TestRequestScheduleService(db)

    return svc.get_master_schedule(
        schedule_id=schedule_id,
    )


# ============================================================
# UPDATE MASTER SCHEDULE
# ============================================================

@router.put("/master/{schedule_id}")
def update_master_schedule(
    schedule_id: UUID,
    data: TestRequestScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.update_master_schedule(
        schedule_id=schedule_id,
        data=data.dict(exclude_unset=True),
        user_id=current_user.id,
    )


# ============================================================
# DELETE MASTER SCHEDULE
# ============================================================

@router.delete("/master/{schedule_id}")
def delete_master_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.delete_master_schedule(
        schedule_id=schedule_id,
        user_id=current_user.id,
    )


# ============================================================
# OPERATIONAL SCHEDULES
# equipment_id != NULL
# ============================================================


# ============================================================
# LIST OPERATIONAL SCHEDULES
# ============================================================

@router.get("/operational/{equipment_id}")
def list_operational_schedules(
    equipment_id: UUID,
    request_category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):

    svc = TestRequestScheduleService(db)

    return svc.list_operational_schedules(
        equipment_id=equipment_id,
        request_category=request_category,
    )


# ============================================================
# GET OPERATIONAL SCHEDULE
# ============================================================

@router.get(
    "/operational/{equipment_id}/{schedule_id}"
)
def get_operational_schedule(
    equipment_id: UUID,
    schedule_id: UUID,
    db: Session = Depends(get_db),
):

    svc = TestRequestScheduleService(db)

    return svc.get_operational_schedule(
        schedule_id=schedule_id,
        equipment_id=equipment_id,
    )


# ============================================================
# UPDATE OPERATIONAL SCHEDULE
# ============================================================

@router.put(
    "/operational/{equipment_id}/{schedule_id}"
)
def update_operational_schedule(
    equipment_id: UUID,
    schedule_id: UUID,
    data: TestRequestScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.update_operational_schedule(
        schedule_id=schedule_id,
        equipment_id=equipment_id,
        data=data.dict(exclude_unset=True),
        user_id=current_user.id,
    )


# ============================================================
# PAUSE OPERATIONAL SCHEDULE
# ============================================================

@router.patch(
    "/operational/{equipment_id}/{schedule_id}/pause"
)
def pause_operational_schedule(
    equipment_id: UUID,
    schedule_id: UUID,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.pause_operational_schedule(
        schedule_id=schedule_id,
        equipment_id=equipment_id,
        user_id=current_user.id,
        reason=reason,
    )


# ============================================================
# RESUME OPERATIONAL SCHEDULE
# ============================================================

@router.patch(
    "/operational/{equipment_id}/{schedule_id}/resume"
)
def resume_operational_schedule(
    equipment_id: UUID,
    schedule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.resume_operational_schedule(
        schedule_id=schedule_id,
        equipment_id=equipment_id,
        user_id=current_user.id,
    )


# ============================================================
# DELETE OPERATIONAL SCHEDULE
# ============================================================

@router.delete(
    "/operational/{equipment_id}/{schedule_id}"
)
def delete_operational_schedule(
    equipment_id: UUID,
    schedule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    svc = TestRequestScheduleService(db)

    return svc.delete_operational_schedule(
        schedule_id=schedule_id,
        equipment_id=equipment_id,
        user_id=current_user.id,
    )


# ============================================================
# RUN NOW
# ============================================================

@router.post(
    "/operational/{equipment_id}/{schedule_id}/run"
)
def run_now(
    equipment_id: UUID,
    schedule_id: UUID,
    db: Session = Depends(get_db),
):

    svc = TestRequestScheduleService(db)

    schedule = (
        svc.get_operational_schedule(
            schedule_id=schedule_id,
            equipment_id=equipment_id,
        )
    )

    return svc.create_one_ticket(
        db=db,
        schedule=schedule,
        now=svc._utc_now(),
        force_run=True,
    )


# ============================================================
# LOGS
# ============================================================

@router.get(
    "/operational/{equipment_id}/{schedule_id}/logs"
)
def get_schedule_logs(
    equipment_id: UUID,
    schedule_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):

    svc = TestRequestScheduleService(db)

    schedule = (
        svc.get_operational_schedule(
            schedule_id=schedule_id,
            equipment_id=equipment_id,
        )
    )

    return (
        db.query(schedule.logs.__class__)
        .filter(
            schedule.logs.__class__.schedule_id
                == schedule.id
        )
        .offset(skip)
        .limit(limit)
        .all()
    )