from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models import (
    Equipment,
    NextActionType,
    Recommendation,
    RecommendationType,
    ScheduleFrequency,
    TestingRequest,
    TestingRequestStatus,
)
from utils.common_service import UTCDateTimeMixin


class RecommendationService:

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Base query — always eager-load the full join chain so _enrich() never
    # triggers a lazy load (which would fail after the session is closed by
    # the time Pydantic serialises the response).
    #
    # Chain:
    #   Recommendation
    #     → testing_request  (TestingRequest)
    #         → equipment    (Equipment)
    #             → equipment_type  (CategoryMaster)  ← this is the name we group by
    #     → submitter        (User)
    #     → approver         (User)
    # ─────────────────────────────────────────────────────────────────────────
    def _base_query(self):
        return (
            self.db.query(Recommendation)
            .options(
                joinedload(Recommendation.testing_request)
                .joinedload(TestingRequest.equipment)
                .joinedload(Equipment.equipment_type),
                joinedload(Recommendation.submitter),
                joinedload(Recommendation.approver),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # CREATE
    # ─────────────────────────────────────────────────────────────────────────
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
        test_types: Optional[list] = None,
    ) -> Recommendation:

        # Fetch the parent testing request with its equipment chain pre-loaded
        request = (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.equipment)
                .joinedload(Equipment.equipment_type)
            )
            .filter(TestingRequest.id == testing_request_id)
            .first()
        )
        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Testing request not found",
            )

        from models import RequestCategory as _RC
        _is_fr = request.request_category == _RC.failure_registry
        if not _is_fr:
            allowed = [
                TestingRequestStatus.test_submitted,
                TestingRequestStatus.accepted,
                TestingRequestStatus.in_progress,
                TestingRequestStatus.under_review,
            ]
            if request.status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot create recommendation for request in "
                        f"'{request.status.value}' status"
                    ),
                )

        # Validate recommendation_type enum
        try:
            rec_type = RecommendationType(recommendation_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid recommendation type: {recommendation_type}. "
                    "Must be one of: pass, fail, conditional, retest"
                ),
            )

        # Validate next_action enum
        parsed_next_action = None
        if next_action:
            try:
                parsed_next_action = NextActionType(next_action)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid next_action: {next_action}. "
                        f"Must be one of: {[e.value for e in NextActionType]}"
                    ),
                )

        # Validate schedule_frequency enum
        parsed_frequency = None
        if schedule_frequency:
            try:
                parsed_frequency = ScheduleFrequency(schedule_frequency)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid schedule_frequency: {schedule_frequency}",
                )

        # If a pending recommendation already exists for this TR, update it
        # in-place rather than creating a duplicate.
        existing_rec = (
            self._base_query()
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
            existing_rec.test_types = (
                test_types if test_types is not None else existing_rec.test_types
            )
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
                test_types=test_types or [],
                submitted_by=submitted_by,
                submitted_at=UTCDateTimeMixin._utc_now(),
                approval_status="pending",
                created_by=submitted_by,
            )
            self.db.add(recommendation)

        # Advance the testing-request status
        if request.is_multi_session and request.total_sessions_planned:
            from models import TestSession

            completed_sessions = (
                self.db.query(TestSession)
                .filter(
                    TestSession.testing_request_id == testing_request_id,
                    TestSession.status == "completed",
                )
                .count()
            )
            if completed_sessions >= request.total_sessions_planned:
                request.status = TestingRequestStatus.under_approval
            else:
                request.status = TestingRequestStatus.in_progress
        else:
            request.status = TestingRequestStatus.under_approval

        request.modified_by = submitted_by
        self.db.commit()

        # Re-fetch with eager loads so _enrich() has everything in-session
        refreshed = (
            self._base_query()
            .filter(Recommendation.id == recommendation.id)
            .first()
        )
        return self._enrich(refreshed)

    # ─────────────────────────────────────────────────────────────────────────
    # ENRICH
    # Attaches computed display fields onto the ORM object.
    # IMPORTANT: all relationships must already be loaded (via _base_query)
    # before calling this method — never call it with a lazily-loaded object
    # because the session may already be closed at serialisation time.
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _enrich(rec: Recommendation) -> Recommendation:
        def _name(user):
            if not user:
                return None
            full = f"{user.firstname or ''} {user.lastname or ''}".strip()
            return full or user.email or None

        # Resolved user display names
        rec.submitted_by_name = _name(rec.submitter)
        rec.approved_by_name = _name(rec.approver)

        # Testing-request context
        tr = rec.testing_request
        if tr:
            rec.request_number = tr.request_number
            rec.request_title = tr.title

            # Equipment context — both already eager-loaded, zero lazy hits
            eq = tr.equipment
            if eq:
                rec.equipment_ueic = eq.ueic
                cat = eq.equipment_type          # CategoryMaster row
                rec.equipment_type_name = cat.name if cat else None
            else:
                rec.equipment_ueic = None
                rec.equipment_type_name = None
        else:
            rec.request_number = None
            rec.request_title = None
            rec.equipment_ueic = None
            rec.equipment_type_name = None

        return rec

    # ─────────────────────────────────────────────────────────────────────────
    # READ — single
    # ─────────────────────────────────────────────────────────────────────────
    def get_recommendation(self, recommendation_id: UUID) -> Recommendation:
        rec = (
            self._base_query()
            .filter(Recommendation.id == recommendation_id)
            .first()
        )
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recommendation not found",
            )
        return self._enrich(rec)

    # ─────────────────────────────────────────────────────────────────────────
    # READ — list with optional filters
    # ─────────────────────────────────────────────────────────────────────────
    def get_recommendations(
        self,
        testing_request_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        approval_status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Recommendation]:
        query = self._base_query()

        if testing_request_id:
            query = query.filter(
                Recommendation.testing_request_id == testing_request_id
            )
        if organization_id:
            query = query.filter(
                Recommendation.organization_id == organization_id
            )
        if approval_status:
            query = query.filter(
                Recommendation.approval_status == approval_status
            )

        recs = (
            query
            .order_by(Recommendation.cts.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [self._enrich(r) for r in recs]

    # ─────────────────────────────────────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────────────────────────────────────
    def update_recommendation(
        self,
        recommendation_id: UUID,
        data: dict,
        modified_by: UUID,
    ) -> Recommendation:
        # get_recommendation already uses _base_query + _enrich
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

        # Re-fetch so the returned object has fresh eager-loaded state
        return self.get_recommendation(recommendation_id)