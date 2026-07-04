from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.precommission_service import PreCommissionService

router = APIRouter(
    prefix="/precommission",
    tags=["precommission"],
    dependencies=[Depends(get_current_user)],
)


class PreCommissionRequestCreate(BaseModel):
    vendor_name:                str
    purchase_order_number:      str
    dept_id:                    Optional[UUID]  = None
    po_date:                    Optional[str]   = None
    rated_mva:                  Optional[float] = None
    voltage_class:              Optional[str]   = None
    transformer_type:           Optional[str]   = None   # Two-winding / Three-winding / Auto
    cooling_class:              Optional[str]   = None   # ONAN / ONAF / OFAF / ODAF
    vector_group:               Optional[str]   = None   # e.g. YNyn0d11
    quantity:                   Optional[int]   = 1
    factory_location:           Optional[str]   = None
    proposed_inspection_date:   Optional[str]   = None
    equipment_type_id:          Optional[int]   = None
    remarks:                    Optional[str]   = None


class ApprovalRequest(BaseModel):
    notes: Optional[str] = None


class LinkEquipmentRequest(BaseModel):
    equipment_id: UUID


class StageSaveRequest(BaseModel):
    stage_id:  UUID
    form_data: dict


class StageAdvanceRequest(BaseModel):
    action:  str            # "approve" | "reject"
    remarks: Optional[str] = None


# ── Request CRUD ──────────────────────────────────────────────────────────────

@router.post("/requests")
def create_request(
    payload: PreCommissionRequestCreate,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).create_request(payload.dict(), user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/config/ensure")
def ensure_config(
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Idempotently seed PRE_COMMISSION stage role mappings for this org."""
    try:
        from seed_precommission_workflow import seed_precommission_role_mappings
        seeded = seed_precommission_role_mappings(db, user.organization_id)
        return {"message": "Pre-commission configuration ready", "role_mappings_upserted": seeded}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/requests/unlinked")
def list_unlinked_requests(
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Returns approved PCR requests that have no equipment linked yet.
    Used to populate the optional PCR dropdown during equipment registration.
    """
    try:
        return PreCommissionService(db).list_unlinked(user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/requests")
def list_requests(
    approval_status: Optional[str] = Query(None, description="pending | approved | rejected | all"),
    department_id:   Optional[UUID] = Query(None),
    skip:  int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return PreCommissionService(db).list_requests(
        user, approval_status=approval_status,
        department_id=department_id, skip=skip, limit=limit,
    )


@router.get("/requests/{request_id}")
def get_request(
    request_id: UUID,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).get_request(request_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Approval ──────────────────────────────────────────────────────────────────

@router.post("/requests/{request_id}/approve")
def approve_request(
    request_id: UUID,
    payload: ApprovalRequest,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).approve_request(request_id, payload.notes, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/requests/{request_id}/reject")
def reject_request(
    request_id: UUID,
    payload: ApprovalRequest,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).reject_request(request_id, payload.notes, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Equipment link ────────────────────────────────────────────────────────────

@router.post("/requests/{request_id}/link-equipment")
def link_equipment(
    request_id: UUID,
    payload: LinkEquipmentRequest,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).link_equipment(request_id, payload.equipment_id, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Stage workflow pass-through ───────────────────────────────────────────────

@router.get("/requests/{request_id}/form")
def current_form(
    request_id: UUID,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).current_form(request_id, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/requests/{request_id}/save")
def save_stage(
    request_id: UUID,
    payload: StageSaveRequest,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).save_stage(request_id, payload.stage_id, payload.form_data, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/requests/{request_id}/advance")
def advance_stage(
    request_id: UUID,
    payload: StageAdvanceRequest,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).advance_stage(request_id, payload.action, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/requests/{request_id}/timeline")
def timeline(
    request_id: UUID,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).timeline(request_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/requests/{request_id}/actions")
def available_actions(
    request_id: UUID,
    db:   Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return PreCommissionService(db).available_actions(request_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))
