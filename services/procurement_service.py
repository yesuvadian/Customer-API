from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import ProcurementRequest, TestingRequest, TestingRequestStatus, Recommendation
from utils.common_service import UTCDateTimeMixin


class ProcurementService:

    def __init__(self, db: Session):
        self.db = db

    def _generate_procurement_number(self) -> str:
        today = UTCDateTimeMixin._utc_now().strftime("%Y%m%d")
        count = (
            self.db.query(func.count(ProcurementRequest.id))
            .filter(ProcurementRequest.procurement_number.like(f"PR-{today}-%"))
            .scalar()
        )
        return f"PR-{today}-{(count + 1):04d}"

    def create_procurement(self, data: dict, raised_by: UUID) -> ProcurementRequest:
        testing_request_id = data["testing_request_id"]
        request = self.db.query(TestingRequest).filter(TestingRequest.id == testing_request_id).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")
        if request.status != TestingRequestStatus.approved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procurement can only be initiated for approved testing requests",
            )

        # Validate recommendation if provided
        recommendation_id = data.get("recommendation_id")
        if recommendation_id:
            rec = self.db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
            if not rec:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
            if rec.approval_status != "approved":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Procurement can only reference approved recommendations",
                )

        procurement = ProcurementRequest(
            procurement_number=self._generate_procurement_number(),
            testing_request_id=testing_request_id,
            recommendation_id=recommendation_id,
            title=data["title"],
            description=data.get("description"),
            estimated_cost=data.get("estimated_cost"),
            quantity=data.get("quantity"),
            specifications=data.get("specifications"),
            status="initiated",
            raised_by=raised_by,
            created_by=raised_by,
        )
        self.db.add(procurement)

        # Update testing request status
        request.status = TestingRequestStatus.procurement_initiated
        request.modified_by = raised_by

        self.db.commit()
        self.db.refresh(procurement)
        return procurement

    def get_procurement(self, procurement_id: UUID) -> ProcurementRequest:
        proc = self.db.query(ProcurementRequest).filter(ProcurementRequest.id == procurement_id).first()
        if not proc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Procurement request not found")
        return proc

    def get_procurements(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
        raised_by: Optional[UUID] = None,
    ) -> List[ProcurementRequest]:
        query = self.db.query(ProcurementRequest)
        if status_filter:
            query = query.filter(ProcurementRequest.status == status_filter)
        if raised_by:
            query = query.filter(ProcurementRequest.raised_by == raised_by)
        return query.order_by(ProcurementRequest.cts.desc()).offset(skip).limit(limit).all()

    def update_procurement(self, procurement_id: UUID, data: dict, modified_by: UUID) -> ProcurementRequest:
        proc = self.get_procurement(procurement_id)
        for key, value in data.items():
            if hasattr(proc, key) and value is not None:
                setattr(proc, key, value)
        proc.modified_by = modified_by
        self.db.commit()
        self.db.refresh(proc)
        return proc

    def complete_procurement(self, procurement_id: UUID, modified_by: UUID) -> ProcurementRequest:
        proc = self.get_procurement(procurement_id)
        if proc.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procurement is already completed",
            )
        proc.status = "completed"
        proc.modified_by = modified_by

        # Update testing request to completed
        request = self.db.query(TestingRequest).filter(TestingRequest.id == proc.testing_request_id).first()
        if request:
            request.status = TestingRequestStatus.completed
            request.completed_at = UTCDateTimeMixin._utc_now()
            request.modified_by = modified_by

        self.db.commit()
        self.db.refresh(proc)
        return proc
