from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import Recommendation, RecommendationType, TestingRequest, TestingRequestStatus
from utils.common_service import UTCDateTimeMixin


class RecommendationService:

    def __init__(self, db: Session):
        self.db = db

    def create_recommendation(
        self,
        testing_request_id: UUID,
        recommendation_type: str,
        summary: str,
        submitted_by: UUID,
        detailed_notes: Optional[str] = None,
    ) -> Recommendation:
        request = self.db.query(TestingRequest).filter(TestingRequest.id == testing_request_id).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")
        if request.status != TestingRequestStatus.test_submitted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recommendations can only be created for test-submitted requests",
            )

        try:
            rec_type = RecommendationType(recommendation_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid recommendation type: {recommendation_type}. Must be one of: pass, fail, conditional, retest",
            )

        recommendation = Recommendation(
            testing_request_id=testing_request_id,
            organization_id=request.organization_id,  # Set from testing request
            recommendation_type=rec_type,
            summary=summary,
            detailed_notes=detailed_notes,
            submitted_by=submitted_by,
            submitted_at=UTCDateTimeMixin._utc_now(),
            approval_status="pending",
            created_by=submitted_by,
        )
        self.db.add(recommendation)

        # Transition testing request to under_approval
        request.status = TestingRequestStatus.under_approval
        request.modified_by = submitted_by

        self.db.commit()
        self.db.refresh(recommendation)
        return recommendation

    @staticmethod
    def _enrich(rec: Recommendation) -> Recommendation:
        """Attach resolved user display names to the ORM object."""
        def _name(user):
            if not user:
                return None
            full = f"{user.firstname or ''} {user.lastname or ''}".strip()
            return full or user.email or None

        rec.submitted_by_name = _name(rec.submitter)
        rec.approved_by_name = _name(rec.approver)
        return rec

    def get_recommendation(self, recommendation_id: UUID) -> Recommendation:
        rec = self.db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
        return self._enrich(rec)

    def get_recommendations(
        self,
        testing_request_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Recommendation]:
        query = self.db.query(Recommendation)
        if testing_request_id:
            query = query.filter(Recommendation.testing_request_id == testing_request_id)
        if organization_id:
            query = query.filter(Recommendation.organization_id == organization_id)
        return [self._enrich(r) for r in query.order_by(Recommendation.cts.desc()).offset(skip).limit(limit).all()]

    def update_recommendation(self, recommendation_id: UUID, data: dict, modified_by: UUID) -> Recommendation:
        rec = self.get_recommendation(recommendation_id)
        if rec.approval_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending recommendations can be updated",
            )
        for key, value in data.items():
            if key == "recommendation_type" and value is not None:
                try:
                    value = RecommendationType(value)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid recommendation type: {value}",
                    )
            if hasattr(rec, key) and value is not None:
                setattr(rec, key, value)
        rec.modified_by = modified_by
        self.db.commit()
        self.db.refresh(rec)
        return rec
