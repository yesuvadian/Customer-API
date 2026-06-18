"""
Workflow Configuration API

CRUD endpoints for managing workflow stage definitions, role permissions,
and approve/reject transition graphs for all five workflow types.

Access: super_admin usertype only (enforced via require_super_admin dependency).
"""
from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    OrgRole,
    OrgTestTemplate,
    RepairStageDefinition,
    RepairStageRole,
    RepairStageTemplate,
    RepairStageTransition,
    RepairWorkflowDefinition,
    User,
)
from schemas_workflow_config import (
    ReorderRequest,
    RoleOption,
    StagePatch,
    StageCreate,
    StageOut,
    StageRoleOut,
    StageRolesReplace,
    TemplateOption,
    TransitionOut,
    TransitionUpsert,
    WorkflowCreate,
    WorkflowOut,
    WorkflowPatch,
)

router = APIRouter(prefix="/workflow-config", tags=["Workflow Configuration"])


# ---------------------------------------------------------------------------
# Auth guard — super_admin only
# ---------------------------------------------------------------------------

def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if getattr(current_user, "usertype", None) != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workflow configuration requires super_admin access.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_stage_out(stage: RepairStageDefinition, db: Session) -> StageOut:
    # Roles
    stage_roles = db.query(RepairStageRole).filter_by(stage_id=stage.id).all()
    role_ids = [sr.role_id for sr in stage_roles]
    org_roles = {r.id: r for r in db.query(OrgRole).filter(OrgRole.id.in_(role_ids)).all()}

    roles_out = [
        StageRoleOut(
            role_id=sr.role_id,
            role_name=org_roles[sr.role_id].name if sr.role_id in org_roles else "Unknown",
            can_edit=sr.can_edit,
            can_approve=sr.can_approve,
            can_assign=sr.can_assign,
        )
        for sr in stage_roles
    ]

    # Transitions
    approve_t = (
        db.query(RepairStageTransition)
        .filter_by(from_stage_id=stage.id, action="approve")
        .first()
    )
    reject_t = (
        db.query(RepairStageTransition)
        .filter_by(from_stage_id=stage.id, action="reject")
        .first()
    )
    transitions_out = TransitionOut(
        approve_to_stage_id=approve_t.to_stage_id if approve_t else None,
        reject_to_stage_id=reject_t.to_stage_id if reject_t else None,
    )

    # Template
    stage_tmpl = (
        db.query(RepairStageTemplate).filter_by(stage_id=stage.id).first()
    )
    template_key = None
    if stage_tmpl and stage_tmpl.template_id:
        tmpl = db.query(OrgTestTemplate).filter_by(id=stage_tmpl.template_id).first()
        template_key = tmpl.template_key if tmpl else None

    return StageOut(
        id=stage.id,
        name=stage.name,
        code=stage.code,
        sequence=stage.sequence,
        weight=stage.weight,
        is_active=stage.is_active,
        is_mandatory=stage.is_mandatory,
        default_duration_days=stage.default_duration_days,
        workflow_definition_id=stage.workflow_definition_id,
        template_id=stage_tmpl.template_id if stage_tmpl else None,
        template_key=template_key,
        roles=roles_out,
        transitions=transitions_out,
    )


# ---------------------------------------------------------------------------
# Workflow endpoints
# ---------------------------------------------------------------------------

