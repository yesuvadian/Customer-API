"""
direct_submission_service.py
────────────────────────────
Handles direct-submission modules that bypass the normal tester-assignment
flow:

  • Failure Registry  (RequestCategory.failure_registry, prefix FR-)
  • TA&QC Inspection  (RequestCategory.taqc_inspection,  prefix TQ-)

Both create a TestingRequest + TestResult in one atomic transaction and
immediately place the record in the under_approval queue so the approver
can review without any prior assignment or testing step.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from models import (
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    RequestCategory,
    Recommendation,
    RecommendationType,
    User,
    Equipment,
)
from utils.common_service import UTCDateTimeMixin


# ── prefix map ────────────────────────────────────────────────────────────────
_PREFIX = {
    RequestCategory.failure_registry: "FR",
    RequestCategory.taqc_inspection: "TQ",
}

# Roles allowed to submit each category.
# These match BOTH global roles (Admin/SuperAdmin) and org-level role names.
_ALLOWED_ROLES: dict[RequestCategory, set[str]] = {
    RequestCategory.failure_registry: {
        # Global roles
        "Admin", "SuperAdmin",
        # KPTCL org roles — field staff who witness/record failures
        "Field Staff", "Field Tester",
        "AEE", "AEE Maintenance",
        "EE TLSS",
        "TA&QC Officer",
        "Originator",
        # Supervisory who may also file
        "Department Head", "Test Assigner",
    },
    RequestCategory.taqc_inspection: {
        # Global roles
        "Admin", "SuperAdmin",
        # KPTCL org roles for TA&QC
        "TA&QC Officer",
        "AEE Maintenance",
        "EE TLSS",
        "Department Head",
    },
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

    def _check_role_access(
        self, user: User, category: RequestCategory
    ) -> None:
        """Raise 403 if the user does not have a permitted role for this category.
        Checks both global user_roles and org_user_roles (org-level roles).
        """
        from models import Role, UserRole, OrgRole, OrgUserRole

        # 1. Global roles (admin@relu.com, superadmin@system.com)
        global_roles = (
            self.db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == user.id)
            .all()
        )
        # 2. Org-level roles (KPTCL users: ee.tlss@kptcl.com, aee.maintenance@kptcl.com …)
        org_roles = (
            self.db.query(OrgRole.name)
            .join(OrgUserRole, OrgUserRole.org_role_id == OrgRole.id)
            .filter(OrgUserRole.user_id == user.id)
            .all()
        )

        user_role_names = {r[0] for r in global_roles} | {r[0] for r in org_roles}
        allowed = _ALLOWED_ROLES.get(category, set())

        if not user_role_names.intersection(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({', '.join(user_role_names) or 'none'}) is not permitted to submit {category.value} records.",
            )

    # ── main operation ────────────────────────────────────────────────────────

    def create_direct_submission(
        self,
        data: dict,
        submitter: User,
    ) -> dict:
        """
        Creates a TestingRequest (status=under_approval, is_direct_submission=True)
        and a linked TestResult in one atomic transaction.

        Required keys in `data`:
          request_category   str  — "failure_registry" | "taqc_inspection"
          template_key       str
          title              str
          test_data          dict

        Optional keys:
          equipment_id       UUID str
          organization_id    UUID str
          department_id      UUID str
          overall_result     str   — default "fail" for failure_registry, "advisory" for taqc
          remarks            str
          notes              str
          priority           str   — default "normal"
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

        self._check_role_access(submitter, category)

        now = self._utc_now()
        request_number = self._generate_request_number(category)

        # Default overall_result by category
        default_result = (
            "fail" if category == RequestCategory.failure_registry else "advisory"
        )

        # Resolve org — prefer body, fall back to submitter's own org
        org_id = data.get("organization_id") or getattr(submitter, "organization_id", None)
        dept_id = data.get("department_id")

        # ── TestingRequest ────────────────────────────────────────────────────
        req = TestingRequest(
            request_number=request_number,
            title=data.get("title") or request_number,
            description=data.get("description"),
            request_category=category,
            equipment_id=data.get("equipment_id"),
            organization_id=org_id,
            department_id=dept_id,
            priority=data.get("priority", "normal"),
            notes=data.get("notes"),
            status=TestingRequestStatus.under_approval,
            is_direct_submission=True,
            originator_id=submitter.id,
            created_by=submitter.id,
            requested_date=now,
        )
        self.db.add(req)
        self.db.flush()  # get req.id without committing

        # ── TestResult ────────────────────────────────────────────────────────
        result = TestResult(
            testing_request_id=req.id,
            template_key=data.get("template_key", category.value),
            test_name=data.get("title") or category.value.replace("_", " ").title(),
            test_category=category.value,
            test_data=data.get("test_data", {}),
            overall_result=data.get("overall_result") or default_result,
            remarks=data.get("remarks"),
            tested_by=submitter.id,
            tested_at=now,
        )
        self.db.add(result)
        self.db.flush()

        # ── Recommendation (enables approval workflow) ─────────────────────────
        # Map overall_result → RecommendationType for the approval queue
        _result_to_rec_type = {
            "pass":             RecommendationType.pass_test,
            "conditional_pass": RecommendationType.conditional,
            "fail":             RecommendationType.fail,
            "advisory":         RecommendationType.conditional,
            "retest":           RecommendationType.retest,
        }
        rec_type = _result_to_rec_type.get(
            (data.get("overall_result") or default_result).lower(),
            RecommendationType.conditional,
        )
        rec = Recommendation(
            testing_request_id=req.id,
            organization_id=org_id,
            recommendation_type=rec_type,
            summary=(
                f"[Direct Submission] {category.value.replace('_',' ').title()} — "
                f"{data.get('title', req.request_number)}"
            ),
            detailed_notes=data.get("remarks"),
            approval_status="pending",
            submitted_by=submitter.id,
            submitted_at=now,
            created_by=submitter.id,
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(req)
        self.db.refresh(result)

        # Notify approvers that a new submission is pending
        try:
            from services.notification_service import NotificationService
            NotificationService(self.db).notify_request_submitted(req)
        except Exception as _n:
            print(f"[WARN] request_submitted notification failed: {_n}")

        return {
            "request_id": str(req.id),
            "result_id": str(result.id),
            "request_number": req.request_number,
            "request_category": category.value,
            "status": req.status.value,
            "submitted_at": now.isoformat(),
        }

    # ── list submissions ──────────────────────────────────────────────────────

    def list_submissions(
        self,
        category: str,
        user: User,
        skip: int = 0,
        limit: int = 50,
        own_only: bool = False,
    ) -> list:
        """
        Return direct-submission records for a given category.
        If own_only=True, returns only records created by this user.
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
        # Pull the first (and typically only) TestResult for direct submissions
        result = req.test_results[0] if req.test_results else None

        eq = req.equipment
        eq_type_name = None
        if eq and eq.equipment_type:
            eq_type_name = getattr(eq.equipment_type, "name", None)

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

            # Use "cts" key to match Flutter client expectations
            "cts": req.cts.isoformat() if req.cts else None,

            "notes": req.notes,

            # TestResult fields — populated for all direct submissions
            "test_data": result.test_data if result else {},
            "overall_result": result.overall_result if result else None,
            "remarks": result.remarks if result else None,

            # Attachment metadata (file_data itself is not serialised here)
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
