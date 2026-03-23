-- ============================================================
-- SEED: Testing Request Workflow with Permission Matrix
-- ============================================================
-- Description: Creates default testing request workflow with
-- all states, transitions, and role-based permissions
-- Date: 2026-03-22
-- ============================================================

-- Variables for IDs (using specific UUIDs for consistency)
DO $$
DECLARE
    v_workflow_id UUID;

    -- State IDs
    v_state_draft UUID;
    v_state_submitted UUID;
    v_state_pending_approval UUID;
    v_state_assigned UUID;
    v_state_accepted UUID;
    v_state_in_progress UUID;
    v_state_test_submitted UUID;
    v_state_approved UUID;
    v_state_rejected UUID;
    v_state_cancelled UUID;

    -- Transition IDs
    v_trans_submit UUID;
    v_trans_send_for_approval UUID;
    v_trans_approve_and_assign UUID;
    v_trans_reject_request UUID;
    v_trans_accept UUID;
    v_trans_reject_from_assigned UUID;
    v_trans_start UUID;
    v_trans_submit_results UUID;
    v_trans_approve UUID;
    v_trans_reject_from_test_submitted UUID;
    v_trans_cancel_from_draft UUID;
    v_trans_cancel_from_submitted UUID;

    -- Role IDs (to be looked up)
    v_role_requester UUID;
    v_role_department_head UUID;
    v_role_tester UUID;
    v_role_section_head UUID;
    v_role_division_head UUID;
    v_role_admin UUID;

