from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from schemas import (
    RepairWorkflowStartRequest,
    RepairWorkflowResponse,
    RepairAdvanceRequest,
    RepairSaveDataRequest,
    RepairStageCreate,
    RepairStageUpdate,
    RepairRoleAssignment,
    RepairTransitionUpsert,
)
from services.repair_workflow_service import RepairWorkflowService

router = APIRouter(
    prefix="/repair-workflows",
    tags=["repair-workflows"],
    dependencies=[Depends(get_current_user)],
)

# ---------------------------------------------------------------------------
# Admin Config Routes   (/repair-workflows/config/...)
# ---------------------------------------------------------------------------

@router.get("/config/stages")
def list_stages(db: Session = Depends(get_db)):
    """List all stage definitions with template, roles, and transitions."""
    svc = RepairWorkflowService(db)
    return svc.list_stages()


@router.post("/config/stages")
def create_stage(payload: RepairStageCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Create a new stage definition."""
    svc = RepairWorkflowService(db)
    return svc.create_stage(payload.dict(), user.id)


@router.put("/config/stages/reorder")
def reorder_stages(items: List[dict], db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Bulk reorder stages. Body: [{id, sequence}, ...]"""
    svc = RepairWorkflowService(db)
    svc.reorder_stages(items, user.id)
    return {"message": "Reordered successfully"}


@router.put("/config/stages/{stage_id}")
def update_stage(stage_id: UUID, payload: RepairStageUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Update a stage definition."""
    svc = RepairWorkflowService(db)
    try:
        return svc.update_stage(stage_id, payload.dict(exclude_none=True), user.id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/config/stages/{stage_id}/template")
def set_stage_template(stage_id: UUID, payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Assign a template to a stage. Body: {template_id: UUID}"""
    svc = RepairWorkflowService(db)
    try:
        svc.set_stage_template(stage_id, payload["template_id"], user.id)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return {"message": "Template assigned"}


@router.put("/config/stages/{stage_id}/roles")
def set_stage_roles(stage_id: UUID, roles: List[RepairRoleAssignment], db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Replace all role assignments for a stage."""
    svc = RepairWorkflowService(db)
    svc.set_stage_roles(stage_id, [r.dict() for r in roles], user.id)
    return {"message": "Roles updated"}


@router.get("/config/transitions")
def list_transitions(db: Session = Depends(get_db)):
    """List all stage transitions."""
    svc = RepairWorkflowService(db)
    return svc.list_transitions()


@router.put("/config/transitions")
def upsert_transitions(transitions: List[RepairTransitionUpsert], db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Bulk upsert stage transitions."""
    svc = RepairWorkflowService(db)
    svc.upsert_transitions([t.dict() for t in transitions], user.id)
    return {"message": "Transitions updated"}


# ---------------------------------------------------------------------------
# Workflow Execution Routes   (/repair-workflows/...)
# ---------------------------------------------------------------------------

@router.post("/start")
def start_workflow(payload: RepairWorkflowStartRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Start a new repair workflow for a piece of equipment."""
    svc = RepairWorkflowService(db)
    try:
        wf = svc.start_workflow(payload.equipment_id, user.id)
        return wf
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
def list_workflows(
    equipment_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List workflows with optional filters."""
    svc = RepairWorkflowService(db)
    return svc.list_workflows(equipment_id=equipment_id, status=status, skip=skip, limit=limit)


@router.get("/{workflow_id}/current-form")
def current_form(workflow_id: UUID, db: Session = Depends(get_db)):
    """Get the current stage form template and saved data."""
    svc = RepairWorkflowService(db)
    try:
        return svc.get_current_form(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}/timeline")
def timeline(workflow_id: UUID, db: Session = Depends(get_db)):
    """Full audit trail for the workflow."""
    svc = RepairWorkflowService(db)
    return svc.get_timeline(workflow_id)


@router.get("/{workflow_id}/progress")
def get_progress(workflow_id: UUID, db: Session = Depends(get_db)):
    """Current stage, progress percentage, and status."""
    svc = RepairWorkflowService(db)
    try:
        return svc.get_progress(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}")
def get_workflow(workflow_id: UUID, db: Session = Depends(get_db)):
    """Full workflow detail including all stage instances."""
    svc = RepairWorkflowService(db)
    try:
        return svc.get_workflow_detail(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{workflow_id}/stages/{stage_id}/save")
def save_stage(
    workflow_id: UUID,
    stage_id: UUID,
    payload: RepairSaveDataRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Save form data for a stage."""
    svc = RepairWorkflowService(db)
    try:
        return svc.save_stage_data(workflow_id, stage_id, payload.form_data, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{workflow_id}/stages/{stage_id}/upload")
async def upload_stage_file(
    workflow_id: UUID,
    stage_id: UUID,
    field_key: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload a file for a specific field in a stage."""
    svc = RepairWorkflowService(db)
    try:
        file_bytes = await file.read()
        return svc.upload_stage_file(
            workflow_id=workflow_id,
            stage_id=stage_id,
            field_key=field_key,
            file_name=file.filename,
            file_bytes=file_bytes,
            mime_type=file.content_type,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{workflow_id}/advance")
def advance(workflow_id: UUID, payload: RepairAdvanceRequest = RepairAdvanceRequest(), db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Approve current stage and advance to next."""
    svc = RepairWorkflowService(db)
    try:
        return svc.advance_stage(workflow_id, payload.remarks, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{workflow_id}/reject")
def reject(workflow_id: UUID, payload: RepairAdvanceRequest = RepairAdvanceRequest(), db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Reject current stage and move back to previous."""
    svc = RepairWorkflowService(db)
    try:
        return svc.reject_stage(workflow_id, payload.remarks, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
