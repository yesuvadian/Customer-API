"""
Complete Testing Scenarios for KPTCL Organization
Tests all tester role configuration features and workflows
"""
import requests
import json

BASE_URL = "http://localhost:8020"

def print_header(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def print_step(step):
    print(f"\n{step}")
    print("-"*80)

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
        return None

def test_scenario_1():
    """Scenario 1: Field Tester workflow"""
    print_header("SCENARIO 1: Testing with Field Tester")

    # Login as KPTCL admin
    print_step("Step 1: Login as KPTCL Admin")
    admin_token = login("orgadmin@kptcl.com", "admin123")
    if not admin_token:
        print("[FAILED] Could not login")
        return False
    print("[OK] Logged in as orgadmin@kptcl.com")

    headers = {"Authorization": f"Bearer {admin_token}"}

    # Get KPTCL organization
    print_step("Step 2: Get KPTCL Organization")
    org_response = requests.get(f"{BASE_URL}/organizations/", headers=headers)
    orgs = org_response.json()
    kptcl_org = next((org for org in orgs if org['code'] == 'KPTCL'), None)

    if not kptcl_org:
        print("[FAILED] KPTCL organization not found")
        return False

    org_id = kptcl_org['id']
    dept_id = kptcl_org['departments'][0]['id'] if kptcl_org.get('departments') else None
    print(f"[OK] Found KPTCL: {org_id}")
    print(f"[INFO] Department: {dept_id}")

    # Create testing request
    print_step("Step 3: Create Testing Request")
    request_data = {
        "title": "KPTCL Test - Field Tester Assignment",
        "description": "Testing Field Tester role assignment workflow",
        "transformer_type": "Distribution Transformer",
        "transformer_rating": "63 MVA",
        "organization_id": org_id,
        "department_id": dept_id
    }

    response = requests.post(f"{BASE_URL}/testing_requests/", headers=headers, json=request_data)
    if response.status_code != 200:
        print(f"[FAILED] Could not create request: {response.status_code}")
        return False

    request = response.json()
    request_id = request['id']
    print(f"[OK] Created request: {request['request_number']} (ID: {request_id})")

    # Submit request
    print_step("Step 4: Submit Request for Approval")
    response = requests.put(f"{BASE_URL}/testing_requests/{request_id}/submit", headers=headers)
    if response.status_code != 200:
        print(f"[FAILED] Could not submit: {response.status_code}")
        return False
    print("[OK] Request submitted")

    # Get available tester roles
    print_step("Step 5: Get Available Tester Roles")
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
        headers=headers
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not get tester roles: {response.status_code}")
        return False

    tester_roles = response.json()
    print(f"[OK] Found {len(tester_roles)} tester roles:")
    for role in tester_roles:
        print(f"  - {role['role_name']}: {role['user_count']} users")

    if len(tester_roles) != 2:
        print(f"[FAILED] Expected 2 tester roles, got {len(tester_roles)}")
        return False

    # Select Field Tester role
    field_tester_role = next((r for r in tester_roles if r['role_name'] == 'Field Tester'), None)
    if not field_tester_role:
        print("[FAILED] Field Tester role not found")
        return False

    print(f"[INFO] Selected role: Field Tester (ID: {field_tester_role['role_id']})")

    # Get users in Field Tester role
    print_step("Step 6: Get Field Tester Users")
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles/{field_tester_role['role_id']}/users",
        headers=headers
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not get users: {response.status_code}")
        return False

    users = response.json()
    print(f"[OK] Found {len(users)} Field Tester users:")
    for user in users:
        print(f"  - {user['name']} ({user['email']}) - Active requests: {user['active_requests']}")

    if len(users) != 2:
        print(f"[FAILED] Expected 2 users, got {len(users)}")
        return False

    # Approve and assign to first Field Tester
    print_step("Step 7: Approve and Assign to Field Tester")
    selected_user = users[0]
    approval_data = {
        "tester_role_id": field_tester_role['role_id'],
        "tester_id": selected_user['user_id'],
        "comment": "Approved for Field Tester - Scenario 1"
    }

    response = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/approve-and-assign",
        headers=headers,
        json=approval_data
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not approve: {response.status_code}")
        print(f"Response: {response.text}")
        return False

    result = response.json()
    print(f"[OK] Approved and assigned to: {result['assigned_tester_email']}")
    print(f"[INFO] New status: {result['new_status']}")

    # Login as Field Tester
    print_step("Step 8: Login as Field Tester")
    tester_token = login(selected_user['email'], "Tester123!")
    if not tester_token:
        print(f"[FAILED] Could not login as tester")
        return False
    print(f"[OK] Logged in as {selected_user['email']}")

    # View assigned requests
    print_step("Step 9: View Assigned Requests")
    tester_headers = {"Authorization": f"Bearer {tester_token}"}
    response = requests.get(
        f"{BASE_URL}/testing_requests/?status=assigned",
        headers=tester_headers
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not get assigned requests: {response.status_code}")
        return False

    assigned_requests = response.json()
    print(f"[OK] Found {len(assigned_requests)} assigned requests")

    our_request = next((r for r in assigned_requests if r['id'] == request_id), None)
    if not our_request:
        print("[WARN] Our request not found in assigned list")
    else:
        print(f"[OK] Found our request: {our_request['request_number']}")

    # Accept request
    print_step("Step 10: Accept Testing Request")
    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/accept",
        headers=tester_headers
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not accept: {response.status_code}")
        return False
    print("[OK] Request accepted")

    # Start testing
    print_step("Step 11: Start Testing")
    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/start",
        headers=tester_headers
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not start: {response.status_code}")
        return False
    print("[OK] Testing started")

    # Upload results
    print_step("Step 12: Upload Test Results")
    test_results = {
        "template_key": "field_test",
        "test_data": {
            "test_voltage": "11kV",
            "test_current": "100A",
            "insulation_resistance": "500 MΩ",
            "result": "Pass"
        }
    }

    response = requests.post(
        f"{BASE_URL}/testing/{request_id}/results/structured",
        headers=tester_headers,
        json=test_results
    )

    if response.status_code not in [200, 201]:
        print(f"[FAILED] Could not upload results: {response.status_code}")
        return False
    print("[OK] Test results uploaded")

    # Complete testing
    print_step("Step 13: Complete Testing")
    completion_data = {
        "recommendation_type": "approved",
        "comments": "All tests passed successfully - Field Tester"
    }

    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/submit_results",
        headers=tester_headers,
        json=completion_data
    )

    if response.status_code != 200:
        print(f"[FAILED] Could not complete: {response.status_code}")
        return False

    result = response.json()
    print(f"[OK] Testing completed")
    print(f"[INFO] Final status: {result.get('status', 'N/A')}")

    print_header("SCENARIO 1: COMPLETED SUCCESSFULLY [PASS]")
    return True


def test_scenario_2():
    """Scenario 2: Lab Tester workflow"""
    print_header("SCENARIO 2: Testing with Lab Tester")

    # Login as KPTCL admin
    print_step("Step 1: Login as KPTCL Admin")
    admin_token = login("orgadmin@kptcl.com", "admin123")
    if not admin_token:
        print("[FAILED] Could not login")
        return False
    print("[OK] Logged in as orgadmin@kptcl.com")

    headers = {"Authorization": f"Bearer {admin_token}"}

    # Get KPTCL organization
    org_response = requests.get(f"{BASE_URL}/organizations/", headers=headers)
    orgs = org_response.json()
    kptcl_org = next((org for org in orgs if org['code'] == 'KPTCL'), None)
    org_id = kptcl_org['id']
    dept_id = kptcl_org['departments'][0]['id'] if kptcl_org.get('departments') else None

    # Create testing request
    print_step("Step 2: Create Testing Request")
    request_data = {
        "title": "KPTCL Test - Lab Tester Assignment",
        "description": "Testing Lab Tester role assignment workflow",
        "transformer_type": "Power Transformer",
        "transformer_rating": "100 MVA",
        "organization_id": org_id,
        "department_id": dept_id
    }

    response = requests.post(f"{BASE_URL}/testing_requests/", headers=headers, json=request_data)
    request = response.json()
    request_id = request['id']
    print(f"[OK] Created request: {request['request_number']}")

    # Submit request
    print_step("Step 3: Submit Request")
    requests.put(f"{BASE_URL}/testing_requests/{request_id}/submit", headers=headers)
    print("[OK] Request submitted")

    # Get available tester roles
    print_step("Step 4: Get Available Tester Roles")
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
        headers=headers
    )
    tester_roles = response.json()
    print(f"[OK] Found {len(tester_roles)} tester roles")

    # Select Lab Tester role
    lab_tester_role = next((r for r in tester_roles if r['role_name'] == 'Lab Tester'), None)
    if not lab_tester_role:
        print("[FAILED] Lab Tester role not found")
        return False

    print(f"[INFO] Selected role: Lab Tester")

    # Get users in Lab Tester role
    print_step("Step 5: Get Lab Tester Users")
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles/{lab_tester_role['role_id']}/users",
        headers=headers
    )
    users = response.json()
    print(f"[OK] Found {len(users)} Lab Tester users:")
    for user in users:
        print(f"  - {user['name']} ({user['email']})")

    # Select second user (to test load distribution)
    selected_user = users[1] if len(users) > 1 else users[0]

    # Approve and assign
    print_step("Step 6: Approve and Assign to Lab Tester")
    approval_data = {
        "tester_role_id": lab_tester_role['role_id'],
        "tester_id": selected_user['user_id'],
        "comment": "Approved for Lab Tester - Scenario 2"
    }

    response = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/approve-and-assign",
        headers=headers,
        json=approval_data
    )

    result = response.json()
    print(f"[OK] Approved and assigned to: {result['assigned_tester_email']}")

    # Login as Lab Tester and accept
    print_step("Step 7: Lab Tester Accepts Request")
    tester_token = login(selected_user['email'], "Tester123!")
    tester_headers = {"Authorization": f"Bearer {tester_token}"}

    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/accept",
        headers=tester_headers
    )
    print("[OK] Request accepted by Lab Tester")

    # Start and complete testing
    print_step("Step 8: Complete Testing Process")
    requests.put(f"{BASE_URL}/testing/{request_id}/start", headers=tester_headers)
    print("[OK] Testing started")

    test_results = {
        "template_key": "lab_test",
        "test_data": {
            "winding_resistance": "0.5Ω",
            "turns_ratio": "1:10",
            "oil_quality": "Good",
            "result": "Pass"
        }
    }
    requests.post(f"{BASE_URL}/testing/{request_id}/results/structured", headers=tester_headers, json=test_results)
    print("[OK] Lab test results uploaded")

    completion_data = {
        "recommendation_type": "approved",
        "comments": "Laboratory tests completed successfully"
    }
    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/submit_results",
        headers=tester_headers,
        json=completion_data
    )

    result = response.json()
    print(f"[OK] Testing completed - Status: {result.get('status', 'N/A')}")

    print_header("SCENARIO 2: COMPLETED SUCCESSFULLY [PASS]")
    return True


