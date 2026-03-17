from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import Recommendation, TestingRequest, TestingRequestStatus, TestResult, User
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

    def get_approval_detail(self, recommendation_id: UUID) -> dict:
        """Return recommendation + testing request details + test results for approver review."""
        rec = self.db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")

        request = self.db.query(TestingRequest).filter(TestingRequest.id == rec.testing_request_id).first()

        # Fetch test results
        results = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == rec.testing_request_id)
            .order_by(TestResult.cts.asc())
            .all()
        )

        # Build user name helper
        def _user_name(user_id):
            if not user_id:
                return None
            u = self.db.query(User).filter(User.id == user_id).first()
            if u:
                return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email
            return str(user_id)

        # Build request info
        request_info = None
        if request:
            request_info = {
                "id": str(request.id),
                "request_number": request.request_number,
                "title": request.title,
                "description": request.description,
                "status": request.status.value if request.status else None,
                "priority": request.priority,
                "equipment_type_name": request.equipment_type.name if request.equipment_type else None,
                "test_type_name": request.test_type.name if request.test_type else None,
                "transformer_rating": request.transformer_rating,
                "manufacturer": request.manufacturer,
                "serial_number": request.serial_number,
                "originator_name": _user_name(request.originator_id),
                "assigned_tester_name": _user_name(request.assigned_tester_id),
            }

        # Build test results list
        test_results = []
        for r in results:
            test_results.append({
                "id": str(r.id),
                "test_name": r.test_name,
                "template_key": r.template_key,
                "test_data": r.test_data,
                "overall_result": r.overall_result,
                "remarks": r.remarks,
                "tested_by_name": _user_name(r.tested_by),
                "tested_at": r.tested_at.isoformat() if r.tested_at else None,
                "image_count": len(r.images) if r.images else 0,
            })

        return {
            "id": str(rec.id),
            "testing_request_id": str(rec.testing_request_id),
            "recommendation_type": rec.recommendation_type.value if rec.recommendation_type else None,
            "summary": rec.summary,
            "detailed_notes": rec.detailed_notes,
            "approval_status": rec.approval_status,
            "approved_by": str(rec.approved_by) if rec.approved_by else None,
            "approved_at": rec.approved_at.isoformat() if rec.approved_at else None,
            "approval_notes": rec.approval_notes,
            "submitted_by": str(rec.submitted_by) if rec.submitted_by else None,
            "submitted_by_name": _user_name(rec.submitted_by),
            "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
            "cts": rec.cts.isoformat() if rec.cts else None,
            "mts": rec.mts.isoformat() if rec.mts else None,
            "replacement_products": rec.replacement_products,
            "testing_request": request_info,
            "test_results": test_results,
        }

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