@router.get("/workflows", response_model=List[WorkflowOut])
def list_workflows(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    workflows = db.query(RepairWorkflowDefinition).order_by(RepairWorkflowDefinition.name).all()
    result = []
    for wf in workflows:
        stage_count = (
            db.query(RepairStageDefinition)
            .filter_by(workflow_definition_id=wf.id, is_active=True)
            .count()
        )
        result.append(WorkflowOut(
            id=wf.id,
            workflow_code=wf.workflow_code,
            name=wf.name,
            is_active=wf.is_active,
            stage_count=stage_count,
        ))
    return result


@router.post("/workflows", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
def create_workflow(
    body: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    existing = db.query(RepairWorkflowDefinition).filter_by(workflow_code=body.workflow_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="workflow_code already exists.")

    wf = RepairWorkflowDefinition(
        id=uuid4(),
        workflow_code=body.workflow_code,
        name=body.name,
        is_active=True,
        created_by=current_user.id,
        modified_by=current_user.id,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return WorkflowOut(id=wf.id, workflow_code=wf.workflow_code, name=wf.name, is_active=wf.is_active, stage_count=0)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def patch_workflow(
    workflow_id: UUID,
    body: WorkflowPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    wf = db.query(RepairWorkflowDefinition).filter_by(id=workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if body.name is not None:
        wf.name = body.name
    if body.is_active is not None:
        wf.is_active = body.is_active
    wf.modified_by = current_user.id

    db.commit()
    db.refresh(wf)

    stage_count = (
        db.query(RepairStageDefinition)
        .filter_by(workflow_definition_id=wf.id, is_active=True)
        .count()
    )
    return WorkflowOut(id=wf.id, workflow_code=wf.workflow_code, name=wf.name, is_active=wf.is_active, stage_count=stage_count)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    wf = db.query(RepairWorkflowDefinition).filter_by(id=workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    active_stage_count = (
        db.query(RepairStageDefinition)
        .filter_by(workflow_definition_id=workflow_id, is_active=True)
        .count()
    )
    if active_stage_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete workflow with {active_stage_count} active stage(s). Deactivate or remove all stages first.",
        )

    db.delete(wf)
    db.commit()


# ---------------------------------------------------------------------------
# Stage endpoints
# ---------------------------------------------------------------------------

@router.get("/workflows/{workflow_id}/stages", response_model=List[StageOut])
def list_stages(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    stages = (
        db.query(RepairStageDefinition)
        .filter_by(workflow_definition_id=workflow_id)
        .order_by(RepairStageDefinition.sequence)
        .all()
    )
    return [_build_stage_out(s, db) for s in stages]


@router.post("/workflows/{workflow_id}/stages", response_model=StageOut, status_code=status.HTTP_201_CREATED)
def create_stage(
    workflow_id: UUID,
    body: StageCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    wf = db.query(RepairWorkflowDefinition).filter_by(id=workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if db.query(RepairStageDefinition).filter_by(code=body.code).first():
        raise HTTPException(status_code=400, detail=f"Stage code '{body.code}' already exists.")

    stage = RepairStageDefinition(
        id=uuid4(),
        name=body.name,
        code=body.code,
        sequence=body.sequence,
        weight=body.weight,
        is_active=True,
        is_mandatory=body.is_mandatory,
        default_duration_days=body.default_duration_days,
        workflow_definition_id=workflow_id,
    )
    db.add(stage)
    db.flush()

    if body.template_id:
        db.add(RepairStageTemplate(
            id=uuid4(),
            stage_id=stage.id,
            template_id=body.template_id,
        ))

    db.commit()
    db.refresh(stage)
    return _build_stage_out(stage, db)


@router.patch("/stages/{stage_id}", response_model=StageOut)
def patch_stage(
    stage_id: UUID,
    body: StagePatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    stage = db.query(RepairStageDefinition).filter_by(id=stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found.")

    for field in ("name", "sequence", "weight", "is_active", "is_mandatory", "default_duration_days"):
        val = getattr(body, field)
        if val is not None:
            setattr(stage, field, val)

    if body.remove_template:
        db.query(RepairStageTemplate).filter_by(stage_id=stage_id).delete()
    elif body.template_id is not None:
        existing_tmpl = db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if existing_tmpl:
            existing_tmpl.template_id = body.template_id
        else:
            db.add(RepairStageTemplate(id=uuid4(), stage_id=stage_id, template_id=body.template_id))

    db.commit()
    db.refresh(stage)
    return _build_stage_out(stage, db)


@router.delete("/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stage(
    stage_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    stage = db.query(RepairStageDefinition).filter_by(id=stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found.")
    db.delete(stage)
    db.commit()


@router.post("/stages/reorder", status_code=status.HTTP_204_NO_CONTENT)
def reorder_stages(
    body: ReorderRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    ids = [item.stage_id for item in body.stages]
    stages = {s.id: s for s in db.query(RepairStageDefinition).filter(RepairStageDefinition.id.in_(ids)).all()}

    for item in body.stages:
        if item.stage_id in stages:
            stages[item.stage_id].sequence = item.sequence

    db.commit()


# ---------------------------------------------------------------------------
# Stage role permissions
# ---------------------------------------------------------------------------

@router.get("/stages/{stage_id}/roles", response_model=List[StageRoleOut])
def get_stage_roles(
    stage_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    stage_roles = db.query(RepairStageRole).filter_by(stage_id=stage_id).all()
    role_ids = [sr.role_id for sr in stage_roles]
    org_roles = {r.id: r for r in db.query(OrgRole).filter(OrgRole.id.in_(role_ids)).all()}

    return [
        StageRoleOut(
            role_id=sr.role_id,
            role_name=org_roles[sr.role_id].name if sr.role_id in org_roles else "Unknown",
            can_edit=sr.can_edit,
            can_approve=sr.can_approve,
            can_assign=sr.can_assign,
        )
        for sr in stage_roles
    ]


@router.put("/stages/{stage_id}/roles", response_model=List[StageRoleOut])
def replace_stage_roles(
    stage_id: UUID,
    body: StageRolesReplace,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    if not db.query(RepairStageDefinition).filter_by(id=stage_id).first():
        raise HTTPException(status_code=404, detail="Stage not found.")

    db.query(RepairStageRole).filter_by(stage_id=stage_id).delete()

    role_ids = [item.role_id for item in body.roles]
    org_roles = {r.id: r for r in db.query(OrgRole).filter(OrgRole.id.in_(role_ids)).all()}

    result = []
    for item in body.roles:
        sr = RepairStageRole(
            id=uuid4(),
            stage_id=stage_id,
            role_id=item.role_id,
            can_edit=item.can_edit,
            can_approve=item.can_approve,
            can_assign=item.can_assign,
        )
        db.add(sr)
        result.append(StageRoleOut(
            role_id=item.role_id,
            role_name=org_roles[item.role_id].name if item.role_id in org_roles else "Unknown",
            can_edit=item.can_edit,
            can_approve=item.can_approve,
            can_assign=item.can_assign,
        ))

    db.commit()
    return result


# ---------------------------------------------------------------------------
# Stage transitions
# ---------------------------------------------------------------------------

@router.get("/stages/{stage_id}/transitions", response_model=TransitionOut)
def get_stage_transitions(
    stage_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    approve_t = db.query(RepairStageTransition).filter_by(from_stage_id=stage_id, action="approve").first()
    reject_t = db.query(RepairStageTransition).filter_by(from_stage_id=stage_id, action="reject").first()
    return TransitionOut(
        approve_to_stage_id=approve_t.to_stage_id if approve_t else None,
        reject_to_stage_id=reject_t.to_stage_id if reject_t else None,
    )


@router.put("/stages/{stage_id}/transitions", response_model=TransitionOut)
def upsert_stage_transitions(
    stage_id: UUID,
    body: TransitionUpsert,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    if not db.query(RepairStageDefinition).filter_by(id=stage_id).first():
        raise HTTPException(status_code=404, detail="Stage not found.")

    for action, to_id in [("approve", body.approve_to_stage_id), ("reject", body.reject_to_stage_id)]:
        existing = db.query(RepairStageTransition).filter_by(from_stage_id=stage_id, action=action).first()
        if existing:
            existing.to_stage_id = to_id
        else:
            db.add(RepairStageTransition(
                id=uuid4(),
                from_stage_id=stage_id,
                to_stage_id=to_id,
                action=action,
            ))

    db.commit()
    return TransitionOut(
        approve_to_stage_id=body.approve_to_stage_id,
        reject_to_stage_id=body.reject_to_stage_id,
    )


# ---------------------------------------------------------------------------
# Lookup pickers
# ---------------------------------------------------------------------------

@router.get("/available-roles", response_model=List[RoleOption])
def available_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    roles = db.query(OrgRole).filter_by(is_active=True).order_by(OrgRole.name).all()
    return [RoleOption(id=r.id, name=r.name) for r in roles]


@router.get("/available-templates", response_model=List[TemplateOption])
def available_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    templates = db.query(OrgTestTemplate).order_by(OrgTestTemplate.template_key).all()
    return [TemplateOption(id=t.id, template_key=t.template_key) for t in templates]
