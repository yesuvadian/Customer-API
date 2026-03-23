"""
Integrated Workflow Engine Service

Combines workflow state management with hierarchical role-based permissions.
Handles state transitions, permission validation, and department scope checking.
"""

from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from fastapi import HTTPException, status

from models import (
    Workflow,
    WorkflowState,
    WorkflowTransition,
    PermissionMatrix,
    WorkflowAuditLog,
    User,
    UserRole,
    OrgRole,
    OrgDepartment
)


class IntegratedWorkflowEngine:
    """
    Integrated workflow engine that combines workflow state management
    with hierarchical role-based permission checking.
    """

    def __init__(self, db: Session):
        self.db = db

    # ========================================
    # 1. GET AVAILABLE TRANSITIONS
    # ========================================

    def get_available_transitions(
        self,
        workflow_id: UUID,
        current_state_id: UUID,
        user_id: UUID,
        entity_department_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all transitions available to a user from the current state.

        Args:
            workflow_id: The workflow UUID
            current_state_id: Current state UUID
            user_id: User performing the action
            entity_department_id: Department of the entity (for scope checking)

        Returns:
            List of available transitions with details
        """
        # Get user's active roles (check both old and new role systems)
        user_roles = []

        # Try old role system
        try:
            user_roles = self.db.query(UserRole).filter(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.is_active == True
                )
            ).all()
        except Exception as e:
            print(f"[INFO] Old role system not available in get_available_transitions: {e}")
            self.db.rollback()

        # Check new organization role system
        from models import OrgUserRole
        org_user_roles = self.db.query(OrgUserRole).filter(
            and_(
                OrgUserRole.user_id == user_id,
                OrgUserRole.is_active == True
            )
        ).all()

        if not user_roles and not org_user_roles:
            return []

        # Get all transitions from current state
        transitions = self.db.query(WorkflowTransition).filter(
            and_(
                WorkflowTransition.workflow_id == workflow_id,
                WorkflowTransition.from_state_id == current_state_id,
                WorkflowTransition.is_active == True
            )
        ).all()

        available = []
        for transition in transitions:
            # Check if user has permission for this transition
            has_permission = self._check_transition_permission(
                transition.id,
                user_roles,
                entity_department_id
            )

            if has_permission:
                to_state = self.db.query(WorkflowState).filter(
                    WorkflowState.id == transition.to_state_id
                ).first()

                available.append({
                    "transition_id": str(transition.id),
                    "transition_name": transition.transition_name,
                    "action_code": transition.action_code,
                    "to_state_code": to_state.state_code if to_state else None,
                    "to_state_name": to_state.state_name if to_state else None,
                    "button_label": transition.button_label or transition.transition_name,
                    "button_color": transition.button_color,
                    "icon": transition.icon,
                    "requires_comment": transition.requires_comment,
                })

        return available

    # ========================================
    # 2. CHECK TRANSITION PERMISSION
    # ========================================

    def _check_transition_permission(
        self,
        transition_id: UUID,
        user_roles: List[UserRole],
        entity_department_id: Optional[UUID] = None
    ) -> bool:
        """
        Check if user has permission to execute a transition.

        Args:
            transition_id: Transition UUID
            user_roles: User's active roles
            entity_department_id: Department of the entity

        Returns:
            True if user can execute transition
        """
        for user_role in user_roles:
            # Get permission entries for this transition and role
            permissions = self.db.query(PermissionMatrix).filter(
                and_(
                    PermissionMatrix.transition_id == transition_id,
                    PermissionMatrix.role_id == user_role.role_id,
                    PermissionMatrix.is_active == True,
                    PermissionMatrix.can_execute == True
                )
            ).order_by(PermissionMatrix.priority.desc()).all()

            for perm in permissions:
                # Check department scope
                if self._check_department_scope(
                    perm.scope_type,
                    user_role.department_id,
                    entity_department_id,
                    perm.department_type_id
                ):
                    return True

        return False

    # ========================================
    # 3. CHECK DEPARTMENT SCOPE
    # ========================================

    def _check_department_scope(
        self,
        scope_type: str,
        user_department_id: Optional[UUID],
        entity_department_id: Optional[UUID],
        required_department_type_id: Optional[UUID] = None
    ) -> bool:
        """
        Check if user's department scope covers the entity's department.

        Args:
            scope_type: 'exact', 'department_tree', 'organization', 'any'
            user_department_id: User's department
            entity_department_id: Entity's department
            required_department_type_id: Optional department type restriction

        Returns:
            True if user's scope covers entity
        """
        if scope_type == 'any':
            return True

        if scope_type == 'organization':
            # Can act on any department in the organization
            if not user_department_id or not entity_department_id:
                return True

            user_dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == user_department_id
            ).first()
            entity_dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == entity_department_id
            ).first()

            if user_dept and entity_dept:
                return user_dept.organization_id == entity_dept.organization_id

            return True

        if scope_type == 'exact':
            # Must be exact same department
            if not user_department_id or not entity_department_id:
                return False
            return user_department_id == entity_department_id

        if scope_type == 'department_tree':
            # User can act on their department and all child departments
            if not user_department_id or not entity_department_id:
                return False

            # Get user's department
            user_dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == user_department_id
            ).first()

            # Get entity's department
            entity_dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == entity_department_id
            ).first()

            if not user_dept or not entity_dept:
                return False

            # Check if entity department is in user's tree
            # Entity's hierarchy_path should start with user's hierarchy_path
            return entity_dept.hierarchy_path.startswith(user_dept.hierarchy_path)

        return False

    # ========================================
    # 4. VALIDATE TRANSITION
    # ========================================

    def validate_transition(
        self,
        workflow_id: UUID,
        current_state_code: str,
        transition_id: UUID,
        user_id: UUID,
        entity_department_id: Optional[UUID] = None
    ) -> Tuple[bool, str, Optional[WorkflowTransition]]:
        """
        Validate if a transition can be performed.

        Returns:
            (is_valid, error_message, transition)
        """
        # Get transition
        transition = self.db.query(WorkflowTransition).filter(
            and_(
                WorkflowTransition.id == transition_id,
                WorkflowTransition.workflow_id == workflow_id,
                WorkflowTransition.is_active == True
            )
        ).first()

        if not transition:
            return False, "Transition not found or inactive", None

        # Get current state
        current_state = self.db.query(WorkflowState).filter(
            and_(
                WorkflowState.workflow_id == workflow_id,
                WorkflowState.state_code == current_state_code,
                WorkflowState.is_active == True
            )
        ).first()

        if not current_state:
            return False, "Current state not found", None

        # Verify transition is from current state
        if transition.from_state_id != current_state.id:
            return False, f"Invalid transition from state '{current_state_code}'", None

        # Get user roles (check both old and new role systems)
        user_roles = []

        # Try old role system
        try:
            user_roles = self.db.query(UserRole).filter(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.is_active == True
                )
            ).all()
        except Exception as e:
            print(f"[INFO] Old role system not available in execute_transition: {e}")
            self.db.rollback()

        # Check new organization role system
        from models import OrgUserRole
        org_user_roles = self.db.query(OrgUserRole).filter(
            and_(
                OrgUserRole.user_id == user_id,
                OrgUserRole.is_active == True
            )
        ).all()

        if not user_roles and not org_user_roles:
            return False, "User has no active roles", None

        # Check permission
        has_permission = self._check_transition_permission(
            transition_id,
            user_roles,
            entity_department_id
        )

        if not has_permission:
            return False, "User does not have permission for this transition", None

        return True, "", transition

    # ========================================
    # 5. PERFORM TRANSITION
    # ========================================

    def perform_transition(
        self,
        workflow_id: UUID,
        entity_type: str,
        entity_id: UUID,
        current_state_code: str,
        transition_id: UUID,
        user_id: UUID,
        entity_department_id: Optional[UUID] = None,
        comment: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Execute a workflow transition.

        Returns:
            (success, message, new_state_code)
        """
        # Validate transition
        is_valid, error_msg, transition = self.validate_transition(
            workflow_id,
            current_state_code,
            transition_id,
            user_id,
            entity_department_id
        )

        if not is_valid:
            # Log failed attempt
            self._create_audit_log(
                workflow_id=workflow_id,
                entity_type=entity_type,
                entity_id=entity_id,
                transition_id=transition_id,
                from_state_code=current_state_code,
                to_state_code=None,
                action_code=None,
                user_id=user_id,
                comment=comment,
                metadata=metadata,
                success=False,
                error_message=error_msg
            )
            return False, error_msg, None

        # Get from and to states
        from_state = self.db.query(WorkflowState).filter(
            WorkflowState.id == transition.from_state_id
        ).first()

        to_state = self.db.query(WorkflowState).filter(
            WorkflowState.id == transition.to_state_id
        ).first()

        if not to_state:
            return False, "Target state not found", None

        # Check if comment is required
        if transition.requires_comment and not comment:
            return False, "Comment is required for this transition", None

        # Get user's role and department for audit (optional)
        user_role = None
        try:
            user_role = self.db.query(UserRole).filter(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.is_active == True
                )
            ).first()
        except Exception:
            self.db.rollback()

        # Create audit log
        audit_log = self._create_audit_log(
            workflow_id=workflow_id,
            entity_type=entity_type,
            entity_id=entity_id,
            transition_id=transition_id,
            from_state_code=from_state.state_code if from_state else None,
            to_state_code=to_state.state_code,
            action_code=transition.action_code,
            user_id=user_id,
            user_role_id=user_role.role_id if user_role else None,
            user_department_id=user_role.department_id if user_role else None,
            comment=comment,
            metadata=metadata,
            success=True,
            error_message=None
        )

        return True, f"Transition '{transition.transition_name}' completed successfully", to_state.state_code

    # ========================================
    # 6. CREATE AUDIT LOG
    # ========================================

    def _create_audit_log(
        self,
        workflow_id: UUID,
        entity_type: str,
        entity_id: UUID,
        transition_id: Optional[UUID],
        from_state_code: Optional[str],
        to_state_code: Optional[str],
        action_code: Optional[str],
        user_id: UUID,
        user_role_id: Optional[UUID] = None,
        user_department_id: Optional[UUID] = None,
        comment: Optional[str] = None,
        metadata: Optional[Dict] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> WorkflowAuditLog:
        """Create an audit log entry for a transition attempt."""

        # Get state IDs from codes
        from_state_id = None
        to_state_id = None

        if from_state_code:
            from_state = self.db.query(WorkflowState).filter(
                and_(
                    WorkflowState.workflow_id == workflow_id,
                    WorkflowState.state_code == from_state_code
                )
            ).first()
            from_state_id = from_state.id if from_state else None

        if to_state_code:
            to_state = self.db.query(WorkflowState).filter(
                and_(
                    WorkflowState.workflow_id == workflow_id,
                    WorkflowState.state_code == to_state_code
                )
            ).first()
            to_state_id = to_state.id if to_state else None

        audit_log = WorkflowAuditLog(
            workflow_id=workflow_id,
            entity_type=entity_type,
            entity_id=entity_id,
            transition_id=transition_id,
            from_state_id=from_state_id,
            to_state_id=to_state_id,
            action_code=action_code,
            performed_by=user_id,
            user_role_id=user_role_id,
            user_department_id=user_department_id,
            comment=comment,
            metadata=metadata,
            success=success,
            error_message=error_message
        )

        self.db.add(audit_log)
        self.db.commit()
        self.db.refresh(audit_log)

        return audit_log

    # ========================================
    # 7. GET WORKFLOW BY TYPE
    # ========================================

    def get_workflow_by_type(
        self,
        workflow_type: str,
        organization_id: Optional[UUID] = None
    ) -> Optional[Workflow]:
        """
        Get the active workflow for a given type and organization.

        Args:
            workflow_type: Type of workflow (e.g., 'testing_request')
            organization_id: Organization UUID (optional for global workflows)

        Returns:
            Workflow instance or None
        """
        query = self.db.query(Workflow).filter(
            and_(
                Workflow.workflow_type == workflow_type,
                Workflow.is_active == True
            )
        )

        if organization_id:
            query = query.filter(
                or_(
                    Workflow.organization_id == organization_id,
                    Workflow.organization_id == None
                )
            )
        else:
            query = query.filter(Workflow.organization_id == None)

        # Order by organization_id DESC (org-specific first), then by version DESC
        workflow = query.order_by(
            Workflow.organization_id.desc().nullslast(),
            Workflow.version.desc()
        ).first()

        return workflow

    # ========================================
    # 8. GET STATE BY CODE
    # ========================================

    def get_state_by_code(
        self,
        workflow_id: UUID,
        state_code: str
    ) -> Optional[WorkflowState]:
        """Get a workflow state by its code."""
        return self.db.query(WorkflowState).filter(
            and_(
                WorkflowState.workflow_id == workflow_id,
                WorkflowState.state_code == state_code,
                WorkflowState.is_active == True
            )
        ).first()

    # ========================================
    # 9. GET WORKFLOW AUDIT HISTORY
    # ========================================

    def get_audit_history(
        self,
        entity_type: str,
        entity_id: UUID
    ) -> List[WorkflowAuditLog]:
        """Get complete audit history for an entity."""
        return self.db.query(WorkflowAuditLog).filter(
            and_(
                WorkflowAuditLog.entity_type == entity_type,
                WorkflowAuditLog.entity_id == entity_id
            )
        ).order_by(WorkflowAuditLog.performed_at.asc()).all()
