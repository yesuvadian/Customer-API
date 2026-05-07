from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import ProcurementRequestCreate, ProcurementRequestUpdate, ProcurementRequestResponse
from services.procurement_service import ProcurementService

router = APIRouter(
    prefix="/validation_requests",
    tags=["validation_requests"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/", response_model=ProcurementRequestResponse)
def create_procurement_request(
    data: ProcurementRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.create_procurement(data.dict(), raised_by=current_user.id)


@router.get("/", response_model=List[ProcurementRequestResponse])
def list_procurement_requests(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    raised_by: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.get_procurements(
        skip=skip,
        limit=limit,
        status_filter=status,
        raised_by=raised_by,
    )


@router.get("/{procurement_id}", response_model=ProcurementRequestResponse)
def get_procurement_request(
    procurement_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.get_procurement(procurement_id)


@router.put("/{procurement_id}", response_model=ProcurementRequestResponse)
def update_procurement_request(
    procurement_id: UUID,
    data: ProcurementRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.update_procurement(procurement_id, data.dict(exclude_unset=True), modified_by=current_user.id)


@router.put("/{procurement_id}/complete", response_model=ProcurementRequestResponse)
def complete_procurement(
    procurement_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.complete_procurement(procurement_id, modified_by=current_user.id)


@router.put("/{procurement_id}/finance-approve")
def finance_approve(
    procurement_id: UUID,
    data: ProcurementRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Finance Approver approves a replacement procurement request.

    Side effects:
    • ProcurementRequest.status → approved
    • TestingRequest.status    → outcome_active (terminal)
    """
    from models import ProcurementRequest, TestingRequest, TestingRequestStatus

    pr = db.query(ProcurementRequest).filter(ProcurementRequest.id == procurement_id).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Procurement request not found")
    if pr.status != "pending_finance":
        raise HTTPException(status_code=400, detail=f"Expected status 'pending_finance', got '{pr.status}'")

    pr.status = "approved"
    pr.modified_by = current_user.id

    # Move the linked TR to outcome_active
    tr = db.query(TestingRequest).filter(TestingRequest.id == pr.testing_request_id).first()
    if tr:
        tr.status = TestingRequestStatus.outcome_active
        tr.modified_by = current_user.id

    db.commit()

    # Notify originator / tester that procurement was approved
    if tr:
        try:
            from services.notification_service import NotificationService
            notes = data.dict(exclude_unset=True).get("description", "")
            NotificationService(db).notify_procurement_decision(
                tr, pr.procurement_number, decision="approved", notes=notes
            )
        except Exception as _n:
            print(f"[WARN] procurement_decision (approved) notification failed: {_n}")

    return {"message": "Procurement approved", "procurement_number": pr.procurement_number, "status": "approved"}


@router.put("/{procurement_id}/finance-reject")
def finance_reject(
    procurement_id: UUID,
    data: ProcurementRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Finance Approver rejects a replacement procurement request.

    Side effects:
    • ProcurementRequest.status  → rejected
    • TestingRequest.status      → under_review (Tester revises recommendation)
    • Recommendation.approval_status → pending (allow resubmit)
    """
    from models import ProcurementRequest, Recommendation, TestingRequest, TestingRequestStatus

    pr = db.query(ProcurementRequest).filter(ProcurementRequest.id == procurement_id).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Procurement request not found")
    if pr.status != "pending_finance":
        raise HTTPException(status_code=400, detail=f"Expected status 'pending_finance', got '{pr.status}'")

    notes = data.dict(exclude_unset=True).get("description", "Finance rejected")

    pr.status = "rejected"
    pr.modified_by = current_user.id

    # Move TR back to under_review so tester can revise next_action
    tr = db.query(TestingRequest).filter(TestingRequest.id == pr.testing_request_id).first()
    if tr:
        tr.status = TestingRequestStatus.under_review
        tr.rejection_reason = notes
        tr.modified_by = current_user.id

    # Re-open the recommendation so tester can resubmit
    if pr.recommendation_id:
        rec = db.query(Recommendation).filter(Recommendation.id == pr.recommendation_id).first()
        if rec:
            rec.approval_status = "pending"
            rec.approval_notes = notes
            rec.modified_by = current_user.id

    db.commit()

    # Notify the tester that their procurement was rejected and needs revision
    if tr:
        try:
            from services.notification_service import NotificationService
            NotificationService(db).notify_procurement_decision(
                tr, pr.procurement_number, decision="rejected", notes=notes
            )
        except Exception as _n:
            print(f"[WARN] procurement_decision (rejected) notification failed: {_n}")

    return {"message": "Procurement rejected — returned to tester for revision",
            "procurement_number": pr.procurement_number, "status": "rejected"}
