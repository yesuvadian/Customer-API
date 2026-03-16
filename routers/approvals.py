from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import ApprovalAction, RecommendationResponse
from services.approval_service import ApprovalService

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/pending", response_model=List[RecommendationResponse])
def get_pending_approvals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApprovalService(db)
    return service.get_pending_approvals(skip=skip, limit=limit)


@router.put("/{recommendation_id}/approve", response_model=RecommendationResponse)
def approve_recommendation(
    recommendation_id: UUID,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApprovalService(db)
    return service.approve_recommendation(
        recommendation_id=recommendation_id,
        approver_id=current_user.id,
        notes=data.notes,
    )


@router.put("/{recommendation_id}/reject", response_model=RecommendationResponse)
def reject_recommendation(
    recommendation_id: UUID,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApprovalService(db)
    return service.reject_recommendation(
        recommendation_id=recommendation_id,
        approver_id=current_user.id,
        notes=data.notes,
    )
