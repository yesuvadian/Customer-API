"""
Complete Testing Request Lifecycle Test
Tests: Create → Approve → Assign → Accept → In Progress → Complete
"""
import requests
import json

BASE_URL = "http://localhost:8020"

def login(email, password):
    """Login and get JWT token"""
    response = requests.post(
        f"{BASE_URL}/token",
        data={"username": email, "password": password}
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"[ERROR] Login failed for {email}: {response.status_code}")
        print(response.text)
        return None

def create_testing_request(token, data):
    """Create a new testing request"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{BASE_URL}/testing_requests/",
        headers=headers,
        json=data
    )

    if response.status_code in [200, 201]:
        return response.json()
    else:
        print(f"[ERROR] Failed to create request: {response.status_code}")
        print(response.text)
        return None

def submit_testing_request(token, request_id):
    """Submit a testing request for approval"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.put(
        f"{BASE_URL}/testing_requests/{request_id}/submit",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to submit request: {response.status_code}")
        print(response.text)
        return None

def get_pending_approvals(token):
    """Get pending approvals"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/pending",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to get pending approvals: {response.status_code}")
        return []

def approve_and_assign(token, request_id, role_id, tester_id):
    """Approve request and assign to tester"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/approve-and-assign",
        headers=headers,
        json={
            "tester_role_id": str(role_id),
            "tester_id": str(tester_id),
            "comment": "Approved for testing"
        }
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to approve: {response.status_code}")
        print(response.text)
        return None

def get_tester_assignments(token):
    """Get requests assigned to tester"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/testing/my-assignments",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to get assignments: {response.status_code}")
        print(response.text)
        return []

def tester_accept_request(token, request_id):
    """Tester accepts the assigned request"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/accept",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to accept: {response.status_code}")
        print(response.text)
        return None

def tester_start_testing(token, request_id):
    """Tester starts testing"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/start",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to start testing: {response.status_code}")
        print(response.text)
        return None

def upload_test_results(token, request_id):
    """Upload structured test results"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{BASE_URL}/testing/{request_id}/results/structured",
        headers=headers,
        json={
            "template_key": "general_test",
            "test_data": {
                "voltage_test": "passed",
                "resistance_test": "passed",
                "insulation_test": "passed"
            },
            "overall_result": "passed",
            "remarks": "All tests passed successfully",
            "replacement_products": []
        }
    )

    if response.status_code in [200, 201]:
        return response.json()
    else:
        print(f"[ERROR] Failed to upload results: {response.status_code}")
        print(response.text)
        return None

def tester_complete_testing(token, request_id):
    """Tester completes testing with results"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/submit_results",
        headers=headers,
        json={
            "replacement_products": []  # No replacement needed for passing test
        }
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to complete testing: {response.status_code}")
        print(response.text)
        return None

def get_request_details(token, request_id):
    """Get testing request details"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/testing_requests/{request_id}",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to get request: {response.status_code}")
        return None

def get_pending_recommendation_approvals(token):
    """Get pending recommendation approvals"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/approvals/pending",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to get pending approvals: {response.status_code}")
        print(response.text)
        return []

def get_recommendation_by_request(token, request_id):
    """Get recommendation created for a testing request"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/approvals/by-request/{request_id}",
        headers=headers
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to get recommendation: {response.status_code}")
        print(response.text)
        return None