BEGIN
    -- ============================================================
    -- 1. CREATE WORKFLOW
    -- ============================================================

    INSERT INTO workflows (
        id,
        name,
        description,
        workflow_type,
        organization_id,
        is_active,
        version
    ) VALUES (
        uuid_generate_v4(),
        'Testing Request Workflow',
        'Standard workflow for equipment testing requests with role-based approval hierarchy',
        'testing_request',
        NULL,  -- Global workflow (applies to all organizations)
        TRUE,
        1
    ) RETURNING id INTO v_workflow_id;

    RAISE NOTICE 'Created workflow: %', v_workflow_id;

    -- ============================================================
    -- 2. CREATE STATES
    -- ============================================================

    -- Draft
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'draft', 'Draft',
        'Request is being prepared and not yet submitted',
        'initial', '#9E9E9E', 'edit', 0, TRUE
    ) RETURNING id INTO v_state_draft;

    -- Submitted
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'submitted', 'Submitted',
        'Request has been submitted for approval',
        'intermediate', '#2196F3', 'send', 1, TRUE
    ) RETURNING id INTO v_state_submitted;

    -- Pending Approval
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'pending_approval', 'Pending Approval',
        'Request submitted and awaiting approval from department/section head',
        'intermediate', '#FFC107', 'approval', 1.5, TRUE
    ) RETURNING id INTO v_state_pending_approval;

    -- Assigned
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'assigned', 'Assigned',
        'Tester has been assigned to the request',
        'intermediate', '#FF9800', 'person_add', 2, TRUE
    ) RETURNING id INTO v_state_assigned;

    -- Accepted
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'accepted', 'Accepted',
        'Tester has accepted the testing assignment',
        'intermediate', '#4CAF50', 'check_circle', 3, TRUE
    ) RETURNING id INTO v_state_accepted;

    -- In Progress
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'in_progress', 'In Progress',
        'Testing is currently underway',
        'intermediate', '#00BCD4', 'engineering', 4, TRUE
    ) RETURNING id INTO v_state_in_progress;

    -- Test Submitted
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'test_submitted', 'Test Submitted',
        'Test results have been submitted and awaiting approval',
        'intermediate', '#9C27B0', 'assignment_turned_in', 5, TRUE
    ) RETURNING id INTO v_state_test_submitted;

    -- Approved
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'approved', 'Approved',
        'Test results have been approved',
        'final', '#4CAF50', 'verified', 6, TRUE
    ) RETURNING id INTO v_state_approved;

    -- Rejected
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'rejected', 'Rejected',
        'Request or test results have been rejected',
        'final', '#F44336', 'cancel', 7, TRUE
    ) RETURNING id INTO v_state_rejected;

    -- Cancelled
    INSERT INTO workflow_states (
        id, workflow_id, state_code, state_name, description,
        state_type, color, icon, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, 'cancelled', 'Cancelled',
        'Request has been cancelled',
        'cancelled', '#607D8B', 'block', 8, TRUE
    ) RETURNING id INTO v_state_cancelled;

    RAISE NOTICE 'Created 10 workflow states';

    -- ============================================================
    -- 3. CREATE TRANSITIONS
    -- ============================================================

    -- Draft → Submitted
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_draft, v_state_submitted,
        'Submit Request', 'submit', 'Submit the testing request for approval',
        'Submit', '#2196F3', 'send', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_submit;

    -- Submitted → Pending Approval (automatic)
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_submitted, v_state_pending_approval,
        'Send for Approval', 'send_for_approval', 'Automatically send to approval queue',
        NULL, NULL, 'send', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_send_for_approval;

    -- Pending Approval → Assigned (after approval with tester selection)
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_pending_approval, v_state_assigned,
        'Approve and Assign', 'approve_and_assign', 'Approve request and assign to tester based on selected role/location',
        'Approve & Assign', '#4CAF50', 'check_circle', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_approve_and_assign;

    -- Pending Approval → Rejected
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_pending_approval, v_state_rejected,
        'Reject Request', 'reject_request', 'Reject the testing request',
        'Reject', '#F44336', 'cancel', TRUE, 1, TRUE
    ) RETURNING id INTO v_trans_reject_request;

    -- Assigned → Accepted
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_assigned, v_state_accepted,
        'Accept Assignment', 'accept', 'Accept the testing assignment',
        'Accept', '#4CAF50', 'check_circle', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_accept;

    -- Assigned → Rejected
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_assigned, v_state_rejected,
        'Reject Assignment', 'reject_assignment', 'Reject the testing assignment',
        'Reject', '#F44336', 'cancel', TRUE, 1, TRUE
    ) RETURNING id INTO v_trans_reject_from_assigned;

    -- Accepted → In Progress
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_accepted, v_state_in_progress,
        'Start Testing', 'start', 'Begin the testing process',
        'Start Testing', '#00BCD4', 'play_arrow', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_start;

    -- In Progress → Test Submitted
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_in_progress, v_state_test_submitted,
        'Submit Test Results', 'submit_results', 'Submit the completed test results',
        'Submit Results', '#9C27B0', 'assignment_turned_in', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_submit_results;

    -- Test Submitted → Approved
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_test_submitted, v_state_approved,
        'Approve Results', 'approve', 'Approve the test results',
        'Approve', '#4CAF50', 'verified', FALSE, 0, TRUE
    ) RETURNING id INTO v_trans_approve;

    -- Test Submitted → Rejected
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_test_submitted, v_state_rejected,
        'Reject Results', 'reject_results', 'Reject the test results',
        'Reject', '#F44336', 'cancel', TRUE, 1, TRUE
    ) RETURNING id INTO v_trans_reject_from_test_submitted;

    -- Draft → Cancelled
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_draft, v_state_cancelled,
        'Cancel Request', 'cancel', 'Cancel the testing request',
        'Cancel', '#607D8B', 'block', TRUE, 10, TRUE
    ) RETURNING id INTO v_trans_cancel_from_draft;

    -- Submitted → Cancelled
    INSERT INTO workflow_transitions (
        id, workflow_id, from_state_id, to_state_id,
        transition_name, action_code, description,
        button_label, button_color, icon, requires_comment, display_order, is_active
    ) VALUES (
        uuid_generate_v4(), v_workflow_id, v_state_submitted, v_state_cancelled,
        'Cancel Request', 'cancel', 'Cancel the testing request',
        'Cancel', '#607D8B', 'block', TRUE, 10, TRUE
    ) RETURNING id INTO v_trans_cancel_from_submitted;

    RAISE NOTICE 'Created 10 workflow transitions';

    -- ============================================================
    -- 4. CREATE PERMISSION MATRIX (Role-Based)
    -- ============================================================

    -- NOTE: This section assumes roles already exist in org_roles table
    -- If roles don't exist yet, these inserts will fail
    -- You may need to adjust role_id values based on your actual role IDs

    -- For now, we'll create permissions with placeholders
    -- You can update these after roles are created

    RAISE NOTICE 'Workflow seeding completed successfully';
    RAISE NOTICE 'TODO: Add permission matrix entries after creating organization roles';

END $$;

-- ============================================================
-- END OF SEED SCRIPT
-- ============================================================
