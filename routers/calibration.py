from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import Equipment
from services.calibration_service import CalibrationService

router = APIRouter(
    prefix="/calibration",
    tags=["calibration"],
    dependencies=[Depends(get_current_user)],
)


def _assert_equipment_exists(equipment_id: UUID, db: Session) -> None:
    """Raise 404 if equipment_id does not exist in the equipment table."""
    exists = db.query(Equipment.id).filter(Equipment.id == equipment_id).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="Equipment not found")


class CalibrationConfigBody(BaseModel):
    lead_days: int = 30
    is_scheduled: Optional[bool] = None


# ── Equipment schedule config ─────────────────────────────────────────────────

@router.get("/equipment/{equipment_id}/config")
def get_config(equipment_id: UUID, db: Session = Depends(get_db)):
    """Get calibration schedule config (lead_days, is_scheduled) for an equipment."""
    _assert_equipment_exists(equipment_id, db)
    return CalibrationService(db).get_config(equipment_id)


@router.post("/equipment/{equipment_id}/config")
def set_config(
    equipment_id: UUID,
    body: CalibrationConfigBody,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set calibration schedule config for an equipment."""
    _assert_equipment_exists(equipment_id, db)
    return CalibrationService(db).set_config(
        equipment_id, body.lead_days, body.is_scheduled, user.id
    )


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@router.get("/equipment/{equipment_id}/status")
def get_status(equipment_id: UUID, db: Session = Depends(get_db)):
    """
    Compute and return current calibration state:
    NOT_CALIBRATED | NORMAL | DUE_SOON | OVERDUE | CRITICAL
    Also returns last_calibration_date, next_due_date, days_until_due.
    """
    _assert_equipment_exists(equipment_id, db)
    return CalibrationService(db).get_calibration_status(equipment_id)


@router.post("/equipment/{equipment_id}/evaluate")
def evaluate(
    equipment_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Run the DATE_ADD rule engine on the latest calibration reading.
    If result == Fail: stops scheduling and creates a REPAIR_OR_REPLACE recommendation.
    """
    _assert_equipment_exists(equipment_id, db)
    return CalibrationService(db).evaluate_calibration(equipment_id, user.id)


@router.post("/equipment/{equipment_id}/resume")
def resume_schedule(
    equipment_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resume calibration scheduling after a repair is completed.
    Sets is_scheduled = True for the equipment.
    """
    _assert_equipment_exists(equipment_id, db)
    return CalibrationService(db).resume_schedule(equipment_id, user.id)


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/equipment/{equipment_id}/history")
def get_history(equipment_id: UUID, db: Session = Depends(get_db)):
    """Return all calibration records for the equipment, newest first."""
    _assert_equipment_exists(equipment_id, db)
    return CalibrationService(db).get_history(equipment_id)