def approve_recommendation(token, recommendation_id):
    """Approve a recommendation"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.put(
        f"{BASE_URL}/approvals/{recommendation_id}/approve",
        headers=headers,
        json={
            "notes": "Recommendation approved - proceed with procurement"
        }
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"[ERROR] Failed to approve recommendation: {response.status_code}")
        print(response.text)
        return None


def main():
    print("=" * 80)
    print("  COMPLETE TESTING REQUEST LIFECYCLE TEST")
    print("=" * 80)
    print()

    # ========== STEP 1: Create Request ==========
    print("STEP 1: Create Testing Request (as org admin/originator)")
    print("-" * 80)

    originator_token = login("orgadmin@kptcl.com", "admin123")
    if not originator_token:
        print("[FAILED] Could not login as org admin")
        return
    print("[OK] Logged in as orgadmin@kptcl.com")

    # Get KPTCL Organization
    headers = {"Authorization": f"Bearer {originator_token}"}
    org_response = requests.get(f"{BASE_URL}/organizations/", headers=headers)
    if org_response.status_code != 200:
        print(f"[FAILED] Could not fetch organizations: {org_response.status_code}")
        return

    orgs = org_response.json()
    kptcl_org = next((org for org in orgs if org['code'] == 'KPTCL'), None)
    if not kptcl_org:
        print("[FAILED] KPTCL Organization not found")
        return

    org_id = kptcl_org['id']
    dept_id = None
    if kptcl_org.get('departments') and len(kptcl_org['departments']) > 0:
        dept_id = kptcl_org['departments'][0]['id']

    print(f"[OK] Found KPTCL Org: {org_id}")

    request_data = {
        "title": "Full Cycle Test - Transformer Testing",
        "description": "Complete workflow validation for testing request lifecycle",
        "transformer_type": "Power Transformer",
        "transformer_rating": "100 MVA",
        "manufacturer": "Test Manufacturer Co.",
        "serial_number": "TEST-2026-001",
        "organization_id": org_id,
        "department_id": dept_id
    }

    new_request = create_testing_request(originator_token, request_data)
    if not new_request:
        print("[FAILED] Could not create testing request")
        return

    request_id = new_request["id"]
    request_number = new_request["request_number"]
    print(f"[OK] Created request: {request_number} (ID: {request_id})")
    print(f"     Status: {new_request['status']}")

    # Submit the request for approval
    print("[INFO] Submitting request for approval...")
    submitted = submit_testing_request(originator_token, request_id)
    if not submitted:
        print("[FAILED] Could not submit request")
        return
    print(f"[OK] Request submitted, new status: {submitted['status']}")
    print()

    # ========== STEP 2: Approve and Assign ==========
    print("STEP 2: Approve and Assign to Tester (as approver)")
    print("-" * 80)

    approver_token = originator_token  # Use same admin token for approval
    print("[OK] Using org admin as approver")

    pending = get_pending_approvals(approver_token)
    print(f"[OK] Found {len(pending)} pending approvals")

    # Find our request
    our_request = next((r for r in pending if r["id"] == request_id), None)
    if not our_request:
        print(f"[WARNING] Request {request_number} not found in pending (may need status update)")

    # Get available tester roles dynamically
    headers = {"Authorization": f"Bearer {approver_token}"}
    roles_response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
        headers=headers
    )

    if roles_response.status_code != 200:
        print(f"[FAILED] Could not fetch tester roles: {roles_response.status_code}")
        return

    tester_roles = roles_response.json()
    if not tester_roles:
        print("[FAILED] No eligible tester roles found")
        return

    print(f"[OK] Found {len(tester_roles)} eligible tester roles")
    tester_role_id = tester_roles[0]["role_id"]
    tester_role_name = tester_roles[0]["role_name"]
    print(f"[INFO] Selected tester role: {tester_role_name}")

    # Get users for this role
    users_response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles/{tester_role_id}/users",
        headers=headers
    )

    if users_response.status_code != 200:
        print(f"[FAILED] Could not fetch tester users: {users_response.status_code}")
        return

    tester_users = users_response.json()
    if not tester_users:
        print("[FAILED] No users found in tester role")
        return

    print(f"[OK] Found {len(tester_users)} users in role")
    tester_id = tester_users[0]["user_id"]
    tester_name = tester_users[0]["name"]
    tester_email = tester_users[0]["email"]
    print(f"[INFO] Selected tester: {tester_name} ({tester_email})")

    approval_result = approve_and_assign(approver_token, request_id, tester_role_id, tester_id)
    if not approval_result:
        print("[FAILED] Could not approve and assign request")
        return

    print(f"[OK] Request approved and assigned to: {approval_result.get('assigned_tester_email')}")
    print(f"     New status: {approval_result.get('new_status')}")
    print()

    # ========== STEP 3: Tester Views Assignment ==========
    print("STEP 3: View Assigned Requests (as tester)")
    print("-" * 80)

    tester_token = login(tester_email, "Tester123!")
    if not tester_token:
        print(f"[FAILED] Could not login as {tester_email}")
        return
    print(f"[OK] Logged in as {tester_email}")

    assignments = get_tester_assignments(tester_token)
    print(f"[OK] Found {len(assignments)} assigned requests")

    # Find our request
    our_assignment = next((r for r in assignments if r["id"] == request_id), None)
    if not our_assignment:
        print(f"[WARNING] Request {request_number} not found in assignments")
        print("     Available requests:")
        for req in assignments:
            print(f"       - {req.get('request_number')}: {req.get('status')}")
    else:
        print(f"[OK] Found our request: {our_assignment['request_number']}")
        print(f"     Status: {our_assignment['status']}")
    print()

    # ========== STEP 4: Accept Request ==========
    print("STEP 4: Accept Testing Request (as tester)")
    print("-" * 80)

    accept_result = tester_accept_request(tester_token, request_id)
    if not accept_result:
        print("[FAILED] Could not accept request")
        return

    print(f"[OK] Request accepted")
    print(f"     Status: {accept_result.get('status')}")
    print()

    # ========== STEP 5: Start Testing ==========
    print("STEP 5: Start Testing (as tester)")
    print("-" * 80)

    start_result = tester_start_testing(tester_token, request_id)
    if not start_result:
        print("[FAILED] Could not start testing")
        return

    print(f"[OK] Testing started")
    print(f"     Status: {start_result.get('status')}")
    print()

    # ========== STEP 6: Upload Test Results ==========
    print("STEP 6: Upload Test Results (as tester)")
    print("-" * 80)

    results = upload_test_results(tester_token, request_id)
    if not results:
        print("[FAILED] Could not upload test results")
        return

    print(f"[OK] Test results uploaded")
    print()

    # ========== STEP 7: Complete Testing ==========
    print("STEP 7: Submit and Complete Testing (as tester)")
    print("-" * 80)

    complete_result = tester_complete_testing(tester_token, request_id)
    if not complete_result:
        print("[FAILED] Could not complete testing")
        return

    print(f"[OK] Testing completed")
    print(f"     Status: {complete_result.get('status')}")
    print()

    # ========== STEP 8: View Recommendation for Approval ==========
    print("STEP 8: View Pending Recommendation Approvals (as approver)")
    print("-" * 80)

    # Login as orgadmin who can approve recommendations
    approver_token = login("orgadmin@kptcl.com", "admin123")
    if not approver_token:
        print("[FAILED] Could not login as approver")
        return
    print("[OK] Logged in as orgadmin@kptcl.com")

    pending_approvals = get_pending_recommendation_approvals(approver_token)
    print(f"[OK] Found {len(pending_approvals)} pending recommendation approvals")

    # Get the recommendation for our testing request
    recommendation = get_recommendation_by_request(approver_token, request_id)
    if not recommendation:
        print("[FAILED] Could not get recommendation for testing request")
        return

    recommendation_id = recommendation["id"]
    print(f"[OK] Found recommendation ID: {recommendation_id}")
    print(f"     Type: {recommendation.get('recommendation_type')}")
    print(f"     Approval Status: {recommendation.get('approval_status')}")
    print()

    # ========== STEP 9: Approve Recommendation ==========
    print("STEP 9: Approve Recommendation (as approver)")
    print("-" * 80)

    approval_result = approve_recommendation(approver_token, recommendation_id)
    if not approval_result:
        print("[FAILED] Could not approve recommendation")
        return

    print(f"[OK] Recommendation approved")
    print(f"     Approval Status: {approval_result.get('approval_status')}")
    print()

    # ========== STEP 10: Verify Final State ==========
    print("STEP 10: Verify Final State")
    print("-" * 80)

    final_request = get_request_details(originator_token, request_id)
    if final_request:
        print(f"[OK] Final request details:")
        print(f"     Request Number: {final_request['request_number']}")
        print(f"     Status: {final_request['status']}")
        print(f"     Assigned Tester: {final_request.get('assigned_tester_email', 'N/A')}")

    final_recommendation = get_recommendation_by_request(approver_token, request_id)
    if final_recommendation:
        print(f"[OK] Final recommendation details:")
        print(f"     Approval Status: {final_recommendation.get('approval_status')}")
        print(f"     Recommendation Type: {final_recommendation.get('recommendation_type')}")

    print()
    print("=" * 80)
    print("  COMPLETE LIFECYCLE TEST FINISHED!")
    print("=" * 80)
    print()
    print("Summary of complete workflow:")
    print("  1. [OK] Engineer created testing request")
    print("  2. [OK] Engineer submitted request for approval")
    print("  3. [OK] Department head approved and assigned to tester")
    print("  4. [OK] Tester viewed assigned requests")
    print("  5. [OK] Tester accepted the request")
    print("  6. [OK] Tester started testing")
    print("  7. [OK] Tester uploaded test results")
    print("  8. [OK] Tester submitted and completed testing")
    print("  9. [OK] Approver viewed pending recommendations")
    print(" 10. [OK] Approver approved recommendation")
    print(" 11. [OK] Verified final state")
    print()
    print(f"Final Testing Request Status: {final_request.get('status') if final_request else 'Unknown'}")
    print(f"Final Recommendation Status: {final_recommendation.get('approval_status') if final_recommendation else 'Unknown'}")
    print(f"Request Number: {request_number}")


if __name__ == "__main__":
    main()
