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
    User,
)
from utils.common_service import UTCDateTimeMixin


# ── prefix map ────────────────────────────────────────────────────────────────
_PREFIX = {
    RequestCategory.failure_registry: "FR",
    RequestCategory.taqc_inspection: "TQ",
}

# Roles allowed to submit each category
_ALLOWED_ROLES: dict[RequestCategory, set[str]] = {
    RequestCategory.failure_registry: {
        "Field Staff",
        "AEE",
        "EE TLSS",
        "TA&QC Officer",
        "Admin",
        "SuperAdmin",
    },
    RequestCategory.taqc_inspection: {
        "TA&QC Officer",
        "Admin",
        "SuperAdmin",
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
        """Raise 403 if the user does not have a permitted role for this category."""
        from models import Role, UserRole

        user_roles = (
            self.db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == user.id)
            .all()
        )
        user_role_names = {r[0] for r in user_roles}
        allowed = _ALLOWED_ROLES.get(category, set())

        if not user_role_names.intersection(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role is not permitted to submit {category.value} records.",
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

        # ── TestingRequest ────────────────────────────────────────────────────
        req = TestingRequest(
            request_number=request_number,
            title=data.get("title") or request_number,
            description=data.get("description"),
            request_category=category,
            equipment_id=data.get("equipment_id"),
            organization_id=data.get("organization_id"),
            department_id=data.get("department_id"),
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
        self.db.commit()
        self.db.refresh(req)
        self.db.refresh(result)

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
                joinedload(TestingRequest.equipment),
                joinedload(TestingRequest.organization),
                joinedload(TestingRequest.department),
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
                joinedload(TestingRequest.equipment),
                joinedload(TestingRequest.organization),
                joinedload(TestingRequest.department),
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
        orig = req.originator
        orig_name = (
            f"{orig.firstname or ''} {orig.lastname or ''}".strip() or orig.email
            if orig else "-"
        )
        return {
            "id": str(req.id),
            "request_number": req.request_number,
            "title": req.title,
            "request_category": req.request_category.value if req.request_category else None,
            "status": req.status.value if req.status else None,
            "priority": req.priority,
            "equipment_ueic": req.equipment.ueic if req.equipment else None,
            "equipment_name": req.equipment.name if req.equipment else None,
            "organization": req.organization.name if req.organization else None,
            "department": req.department.name if req.department else None,
            "submitted_by": orig_name,
            "submitted_at": req.cts.isoformat() if req.cts else None,
            "notes": req.notes,
        }
