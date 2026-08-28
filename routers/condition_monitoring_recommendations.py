"""
Router: /condition-recommendations

Config CRUD and activation endpoint for the condition monitoring recommendation module.
Access gate: any authenticated user with access to the AI module (get_current_user).
Module-level visibility is enforced by the frontend permission system.
All DB logic lives in services/condition_recommendation_service.py.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_vendor_db
from models import User
from services.condition_recommendation_service import (
    activate,
    create_config,
    deactivate_config,
    delete_config_permanently,
    list_configs,
    update_config,
)

router = APIRouter(
    prefix="/condition-recommendations",
    tags=["condition-recommendations"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecommendationConfigCreate(BaseModel):
    equipment_type_id: int
    score_from: float
    score_to: float
    test_type_id: int
    frequency: str
    display_order: int = 0
    is_active: bool = True
    organization_id: Optional[UUID] = None


class RecommendationConfigUpdate(BaseModel):
    score_from: Optional[float] = None
    score_to: Optional[float] = None
    frequency: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class RecommendationConfigResponse(BaseModel):
    id: UUID
    equipment_type_id: int
    equipment_type_name: str
    score_from: float
    score_to: float
    test_type_id: int
    test_type_name: str
    frequency: str
    is_active: bool
    display_order: int

    class Config:
        from_attributes = True


class ActivateRequest(BaseModel):
    equipment_id: UUID
    start_date: str  # YYYY-MM-DD


# ── Route handlers ────────────────────────────────────────────────────────────

@router.get("/", response_model=List[RecommendationConfigResponse])
def get_configs(
    equipment_type_id: Optional[int]  = Query(None),
    is_active:         Optional[bool] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: User    = Depends(get_current_user),
):
    rows = list_configs(db, equipment_type_id=equipment_type_id, is_active=is_active)
    return [
        RecommendationConfigResponse(
            id=r.id,
            equipment_type_id=r.equipment_type_id,
            equipment_type_name=r.equipment_type.name if r.equipment_type else "",
            score_from=float(r.score_from),
            score_to=float(r.score_to),
            test_type_id=r.test_type_id,
            test_type_name=r.test_type.name if r.test_type else "",
            frequency=r.frequency.value,
            is_active=r.is_active,
            display_order=r.display_order,
        )
        for r in rows
    ]


@router.post("/", response_model=RecommendationConfigResponse, status_code=status.HTTP_201_CREATED)
def post_config(
    body: RecommendationConfigCreate,
    db:   Session = Depends(get_vendor_db),
    user: User    = Depends(get_current_user),
):
    rec = create_config(
        db,
        organization_id   = body.organization_id,
        equipment_type_id = body.equipment_type_id,
        score_from        = body.score_from,
        score_to          = body.score_to,
        test_type_id      = body.test_type_id,
        frequency         = body.frequency,
        display_order     = body.display_order,
        is_active         = body.is_active,
        created_by        = user.id if user else None,
    )
    return RecommendationConfigResponse(
        id=rec.id,
        equipment_type_id=rec.equipment_type_id,
        equipment_type_name=rec.equipment_type.name if rec.equipment_type else "",
        score_from=float(rec.score_from),
        score_to=float(rec.score_to),
        test_type_id=rec.test_type_id,
        test_type_name=rec.test_type.name if rec.test_type else "",
        frequency=rec.frequency.value,
        is_active=rec.is_active,
        display_order=rec.display_order,
    )


@router.put("/{rec_id}", response_model=RecommendationConfigResponse)
def put_config(
    rec_id: UUID,
    body:   RecommendationConfigUpdate,
    db:     Session = Depends(get_vendor_db),
    user:   User    = Depends(get_current_user),
):
    rec = update_config(
        db, rec_id,
        score_from=body.score_from, score_to=body.score_to,
        frequency=body.frequency, display_order=body.display_order,
        is_active=body.is_active,
    )
    return RecommendationConfigResponse(
        id=rec.id,
        equipment_type_id=rec.equipment_type_id,
        equipment_type_name=rec.equipment_type.name if rec.equipment_type else "",
        score_from=float(rec.score_from),
        score_to=float(rec.score_to),
        test_type_id=rec.test_type_id,
        test_type_name=rec.test_type.name if rec.test_type else "",
        frequency=rec.frequency.value,
        is_active=rec.is_active,
        display_order=rec.display_order,
    )


@router.delete("/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(
    rec_id: UUID,
    db:     Session = Depends(get_vendor_db),
    user:   User    = Depends(get_current_user),
):
    deactivate_config(db, rec_id)


@router.delete("/{rec_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def delete_config_permanently_route(
    rec_id: UUID,
    db:     Session = Depends(get_vendor_db),
    user:   User    = Depends(get_current_user),
):
    delete_config_permanently(db, rec_id)


@router.post("/{rec_id}/activate")
def activate_recommendation(
    rec_id: UUID,
    body:   ActivateRequest,
    db:     Session = Depends(get_vendor_db),
    user:   User    = Depends(get_current_user),
):
    return activate(db, rec_id, body.equipment_id, body.start_date, user.id if user else None)
