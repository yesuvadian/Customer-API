from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from auth_utils import get_current_user
from database import get_db

from schemas import RepairWorkflowCreate, RepairWorkflowResponse
from services.repair_workflow_service import RepairWorkflowService

router = APIRouter(
    prefix="/repair-workflows",
    tags=["repair-workflows"],
    dependencies=[Depends(get_current_user)]
)

@router.post("/")
def create(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    service = RepairWorkflowService(db)
    try:
        return service.create_workflow(payload["testing_request_id"], user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    
@router.get("/{workflow_id}/current-form")
def current_form(workflow_id: UUID, db: Session = Depends(get_db)):
    service = RepairWorkflowService(db)
    return service.get_current_form(workflow_id)

@router.get("/{workflow_id}", response_model=RepairWorkflowResponse)
def get_workflow(workflow_id: UUID, db: Session = Depends(get_db)):
    service = RepairWorkflowService(db)
    try:
        return service.get_workflow(workflow_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
@router.post("/{workflow_id}/stage/{stage_id}")
def save_stage(workflow_id: UUID, stage_id: UUID, payload: dict,
               db: Session = Depends(get_db), user=Depends(get_current_user)):
    service = RepairWorkflowService(db)
    return service.save_stage_data(workflow_id, stage_id, payload.get("form_data"), user.id)



@router.post("/{workflow_id}/advance")
def advance(workflow_id: UUID, db: Session = Depends(get_db), user=Depends(get_current_user)):
    service = RepairWorkflowService(db)
    return service.advance_stage(workflow_id, user.id)


@router.post("/{workflow_id}/reject")
def reject(workflow_id: UUID, db: Session = Depends(get_db), user=Depends(get_current_user)):
    service = RepairWorkflowService(db)
    try:
        return service.reject_stage(workflow_id, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.get("/{workflow_id}/timeline")
def timeline(workflow_id: UUID, db: Session = Depends(get_db)):
    service = RepairWorkflowService(db)
    return service.get_timeline(workflow_id)

@router.get("/{workflow_id}/progress")
def get_progress(workflow_id: UUID, db: Session = Depends(get_db)):
    service = RepairWorkflowService(db)
    return service.get_progress(workflow_id)