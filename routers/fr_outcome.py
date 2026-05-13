"""
fr_outcome.py
─────────────
Routes:
  GET  /fr-outcomes/{request_id}        — outcome log for a single FR
  POST /fr-outcomes/{request_id}/retry  — manually re-trigger outcome processing (admin only)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    FROutcomeLog,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    User,
)
from services.outcome_service import OutcomeService

router = APIRouter(
    prefix="/fr-outcomes",
    tags=["fr-outcomes"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ────────────────────────────────────────────────────────────────────

def _serialize_log(log: FROutcomeLog) -> dict:
    return {
        "id":                  str(log.id),
        "testing_request_id":  str(log.testing_request_id),
        "next_action":         log.next_action,
        "action_taken":        log.action_taken,
        "schedule_id":         str(log.schedule_id)        if log.schedule_id        else None,
        "child_request_id":    str(log.child_request_id)   if log.child_request_id   else None,
        "procurement_id":      str(log.procurement_id)     if log.procurement_id     else None,
        "error_message":       log.error_message,
        "processed_by":        str(log.processed_by)       if log.processed_by       else None,
        "cts":                 log.cts.isoformat()          if log.cts                else None,
    }


# ── GET outcome log ────────────────────────────────────────────────────────────

@router.get("/{request_id}")
def get_outcome_log(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the FR outcome processing log for a given TestingRequest.
    Useful for debugging why a schedule or ticket was/wasn't created.
    """
    req = db.query(TestingRequest).filter_by(id=request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.request_category != RequestCategory.failure_registry:
        raise HTTPException(
            status_code=400,
            detail="Outcome logs are only available for failure_registry requests",
        )

    logs = (
        db.query(FROutcomeLog)
        .filter_by(testing_request_id=request_id)
        .order_by(FROutcomeLog.cts.desc())
        .all()
    )
    return {
        "request_id":     str(request_id),
        "request_number": req.request_number,
        "status":         req.status.value,
        # "outcome_logs":   [_serialize_log(l) for l in logs],
    }


# ── POST retry (admin only) ────────────────────────────────────────────────────

@router.post("/{request_id}/retry", status_code=status.HTTP_200_OK)
def retry_outcome(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually re-trigger FR outcome processing.
    Only works if the FR is already approved.
    Restricted to Admin / SuperAdmin.
    """
    # Role guard
    from models import Role, UserRole
    user_roles = (
        db.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == current_user.id)
        .all()
    )
    role_names = {r[0] for r in user_roles}
    if not role_names.intersection({"Admin", "SuperAdmin"}):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin or SuperAdmin can retry FR outcome processing",
        )

    req = db.query(TestingRequest).filter_by(id=request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.request_category != RequestCategory.failure_registry:
        raise HTTPException(status_code=400, detail="Not a failure registry request")
    if req.status != TestingRequestStatus.approved:
        raise HTTPException(
            status_code=400,
            detail=f"Request must be approved to retry outcome. Current status: {req.status.value}",
        )

    svc = OutcomeService(db)
    result = svc.handle_fr_approval(req.id, current_user.id)
    return {
        "message": "Outcome processing completed",
        "result":  result,
    }