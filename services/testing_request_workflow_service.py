"""
Testing Request Workflow Integration Service

Bridges the existing testing request system with the workflow engine.
Provides helper methods to perform status transitions using workflows.
Includes auto-assignment of testers when requests are submitted.
"""

from typing import Optional, Dict, Any, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from models import TestingRequest, User, TestingRequestStatus
from services.workflow_engine import IntegratedWorkflowEngine
from services.tester_auto_assignment_service import TesterAutoAssignmentService


class TestingRequestWorkflowService:
    """
    Service to manage testing request workflow transitions.
    """

    WORKFLOW_TYPE = "testing_request"
    ENTITY_TYPE = "testing_request"

    def __init__(self, db: Session):
        self.db = db
        self.workflow_engine = IntegratedWorkflowEngine(db)
        self.auto_assignment_service = TesterAutoAssignmentService(db)

    # ========================================
    # GET WORKFLOW
    # ========================================

    def _get_workflow(self, organization_id: Optional[UUID] = None):
        """Get the active testing request workflow."""
        workflow = self.workflow_engine.get_workflow_by_type(
            self.WORKFLOW_TYPE,
            organization_id
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Testing request workflow not configured"
            )
        return workflow

    # ========================================
    # GET AVAILABLE ACTIONS
    # ========================================

    def get_available_actions(
        self,
        testing_request: TestingRequest,
        user: User
    ) -> list[Dict[str, Any]]:
        """
        Get all available workflow actions for a testing request.

        Returns:
            List of available transitions with button details
        """
        workflow = self._get_workflow(testing_request.organization_id)

        return self.workflow_engine.get_available_transitions(
            workflow_id=workflow.id,
            current_state_id=self._get_state_id(workflow.id, testing_request.status),
            user_id=user.id,
            entity_department_id=testing_request.department_id
        )

    # ========================================
    # PERFORM TRANSITION
    # ========================================

    def perform_transition(
        self,
        testing_request: TestingRequest,
        action_code: str,
        user: User,
        comment: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> tuple[bool, str]:
        """
        Perform a workflow transition on a testing request.

        Args:
            testing_request: The testing request instance
            action_code: Action code (e.g., 'submit', 'accept', 'approve')
            user: User performing the action
            comment: Optional comment for the transition
            metadata: Optional additional data

        Returns:
            (success, message)
        """
        workflow = self._get_workflow(testing_request.organization_id)

        # Get the transition by action code
        transition = self.db.query(models.WorkflowTransition).filter(
            and_(
                models.WorkflowTransition.workflow_id == workflow.id,
                models.WorkflowTransition.action_code == action_code,
                models.WorkflowTransition.is_active == True
            )
        ).first()

        if not transition:
            return False, f"Transition with action '{action_code}' not found"

        # Perform the transition
        success, message, new_state_code = self.workflow_engine.perform_transition(
            workflow_id=workflow.id,
            entity_type=self.ENTITY_TYPE,
            entity_id=testing_request.id,
            current_state_code=testing_request.status.value,  # Convert enum to string
            transition_id=transition.id,
            user_id=user.id,
            entity_department_id=testing_request.department_id,
            comment=comment,
            metadata=metadata
        )

        if success and new_state_code:
            # Update the testing request status
            from_state = testing_request.status.value
            testing_request.status = TestingRequestStatus[new_state_code]
            testing_request.modified_by = user.id
            self.db.commit()

            try:
                from services.notification_service import NotificationService
                _changed_by = (
                    getattr(user, "full_name", None)
                    or getattr(user, "firstname", None)
                    or str(user.id)
                )
                NotificationService(self.db).fire(
                    event_type="status_changed",
                    context={
                        "request.number":  testing_request.request_number or str(testing_request.id),
                        "request.status":  new_state_code,
                        "request.title":   getattr(testing_request, "title", "") or "",
                        "status_from":     from_state,
                        "status_to":       new_state_code,
                        "changed_by":      _changed_by,
                    },
                    organization_id=testing_request.organization_id,
                    department_id=getattr(testing_request, "department_id", None),
                    source_id=testing_request.id,
                    source_type="testing_request",
                    severity="info",
                    workflow_type=self.WORKFLOW_TYPE,
                    equipment_type=(testing_request.equipment_type.name if testing_request.equipment_type else None),
                    test_type=(testing_request.request_category.value if testing_request.request_category else None),
                    status_from=from_state,
                    status_to=new_state_code,
                )
            except Exception as _em:
                import logging
                logging.getLogger(__name__).warning(f"Status change notification failed: {_em}")

        return success, message

    # ========================================
    # CONVENIENCE METHODS FOR SPECIFIC ACTIONS
    # ========================================

    def submit_request(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: Optional[str] = None,
        auto_assign: bool = True,
        assignment_strategy: str = 'least_loaded'
    ) -> Tuple[bool, str]:
        """
        Submit a draft testing request.

        Args:
            testing_request: The testing request to submit
            user: User performing the submission
            comment: Optional comment
            auto_assign: Whether to auto-assign a tester (default: True)
            assignment_strategy: Strategy for auto-assignment ('least_loaded', 'round_robin', 'random', 'priority')

        Returns:
            (success, message)
        """
        # First, submit the request (draft → submitted)
        success, message = self.perform_transition(
            testing_request=testing_request,
            action_code="submit",
            user=user,
            comment=comment
        )

        if not success:
            return False, message

        # If auto-assign is enabled, automatically assign a tester
        if auto_assign:
            assign_success, tester_id, assign_message = self.auto_assignment_service.auto_assign_tester(
                testing_request=testing_request,
                strategy=assignment_strategy
            )

            if assign_success and tester_id:
                # Update the testing request with assigned tester
                testing_request.assigned_tester_id = tester_id
                self.db.commit()

                # Automatically transition to 'assigned' state
                # This uses the system/admin user context for the auto-transition
                transition_success, transition_msg = self.perform_transition(
                    testing_request=testing_request,
                    action_code="assign_tester",
                    user=user,  # Use the submitting user for audit
                    comment=f"Auto-assigned: {assign_message}",
                    metadata={"auto_assigned": True, "strategy": assignment_strategy}
                )

                if transition_success:
                    return True, f"Request submitted and auto-assigned successfully. {assign_message}"
                else:
                    # Assignment happened but workflow transition failed
                    # This is still a success, just log the workflow issue
                    return True, f"Request submitted and tester assigned. Note: {transition_msg}"
            else:
                # Auto-assignment failed, but submission was successful
                return True, f"Request submitted successfully. {assign_message}. Manual assignment required."

        return True, message

    def assign_tester(
        self,
        testing_request: TestingRequest,
        user: User,
        tester_id: UUID,
        comment: Optional[str] = None
    ) -> tuple[bool, str]:
        """Assign a tester to the request.

        Sets assigned_tester_id on the request BEFORE the workflow transition
        so that:
          1. The DB record is updated to reflect the assignment.
          2. notify_tester_assigned() can read request.assigned_tester for
             the in-app / email notification sent to the specific tester.
        """
        # Set the tester before the transition so notify_tester_assigned()
        # can safely access request.assigned_tester after the commit.
        testing_request.assigned_tester_id = tester_id

        success, message = self.perform_transition(
            testing_request=testing_request,
            action_code="assign_tester",
            user=user,
            comment=comment,
            metadata={"tester_id": str(tester_id)}
        )

        if success:
            # Refresh so ORM relationships (assigned_tester, equipment, …) are
            # populated before the notification service reads them.
            try:
                self.db.refresh(testing_request)
            except Exception:
                pass
            try:
                from services.notification_service import NotificationService
                NotificationService(self.db).notify_tester_assigned(testing_request)
            except Exception as notif_exc:
                import logging
                logging.getLogger(__name__).warning(
                    f"[TestingRequest] notify_tester_assigned failed: {notif_exc}"
                )

        return success, message

    def accept_assignment(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: Optional[str] = None
    ) -> tuple[bool, str]:
        """Tester accepts the assignment."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="accept",
            user=user,
            comment=comment
        )

    def reject_assignment(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: str
    ) -> tuple[bool, str]:
        """Tester rejects the assignment."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="reject_assignment",
            user=user,
            comment=comment
        )

    def start_testing(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: Optional[str] = None
    ) -> tuple[bool, str]:
        """Start the testing process."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="start",
            user=user,
            comment=comment
        )

    def submit_test_results(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: Optional[str] = None
    ) -> tuple[bool, str]:
        """Submit test results."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="submit_results",
            user=user,
            comment=comment
        )

    def approve_results(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: Optional[str] = None
    ) -> tuple[bool, str]:
        """Approve test results."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="approve",
            user=user,
            comment=comment
        )

    def reject_results(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: str
    ) -> tuple[bool, str]:
        """Reject test results."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="reject_results",
            user=user,
            comment=comment
        )

    def cancel_request(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: str
    ) -> tuple[bool, str]:
        """Cancel the testing request."""
        return self.perform_transition(
            testing_request=testing_request,
            action_code="cancel",
            user=user,
            comment=comment
        )

    # ========================================
    # HELPER METHODS
    # ========================================

    def _get_state_id(self, workflow_id: UUID, status_code: str) -> UUID:
        """Get state ID from status code."""
        state = self.workflow_engine.get_state_by_code(workflow_id, status_code)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Workflow state '{status_code}' not found"
            )
        return state.id

    def get_workflow_history(
        self,
        testing_request_id: UUID
    ) -> list:
        """Get the complete workflow history for a testing request."""
        return self.workflow_engine.get_audit_history(
            entity_type=self.ENTITY_TYPE,
            entity_id=testing_request_id
        )

    def approve_and_assign_tester(
        self,
        testing_request,
        user,
        tester_id: str,
        tester_role_id: str,
        comment: str = None
    ) -> tuple[bool, str]:
        """
        Approve a testing request and assign to a specific tester.
        Approver manually selects the tester after choosing a role.

        Args:
            testing_request: The TestingRequest object
            user: The approving user
            tester_id: Specific tester user ID selected by approver
            tester_role_id: Organization role ID for verification
            comment: Optional approval comment

        Returns:
            (success: bool, message: str)
        """
        try:
            # 1. Validate current state
            # Using submitted for testing (pending_approval requires migration)
            if testing_request.status not in [TestingRequestStatus.pending_approval, TestingRequestStatus.submitted]:
                return False, f"Request must be in 'pending_approval' or 'submitted' state, currently: {testing_request.status}"

            # 2. Verify tester exists and is active
            from models import User
            selected_tester = self.db.query(User).filter(
                User.id == tester_id,
                User.isactive == True
            ).first()

            if not selected_tester:
                return False, "Selected tester not found or inactive"

            # 3. Verify tester has the specified role
            from models import OrgUserRole
            has_role = self.db.query(OrgUserRole).filter(
                OrgUserRole.user_id == tester_id,
                OrgUserRole.org_role_id == tester_role_id,
                OrgUserRole.is_active == True
            ).first()

            if not has_role:
                return False, "Selected tester does not have the specified role"

            # 4. Check if we're in testing mode with 'submitted' status
            if testing_request.status == TestingRequestStatus.submitted:
                # TESTING MODE: Bypass workflow engine for submitted status
                # Just do direct assignment without workflow transitions
                testing_request.assigned_tester_id = selected_tester.id
                testing_request.status = TestingRequestStatus.assigned
                self.db.commit()
                self.db.refresh(testing_request)

                try:
                    from services.notification_service import NotificationService
                    NotificationService(self.db).notify_tester_assigned(testing_request)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Notification failed: {e}")

                return True, f"Request approved and assigned to {selected_tester.email} (testing mode)"

            # 4. Execute workflow transition: pending_approval → assigned
            from models import WorkflowTransition
            transition = self.db.query(WorkflowTransition).join(
                WorkflowTransition.workflow
            ).filter(
                WorkflowTransition.action_code == 'approve_and_assign',
                WorkflowTransition.workflow.has(workflow_type='testing_request')
            ).first()

            if not transition:
                return False, "Approval transition not found in workflow"

            # 5. Assign the tester BEFORE executing transition
            testing_request.assigned_tester_id = selected_tester.id

            # 6. Execute transition
            success, msg = self.execute_transition(
                testing_request=testing_request,
                transition=transition,
                user=user,
                comment=comment or f"Approved and assigned to {selected_tester.email}"
            )

            if not success:
                return False, msg

            # 7. Update status
            testing_request.status = TestingRequestStatus.assigned

            # 8. Log the assignment
            from models import WorkflowAuditLog
            import uuid
            from datetime import datetime

            audit_log = WorkflowAuditLog(
                id=uuid.uuid4(),
                workflow_instance_id=testing_request.workflow_instance_id,
                transition_id=transition.id,
                from_state_code='pending_approval',
                to_state_code='assigned',
                performed_by=user.id,
                comment=f"Approved and manually assigned to {selected_tester.email} (role: {tester_role_id})",
                metadata={
                    'tester_id': str(selected_tester.id),
                    'tester_email': selected_tester.email,
                    'tester_role_id': str(tester_role_id),
                    'manual_selection': True
                },
                cts=datetime.now(datetime.now().astimezone().tzinfo)
            )
            self.db.add(audit_log)

            self.db.commit()
            self.db.refresh(testing_request)

            try:
                from services.notification_service import NotificationService
                NotificationService(self.db).notify_tester_assigned(testing_request)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Notification failed: {e}")

            return True, f"Request approved and assigned to {selected_tester.email}"

        except Exception as e:
            self.db.rollback()
            return False, f"Error approving request: {str(e)}"

    def reject_testing_request(
        self,
        testing_request,
        user,
        comment: str
    ) -> tuple[bool, str]:
        """
        Reject a testing request during approval stage.

        Args:
            testing_request: The TestingRequest object
            user: The rejecting user
            comment: Rejection reason (required)

        Returns:
            (success: bool, message: str)
        """
        try:
            # 1. Validate current state
            # Using submitted for testing (pending_approval requires migration)
            if testing_request.status not in [TestingRequestStatus.pending_approval, TestingRequestStatus.submitted]:
                return False, f"Request must be in 'pending_approval' or 'submitted' state"

            if not comment:
                return False, "Rejection comment is required"

            # 2. Check if we're in testing mode with 'submitted' status
            if testing_request.status == TestingRequestStatus.submitted:
                # TESTING MODE: Bypass workflow engine for submitted status
                testing_request.status = TestingRequestStatus.rejected
                self.db.commit()

                try:
                    from services.notification_service import NotificationService
                    NotificationService(self.db).notify_request_rejected(
                        testing_request,
                        getattr(user, "full_name", None) or getattr(user, "email", ""),
                        comment,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Notification failed: {e}")

                return True, f"Request rejected (testing mode): {comment}"

            # 2. Get rejection transition
            from models import WorkflowTransition
            transition = self.db.query(WorkflowTransition).join(
                WorkflowTransition.workflow
            ).filter(
                WorkflowTransition.action_code == 'reject_request',
                WorkflowTransition.workflow.has(workflow_type='testing_request')
            ).first()

            if not transition:
                return False, "Rejection transition not found"

            # 3. Execute transition
            success, msg = self.execute_transition(
                testing_request=testing_request,
                transition=transition,
                user=user,
                comment=comment
            )

            if not success:
                return False, msg

            # 4. Update status
            testing_request.status = 'rejected'

            self.db.commit()

            try:
                from services.notification_service import NotificationService
                NotificationService(self.db).notify_request_rejected(
                    testing_request,
                    getattr(user, "full_name", None) or getattr(user, "email", ""),
                    comment,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Notification failed: {e}")

            return True, "Request rejected successfully"

        except Exception as e:
            self.db.rollback()
            return False, f"Error rejecting request: {str(e)}"


    # ========================================
    # TR_WF_* NEW WORKFLOW PATH (parallel engine)
    # ========================================

    def tr_wf_l2_approve_and_route(
        self,
        testing_request: TestingRequest,
        user: User,
        comment: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        L2 approve path for the new configurable workflow engine.

        Instead of assigning a tester directly, this:
          1. Sets legacy status → pending_assignment (backward compat)
          2. Resolves routing → creates TrWfInstance at first stage
          3. Fires notification

        Caller must db.commit() after this returns True.
        """
        from services.tr_workflow_routing_service import WorkflowRoutingService, WorkflowConfigError
        from models import TrWfInstance

        try:
            routing_svc = WorkflowRoutingService(self.db)

            # Instance is created at submission; fall back to creating here if missing
            instance: TrWfInstance = (
                self.db.query(TrWfInstance)
                .filter(TrWfInstance.id == testing_request.wf_instance_id)
                .first()
            ) if testing_request.wf_instance_id else None

            if instance is None:
                instance = routing_svc.instantiate_workflow(
                    testing_request=testing_request,
                    performed_by_id=user.id,
                )

            # Advance past l2_approve_route stage
            routing_svc.advance_stage(
                instance=instance,
                action_code="approve",
                performed_by_id=user.id,
                comment=comment,
            )

            # Keep legacy status populated for old dashboards
            testing_request.status = TestingRequestStatus.pending_assignment
            testing_request.modified_by = user.id

            try:
                from services.notification_service import NotificationService
                NotificationService(self.db).fire(
                    event_type="status_changed",
                    context={
                        "request.number": testing_request.request_number or str(testing_request.id),
                        "request.status": "pending_assignment",
                        "changed_by": getattr(user, "full_name", None) or getattr(user, "email", ""),
                    },
                    organization_id=testing_request.organization_id,
                    department_id=getattr(testing_request, "department_id", None),
                    source_id=testing_request.id,
                    source_type="testing_request",
                    severity="info",
                )
            except Exception as _ne:
                import logging
                logging.getLogger(__name__).warning(f"L2 route notification failed: {_ne}")

            return True, f"Request approved and routed to workflow '{instance.wf_definition_id}'"

        except WorkflowConfigError as wce:
            return False, wce.detail
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("tr_wf_l2_approve_and_route error")
            return False, str(exc)

    def tr_wf_l3_assign_tester(
        self,
        testing_request: TestingRequest,
        user: User,
        tester_id: UUID,
        tester_role_id: UUID,
        comment: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        L3 assigner (AEE R&T / AEE R&D) assigns a Level-4 tester from their
        department hierarchy using the new configurable workflow engine.

        Advances the workflow instance via 'assign' action_code.
        Caller must db.commit() after this returns True.
        """
        from services.tr_workflow_routing_service import WorkflowRoutingService, WorkflowConfigError
        from models import User as UserModel, OrgUserRole

        try:
            # Validate tester
            tester = self.db.query(UserModel).filter(
                UserModel.id == tester_id,
                UserModel.isactive.is_(True),
            ).first()
            if not tester:
                return False, "Selected tester not found or inactive"

            has_role = self.db.query(OrgUserRole).filter(
                OrgUserRole.user_id == tester_id,
                OrgUserRole.org_role_id == tester_role_id,
                OrgUserRole.is_active.is_(True),
            ).first()
            if not has_role:
                return False, "Selected tester does not have the specified role"

            routing_svc = WorkflowRoutingService(self.db)
            routing_svc.advance_stage(
                testing_request=testing_request,
                action_code="assign",
                performed_by_id=user.id,
                role_id=tester_role_id,
                comment=comment,
                assigned_user_id=tester_id,
                assigned_role_id=tester_role_id,
            )

            # Keep legacy fields populated for old code paths
            testing_request.assigned_tester_id = tester_id
            testing_request.status = TestingRequestStatus.in_progress
            testing_request.modified_by = user.id

            try:
                from services.notification_service import NotificationService
                self.db.flush()
                self.db.refresh(testing_request)
                NotificationService(self.db).notify_tester_assigned(testing_request)
            except Exception as _ne:
                import logging
                logging.getLogger(__name__).warning(f"L3 assign notification failed: {_ne}")

            return True, f"Tester assigned successfully"

        except WorkflowConfigError as wce:
            return False, wce.detail
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("tr_wf_l3_assign_tester error")
            return False, str(exc)

    def tr_wf_advance(
        self,
        testing_request: TestingRequest,
        user: User,
        action_code: str,
        role_id: Optional[UUID] = None,
        comment: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Generic advance for any tr_wf_* action (return, complete, close, reject, etc.).
        Caller must db.commit() after this returns True.
        """
        from services.tr_workflow_routing_service import WorkflowRoutingService, WorkflowConfigError

        try:
            routing_svc = WorkflowRoutingService(self.db)
            routing_svc.advance_stage(
                testing_request=testing_request,
                action_code=action_code,
                performed_by_id=user.id,
                role_id=role_id,
                comment=comment,
            )
            testing_request.modified_by = user.id
            return True, f"Action '{action_code}' applied"

        except WorkflowConfigError as wce:
            return False, wce.detail
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("tr_wf_advance error")
            return False, str(exc)


# Import models at the end to avoid circular imports
from models import TestingRequestStatus
import models
from sqlalchemy import and_
