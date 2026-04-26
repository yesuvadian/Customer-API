"""
direct_submissions.py
─────────────────────
Endpoints for the two direct-submission modules:

  POST   /direct-submissions/           — create (failure_registry or taqc_inspection)
  GET    /direct-submissions/           — list (filter by category)
  GET    /direct-submissions/{id}       — single record detail

Both modules share the same API; the `request_category` field in the body
(or query param for list) selects which module is used.

Access is role-gated inside the service layer.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from services.direct_submission_service import DirectSubmissionService

router = APIRouter(
    prefix="/direct-submissions",
    tags=["direct-submissions"],
    dependencies=[Depends(get_current_user)],
)


# ── Request / Response schemas ─────────────────────────────────────────────

class DirectSubmitBody(BaseModel):
    request_category: str          # "failure_registry" | "taqc_inspection"
    template_key: str
    title: str
    test_data: dict

    # optional linkage
    equipment_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None

    # result
    overall_result: Optional[str] = None   # default by category if omitted
    remarks: Optional[str] = None
    notes: Optional[str] = None
    priority: str = "normal"


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_direct_submission(
    body: DirectSubmitBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a Failure Registry or TA&QC Inspection record.

    Atomically creates TestingRequest (status=under_approval) + TestResult.
    No tester assignment step — the submitter is the data entry officer.
    """
    svc = DirectSubmissionService(db)
    return svc.create_direct_submission(body.model_dump(), current_user)


@router.get("/")
def list_direct_submissions(
    category: str = Query(
        ..., description="failure_registry | taqc_inspection"
    ),
    own_only: bool = Query(
        False,
        description="If true, return only submissions created by the current user",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List direct-submission records for a given category."""
    svc = DirectSubmissionService(db)
    return svc.list_submissions(
        category=category,
        user=current_user,
        skip=skip,
        limit=limit,
        own_only=own_only,
    )


@router.get("/{submission_id}")
def get_direct_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full detail for a single direct-submission record including its test result."""
    svc = DirectSubmissionService(db)
    return svc.get_submission(submission_id, current_user)
