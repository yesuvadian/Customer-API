from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from models import TestingRequest, TestingRequestStatus, User
from utils.common_service import UTCDateTimeMixin


class TestingRequestService:

    def __init__(self, db: Session):
        self.db = db

    def _generate_request_number(self) -> str:
        today = UTCDateTimeMixin._utc_now().strftime("%Y%m%d")
        count = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.request_number.like(f"TR-{today}-%"))
            .scalar()
        )
        return f"TR-{today}-{(count + 1):04d}"

    def create_request(self, data: dict, originator_id: UUID) -> TestingRequest:
        request_number = self._generate_request_number()
        request = TestingRequest(
            request_number=request_number,
            title=data["title"],
            description=data.get("description"),
            transformer_type=data.get("transformer_type"),
            transformer_rating=data.get("transformer_rating"),
            manufacturer=data.get("manufacturer"),
            serial_number=data.get("serial_number"),
            equipment_type_id=data.get("equipment_type_id"),
            test_type_id=data.get("test_type_id"),
            equipment_id=data.get("equipment_id"),
            request_category=data.get("request_category", "test"),
            organization_id=data.get("organization_id"),
            department_id=data.get("department_id"),
            zone=data.get("zone"),
            ce_circle=data.get("ce_circle"),
            se_division=data.get("se_division"),
            ee_subdivision=data.get("ee_subdivision"),
            aee_section=data.get("aee_section"),
            ae_je=data.get("ae_je"),
            assigned_tester_id=data.get("assigned_tester_id"),
            priority=data.get("priority", "normal"),
            requested_date=data.get("requested_date"),
            due_date=data.get("due_date"),
            scheduled_start_date=data.get("scheduled_start_date"),
            notes=data.get("notes"),
            status=TestingRequestStatus.draft,
            originator_id=originator_id,
            created_by=originator_id,
            is_multi_session=data.get("is_multi_session", False),
            total_sessions_planned=data.get("total_sessions_planned"),
            session_interval_days=data.get("session_interval_days"),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def get_request(self, request_id: UUID) -> TestingRequest:
        request = self.db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")
        return request

    def get_requests(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        originator_id: Optional[UUID] = None,
        tester_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
    ) -> List[TestingRequest]:
        query = self.db.query(TestingRequest)
        if status_filter:
            query = query.filter(TestingRequest.status == status_filter)
        if category_filter:
            query = query.filter(TestingRequest.request_category == category_filter)
        if originator_id:
            query = query.filter(TestingRequest.originator_id == originator_id)
        if tester_id:
            query = query.filter(TestingRequest.assigned_tester_id == tester_id)
        if organization_id:
            query = query.filter(TestingRequest.organization_id == organization_id)
        return query.order_by(TestingRequest.cts.desc()).offset(skip).limit(limit).all()

    def get_requests_for_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
    ) -> List[TestingRequest]:
        """Return requests where user is originator OR assigned tester."""
        query = self.db.query(TestingRequest).filter(
            or_(
                TestingRequest.originator_id == user_id,
                TestingRequest.assigned_tester_id == user_id,
            )
        )
        if status_filter:
            query = query.filter(TestingRequest.status == status_filter)
        return query.order_by(TestingRequest.cts.desc()).offset(skip).limit(limit).all()

    def update_request(self, request_id: UUID, data: dict, modified_by: UUID) -> TestingRequest:
        request = self.get_request(request_id)
        if request.status != TestingRequestStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft requests can be updated",
            )
        for key, value in data.items():
            if hasattr(request, key) and value is not None:
                setattr(request, key, value)
        request.modified_by = modified_by
        self.db.commit()
        self.db.refresh(request)
        return request

    def delete_request(self, request_id: UUID) -> dict:
        request = self.get_request(request_id)
        if request.status != TestingRequestStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft requests can be deleted",
            )
        self.db.delete(request)
        self.db.commit()
        return {"message": "Testing request deleted successfully"}

    def submit_request(self, request_id: UUID, modified_by: UUID) -> TestingRequest:
        request = self.get_request(request_id)
        if request.status != TestingRequestStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft requests can be submitted",
            )
        # If tester already assigned during creation, go straight to 'assigned'
        if request.assigned_tester_id:
            request.status = TestingRequestStatus.assigned
            request.assigned_at = UTCDateTimeMixin._utc_now()
        else:
            request.status = TestingRequestStatus.submitted
        request.modified_by = modified_by
        self.db.commit()
        self.db.refresh(request)
        return request

    def assign_tester(self, request_id: UUID, tester_id: UUID, assigned_by: UUID) -> TestingRequest:
        request = self.get_request(request_id)
        if request.status != TestingRequestStatus.submitted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only submitted requests can be assigned",
            )
        tester = self.db.query(User).filter(User.id == tester_id).first()
        if not tester:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tester not found")

        request.assigned_tester_id = tester_id
        request.assigned_at = UTCDateTimeMixin._utc_now()
        request.status = TestingRequestStatus.assigned
        request.modified_by = assigned_by
        self.db.commit()
        self.db.refresh(request)
        return request

    def get_stats(self, user_id: UUID = None, organization_id: UUID = None) -> dict:
        """Return counts by testing request status."""
        query = self.db.query(TestingRequest)
        if organization_id:
            query = query.filter(TestingRequest.organization_id == organization_id)
        elif user_id:
            # Fallback for backward compatibility
            query = query.filter(
                or_(
                    TestingRequest.originator_id == user_id,
                    TestingRequest.assigned_tester_id == user_id,
                )
            )
        total = query.count()
        draft = query.filter(TestingRequest.status == TestingRequestStatus.draft).count()
        submitted = query.filter(TestingRequest.status == TestingRequestStatus.submitted).count()
        in_progress = query.filter(
            TestingRequest.status.in_([
                TestingRequestStatus.assigned,
                TestingRequestStatus.accepted,
                TestingRequestStatus.in_progress,
            ])
        ).count()
        under_approval = query.filter(TestingRequest.status == TestingRequestStatus.under_approval).count()
        approved = query.filter(TestingRequest.status == TestingRequestStatus.approved).count()
        rejected = query.filter(TestingRequest.status == TestingRequestStatus.rejected).count()
        completed = query.filter(TestingRequest.status == TestingRequestStatus.completed).count()
        # Category breakdown
        from models import RequestCategory
        by_category = {}
        for cat in RequestCategory:
            by_category[cat.value] = query.filter(
                TestingRequest.request_category == cat.value
            ).count()

        return {
            "total": total,
            "draft": draft,
            "submitted": submitted,
            "in_progress": in_progress,
            "under_approval": under_approval,
            "approved": approved,
            "rejected": rejected,
            "completed": completed,
            "by_category": by_category,
        }

    # NOTE: Tester workflow transitions (accept, start, submit_results)
    # are in services/testing_service.py, used by routers/testing.py.
