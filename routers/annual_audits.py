from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.annual_audit_service import AnnualAuditService


router = APIRouter(
    prefix="/annual-audits",
    tags=["annual-audits"],
    dependencies=[Depends(get_current_user)],
)


class AnnualInspectionCreate(BaseModel):
    substation_id: UUID
    inspection_date: date
    inspected_by: Optional[UUID] = None
    remarks: Optional[str] = None


class AnnualObservationCreate(BaseModel):
    category_detail_id: int
    severity: Optional[str] = None
    target_compliance_date: Optional[date] = None
    observation_description: Optional[str] = None


class AnnualStageSaveRequest(BaseModel):
    form_data: dict


class AnnualAssignRequest(BaseModel):
    assign_to_user_id: UUID


class AnnualStageActionRequest(BaseModel):
    remarks: Optional[str] = None


@router.post("/config/ensure")
def ensure_config(db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        AnnualAuditService(db).ensure_configuration(user.organization_id)
        return {"message": "Annual Audit configuration ready"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/inspections")
def create_inspection(
    payload: AnnualInspectionCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).create_inspection(payload.dict(), user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/inspections")
def list_inspections(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return AnnualAuditService(db).list_inspections(user, skip=skip, limit=limit)


@router.get("/inspections/{inspection_id}")
def get_inspection(
    inspection_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).get_inspection(inspection_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/inspections/{inspection_id}/observations")
def create_observation(
    inspection_id: UUID,
    payload: AnnualObservationCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).create_observation(inspection_id, payload.dict(), user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/observations")
def list_observations(
    status: str = Query("all"),
    assigned_to_me: bool = Query(False),
    overdue: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return AnnualAuditService(db).list_observations(
        user,
        status=status,
        assigned_to_me=assigned_to_me,
        overdue=overdue,
        skip=skip,
        limit=limit,
    )


@router.get("/observations/{observation_id}")
def get_observation(
    observation_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).get_observation(observation_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/observations/{observation_id}/current-form")
def current_form(
    observation_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).current_form(observation_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/observations/{observation_id}/timeline")
def timeline(
    observation_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).timeline(observation_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/observations/{observation_id}/available-actions")
def available_actions(
    observation_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).available_actions(observation_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/assignment-queue")
def assignment_queue(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return AnnualAuditService(db).assignment_queue(user)


@router.get("/observations/{observation_id}/stages/{stage_id}/eligible-users")
def eligible_users(
    observation_id: UUID,
    stage_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).eligible_users(observation_id, stage_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/observations/{observation_id}/stages/{stage_id}/assign")
def assign_stage(
    observation_id: UUID,
    stage_id: UUID,
    payload: AnnualAssignRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).assign_stage(
            observation_id, stage_id, payload.assign_to_user_id, user
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/observations/{observation_id}/stages/{stage_id}/save")
def save_stage(
    observation_id: UUID,
    stage_id: UUID,
    payload: AnnualStageSaveRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).save_stage(observation_id, stage_id, payload.form_data, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/observations/{observation_id}/stages/{stage_id}/submit")
def submit_stage(
    observation_id: UUID,
    stage_id: UUID,
    payload: AnnualStageActionRequest = AnnualStageActionRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).submit_stage(observation_id, stage_id, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/observations/{observation_id}/stages/{stage_id}/approve")
def approve_stage(
    observation_id: UUID,
    stage_id: UUID,
    payload: AnnualStageActionRequest = AnnualStageActionRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).approve_stage(observation_id, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/observations/{observation_id}/stages/{stage_id}/reject")
def reject_stage(
    observation_id: UUID,
    stage_id: UUID,
    payload: AnnualStageActionRequest = AnnualStageActionRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return AnnualAuditService(db).reject_stage(observation_id, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return AnnualAuditService(db).dashboard(user)


@router.post("/sla/run-overdue-check")
def run_overdue_check(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return AnnualAuditService(db).run_overdue_check(user)
