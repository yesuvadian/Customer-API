"""
Test the approval workflow starting from Step 2 (with existing request)
"""
import requests

BASE_URL = "http://localhost:8020"
REQUEST_ID = "5a56571f-42e7-4f38-bc3f-30eb76db3002"  # From previous run

def login(email, password):
    """Login and get JWT token"""
    response = requests.post(
        f"{BASE_URL}/token",
        data={"username": email, "password": password}
    )
    if response.status_code == 200:
        data = response.json()
        return data["access_token"]
    else:
        print(f"[ERROR] Login failed for {email}: {response.status_code}")
        print(response.text)
        return None

def get_pending_approvals(token):
    """Get pending approvals as department head"""
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/pending",
        headers=headers
    )

    if response.status_code == 200:
        data = response.json()
        print(f"\n[INFO] Found {len(data)} pending approvals")
        for req in data:
            print(f"  - {req['request_number']}: {req['description'][:50] if 'description' in req else 'N/A'}")
        return data
    else:
        print(f"[ERROR] Failed to get pending approvals: {response.status_code}")
        print(response.text)
        return []

def get_tester_roles(token, request_id):
    """Get available tester roles for assignment"""
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
        headers=headers
    )

    if response.status_code == 200:
        data = response.json()
        print(f"\n[INFO] Found {len(data)} tester roles")
        for role in data:
            print(f"  - {role['role_name']} (ID: {role['role_id']}, Users: {role['user_count']})")
        return data
    else:
        print(f"[ERROR] Failed to get tester roles: {response.status_code}")
        print(response.text)
        return []

def get_testers_by_role(token, request_id, role_id):
    """Get available testers for a specific role"""
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles/{role_id}/users",
        headers=headers
    )

    if response.status_code == 200:
        data = response.json()
        print(f"\n[INFO] Found {len(data)} testers in role")
        for tester in data:
            print(f"  - {tester['name']} ({tester['email']}) - Active requests: {tester['active_requests']}")
        return data
    else:
        print(f"[ERROR] Failed to get testers: {response.status_code}")
        print(response.text)
        return []

def approve_and_assign(token, request_id, role_id, tester_id):
    """Approve request and assign to tester"""
    headers = {"Authorization": f"Bearer {token}"}

    approval_data = {
        "tester_role_id": str(role_id),
        "tester_id": str(tester_id),
        "comment": "Approved for testing - automated test"
    }

    response = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/approve-and-assign",
        headers=headers,
        json=approval_data
    )

    if response.status_code == 200:
        data = response.json()
        print(f"\n[SUCCESS] Request approved and assigned!")
        print(f"  Message: {data['message']}")
        print(f"  Assigned to: {data.get('assigned_tester_email', 'N/A')}")
        print(f"  New status: {data['new_status']}")
        return True
    else:
        print(f"[ERROR] Failed to approve: {response.status_code}")
        print(response.text)
        return False

def main():
    print("=" * 80)
    print("  TESTING APPROVAL WORKFLOW (Starting from Step 2)")
    print("=" * 80)
    print()

    # Step 2: Login as Department Head and view pending approvals
    print("Step 2: Login as Department Head and view pending approvals")
    print("-" * 80)
    depthead_token = login("depthead@kptcl.com", "admin123")
    if not depthead_token:
        print("[FAILED] Could not login as department head")
        return

    pending = get_pending_approvals(depthead_token)
    if not pending:
        print("[FAILED] No pending approvals found")
        return

    # Find our request
    our_request = next((r for r in pending if r["id"] == REQUEST_ID), None)
    if not our_request:
        print(f"[ERROR] Request {REQUEST_ID} not found in pending approvals")
        print(f"Using first available request instead...")
        our_request = pending[0]

    # Use the actual request ID from the found request
    request_id = our_request["id"]

    # Step 3: Get tester roles
    print("\n\nStep 3: Get available tester roles")
    print("-" * 80)
    tester_roles = get_tester_roles(depthead_token, request_id)
    if not tester_roles:
        print("[FAILED] No tester roles found")
        return

    # Use first role
    selected_role = tester_roles[0]
    print(f"\n[INFO] Selected role: {selected_role['role_name']}")

    # Step 4: Get testers in selected role
    print("\n\nStep 4: Get available testers in selected role")
    print("-" * 80)
    testers = get_testers_by_role(depthead_token, request_id, selected_role["role_id"])
    if not testers:
        print("[FAILED] No testers found in role")
        return

    # Use tester with least workload
    selected_tester = min(testers, key=lambda t: t["active_requests"])
    print(f"\n[INFO] Selected tester: {selected_tester['name']} (workload: {selected_tester['active_requests']})")

    # Step 5: Approve and assign
    print("\n\nStep 5: Approve request and assign to tester")
    print("-" * 80)
    success = approve_and_assign(
        depthead_token,
        request_id,
        selected_role["role_id"],
        selected_tester["user_id"]
    )

    if success:
        print("\n\n" + "=" * 80)
        print("  APPROVAL WORKFLOW TEST COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Summary:")
        print(f"  1. [OK] Department head viewed pending approvals")
        print(f"  2. [OK] Selected tester role and user")
        print(f"  3. [OK] Approved and assigned request to tester")
        print(f"  4. [OK] Tester: {selected_tester['email']}")
        print()
        print("Next steps to verify in Flutter app:")
        print("  1. Login as depthead@kptcl.com")
        print("  2. Check 'Testing Request Approvals' - should be empty now")
        print(f"  3. Login as {selected_tester['email']}")
        print("  4. Check 'Testing Requests' - should see the assigned request")
    else:
        print("\n[FAILED] Approval workflow test failed")

if __name__ == "__main__":
    main()
