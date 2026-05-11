from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import (
    NextActionType, Recommendation, RecommendationType,
    ScheduleFrequency, TestingRequest, TestingRequestStatus,
)
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
        next_action: Optional[str] = None,
        schedule_frequency: Optional[str] = None,
        replacement_products: Optional[list] = None,
    ) -> Recommendation:
        request = self.db.query(TestingRequest).filter(TestingRequest.id == testing_request_id).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")

        # Allow creation from accepted, in_progress, or test_submitted states
        allowed = [
            TestingRequestStatus.test_submitted,
            TestingRequestStatus.accepted,
            TestingRequestStatus.in_progress,
            TestingRequestStatus.under_review,  # tester resubmitting
        ]
        if request.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot create recommendation for request in '{request.status.value}' status",
            )

        try:
            rec_type = RecommendationType(recommendation_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid recommendation type: {recommendation_type}. Must be one of: pass, fail, conditional, retest",
            )

        # Resolve next_action enum
        parsed_next_action = None
        if next_action:
            try:
                parsed_next_action = NextActionType(next_action)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid next_action: {next_action}. Must be one of: {[e.value for e in NextActionType]}",
                )

        # Resolve schedule_frequency enum
        parsed_frequency = None
        if schedule_frequency:
            try:
                parsed_frequency = ScheduleFrequency(schedule_frequency)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid schedule_frequency: {schedule_frequency}",
                )

        # If a previous pending recommendation exists for this TR, replace it
        existing_rec = (
            self.db.query(Recommendation)
            .filter(
                Recommendation.testing_request_id == testing_request_id,
                Recommendation.approval_status == "pending",
            )
            .first()
        )
        if existing_rec:
            existing_rec.recommendation_type = rec_type
            existing_rec.summary = summary
            existing_rec.detailed_notes = detailed_notes
            existing_rec.next_action = parsed_next_action
            existing_rec.schedule_frequency = parsed_frequency
            existing_rec.replacement_products = replacement_products or []
            existing_rec.submitted_by = submitted_by
            existing_rec.submitted_at = UTCDateTimeMixin._utc_now()
            existing_rec.modified_by = submitted_by
            recommendation = existing_rec
        else:
            recommendation = Recommendation(
                testing_request_id=testing_request_id,
                organization_id=request.organization_id,
                recommendation_type=rec_type,
                summary=summary,
                detailed_notes=detailed_notes,
                next_action=parsed_next_action,
                schedule_frequency=parsed_frequency,
                replacement_products=replacement_products or [],
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
        approval_status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Recommendation]:
        query = self.db.query(Recommendation)
        if testing_request_id:
            query = query.filter(Recommendation.testing_request_id == testing_request_id)
        if organization_id:
            query = query.filter(Recommendation.organization_id == organization_id)
        if approval_status:
            query = query.filter(Recommendation.approval_status == approval_status)
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
