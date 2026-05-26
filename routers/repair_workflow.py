from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import RepairWorkflow
from schemas import (
    RepairWorkflowStartRequest,
    RepairWorkflowResponse,
    RepairAdvanceRequest,
    RepairAssignRequest,
    RepairCancelRequest,
    RepairSaveDataRequest,
    RepairSubmitRequest,
    RepairStageCreate,
    RepairStageUpdate,
    RepairRoleAssignment,
    RepairTransitionUpsert,
)
from services.repair_workflow_service import RepairWorkflowService
from services.repair_timeliness_service import RepairTimelinessService

router = APIRouter(
    prefix="/repair-workflows",
    tags=["repair-workflows"],
    dependencies=[Depends(get_current_user)],
)

# =============================================================================
# Admin Config   — module: repair-workflows  |  HTTP method drives privilege
# =============================================================================

@router.get("/config/stages")
def list_stages(db: Session = Depends(get_db)):
    """List all stage definitions with template, roles, and transitions."""
    return RepairWorkflowService(db).list_stages()


@router.post("/config/stages")
def create_stage(
    payload: RepairStageCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new stage definition. Requires org-admin role."""
    try:
        return RepairWorkflowService(db).create_stage(payload.dict(), user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/config/stages/reorder")
def reorder_stages(
    items: List[dict],
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Bulk reorder stages. Body: [{id, sequence}, ...]. Requires org-admin role."""
    try:
        RepairWorkflowService(db).reorder_stages(items, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": "Reordered successfully"}


@router.put("/config/stages/{stage_id}")
def update_stage(
    stage_id: UUID,
    payload: RepairStageUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a stage definition. Requires org-admin role."""
    try:
        return RepairWorkflowService(db).update_stage(
            stage_id, payload.dict(exclude_none=True), user.id
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/config/stages/{stage_id}")
def deactivate_stage(
    stage_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Soft-delete a stage (sets is_active=False). Requires org-admin role."""
    try:
        RepairWorkflowService(db).deactivate_stage(stage_id, user.id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"message": "Stage deactivated"}


@router.put("/config/stages/{stage_id}/template")
def set_stage_template(
    stage_id: UUID,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Assign a form template to a stage. Body: {template_id}. Requires org-admin role."""
    try:
        RepairWorkflowService(db).set_stage_template(
            stage_id, payload["template_id"], user.id
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return {"message": "Template assigned"}


@router.put("/config/stages/{stage_id}/roles")
def set_stage_roles(
    stage_id: UUID,
    roles: List[RepairRoleAssignment],
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Replace all role assignments for a stage. Requires org-admin role."""
    try:
        RepairWorkflowService(db).set_stage_roles(
            stage_id, [r.dict() for r in roles], user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": "Roles updated"}


@router.get("/config/transitions")
def list_transitions(db: Session = Depends(get_db)):
    """List all stage transitions."""
    return RepairWorkflowService(db).list_transitions()


@router.put("/config/transitions")
def upsert_transitions(
    transitions: List[RepairTransitionUpsert],
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Bulk upsert stage transitions. Requires org-admin role."""
    try:
        RepairWorkflowService(db).upsert_transitions(
            [t.dict() for t in transitions], user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": "Transitions updated"}


# =============================================================================
# Workflow Execution
# =============================================================================

@router.post("/start")
def start_workflow(
    payload: RepairWorkflowStartRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Start a new repair workflow for a piece of equipment."""
    try:
        return RepairWorkflowService(db).start_workflow(
    equipment_id=payload.equipment_id,
    user_id=user.id,
    source_failure_id=payload.source_failure_id,
)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/pending-assignments")
def pending_assignments(db: Session = Depends(get_db)):
    """
    All active workflows awaiting Workflow Coordinator assignment.
    Used by the coordinator's assignment queue page.
    """
    return RepairWorkflowService(db).list_pending_assignments()


@router.get("")
def list_workflows(
    equipment_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List repair workflows. Filter by equipment_id and/or status."""
    return RepairWorkflowService(db).list_workflows(
        equipment_id=equipment_id, status=status, skip=skip, limit=limit
    )


@router.get("/{workflow_id}/current-form")
def current_form(workflow_id: UUID, db: Session = Depends(get_db)):
    """Get the current stage form template and any previously saved data."""
    try:
        return RepairWorkflowService(db).get_current_form(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}/timeline")
def timeline(workflow_id: UUID, db: Session = Depends(get_db)):
    """Full audit trail — every action taken on this workflow in chronological order."""
    return RepairWorkflowService(db).get_timeline(workflow_id)


@router.get("/{workflow_id}/progress")
def get_progress(workflow_id: UUID, db: Session = Depends(get_db)):
    """Current stage, progress percentage, and overall workflow status."""
    try:
        return RepairWorkflowService(db).get_progress(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}/stages/{stage_id}/documents")
def list_stage_documents(
    workflow_id: UUID,
    stage_id: UUID,
    db: Session = Depends(get_db),
):
    """List all uploaded documents for a specific stage."""
    try:
        return RepairWorkflowService(db).list_stage_documents(workflow_id, stage_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}")
def get_workflow(workflow_id: UUID, db: Session = Depends(get_db)):
    """Full workflow detail including all stage instances and their status."""
    try:
        return RepairWorkflowService(db).get_workflow_detail(workflow_id)
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
    """
    Save form data for a stage.
    - Requires the caller's org role to be listed in RepairStageRole for this stage.
    - Runs template validation before persisting.
    """
    try:
        return RepairWorkflowService(db).save_stage_data(
            workflow_id, stage_id, payload.form_data, user.id
        )
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
    """
    Upload a file for a specific field in a stage.
    - Requires the caller's org role to be authorized for this stage.
    - Stores file in uploads/repair/ and records a RepairStageDocument row.
    - Patches form_data[field_key] with the document reference automatically.
    """
    try:
        file_bytes = await file.read()
        return RepairWorkflowService(db).upload_stage_file(
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


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: UUID, db: Session = Depends(get_db)):
    """Download a previously uploaded stage document by its document ID."""
    try:
        abs_path, file_name, mime_type = RepairWorkflowService(db).get_document_file(doc_id)
        return FileResponse(
            path=abs_path,
            filename=file_name,
            media_type=mime_type or "application/octet-stream",
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{workflow_id}/advance")
def advance(
    workflow_id: UUID,
    payload: RepairAdvanceRequest = RepairAdvanceRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Approve current stage and advance to the next.
    - Stage must be SUBMITTED. Requires can_approve on this stage.
    - Uses RepairStageTransition table only — no sequential fallback.
    - On final stage completion, sets equipment.status back to 'active'.
    """
    try:
        return RepairWorkflowService(db).advance_stage(workflow_id, payload.remarks, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{workflow_id}/reject")
def reject(
    workflow_id: UUID,
    payload: RepairAdvanceRequest = RepairAdvanceRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Reject current stage. Stage must be SUBMITTED. Uses RepairStageTransition table only.
    - Requires can_approve on this stage.
    """
    try:
        return RepairWorkflowService(db).reject_stage(workflow_id, payload.remarks, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{workflow_id}/stages/{stage_id}/assign")
def assign_stage_user(
    workflow_id: UUID,
    stage_id: UUID,
    payload: RepairAssignRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    WORKFLOW_COORDINATOR assigns a user to the current pending stage.
    Transitions stage: pending → assigned.
    """
    try:
        return RepairWorkflowService(db).assign_stage_user(
            workflow_id, stage_id, payload.assign_to_user_id, user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{workflow_id}/stages/{stage_id}/submit")
def submit_stage(
    workflow_id: UUID,
    stage_id: UUID,
    payload: RepairSubmitRequest = RepairSubmitRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Assigned user submits the stage after filling the form.
    Transitions stage: assigned → submitted.
    """
    try:
        return RepairWorkflowService(db).submit_stage(
            workflow_id, stage_id, payload.remarks, user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{workflow_id}/assignment-queue")
def get_assignment_queue(
    workflow_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Returns all assignment queue entries for a workflow.
    Workflow Coordinator uses this to see pending assignments.
    """
    try:
        return RepairWorkflowService(db).get_assignment_queue(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}/stages/{stage_id}/eligible-users")
def get_eligible_users(
    workflow_id: UUID,
    stage_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Returns users whose org role is authorised (can_edit) for this stage.
    Workflow Coordinator uses this to populate the assignment dialog.
    """
    try:
        return RepairWorkflowService(db).get_eligible_users(
    workflow_id,
    stage_id,
    current_user,
)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}/available-transitions")
def available_transitions(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Returns the set of actions the calling user can take on this workflow right now.
    Response: {can_assign, can_submit, can_approve, can_reject, can_cancel}
    """
    try:
        return RepairWorkflowService(db).get_available_transitions(workflow_id, user.id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{workflow_id}/cancel")
def cancel_workflow(
    workflow_id: UUID,
    payload: RepairCancelRequest = RepairCancelRequest(),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Cancel an active workflow. Only the workflow creator or an org-admin can cancel.
    """
    try:
        return RepairWorkflowService(db).cancel_workflow(workflow_id, user.id, payload.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


# =============================================================================
# Timeliness & Delay Attribution
# =============================================================================

@router.get("/{workflow_id}/timeliness")
def get_timeliness(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Timeliness summary for a workflow.

    Returns per-stage contracted_date, actual_date, delay_days, timeliness_status,
    delay attribution, and workflow-level total_vendor_delay_days.
    """
    try:
        return RepairTimelinessService(db).get_timeliness_summary(workflow_id)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/{workflow_id}/stages/{stage_instance_id}/attribute-delay")
def attribute_delay(
    workflow_id: UUID,
    stage_instance_id: UUID,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Officer records delay attribution for a completed stage that has delay_days > 0.

    Body:
    {
      "attribution": "vendor" | "kptcl",
      "reason": "Late delivery of core components"
    }

    Requires can_approve role on the stage or org-admin.
    """
    try:
        return RepairTimelinessService(db).record_delay_attribution(
            workflow_id, stage_instance_id, payload, user.id
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
