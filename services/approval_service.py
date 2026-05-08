from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from models import (
    Recommendation,
    RecommendationType,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    User,
)
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

        # Build field-label map from OrgTestTemplate (DB-first, then static fallback)
        def _field_labels_for_key(template_key: str) -> dict:
            """Return {field_key: label} from the template definition."""
            labels = {}
            if not template_key:
                return labels
            try:
                from models import OrgTestTemplate
                tmpl = (
                    self.db.query(OrgTestTemplate)
                    .filter(OrgTestTemplate.template_key == template_key)
                    .first()
                )
                data = tmpl.template_data if tmpl and tmpl.template_data else {}
                if not data:
                    from test_templates import get_template_by_key
                    data = get_template_by_key(template_key) or {}
                for sec in data.get("sections", []):
                    for f in sec.get("fields", []):
                        labels[f["key"]] = f.get("label", f["key"])
            except Exception:
                pass
            return labels

        # Build test results list with field labels for friendly display
        test_results = []
        for r in results:
            labels = _field_labels_for_key(r.template_key)
            test_results.append({
                "id": str(r.id),
                "test_name": r.test_name,
                "template_key": r.template_key,
                "test_data": r.test_data,
                "field_labels": labels,   # {key: friendly_label} from template
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
            "next_action": rec.next_action.value if rec.next_action else None,
            "schedule_frequency": rec.schedule_frequency.value if rec.schedule_frequency else None,
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
    ) -> dict:
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

        request = self.db.query(TestingRequest).filter(TestingRequest.id == rec.testing_request_id).first()
        if request:
            request.modified_by = approver_id

        self.db.commit()
        self.db.refresh(rec)

        # ── Notification ──────────────────────────────────────────────────────
        if request:
            try:
                from services.notification_service import NotificationService
                NotificationService(self.db).notify_recommendation_approved(request, rec)
            except Exception as _n:
                print(f"[WARN] recommendation_approved notification failed: {_n}")

        # ── next_action dispatch (new flow) ───────────────────────────────────
        dispatch_result = {}
        if request and rec.next_action is not None:
            try:
                from services.workflow_dispatch_service import WorkflowDispatchService
                dispatch_result = WorkflowDispatchService(self.db).dispatch(request, rec, approver_id)
            except Exception as _d:
                print(f"[WARN] next_action dispatch failed: {_d}")

        return {
            "id": str(rec.id),
            "testing_request_id": str(rec.testing_request_id),
            "recommendation_type": rec.recommendation_type.value if rec.recommendation_type else None,
            "next_action": rec.next_action.value if rec.next_action else None,
            "schedule_frequency": rec.schedule_frequency.value if rec.schedule_frequency else None,
            "approval_status": rec.approval_status,
            "approved_by": str(rec.approved_by) if rec.approved_by else None,
            "approved_at": rec.approved_at.isoformat() if rec.approved_at else None,
            "approval_notes": rec.approval_notes,
            **dispatch_result,
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _generate_tr_number(self, prefix: str) -> str:
        """Generate a sequential request number like RL-20260501-0001."""
        from sqlalchemy import func
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        count = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.request_number.like(f"{prefix}-{today}-%"))
            .scalar()
        )
        return f"{prefix}-{today}-{(count + 1):04d}"

    def _create_repair_tr(
        self,
        source_request: TestingRequest,
        td: dict,
        approver_id: UUID,
    ) -> str:
        """
        Auto-create a repair_lifecycle TestingRequest linked to an approved FR-,
        and trigger the 10-stage RepairWorkflow for the equipment.
        """
        now = datetime.now(timezone.utc)
        rn = self._generate_tr_number("RL")

        failure_category = td.get("failure_category", "")
        failure_date = td.get("failure_date", "")
        fr_title = source_request.title or source_request.request_number

        # ── RL- ticket (traceability / audit record) ──────────────────────────
        repair_tr = TestingRequest(
            request_number=rn,
            title=f"[Repair] {fr_title}",
            description=(
                f"Auto-created from Failure Registry approval.\n"
                f"Source FR: {source_request.request_number}\n"
                f"Failure Category: {failure_category}\n"
                f"Failure Date: {failure_date}"
            ),
            request_category=RequestCategory.repair_lifecycle,
            equipment_id=source_request.equipment_id,
            organization_id=source_request.organization_id,
            department_id=source_request.department_id,
            priority=source_request.priority or "normal",
            status=TestingRequestStatus.submitted,
            is_direct_submission=False,
            source_failure_id=source_request.id,     # traceability FK
            originator_id=source_request.originator_id,
            created_by=approver_id,
            requested_date=now,
        )
        self.db.add(repair_tr)
        self.db.commit()
        self.db.refresh(repair_tr)

        # ── Trigger the 10-stage repair workflow ──────────────────────────────
        if source_request.equipment_id:
            try:
                from services.repair_workflow_service import RepairWorkflowService
                from models import RepairWorkflow

                svc = RepairWorkflowService(self.db)
                workflow_dict = svc.start_workflow(
                    equipment_id=source_request.equipment_id,
                    user_id=approver_id,
                )
                # Link FR → Workflow for traceability
                wf = self.db.query(RepairWorkflow).filter(
                    RepairWorkflow.id == UUID(workflow_dict["id"])
                ).first()
                if wf:
                    wf.source_failure_id = source_request.id
                    self.db.commit()

                print(
                    f"[INFO] Repair workflow {workflow_dict['id']} started "
                    f"for equipment {source_request.equipment_id} (FR: {source_request.request_number})"
                )
            except Exception as e:
                # Workflow trigger failure must NOT break the approval transaction
                print(f"[WARN] Repair workflow auto-start failed: {e}")

        return repair_tr.request_number

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

        # Move TR to under_review so tester can revise and resubmit
        request = self.db.query(TestingRequest).filter(TestingRequest.id == rec.testing_request_id).first()
        if request:
            request.status = TestingRequestStatus.under_review
            request.rejection_reason = notes
            request.modified_by = approver_id

        self.db.commit()
        self.db.refresh(rec)

        # Notify the submitter of rejection
        if request:
            try:
                from services.notification_service import NotificationService
                ns = NotificationService(self.db)
                if request.request_category == RequestCategory.failure_registry:
                    submitter = self.db.query(User).filter(
                        User.id == request.originator_id
                    ).first() if request.originator_id else None
                    if submitter:
                        ns.fire(
                            event_type="fr_rejected",
                            context={
                                "fr_number": request.request_number,
                                "reason": notes or "No reason provided",
                            },
                            organization_id=request.organization_id,
                            source_id=request.id,
                            source_type="testing_request",
                            severity="alert",
                            extra_recipients=[submitter],
                            workflow_type="failure_registry",
                            test_type="failure_registry",
                        )
                else:
                    # Standard TR rejection — notify the assigned tester to revise
                    ns.notify_recommendation_rejected(request, rec)
            except Exception as _n:
                print(f"[WARN] recommendation_rejected notification failed: {_n}")

        return rec