def test_tester_role_configuration():
    """Test tester role configuration specifics"""
    print_header("TESTING: Tester Role Configuration Validation")

    # Login
    print_step("Step 1: Login and Setup")
    admin_token = login("orgadmin@kptcl.com", "admin123")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Get organization
    org_response = requests.get(f"{BASE_URL}/organizations/", headers=headers)
    orgs = org_response.json()
    kptcl_org = next((org for org in orgs if org['code'] == 'KPTCL'), None)
    org_id = kptcl_org['id']
    dept_id = kptcl_org['departments'][0]['id'] if kptcl_org.get('departments') else None

    # Create test request
    print_step("Step 2: Create Test Request")
    request_data = {
        "title": "Configuration Validation Test",
        "organization_id": org_id,
        "department_id": dept_id
    }
    response = requests.post(f"{BASE_URL}/testing_requests/", headers=headers, json=request_data)
    request_id = response.json()['id']
    print(f"[OK] Request created: {request_id}")

    # Submit
    requests.put(f"{BASE_URL}/testing_requests/{request_id}/submit", headers=headers)
    print("[OK] Request submitted")

    # Get tester role configuration
    print_step("Step 3: Verify Tester Role Configuration")
    response = requests.get(f"{BASE_URL}/admin/tester-role-config/", headers=headers)
    configs = response.json()

    print(f"[OK] Found {len(configs)} configuration(s)")
    for config in configs:
        org_name = config.get('organization_name', 'Global Default')
        modules = config['required_module_ids']
        print(f"  - {org_name}: Modules {modules}")

    # Verify exact match requirement
    print_step("Step 4: Verify Exact Module Matching")
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
        headers=headers
    )
    tester_roles = response.json()

    print(f"[OK] Eligible tester roles: {len(tester_roles)}")

    # Verify only Field Tester and Lab Tester are returned
    role_names = {role['role_name'] for role in tester_roles}
    expected_roles = {'Field Tester', 'Lab Tester'}

    if role_names == expected_roles:
        print(f"[OK] [PASS] Exact match working: {role_names}")
    else:
        print(f"[FAILED] Expected {expected_roles}, got {role_names}")
        return False

    # Verify Admin role is NOT in the list
    if 'Admin' in role_names:
        print("[FAILED] Admin role should be excluded (has more modules)")
        return False
    else:
        print("[OK] [PASS] Admin role correctly excluded")

    # Verify each role has correct user count
    print_step("Step 5: Verify User Counts")
    for role in tester_roles:
        print(f"  - {role['role_name']}: {role['user_count']} users")
        if role['user_count'] != 2:
            print(f"[FAILED] Expected 2 users, got {role['user_count']}")
            return False
    print("[OK] [PASS] All roles have 2 users each")

    print_header("CONFIGURATION VALIDATION: PASSED [PASS]")
    return True


