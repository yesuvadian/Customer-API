"""
Test the complete Testing Request approval workflow
"""
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

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

def create_testing_request(token):
    """Create a testing request as KPTCL engineer"""
    headers = {"Authorization": f"Bearer {token}"}

    # First get the organization departments to select one
    org_response = requests.get(
        f"{BASE_URL}/organizations/my-organization",
        headers=headers
    )
    if org_response.status_code != 200:
        print(f"[ERROR] Failed to get organization: {org_response.status_code}")
        print(f"Response: {org_response.text}")
        return None

    org_data = org_response.json()
    org_id = org_data["id"]
    print(f"[INFO] Organization: {org_data['name']} (ID: {org_id})")

    # Get departments
    dept_response = requests.get(
        f"{BASE_URL}/organizations/{org_id}/departments/",
        headers=headers
    )
    if dept_response.status_code != 200:
        print(f"[ERROR] Failed to get departments: {dept_response.status_code}")
        return None

    departments = dept_response.json()
    if not departments:
        print("[ERROR] No departments found")
        return None

    # Use first department
    dept_id = departments[0]["id"]
    dept_name = departments[0]["name"]
    print(f"[INFO] Using department: {dept_name} (ID: {dept_id})")

    # Create testing request
    request_data = {
        "request_number": f"TR-TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "title": "Approval Workflow Test Request",
        "testing_type": "acceptance",
        "priority": "high",
        "description": "Test request for approval workflow validation",
        "expected_outcome": "Verify approval flow works correctly",
        "test_environment": "Lab environment",
        "department_id": dept_id,
        "components": [
            {
                "component_name": "Test Component",
                "manufacturer": "Test Manufacturer",
                "model_number": "TEST-001",
                "quantity": 5,
                "serial_numbers": ["SN001", "SN002", "SN003", "SN004", "SN005"],
                "specifications": {
                    "voltage": "11kV",
                    "power": "100kW"
                },
                "test_parameters": ["Voltage withstand", "Insulation resistance"]
            }
        ]
    }

    response = requests.post(
        f"{BASE_URL}/testing_requests/",
        headers=headers,
        json=request_data
    )

    if response.status_code in [200, 201]:
        data = response.json()
        print(f"\n[SUCCESS] Testing request created!")
        print(f"  Request ID: {data['id']}")
        print(f"  Request Number: {data['request_number']}")
        print(f"  Status: {data['status']}")
        print(f"  Department: {data.get('department_name', 'N/A')}")
        return data["id"]
    else:
        print(f"[ERROR] Failed to create testing request: {response.status_code}")
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
            print(f"  - {req['request_number']}: {req['description'][:50]}")
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
        f"{BASE_URL}/testing-requests/approvals/{request_id}/testers/{role_id}",
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
        "tester_role_id": role_id,
        "tester_id": tester_id,
        "comment": "Approved for testing - automated test"
    }

    response = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/approve",
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
    print("  TESTING REQUEST APPROVAL WORKFLOW TEST")
    print("=" * 80)
    print()

    # Step 1: Login as KPTCL Engineer and create request
    print("Step 1: Login as KPTCL Engineer and create testing request")
    print("-" * 80)
    engineer_token = login("engineer@kptcl.com", "admin123")
    if not engineer_token:
        print("[FAILED] Could not login as engineer")
        return

    request_id = create_testing_request(engineer_token)
    if not request_id:
        print("[FAILED] Could not create testing request")
        return

    # Step 2: Login as Department Head and view pending approvals
    print("\n\nStep 2: Login as Department Head and view pending approvals")
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
    our_request = next((r for r in pending if r["id"] == request_id), None)
    if not our_request:
        print(f"[ERROR] Our request {request_id} not found in pending approvals")
        return

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
        print("  WORKFLOW TEST COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Summary:")
        print(f"  1. ✓ Engineer created testing request (ID: {request_id})")
        print(f"  2. ✓ Request appeared in department head's approval queue")
        print(f"  3. ✓ Department head approved and assigned to tester")
        print(f"  4. ✓ Tester: {selected_tester['email']}")
        print()
        print("Next steps to verify in Flutter app:")
        print("  1. Login as depthead@kptcl.com")
        print("  2. Check 'Testing Request Approvals' - should be empty now")
        print(f"  3. Login as {selected_tester['email']}")
        print("  4. Check 'Testing Requests' - should see the assigned request")
    else:
        print("\n[FAILED] Workflow test failed at approval step")

if __name__ == "__main__":
    main()
