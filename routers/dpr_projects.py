from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.dpr_project_service import DprProjectService


router = APIRouter(
    prefix="/dpr-projects",
    tags=["dpr-projects"],
    dependencies=[Depends(get_current_user)],
)


class DprProjectCreate(BaseModel):
    title: str
    description: Optional[str] = None
    project_category: Optional[str] = None
    proposing_department_id: Optional[UUID] = None
    equipment_id: Optional[UUID] = None
    estimated_cost: Optional[float] = None


class DprStageSaveRequest(BaseModel):
    form_data: dict


class DprAssignRequest(BaseModel):
    assign_to_user_id: UUID


class DprStageActionRequest(BaseModel):
    remarks: Optional[str] = None


@router.post("")
def create_project(
    payload: DprProjectCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).create_project(payload.dict(), user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
def list_projects(
    status: str = Query("all"),
    stage_code: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return DprProjectService(db).list_projects(
        user, status=status, stage_code=stage_code, skip=skip, limit=limit
    )


@router.get("/{project_id}")
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).get_project(project_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{project_id}/current-form")
def current_form(
    project_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).current_form(project_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{project_id}/timeline")
def timeline(
    project_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).timeline(project_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{project_id}/available-actions")
def available_actions(
    project_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).available_actions(project_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{project_id}/stages/{stage_id}/eligible-users")
def eligible_users(
    project_id: UUID,
    stage_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).eligible_users(project_id, stage_id, user)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{project_id}/stages/{stage_id}/assign")
def assign_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: DprAssignRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).assign_stage(
            project_id, stage_id, payload.assign_to_user_id, user
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/stages/{stage_id}/save")
def save_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: DprStageSaveRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).save_stage(project_id, stage_id, payload.form_data, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/stages/{stage_id}/submit")
def submit_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: DprStageActionRequest = DprStageActionRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).submit_stage(project_id, stage_id, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/stages/{stage_id}/approve")
def approve_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: DprStageActionRequest = DprStageActionRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).approve_stage(project_id, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/stages/{stage_id}/reject")
def reject_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: DprStageActionRequest = DprStageActionRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return DprProjectService(db).reject_stage(project_id, payload.remarks, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
