from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import RecommendationCreate, RecommendationUpdate, RecommendationResponse
from services.recommendation_service import RecommendationService

router = APIRouter(
    prefix="/recommendations",
    tags=["recommendations"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/", response_model=RecommendationResponse)
def create_recommendation(
    data: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.create_recommendation(
        testing_request_id=data.testing_request_id,
        recommendation_type=data.recommendation_type,
        summary=data.summary,
        submitted_by=current_user.id,
        detailed_notes=data.detailed_notes,
    )


@router.get("/", response_model=List[RecommendationResponse])
def list_recommendations(
    testing_request_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.get_recommendations(
        testing_request_id=testing_request_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
def get_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.get_recommendation(recommendation_id)


@router.put("/{recommendation_id}", response_model=RecommendationResponse)
def update_recommendation(
    recommendation_id: UUID,
    data: RecommendationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.update_recommendation(
        recommendation_id, data.dict(exclude_unset=True), modified_by=current_user.id
    )