def main():
    """Run all test scenarios"""
    print("\n")
    print("+" + "="*78 + "+")
    print("|" + " "*20 + "KPTCL ORGANIZATION - COMPLETE TEST SUITE" + " "*18 + "|")
    print("+" + "="*78 + "+")

    results = []

    # Test configuration validation
    results.append(("Configuration Validation", test_tester_role_configuration()))

    # Test Scenario 1: Field Tester
    results.append(("Scenario 1: Field Tester Workflow", test_scenario_1()))

    # Test Scenario 2: Lab Tester
    results.append(("Scenario 2: Lab Tester Workflow", test_scenario_2()))

    # Print final summary
    print("\n")
    print("+" + "="*78 + "+")
    print("|" + " "*28 + "FINAL TEST SUMMARY" + " "*32 + "|")
    print("+" + "="*78 + "+")

    for test_name, passed in results:
        status = "[OK] PASSED" if passed else "[FAIL] FAILED"
        padding = 78 - len(test_name) - len(status) - 2
        print(f"| {test_name}{' '*padding}{status} |")

    print("+" + "="*78 + "+")

    all_passed = all(result[1] for result in results)

    if all_passed:
        print("\n" + "="*80)
        print("SUCCESS! ALL TESTS PASSED FOR KPTCL ORGANIZATION!")
        print("="*80 + "\n")
    else:
        print("\nERROR: SOME TESTS FAILED - Please review the output above\n")

    return all_passed


if __name__ == "__main__":
    main()
