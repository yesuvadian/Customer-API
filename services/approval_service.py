from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import Recommendation, RecommendationType, TestingRequest, TestingRequestStatus, TestResult, User
from utils.common_service import UTCDateTimeMixin


class ApprovalService:

    def __init__(self, db: Session):
        self.db = db

    def get_pending_approvals(self, skip: int = 0, limit: int = 100) -> List[Recommendation]:
        # Auto-create recommendations for orphaned test_submitted requests
        self._auto_create_recommendations_for_orphaned()

        return (
            self.db.query(Recommendation)
            .filter(Recommendation.approval_status == "pending")
            .order_by(Recommendation.cts.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def _auto_create_recommendations_for_orphaned(self):
        """Find test_submitted requests without recommendations and auto-create them."""
        from sqlalchemy import exists, select

        orphaned = (
            self.db.query(TestingRequest)
            .filter(
                TestingRequest.status.in_([
                    TestingRequestStatus.test_submitted,
                    TestingRequestStatus.under_approval,
                ]),
                ~exists(
                    select(Recommendation.id)
                    .where(Recommendation.testing_request_id == TestingRequest.id)
                    .correlate(TestingRequest)
                ),
            )
            .all()
        )

        for request in orphaned:
            results = (
                self.db.query(TestResult)
                .filter(TestResult.testing_request_id == request.id)
                .order_by(TestResult.cts.asc())
                .all()
            )

            # Derive recommendation type
            overall_results = [
                (r.overall_result or "").lower().strip()
                for r in results if r.overall_result
            ]
            if not overall_results:
                rec_type = RecommendationType.conditional
            elif all(r == "pass" for r in overall_results):
                rec_type = RecommendationType.pass_test
            elif any(r == "fail" for r in overall_results):
                rec_type = RecommendationType.fail
            else:
                rec_type = RecommendationType.conditional

            # Build summary
            test_names = [r.test_name or r.template_key or "Test" for r in results]
            tests_str = ", ".join(test_names) if test_names else "No tests"
            title = request.title or request.request_number
            type_label = rec_type.value.upper()
            summary = f"[{type_label}] {title} — {len(results)} test(s): {tests_str}"

            rec = Recommendation(
                testing_request_id=request.id,
                recommendation_type=rec_type,
                summary=summary,
                approval_status="pending",
                submitted_by=request.assigned_tester_id,
                submitted_at=UTCDateTimeMixin._utc_now(),
                created_by=request.assigned_tester_id,
            )
            self.db.add(rec)

            # Move to under_approval if still at test_submitted
            if request.status == TestingRequestStatus.test_submitted:
                request.status = TestingRequestStatus.under_approval

        if orphaned:
            self.db.commit()

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
                "equipment_id": str(request.equipment_id) if request.equipment_id else None,
                "equipment_ueic": request.equipment.ueic if request.equipment else None,
                "department_name": request.department.name if request.department else None,
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

    def get_approval_stats(self, approver_id: UUID = None) -> dict:
        """Return approval counts: pending, approved, rejected, total_reviewed."""
        from sqlalchemy import func

        pending = (
            self.db.query(func.count(Recommendation.id))
            .filter(Recommendation.approval_status == "pending")
            .scalar()
        )

        if approver_id:
            approved = (
                self.db.query(func.count(Recommendation.id))
                .filter(
                    Recommendation.approval_status == "approved",
                    Recommendation.approved_by == approver_id,
                )
                .scalar()
            )
            rejected = (
                self.db.query(func.count(Recommendation.id))
                .filter(
                    Recommendation.approval_status == "rejected",
                    Recommendation.approved_by == approver_id,
                )
                .scalar()
            )
        else:
            approved = (
                self.db.query(func.count(Recommendation.id))
                .filter(Recommendation.approval_status == "approved")
                .scalar()
            )
            rejected = (
                self.db.query(func.count(Recommendation.id))
                .filter(Recommendation.approval_status == "rejected")
                .scalar()
            )

        return {
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "total_reviewed": approved + rejected,
        }

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
