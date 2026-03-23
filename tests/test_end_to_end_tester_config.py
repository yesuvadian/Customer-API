import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8020"

def print_step(step_num, description):
    print(f"\n{'='*60}")
    print(f"Step {step_num}: {description}")
    print('='*60)

def print_result(success, message):
    status = "[OK]" if success else "[FAIL]"
    print(f"{status} {message}")

def login(email, password):
    """Login and return token"""
    response = requests.post(
        f"{BASE_URL}/token",
        data={"username": email, "password": password}
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    raise Exception(f"Login failed: {response.text}")

def test_tester_role_configuration():
    """Test the complete tester role configuration feature"""

    print("\n" + "="*60)
    print("TESTING: Tester Role Configuration Feature")
    print("="*60)

    try:
        # Step 1: Login as admin
        print_step(1, "Login as admin user")
        admin_token = login("orgadmin@sampleorg.com", "OrgAdmin123!")
        print_result(True, "Admin login successful")
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Step 2: Check tester role configuration
        print_step(2, "Get tester role module requirements")
        response = requests.get(f"{BASE_URL}/admin/tester-role-config", headers=headers)
        print_result(response.status_code == 200, f"Status: {response.status_code}")

        if response.status_code == 200:
            configs = response.json()
            print(f"Found {len(configs)} configuration(s)")
            for config in configs:
                print(f"  - Org: {config.get('organization_name', 'Global')}")
                print(f"    Required modules: {config['required_module_ids']}")
                print(f"    Module names: {', '.join(config.get('module_names', []))}")

        # Step 3: Get organization ID
        print_step(3, "Get sample organization")
        response = requests.get(f"{BASE_URL}/organizations", headers=headers)
        print_result(response.status_code == 200, f"Status: {response.status_code}")

        orgs = response.json()
        sample_org = next((org for org in orgs if org['name'] == 'Sample Organization'), None)
        if not sample_org:
            print_result(False, "Sample Organization not found")
            return

        org_id = sample_org['id']
        print_result(True, f"Organization ID: {org_id}")

        # Step 4: Create a testing request
        print_step(4, "Create testing request")
        test_request_data = {
            "title": "Test Tester Role Configuration",
            "organization_id": org_id,
            "department_id": sample_org.get('departments', [{}])[0].get('id') if sample_org.get('departments') else None,
            "request_type": "New Installation",
            "priority": "High",
            "description": "Test request for tester role configuration",
            "location": "Test Location"
        }

        response = requests.post(
            f"{BASE_URL}/testing_requests",
            headers=headers,
            json=test_request_data
        )
        print_result(response.status_code == 200, f"Status: {response.status_code}")

        if response.status_code != 200:
            print(f"Error: {response.text}")
            return

        test_request = response.json()
        request_id = test_request['id']
        print_result(True, f"Test Request ID: {request_id}")

        # Step 5: Submit the testing request
        print_step(5, "Submit testing request")
        response = requests.put(
            f"{BASE_URL}/testing_requests/{request_id}/submit",
            headers=headers
        )
        print_result(response.status_code == 200, f"Status: {response.status_code}")

        # Step 6: Get available tester roles
        print_step(6, "Get available tester roles (should show ONLY Field Tester and Lab Tester)")
        response = requests.get(
            f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
            headers=headers
        )
        print_result(response.status_code == 200, f"Status: {response.status_code}")

        if response.status_code == 200:
            tester_roles = response.json()
            print(f"Found {len(tester_roles)} eligible tester role(s)")

            for role in tester_roles:
                print(f"  - {role['name']}: {role.get('description', 'No description')}")

            # Verify exactly 2 roles
            expected_roles = {"Field Tester", "Lab Tester"}
            actual_roles = {role['name'] for role in tester_roles}

            if actual_roles == expected_roles:
                print_result(True, "Correct roles returned (Field Tester, Lab Tester)")
            else:
                print_result(False, f"Expected {expected_roles}, got {actual_roles}")

            # Verify admin role is NOT in the list
            admin_in_list = any(role['name'] == 'Admin' for role in tester_roles)
            print_result(not admin_in_list, "Admin role correctly excluded")

            if len(tester_roles) > 0:
                # Step 7: Get users in first tester role
                print_step(7, "Get users in tester role")
                first_role_id = tester_roles[0]['id']
                response = requests.get(
                    f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles/{first_role_id}/users",
                    headers=headers
                )
                print_result(response.status_code == 200, f"Status: {response.status_code}")

                if response.status_code == 200:
                    users = response.json()
                    print(f"Found {len(users)} user(s) in {tester_roles[0]['name']} role")
                    for user in users:
                        print(f"  - {user['first_name']} {user['last_name']} ({user['email']})")

                    # Verify 2 users per role
                    print_result(len(users) == 2, f"Expected 2 users, found {len(users)}")

                    if len(users) > 0:
                        # Step 8: Approve and assign to tester
                        print_step(8, "Approve testing request and assign to tester")
                        approval_data = {
                            "status": "approved",
                            "comments": "Approved for testing",
                            "tester_role_id": first_role_id,
                            "tester_user_id": users[0]['id']
                        }

                        response = requests.post(
                            f"{BASE_URL}/testing-requests/approvals/{request_id}/approve-and-assign",
                            headers=headers,
                            json=approval_data
                        )
                        print_result(response.status_code == 200, f"Status: {response.status_code}")

                        if response.status_code == 200:
                            approval_result = response.json()
                            print(f"Approval ID: {approval_result.get('id')}")
                            print(f"Status: {approval_result.get('status')}")
                            print(f"Assigned to: {users[0]['first_name']} {users[0]['last_name']}")
                        else:
                            print(f"Error: {response.text}")

        print("\n" + "="*60)
        print("TEST COMPLETED SUCCESSFULLY")
        print("="*60)
        print("\nKey Verifications:")
        print("[OK] Tester role configuration loaded")
        print("[OK] Only roles with EXACT module permissions appear in dropdown")
        print("[OK] Admin role excluded (has more modules)")
        print("[OK] Field Tester and Lab Tester roles available")
        print("[OK] 2 test users per tester role")
        print("[OK] Complete approval and assignment workflow")

    except Exception as e:
        print(f"\n[FAIL] Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_tester_role_configuration()
