"""
Service methods for testing request approval workflow.
Add these methods to services/testing_request_workflow_service.py
"""

# Add this method to TestingRequestWorkflowService class:

def approve_and_assign_tester(
    self,
    testing_request,
    user,
    tester_id: str,  # The specific tester user ID selected by approver
    tester_role_id: str,  # The organization role ID for verification
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
        if testing_request.status != 'pending_approval':
            return False, f"Request must be in 'pending_approval' state, currently: {testing_request.status}"

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
        testing_request.status = 'assigned'

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
        if testing_request.status != 'pending_approval':
            return False, f"Request must be in 'pending_approval' state"

        if not comment:
            return False, "Rejection comment is required"

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

        return True, "Request rejected successfully"

    except Exception as e:
        self.db.rollback()
        return False, f"Error rejecting request: {str(e)}"
