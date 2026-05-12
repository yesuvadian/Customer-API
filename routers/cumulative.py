from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.cumulative_service import CumulativeService

router = APIRouter(
    prefix="/cumulative",
    tags=["cumulative"],
    dependencies=[Depends(get_current_user)],
)


class ThresholdBody(BaseModel):
    threshold_value: float


# ── Threshold ─────────────────────────────────────────────────────────────────

@router.post("/equipment/{equipment_id}/threshold")
def set_threshold(
    equipment_id: UUID,
    body: ThresholdBody,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return CumulativeService(db).set_threshold(equipment_id, body.threshold_value, user.id)


@router.get("/equipment/{equipment_id}/threshold")
def get_threshold(equipment_id: UUID, db: Session = Depends(get_db)):
    result = CumulativeService(db).get_threshold(equipment_id)
    if not result:
        raise HTTPException(status_code=404, detail="No threshold configured for this equipment")
    return result


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@router.get("/equipment/{equipment_id}/lifecycle")
def get_lifecycle(equipment_id: UUID, db: Session = Depends(get_db)):
    return CumulativeService(db).get_lifecycle_status(equipment_id)


@router.post("/equipment/{equipment_id}/evaluate")
def evaluate(
    equipment_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calculate cumulative and trigger overhaul workflow if threshold crossed."""
    return CumulativeService(db).evaluate_overhaul_trigger(equipment_id, user.id)


@router.post("/recommendations/{recommendation_id}/close")
def close_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
):
    try:
        return CumulativeService(db).close_recommendation(recommendation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

