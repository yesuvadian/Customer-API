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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, TrWfStatus, TrWfInstance, TrWfStage, TrWfDefinition, TestingRequest, RequestCategory
from services.direct_submission_service import DirectSubmissionService
from datetime import date

from services.testing_request_service import TestingRequestService

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


@router.get("/wf-stages")
def get_category_wf_stages(
    category: str = Query(..., description="failure_registry | taqc_inspection"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return ordered WF stages for the workflow used by this direct-submission category."""
    try:
        cat = RequestCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    # Find the WF definition used by requests of this category
    # Use request_type='pm' for failure_registry to target PM Workflow specifically
    req_type = "pm" if cat == RequestCategory.failure_registry else cat.value

    defn = (
        db.query(TrWfDefinition)
        .join(TrWfInstance, TrWfInstance.wf_definition_id == TrWfDefinition.id)
        .join(TestingRequest, TestingRequest.wf_instance_id == TrWfInstance.id)
        .filter(
            TestingRequest.request_category == cat,
            TestingRequest.request_type == req_type,
        )
        .first()
    )
    if not defn:
        return []

    stages = (
        db.query(TrWfStage)
        .filter(
            TrWfStage.wf_definition_id == defn.id,
            TrWfStage.is_active.is_(True),
        )
        .order_by(TrWfStage.sequence)
        .all()
    )
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "sequence": s.sequence,
        }
        for s in stages
    ]


@router.get("/by-equipment")
def get_by_equipment(
    category: str = Query("failure_registry", description="failure_registry | taqc_inspection"),
    department_id: Optional[UUID] = Query(None),
    is_closed: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None), 
):
    """Return direct submissions grouped by equipment with alert bar status."""
    from utils.common_service import get_dept_subtree_ids
    org_id = current_user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    dept_ids = None
    if department_id:
        dept_ids = get_dept_subtree_ids(db, department_id)
    return TestingRequestService(db).get_by_equipment(
        org_id=org_id,
        department_ids=dept_ids,
        request_category=category,
        is_closed=is_closed,
        date_from=date_from,
        date_to=date_to,
    )

@router.get("/")
def list_direct_submissions(
    category: str = Query(...),
    own_only: bool = Query(False),
    department_id: Optional[UUID] = Query(None),

    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    is_closed: Optional[bool] = Query(None),

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
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
        is_closed=is_closed,
    )


@router.post("/{submission_id}/attach")
async def attach_file(
    submission_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a file attachment (photo, PDF, or document) to a direct submission."""
    svc = DirectSubmissionService(db)
    return await svc.attach_file(submission_id, file, current_user)


@router.get("/{submission_id}/attachment")
def download_attachment(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the file attachment for a direct submission."""
    svc = DirectSubmissionService(db)
    return svc.get_attachment(submission_id, current_user)


@router.get("/{submission_id}")
def get_direct_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full detail for a single direct-submission record including its test result."""
    svc = DirectSubmissionService(db)
    return svc.get_submission(submission_id, current_user)
