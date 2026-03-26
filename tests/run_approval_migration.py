"""
Run approval workflow migration without prompts
"""
from database import SessionLocal
from models import Workflow, WorkflowState, WorkflowTransition
import uuid
from datetime import datetime, timezone

def add_approval_step():
    session = SessionLocal()

    try:
        # Get testing request workflow
        workflow = session.query(Workflow).filter_by(
            workflow_type='testing_request',
            is_active=True
        ).first()

        if not workflow:
            print('[ERROR] Testing request workflow not found')
            return False

        print(f'[INFO] Found workflow: {workflow.name}')

        # Check if pending_approval state already exists
        existing_state = session.query(WorkflowState).filter_by(
            workflow_id=workflow.id,
            state_code='pending_approval'
        ).first()

        if existing_state:
            print('[INFO] pending_approval state already exists')
            return True

        # Get states
        draft_state = session.query(WorkflowState).filter_by(
            workflow_id=workflow.id,
            state_code='draft'
        ).first()

        submitted_state = session.query(WorkflowState).filter_by(
            workflow_id=workflow.id,
            state_code='submitted'
        ).first()

        assigned_state = session.query(WorkflowState).filter_by(
            workflow_id=workflow.id,
            state_code='assigned'
        ).first()

        rejected_state = session.query(WorkflowState).filter_by(
            workflow_id=workflow.id,
            state_code='rejected'
        ).first()

        if not all([submitted_state, assigned_state, rejected_state]):
            print('[ERROR] Required states not found')
            return False

        print('[INFO] Creating pending_approval state...')

        # Create pending_approval state
        pending_approval_state = WorkflowState(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            state_code='pending_approval',
            state_name='Pending Approval',
            description='Request submitted and awaiting approval from department/section head',
            state_type='intermediate',
            color='#FFC107',
            icon='approval',
            display_order=1.5,
            is_active=True
        )
        session.add(pending_approval_state)
        session.flush()

        print('[OK] Created pending_approval state')

        # Update submitted->assigned transition to submitted->pending_approval
        print('[INFO] Updating transitions...')

        old_transition = session.query(WorkflowTransition).filter_by(
            workflow_id=workflow.id,
            from_state_id=submitted_state.id,
            to_state_id=assigned_state.id
        ).first()

        if old_transition:
            old_transition.to_state_id = pending_approval_state.id
            old_transition.transition_name = 'Send for Approval'
            old_transition.action_code = 'send_for_approval'
            old_transition.description = 'Automatically send to approval queue'
            old_transition.button_label = None
            print('[OK] Updated submitted->pending_approval transition')

        # Create pending_approval->assigned transition
        approve_transition = WorkflowTransition(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            from_state_id=pending_approval_state.id,
            to_state_id=assigned_state.id,
            transition_name='Approve and Assign',
            action_code='approve_and_assign',
            description='Approve request and assign to tester based on selected role/location',
            button_label='Approve & Assign',
            button_color='#4CAF50',
            icon='check_circle',
            requires_comment=False,
            display_order=0,
            is_active=True
        )
        session.add(approve_transition)
        print('[OK] Created pending_approval->assigned transition')

        # Create pending_approval->rejected transition
        reject_transition = WorkflowTransition(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            from_state_id=pending_approval_state.id,
            to_state_id=rejected_state.id,
            transition_name='Reject Request',
            action_code='reject_request',
            description='Reject the testing request',
            button_label='Reject',
            button_color='#F44336',
            icon='cancel',
            requires_comment=True,
            display_order=1,
            is_active=True
        )
        session.add(reject_transition)
        print('[OK] Created pending_approval->rejected transition')

        session.commit()
        print()
        print('[SUCCESS] Approval workflow added successfully!')
        return True

    except Exception as e:
        session.rollback()
        print(f'[ERROR] {e}')
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

if __name__ == "__main__":
    print('=' * 80)
    print('  ADD APPROVAL STEP TO TESTING REQUEST WORKFLOW')
    print('=' * 80)
    print()

    success = add_approval_step()

    if success:
        print()
        print('Next steps:')
        print('1. Create new testing requests - they will go to pending_approval')
        print('2. Login as approver (depthead@kptcl.com) to see them')
        print('3. Approve and assign testers')
    else:
        print()
        print('[FAILED] Could not add approval step')
