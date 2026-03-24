"""
Add approval step to testing request workflow.
Adds a 'pending_approval' state between 'submitted' and 'assigned'.
"""
import sys
import os

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from database import SessionLocal
from models import WorkflowState, WorkflowTransition
from sqlalchemy import text
import uuid
from datetime import datetime

def add_approval_workflow():
    session = SessionLocal()

    try:
        # Get the testing request workflow
        workflow = session.execute(
            text("SELECT id FROM workflows WHERE workflow_type = 'testing_request' AND is_active = true LIMIT 1")
        ).fetchone()

        if not workflow:
            print("[ERROR] Testing request workflow not found")
            return

        workflow_id = workflow[0]
        print(f"[INFO] Found workflow: {workflow_id}")

        # Check if pending_approval state already exists
        existing_state = session.execute(
            text("SELECT id FROM workflow_states WHERE workflow_id = :wid AND state_code = 'pending_approval'"),
            {"wid": workflow_id}
        ).fetchone()

        if existing_state:
            print("[INFO] pending_approval state already exists. Skipping.")
            return

        # Get state IDs
        states = {}
        state_rows = session.execute(
            text("SELECT state_code, id FROM workflow_states WHERE workflow_id = :wid"),
            {"wid": workflow_id}
        ).fetchall()

        for row in state_rows:
            states[row[0]] = row[1]

        print(f"[INFO] Found {len(states)} existing states")

        # ============================================
        # 1. CREATE NEW STATE: pending_approval
        # ============================================
        new_state_id = uuid.uuid4()

        session.execute(
            text("""
                INSERT INTO workflow_states (
                    id, workflow_id, state_code, state_name, description,
                    state_type, color, icon, display_order, is_active
                ) VALUES (
                    :id, :workflow_id, 'pending_approval', 'Pending Approval',
                    'Request submitted and awaiting approval from department/section head',
                    'intermediate', '#FFC107', 'approval', 1.5, TRUE
                )
            """),
            {
                "id": new_state_id,
                "workflow_id": workflow_id
            }
        )

        states['pending_approval'] = new_state_id
        print(f"[OK] Created pending_approval state: {new_state_id}")

        # Update display_order for other states
        session.execute(
            text("UPDATE workflow_states SET display_order = 2.5 WHERE id = :id"),
            {"id": states['assigned']}
        )
        session.execute(
            text("UPDATE workflow_states SET display_order = 3.5 WHERE id = :id"),
            {"id": states['accepted']}
        )
        session.execute(
            text("UPDATE workflow_states SET display_order = 4.5 WHERE id = :id"),
            {"id": states['in_progress']}
        )
        session.execute(
            text("UPDATE workflow_states SET display_order = 5.5 WHERE id = :id"),
            {"id": states['test_submitted']}
        )
        print("[OK] Updated display order for existing states")

        # ============================================
        # 2. MODIFY TRANSITIONS
        # ============================================

        # Delete old: submitted → assigned transition
        old_transition = session.execute(
            text("""
                SELECT id FROM workflow_transitions
                WHERE workflow_id = :wid
                AND from_state_id = :from_state
                AND to_state_id = :to_state
            """),
            {
                "wid": workflow_id,
                "from_state": states['submitted'],
                "to_state": states['assigned']
            }
        ).fetchone()

        if old_transition:
            session.execute(
                text("DELETE FROM workflow_transitions WHERE id = :id"),
                {"id": old_transition[0]}
            )
            print(f"[OK] Deleted old transition: submitted → assigned")

        # Create new transitions
        transitions = [
            # submitted → pending_approval (automatic)
            {
                "from_state": states['submitted'],
                "to_state": states['pending_approval'],
                "name": "Send for Approval",
                "action_code": "send_for_approval",
                "description": "Automatically send to approval queue",
                "button_label": None,  # Automatic transition
                "button_color": None,
                "icon": "send",
                "requires_comment": False,
                "display_order": 0
            },
            # pending_approval → assigned (after approval, with tester role selection)
            {
                "from_state": states['pending_approval'],
                "to_state": states['assigned'],
                "name": "Approve and Assign",
                "action_code": "approve_and_assign",
                "description": "Approve request and assign to tester based on selected role/location",
                "button_label": "Approve & Assign",
                "button_color": "#4CAF50",
                "icon": "check_circle",
                "requires_comment": False,
                "display_order": 0
            },
            # pending_approval → rejected
            {
                "from_state": states['pending_approval'],
                "to_state": states['rejected'],
                "name": "Reject Request",
                "action_code": "reject_request",
                "description": "Reject the testing request",
                "button_label": "Reject",
                "button_color": "#F44336",
                "icon": "cancel",
                "requires_comment": True,
                "display_order": 1
            }
        ]

        for trans in transitions:
            trans_id = uuid.uuid4()
            session.execute(
                text("""
                    INSERT INTO workflow_transitions (
                        id, workflow_id, from_state_id, to_state_id,
                        transition_name, action_code, description,
                        button_label, button_color, icon,
                        requires_comment, display_order, is_active
                    ) VALUES (
                        :id, :workflow_id, :from_state, :to_state,
                        :name, :action_code, :description,
                        :button_label, :button_color, :icon,
                        :requires_comment, :display_order, TRUE
                    )
                """),
                {
                    "id": trans_id,
                    "workflow_id": workflow_id,
                    "from_state": trans["from_state"],
                    "to_state": trans["to_state"],
                    "name": trans["name"],
                    "action_code": trans["action_code"],
                    "description": trans["description"],
                    "button_label": trans["button_label"],
                    "button_color": trans["button_color"],
                    "icon": trans["icon"],
                    "requires_comment": trans["requires_comment"],
                    "display_order": trans["display_order"]
                }
            )
            print(f"[OK] Created transition: {trans['name']}")

        # ============================================
        # 3. ADD PERMISSIONS FOR APPROVAL TRANSITIONS
        # ============================================

        # Get Approver, Department Head, Section Head roles
        approver_roles = session.execute(
            text("""
                SELECT id, name FROM roles
                WHERE name IN ('Approver', 'Department Head', 'Section Head', 'Division Head', 'Admin')
                AND is_active = TRUE
            """)
        ).fetchall()

        print(f"\n[INFO] Found {len(approver_roles)} approver roles")

        # Get the approve_and_assign transition
        approve_trans = session.execute(
            text("""
                SELECT id FROM workflow_transitions
                WHERE workflow_id = :wid AND action_code = 'approve_and_assign'
            """),
            {"wid": workflow_id}
        ).fetchone()

        reject_trans = session.execute(
            text("""
                SELECT id FROM workflow_transitions
                WHERE workflow_id = :wid AND action_code = 'reject_request'
            """),
            {"wid": workflow_id}
        ).fetchone()

        if approve_trans and reject_trans and approver_roles:
            for role in approver_roles:
                role_id, role_name = role

                # Permission for approve & assign
                session.execute(
                    text("""
                        INSERT INTO permission_matrix (
                            id, workflow_id, transition_id, role_id,
                            scope_type, can_execute, can_view
                        ) VALUES (
                            :id, :workflow_id, :transition_id, :role_id,
                            'department_tree', TRUE, TRUE
                        )
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": uuid.uuid4(),
                        "workflow_id": workflow_id,
                        "transition_id": approve_trans[0],
                        "role_id": role_id
                    }
                )

                # Permission for reject
                session.execute(
                    text("""
                        INSERT INTO permission_matrix (
                            id, workflow_id, transition_id, role_id,
                            scope_type, can_execute, can_view
                        ) VALUES (
                            :id, :workflow_id, :transition_id, :role_id,
                            'department_tree', TRUE, TRUE
                        )
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": uuid.uuid4(),
                        "workflow_id": workflow_id,
                        "transition_id": reject_trans[0],
                        "role_id": role_id
                    }
                )

                print(f"[OK] Added permissions for {role_name}")

        session.commit()

        print("\n" + "=" * 80)
        print("[SUCCESS] Approval workflow added successfully!")
        print("=" * 80)
        print("\nNew workflow:")
        print("  1. draft → submitted (requester)")
        print("  2. submitted → pending_approval (automatic)")
        print("  3. pending_approval → approved & assigned (approver chooses tester role)")
        print("  4. pending_approval → rejected (approver)")
        print("  5. assigned → accepted (tester)")
        print("  6. accepted → in_progress (tester)")
        print("  7. in_progress → test_submitted (tester)")
        print("  8. test_submitted → approved/rejected (final approver)")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    print("=" * 80)
    print("  ADD APPROVAL STEP TO TESTING REQUEST WORKFLOW")
    print("=" * 80)
    print()

    response = input("This will modify the workflow. Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    print()
    add_approval_workflow()
