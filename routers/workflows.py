"""
Workflow Management API Router

Provides endpoints for creating and managing workflows, states, transitions,
and permission matrix entries.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Workflow,
    WorkflowState,
    WorkflowTransition,
    PermissionMatrix,
    WorkflowAuditLog,
    User
)
from schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowStateCreate,
    WorkflowStateUpdate,
    WorkflowStateResponse,
    WorkflowTransitionCreate,
    WorkflowTransitionUpdate,
    WorkflowTransitionResponse,
    PermissionMatrixCreate,
    PermissionMatrixUpdate,
    PermissionMatrixResponse,
    WorkflowFullDetail,
    AvailableTransitionResponse,
    PerformTransitionRequest,
    PerformTransitionResponse,
    WorkflowAuditLogResponse
)
from services.workflow_engine import IntegratedWorkflowEngine
from auth_utils import get_current_user

router = APIRouter(prefix="/workflows", tags=["Workflows"])


# ========================================
# WORKFLOW CRUD
# ========================================

@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workflow: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new workflow definition."""
    db_workflow = Workflow(
        name=workflow.name,
        description=workflow.description,
        workflow_type=workflow.workflow_type,
        organization_id=workflow.organization_id,
        is_active=workflow.is_active,
        version=workflow.version,
        created_by=current_user.id
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    return db_workflow


@router.get("/", response_model=List[WorkflowResponse])
def list_workflows(
    organization_id: Optional[UUID] = None,
    workflow_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all workflows with optional filters."""
    query = db.query(Workflow)

    if organization_id:
        query = query.filter(Workflow.organization_id == organization_id)

    if workflow_type:
        query = query.filter(Workflow.workflow_type == workflow_type)

    if is_active is not None:
        query = query.filter(Workflow.is_active == is_active)

    workflows = query.order_by(Workflow.cts.desc()).all()
    return workflows


@router.get("/{workflow_id}", response_model=WorkflowFullDetail)
def get_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a workflow with all its states, transitions, and permissions."""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    workflow: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a workflow's basic info."""
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not db_workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    if workflow.name is not None:
        db_workflow.name = workflow.name
    if workflow.description is not None:
        db_workflow.description = workflow.description
    if workflow.is_active is not None:
        db_workflow.is_active = workflow.is_active

    db.commit()
    db.refresh(db_workflow)
    return db_workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a workflow (cascades to states, transitions, permissions)."""
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not db_workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    db.delete(db_workflow)
    db.commit()
    return None


# ========================================
# WORKFLOW STATES
# ========================================

@router.post("/states", response_model=WorkflowStateResponse, status_code=status.HTTP_201_CREATED)
def create_state(
    state: WorkflowStateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new workflow state."""
    db_state = WorkflowState(
        workflow_id=state.workflow_id,
        state_code=state.state_code,
        state_name=state.state_name,
        description=state.description,
        state_type=state.state_type,
        color=state.color,
        icon=state.icon,
        display_order=state.display_order,
        is_active=state.is_active,
        created_by=current_user.id
    )
    db.add(db_state)
    db.commit()
    db.refresh(db_state)
    return db_state


@router.get("/states/{state_id}", response_model=WorkflowStateResponse)
def get_state(
    state_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a workflow state by ID."""
    state = db.query(WorkflowState).filter(WorkflowState.id == state_id).first()
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="State not found"
        )
    return state


@router.put("/states/{state_id}", response_model=WorkflowStateResponse)
def update_state(
    state_id: UUID,
    state: WorkflowStateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a workflow state."""
    db_state = db.query(WorkflowState).filter(WorkflowState.id == state_id).first()
    if not db_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="State not found"
        )

    for key, value in state.model_dump(exclude_unset=True).items():
        setattr(db_state, key, value)

    db.commit()
    db.refresh(db_state)
    return db_state


@router.delete("/states/{state_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_state(
    state_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a workflow state."""
    db_state = db.query(WorkflowState).filter(WorkflowState.id == state_id).first()
    if not db_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="State not found"
        )

    db.delete(db_state)
    db.commit()
    return None


# ========================================
# WORKFLOW TRANSITIONS
# ========================================

@router.post("/transitions", response_model=WorkflowTransitionResponse, status_code=status.HTTP_201_CREATED)
def create_transition(
    transition: WorkflowTransitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new workflow transition."""
    db_transition = WorkflowTransition(
        workflow_id=transition.workflow_id,
        from_state_id=transition.from_state_id,
        to_state_id=transition.to_state_id,
        transition_name=transition.transition_name,
        action_code=transition.action_code,
        description=transition.description,
        conditions=transition.conditions,
        button_label=transition.button_label,
        button_color=transition.button_color,
        icon=transition.icon,
        requires_comment=transition.requires_comment,
        display_order=transition.display_order,
        is_active=transition.is_active,
        created_by=current_user.id
    )
    db.add(db_transition)
    db.commit()
    db.refresh(db_transition)
    return db_transition


@router.get("/transitions/{transition_id}", response_model=WorkflowTransitionResponse)
def get_transition(
    transition_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a workflow transition by ID."""
    transition = db.query(WorkflowTransition).filter(
        WorkflowTransition.id == transition_id
    ).first()
    if not transition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transition not found"
        )
    return transition


@router.put("/transitions/{transition_id}", response_model=WorkflowTransitionResponse)
def update_transition(
    transition_id: UUID,
    transition: WorkflowTransitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a workflow transition."""
    db_transition = db.query(WorkflowTransition).filter(
        WorkflowTransition.id == transition_id
    ).first()
    if not db_transition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transition not found"
        )

    for key, value in transition.model_dump(exclude_unset=True).items():
        setattr(db_transition, key, value)

    db.commit()
    db.refresh(db_transition)
    return db_transition


@router.delete("/transitions/{transition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transition(
    transition_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a workflow transition."""
    db_transition = db.query(WorkflowTransition).filter(
        WorkflowTransition.id == transition_id
    ).first()
    if not db_transition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transition not found"
        )

    db.delete(db_transition)
    db.commit()
    return None


# ========================================
# PERMISSION MATRIX
# ========================================

@router.post("/permissions", response_model=PermissionMatrixResponse, status_code=status.HTTP_201_CREATED)
def create_permission(
    permission: PermissionMatrixCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new permission matrix entry."""
    db_permission = PermissionMatrix(
        workflow_id=permission.workflow_id,
        transition_id=permission.transition_id,
        role_id=permission.role_id,
        scope_type=permission.scope_type,
        department_type_id=permission.department_type_id,
        can_execute=permission.can_execute,
        can_view=permission.can_view,
        requires_approval=permission.requires_approval,
        conditions=permission.conditions,
        priority=permission.priority,
        is_active=permission.is_active,
        created_by=current_user.id
    )
    db.add(db_permission)
    db.commit()
    db.refresh(db_permission)
    return db_permission


@router.get("/permissions/{permission_id}", response_model=PermissionMatrixResponse)
def get_permission(
    permission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a permission matrix entry by ID."""
    permission = db.query(PermissionMatrix).filter(
        PermissionMatrix.id == permission_id
    ).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found"
        )
    return permission


@router.get("/permissions", response_model=List[PermissionMatrixResponse])
def list_permissions(
    workflow_id: Optional[UUID] = None,
    transition_id: Optional[UUID] = None,
    role_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List permissions with optional filters."""
    query = db.query(PermissionMatrix)

    if workflow_id:
        query = query.filter(PermissionMatrix.workflow_id == workflow_id)
    if transition_id:
        query = query.filter(PermissionMatrix.transition_id == transition_id)
    if role_id:
        query = query.filter(PermissionMatrix.role_id == role_id)

    permissions = query.all()
    return permissions


@router.put("/permissions/{permission_id}", response_model=PermissionMatrixResponse)
def update_permission(
    permission_id: UUID,
    permission: PermissionMatrixUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a permission matrix entry."""
    db_permission = db.query(PermissionMatrix).filter(
        PermissionMatrix.id == permission_id
    ).first()
    if not db_permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found"
        )

    for key, value in permission.model_dump(exclude_unset=True).items():
        setattr(db_permission, key, value)

    db.commit()
    db.refresh(db_permission)
    return db_permission


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_permission(
    permission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a permission matrix entry."""
    db_permission = db.query(PermissionMatrix).filter(
        PermissionMatrix.id == permission_id
    ).first()
    if not db_permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found"
        )

    db.delete(db_permission)
    db.commit()
    return None


# ========================================
# WORKFLOW EXECUTION
# ========================================

@router.get("/{workflow_id}/available-transitions", response_model=List[AvailableTransitionResponse])
def get_available_transitions(
    workflow_id: UUID,
    current_state_code: str,
    entity_department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available transitions for current user from a given state."""
    engine = IntegratedWorkflowEngine(db)

    # Get current state
    current_state = engine.get_state_by_code(workflow_id, current_state_code)
    if not current_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State '{current_state_code}' not found"
        )

    transitions = engine.get_available_transitions(
        workflow_id=workflow_id,
        current_state_id=current_state.id,
        user_id=current_user.id,
        entity_department_id=entity_department_id
    )

    return transitions


@router.post("/execute-transition", response_model=PerformTransitionResponse)
def execute_transition(
    request: PerformTransitionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Execute a workflow transition on an entity."""
    engine = IntegratedWorkflowEngine(db)

    # Get workflow by entity type
    workflow = engine.get_workflow_by_type(request.entity_type)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active workflow found for type '{request.entity_type}'"
        )

    # TODO: Get current state from entity (depends on entity type)
    # For now, this endpoint needs the current state passed separately
    # In a real implementation, you'd query the entity to get its current state

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="This endpoint needs to be integrated with entity-specific logic"
    )


# ========================================
# AUDIT LOG
# ========================================

@router.get("/audit-log/{entity_type}/{entity_id}", response_model=List[WorkflowAuditLogResponse])
def get_audit_log(
    entity_type: str,
    entity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get audit log for an entity."""
    engine = IntegratedWorkflowEngine(db)
    audit_logs = engine.get_audit_history(entity_type, entity_id)
    return audit_logs
