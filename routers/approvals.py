from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import Recommendation, User
from schemas import ApprovalAction, RecommendationResponse
from services.approval_service import ApprovalService
from services.report_service import ReportService

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/stats")
def get_approval_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return approval counts: pending, approved, rejected, total_reviewed."""
    service = ApprovalService(db)
    return service.get_approval_stats(approver_id=current_user.id)


@router.get("/pending", response_model=List[RecommendationResponse])
def get_pending_approvals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApprovalService(db)
    return service.get_pending_approvals(skip=skip, limit=limit)


@router.get("/{recommendation_id}/detail")
def get_approval_detail(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns recommendation + testing request info + test results for approver review."""
    service = ApprovalService(db)
    return service.get_approval_detail(recommendation_id)


@router.get("/{recommendation_id}/report")
def get_approval_report(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and return a PDF test report for approval review."""
    service = ReportService(db)
    pdf_bytes = service.generate_approval_report(recommendation_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="test_report_{recommendation_id}.pdf"',
        },
    )


@router.get("/by-request/{testing_request_id}")
def get_recommendation_by_request(
    testing_request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the recommendation (with replacement_products) for a given testing request."""
    rec = (
        db.query(Recommendation)
        .filter(Recommendation.testing_request_id == testing_request_id)
        .order_by(Recommendation.cts.desc())
        .first()
    )
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recommendation found for this testing request",
        )
    service = ApprovalService(db)
    return service.get_approval_detail(rec.id)


@router.put("/{recommendation_id}/approve")
def approve_recommendation(
    recommendation_id: UUID,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Approve a recommendation.

    For Failure Registry (FR-) records the response includes extra fields:
      fr_outcome            — "repair" | "replacement" | "under_investigation" | …
      fr_number             — the FR- request number
      fr_equipment_ueic     — UEIC of the failed equipment
      fr_failure_category   — e.g. "Electrical"
      fr_failure_date       — ISO date string from test_data
      auto_created_repair_tr — RL- request number if a repair TR was auto-created
    """
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
