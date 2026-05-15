"""
direct_submission_service.py
────────────────────────────
Handles direct-submission modules that bypass the normal tester-assignment flow:

  • Failure Registry  (RequestCategory.failure_registry, prefix FR-)
  • TA&QC Inspection  (RequestCategory.taqc_inspection,  prefix TQ-)

FR flow:
  1. TestingRequest created (status=submitted, is_direct_submission=True)
     form_data = { <dynamic template fields>, "recommendation": { ...snapshot + id } }
  2. Recommendation row created (drives WorkflowDispatchService after approval)
  No TestResult at submission time — test results come via TestRequestScheduleService.

TAQC flow: TR + TestResult + Recommendation (direct to TechApprover queue).
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from models import (
    NextActionType,
    Recommendation,
    RecommendationType,
    RequestCategory,
    ScheduleFrequency,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    User,
    Equipment,
    OrgRole,
    OrgUserRole,
)
from utils.common_service import UTCDateTimeMixin


# ── prefix map ────────────────────────────────────────────────────────────────
_PREFIX = {
    RequestCategory.failure_registry: "FR",
    RequestCategory.taqc_inspection: "TQ",
}

# Wizard label → enum maps (FR recommendation wizard sends capitalised strings)
_WIZARD_REC_TYPE = {
    "Pass":        RecommendationType.pass_test,
    "Fail":        RecommendationType.fail,
    "Conditional": RecommendationType.conditional,
    "Retest":      RecommendationType.retest,
}
_WIZARD_ACTION = {
    "None":        NextActionType.none,
    "Test":        NextActionType.test,
    "Maintenance": NextActionType.maintenance,
    "Inspection":  NextActionType.inspection,
    "Repair":      NextActionType.repair_cycle,
    "Procurement": NextActionType.replacement,
}
_WIZARD_FREQ = {
    "daily":       ScheduleFrequency.daily,
    "weekly":      ScheduleFrequency.weekly,
    "biweekly":    ScheduleFrequency.biweekly,
    "monthly":     ScheduleFrequency.monthly,
    "quarterly":   ScheduleFrequency.quarterly,
    "semi_annual": ScheduleFrequency.semi_annual,
    "yearly":      ScheduleFrequency.yearly,
    "triennial":   ScheduleFrequency.triennial,
}


class DirectSubmissionService:

    def __init__(self, db: Session):
        self.db = db

    # ── helpers ───────────────────────────────────────────────────────────────

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _generate_request_number(self, category: RequestCategory) -> str:
        prefix = _PREFIX.get(category, "DS")
        today = self._utc_now().strftime("%Y%m%d")
        count = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.request_number.like(f"{prefix}-{today}-%"))
            .scalar()
        )
        return f"{prefix}-{today}-{(count + 1):04d}"

    # ── main operation ────────────────────────────────────────────────────────

    def create_direct_submission(
        self,
        data: dict,
        submitter: User,
    ) -> dict:
        """
        FR:   Creates TestingRequest (status=submitted) with form_data storing
              the dynamic template fields + a recommendation snapshot (including
              the Recommendation row id). No TestResult — results come later via
              TestRequestScheduleService after the Test Assigner approves.

        TAQC: Creates TestingRequest (status=under_approval) + TestResult +
              Recommendation in one atomic transaction.

        Required keys in `data`:
          request_category   str  — "failure_registry" | "taqc_inspection"
          title              str
          test_data          dict — FR: dynamic template fields + wizard outcome fields

        FR optional:
          equipment_id, organization_id, department_id, priority, notes
          replacement_products  list  — from the wizard product picker

        TAQC optional:
          template_key, overall_result, remarks
        """
        raw_category = data.get("request_category", "")
        try:
            category = RequestCategory(raw_category)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid request_category: {raw_category}. "
                       "Accepted: failure_registry, taqc_inspection",
            )

        if category not in _PREFIX:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category '{raw_category}' is not a direct-submission category.",
            )

        now = self._utc_now()
        org_id  = data.get("organization_id") or getattr(submitter, "organization_id", None)
        dept_id = data.get("department_id")    or getattr(submitter, "department_id",   None)
        _td     = data.get("test_data") or {}

        # ── TestingRequest ────────────────────────────────────────────────────
        initial_status = (
            TestingRequestStatus.under_approval  # FR goes straight to Tech Approver queue
            if category == RequestCategory.failure_registry
            else TestingRequestStatus.under_approval
        )

        req = TestingRequest(
            request_number=self._generate_request_number(category),
            title=data.get("title") or f"{category.value.replace('_',' ').title()} Report",
            description=data.get("description"),
            request_category=category,
            equipment_id=data.get("equipment_id"),
            organization_id=org_id,
            department_id=dept_id,
            priority=data.get("priority", "normal"),
            notes=data.get("notes"),
            status=initial_status,
            is_direct_submission=True,
            originator_id=submitter.id,
            created_by=submitter.id,
            requested_date=now,
        )
        self.db.add(req)
        self.db.flush()

        # ── Recommendation ────────────────────────────────────────────────────
        if category == RequestCategory.failure_registry:
            rec_type    = _WIZARD_REC_TYPE.get(_td.get("recommendation_type", ""), RecommendationType.fail)
            next_action = _WIZARD_ACTION.get(_td.get("next_action", ""))
            sched_freq  = _WIZARD_FREQ.get(_td.get("outcome_frequency", ""))
            repl_prods  = data.get("replacement_products") or []
            summary     = _td.get("outcome_summary") or f"[FR] {req.request_number}"
            detailed    = _td.get("outcome_notes") or data.get("remarks")
        else:
            _result_map = {
                "pass": RecommendationType.pass_test, "conditional_pass": RecommendationType.conditional,
                "fail": RecommendationType.fail, "advisory": RecommendationType.conditional,
                "retest": RecommendationType.retest,
            }
            rec_type    = _result_map.get((data.get("overall_result") or "advisory").lower(), RecommendationType.conditional)
            next_action = None
            sched_freq  = None
            repl_prods  = []
            summary     = f"[Direct Submission] {category.value.replace('_',' ').title()} — {req.request_number}"
            detailed    = data.get("remarks")

        rec = Recommendation(
            testing_request_id=req.id,
            organization_id=org_id,
            recommendation_type=rec_type,
            next_action=next_action,
            schedule_frequency=sched_freq,
            test_types=_td.get("test_types") or None,
            replacement_products=repl_prods,
            summary=summary,
            detailed_notes=detailed,
            approval_status="pending",
            submitted_by=submitter.id,
            submitted_at=now,
            created_by=submitter.id,
        )
        self.db.add(rec)
        self.db.flush()  # get rec.id

        # ── FR: store template fields + recommendation snapshot in form_data ──
        if category == RequestCategory.failure_registry:
            req.form_data = {
                **_td,
                "recommendation": {
                    "id":                  str(rec.id),
                    "recommendation_type": _td.get("recommendation_type"),
                    "next_action":         _td.get("next_action"),
                    "test_types":          _td.get("test_types", []),
                    "schedule_frequency":  _td.get("outcome_frequency"),
                    "summary":             summary,
                    "notes":               detailed,
                    "replacement_products": repl_prods,
                },
            }
            flag_modified(req, "form_data")

        # ── TAQC: TestResult (form data lives here for TAQC) ─────────────────
        result = None
        if category == RequestCategory.taqc_inspection:
            result = TestResult(
                testing_request_id=req.id,
                template_key=data.get("template_key", category.value),
                test_name=data.get("title") or category.value.replace("_", " ").title(),
                test_category=category.value,
                test_data=_td,
                overall_result=data.get("overall_result") or "advisory",
                remarks=data.get("remarks"),
                tested_by=submitter.id,
                tested_at=now,
            )
            self.db.add(result)

        self.db.commit()
        self.db.refresh(req)

        try:
            from services.notification_service import NotificationService
            NotificationService(self.db).notify_request_submitted(req)
        except Exception as _n:
            print(f"[WARN] request_submitted notification failed: {_n}")

        return {
            "request_id":       str(req.id),
            "recommendation_id": str(rec.id),
            "request_number":   req.request_number,
            "request_category": category.value,
            "status":           req.status.value,
            "submitted_at":     now.isoformat(),
        }

    # ── list submissions ──────────────────────────────────────────────────────

    def _get_user_scope(self, user: User):
        """
        Return (is_org_admin: bool, department_id: UUID | None).
        Delegates to shared get_user_dept_scope() in utils.common_service.
        """
        from utils.common_service import get_user_dept_scope
        return get_user_dept_scope(self.db, user.id, None)

    def list_submissions(
        self,
        category: str,
        user: User,
        skip: int = 0,
        limit: int = 50,
        own_only: bool = False,
    ) -> list:
        """
        Return direct-submission records for a given category, dept-scoped
        to the logged-in user (same scope rules as /testing_requests/).
        If own_only=True, additionally restricts to records created by this user.
        """
        try:
            cat = RequestCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid category: {category}",
            )

        query = (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.originator),
                joinedload(TestingRequest.equipment).joinedload(Equipment.equipment_type),
                joinedload(TestingRequest.organization),
                joinedload(TestingRequest.department),
                joinedload(TestingRequest.test_results),
            )
            .filter(
                TestingRequest.request_category == cat,
                TestingRequest.is_direct_submission == True,
            )
            .order_by(TestingRequest.cts.desc())
        )

        # Apply department scope — org-admins see all; others see only their dept
        is_org_admin, dept_id = self._get_user_scope(user)
        if not is_org_admin and dept_id:
            query = query.filter(TestingRequest.department_id == dept_id)

        if own_only:
            query = query.filter(TestingRequest.originator_id == user.id)

        records = query.offset(skip).limit(limit).all()
        return [self._serialize(r) for r in records]

    def get_submission(self, request_id: UUID, user: User) -> dict:
        """Return single submission with its test result."""
        req = (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.originator),
                joinedload(TestingRequest.equipment).joinedload(Equipment.equipment_type),
                joinedload(TestingRequest.organization),
                joinedload(TestingRequest.department),
                joinedload(TestingRequest.test_results),
            )
            .filter(
                TestingRequest.id == request_id,
                TestingRequest.is_direct_submission == True,
            )
            .first()
        )
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )

        result = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == request_id)
            .order_by(TestResult.tested_at.desc())
            .first()
        )

        out = self._serialize(req)
        if result:
            out["result"] = {
                "id": str(result.id),
                "template_key": result.template_key,
                "test_data": result.test_data,
                "overall_result": result.overall_result,
                "remarks": result.remarks,
                "tested_at": result.tested_at.isoformat() if result.tested_at else None,
            }
        return out

    # ── serialiser ────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize(req: TestingRequest) -> dict:
        # FR: data lives in req.form_data (no TestResult)
        # TAQC: data lives in the linked TestResult
        result = req.test_results[0] if req.test_results else None

        eq = req.equipment
        eq_type_name = None
        if eq and eq.equipment_type:
            eq_type_name = getattr(eq.equipment_type, "name", None)

        is_fr = getattr(req.request_category, "value", None) == "failure_registry"
        form_data = req.form_data or {}

        return {
            "id": str(req.id),
            "request_number": req.request_number,
            "title": req.title,

            "request_category": getattr(req.request_category, "value", None),
            "status": getattr(req.status, "value", None),
            "priority": req.priority,

            "equipment_ueic": getattr(eq, "ueic", None),
            "equipment_type_name": eq_type_name,
            "equipment_manufacturer": getattr(eq, "manufacturer", None),

            "organization": getattr(req.organization, "name", None),
            "department": getattr(req.department, "name", None),

            "submitted_by": (
                f"{req.originator.firstname or ''} {req.originator.lastname or ''}".strip()
                if req.originator else "-"
            ),

            "cts": req.cts.isoformat() if req.cts else None,
            "notes": req.notes,

            # FR: form_data holds template fields + recommendation snapshot
            # TAQC: form_data is empty; test_data/overall_result come from TestResult
            "form_data":     form_data if is_fr else {},
            "test_data":     result.test_data if result else {},
            "overall_result": result.overall_result if result else None,
            "remarks":       result.remarks if result else None,

            # Attachment metadata
            "has_attachment": bool(result and result.file_data),
            "attachment_name": result.file_name if result else None,
            "attachment_size": result.file_size if result else None,
            "attachment_type": result.file_type if result else None,
        }

    # ── file attachment ───────────────────────────────────────────────────────

    async def attach_file(
        self,
        request_id: UUID,
        file,          # UploadFile — typed loosely to avoid import cycle
        user: User,
    ) -> dict:
        """Store a file attachment on the TestResult linked to this submission."""
        req = (
            self.db.query(TestingRequest)
            .filter(
                TestingRequest.id == request_id,
                TestingRequest.is_direct_submission.is_(True),
            )
            .first()
        )
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )

        result = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == request_id)
            .order_by(TestResult.tested_at.desc())
            .first()
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TestResult not found for this submission",
            )

        # Read and store
        data = await file.read()
        result.file_name = file.filename
        result.file_type = file.content_type or "application/octet-stream"
        result.file_size = len(data)
        result.file_data = data
        self.db.commit()

        return {
            "file_name": file.filename,
            "file_size": len(data),
            "file_type": file.content_type,
        }

    def get_attachment(self, request_id: UUID, user: User):
        """Return the binary file attachment for a submission."""
        from fastapi.responses import Response as FastResponse

        result = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == request_id)
            .order_by(TestResult.tested_at.desc())
            .first()
        )
        if not result or not result.file_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No attachment found for this submission",
            )

        fname = result.file_name or "attachment"
        ctype = result.file_type or "application/octet-stream"
        return FastResponse(
            content=bytes(result.file_data),
            media_type=ctype,
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "Content-Length": str(result.file_size or len(result.file_data)),
            },
        )
