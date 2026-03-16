from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import Recommendation, TestingRequest, TestingRequestStatus
from utils.common_service import UTCDateTimeMixin


class ApprovalService:

    def __init__(self, db: Session):
        self.db = db

    def get_pending_approvals(self, skip: int = 0, limit: int = 100) -> List[Recommendation]:
        return (
            self.db.query(Recommendation)
            .filter(Recommendation.approval_status == "pending")
            .order_by(Recommendation.cts.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def approve_recommendation(
        self, recommendation_id: UUID, approver_id: UUID, notes: Optional[str] = None
    ) -> Recommendation:
        rec = self.db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
        if rec.approval_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending recommendations can be approved",
            )

        rec.approval_status = "approved"
        rec.approved_by = approver_id
        rec.approved_at = UTCDateTimeMixin._utc_now()
        rec.approval_notes = notes
        rec.modified_by = approver_id

        # Update testing request status
        request = self.db.query(TestingRequest).filter(TestingRequest.id == rec.testing_request_id).first()
        if request:
            request.status = TestingRequestStatus.approved
            request.modified_by = approver_id

        self.db.commit()
        self.db.refresh(rec)
        return rec

    def reject_recommendation(
        self, recommendation_id: UUID, approver_id: UUID, notes: Optional[str] = None
    ) -> Recommendation:
        rec = self.db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
        if rec.approval_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending recommendations can be rejected",
            )

        rec.approval_status = "rejected"
        rec.approved_by = approver_id
        rec.approved_at = UTCDateTimeMixin._utc_now()
        rec.approval_notes = notes
        rec.modified_by = approver_id

        # Update testing request status
        request = self.db.query(TestingRequest).filter(TestingRequest.id == rec.testing_request_id).first()
        if request:
            request.status = TestingRequestStatus.rejected
            request.rejection_reason = notes
            request.modified_by = approver_id

        self.db.commit()
        self.db.refresh(rec)
        return rec
