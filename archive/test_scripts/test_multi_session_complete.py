"""
Comprehensive Multi-Session Testing Script
Tests all endpoints with different user roles and validates scenarios
"""
import requests
import json
from datetime import datetime, timedelta
import time

# Configuration
BASE_URL = "http://localhost:8001"
HEADERS = {"Content-Type": "application/json"}

# Color codes for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'=' * 80}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{text.center(80)}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'=' * 80}{Colors.END}\n")

def print_section(text):
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'─' * 80}{Colors.END}")
    print(f"{Colors.BLUE}{Colors.BOLD}{text}{Colors.END}")
    print(f"{Colors.BLUE}{'─' * 80}{Colors.END}")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.YELLOW}ℹ {text}{Colors.END}")

# Test users (from existing seed.py)
users = {
    "requester": {"email": "originator@sampleorg.com", "password": "Originator123!", "token": None},  # Originator role
    "approver": {"email": "testassigner@sampleorg.com", "password": "Assigner123!", "token": None},  # Test Assigner role
    "tester": {"email": "fieldtester1@sampleorg.com", "password": "Tester123!", "token": None},  # Field Tester role
    "result_approver": {"email": "orgadmin@sampleorg.com", "password": "OrgAdmin123!", "token": None}  # Org Admin can approve results
}

# Test data storage
test_data = {
    "organization_id": None,
    "department_id": None,
    "equipment_type_id": None,
    "test_type_id": None,
    "testing_request_id": None,
    "session_ids": [],
}

def login_user(user_type):
    """Login and get auth token"""
    print_info(f"Logging in as {user_type}...")

    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": users[user_type]["email"],
            "password": users[user_type]["password"]
        }
    )

    if response.status_code == 200:
        token = response.json()["access_token"]
        users[user_type]["token"] = token
        print_success(f"Logged in as {user_type}")
        return token
    else:
        print_error(f"Failed to login as {user_type}: {response.text}")
        return None

def get_auth_header(user_type):
    """Get authorization header for user"""
    return {
        **HEADERS,
        "Authorization": f"Bearer {users[user_type]['token']}"
    }

# ═════════════════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═════════════════════════════════════════════════════════════════════════════

def test_01_create_multi_session_request():
    """Test 1: Create a multi-session testing request"""
    print_section("TEST 1: Create Multi-Session Testing Request")

    # Calculate dates
    start_date = datetime.now() + timedelta(days=1)

    payload = {
        "title": "5-Week Transformer Monitoring Test",
        "description": "Monitor transformer load over 5 weeks with weekly sessions",
        "equipment_type_id": test_data["equipment_type_id"],
        "test_type_id": test_data["test_type_id"],
        "organization_id": test_data["organization_id"],
        "department_id": test_data["department_id"],
        "priority": "high",
        "scheduled_start_date": start_date.isoformat(),
        "is_multi_session": True,
        "total_sessions_planned": 5,
        "session_interval_days": 7,
        "status": "submitted"  # Submit directly for testing
    }

    response = requests.post(
        f"{BASE_URL}/testing_requests",
        headers=get_auth_header("requester"),
        json=payload
    )

    if response.status_code == 201:
        data = response.json()
        test_data["testing_request_id"] = data["id"]
        print_success(f"Created testing request: {data['id']}")
        print_info(f"  Title: {data['title']}")
        print_info(f"  Start Date: {data['scheduled_start_date']}")
        print_info(f"  Total Sessions: {data['total_sessions_planned']}")
        print_info(f"  Interval: {data['session_interval_days']} days")
        return True
    else:
        print_error(f"Failed to create testing request: {response.status_code}")
        print_error(response.text)
        return False

def test_02_approve_request():
    """Test 2: Submit and approve the request"""
    print_section("TEST 2: Submit and Approve Testing Request")

    request_id = test_data["testing_request_id"]

    # First submit the request
    response = requests.put(
        f"{BASE_URL}/testing_requests/{request_id}/submit",
        headers=get_auth_header("requester")
    )

    if response.status_code != 200:
        print_error(f"Failed to submit: {response.status_code}")
        return False

    print_success("Testing request submitted")

    # Get tester user ID for assignment
    response = requests.get(
        f"{BASE_URL}/users/me",
        headers=get_auth_header("tester")
    )
    if response.status_code != 200:
        print_error("Failed to get tester user ID")
        return False
    tester_id = response.json()["id"]

    # Get available tester roles
    response = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/tester-roles",
        headers=get_auth_header("approver")
    )
    if response.status_code != 200 or not response.json():
        print_error(f"Failed to get tester roles: {response.status_code}")
        if response.status_code == 200:
            print_error("No eligible tester roles found")
        return False

    roles = response.json()
    tester_role_id = roles[0]["role_id"]  # Use first available role
    print_info(f"Using tester role: {roles[0]['role_name']} ({roles[0]['user_count']} users available)")

    # Now approve and assign in one step
    response = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{request_id}/approve-and-assign",
        headers=get_auth_header("approver"),
        json={
            "tester_id": tester_id,
            "tester_role_id": tester_role_id
        }
    )

    if response.status_code == 200:
        print_success("Testing request approved and tester assigned")
        return True
    else:
        print_error(f"Failed to approve: {response.status_code}, {response.text}")
        return False

def test_03_assign_tester():
    """Test 3: Verify tester assignment"""
    print_section("TEST 3: Verify Tester Assignment")

    request_id = test_data["testing_request_id"]

    # Verify the request details
    response = requests.get(
        f"{BASE_URL}/testing_requests/{request_id}",
        headers=get_auth_header("tester")
    )

    if response.status_code == 200:
        data = response.json()
        if data.get("assigned_tester_id"):
            print_success(f"Tester assigned: {data['assigned_tester_id']}")
            print_info(f"  Status: {data['status']}")
            return True
        else:
            print_error("No tester assigned")
            return False
    else:
        print_error(f"Failed to get request: {response.status_code}")
        return False

def test_04_tester_accept():
    """Test 4: Tester accepts the assignment"""
    print_section("TEST 4: Tester Accepts Assignment")

    request_id = test_data["testing_request_id"]

    response = requests.put(
        f"{BASE_URL}/testing/{request_id}/accept",
        headers=get_auth_header("tester")
    )

    if response.status_code == 200:
        print_success("Tester accepted assignment")

        # Immediately start testing
        response = requests.put(
            f"{BASE_URL}/testing/{request_id}/start",
            headers=get_auth_header("tester")
        )

        if response.status_code == 200:
            print_success("Testing started (status: in_progress)")
            return True
        else:
            print_error(f"Failed to start testing: {response.status_code}")
            return False
    else:
        print_error(f"Failed to accept: {response.status_code}")
        return False

def test_05_auto_generate_sessions():
    """Test 5: Auto-generate all sessions"""
    print_section("TEST 5: Auto-Generate Sessions")

    request_id = test_data["testing_request_id"]

    response = requests.post(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/auto-generate",
        headers=get_auth_header("tester")
    )

    if response.status_code in [200, 201]:
        sessions = response.json()
        test_data["session_ids"] = [s["id"] for s in sessions]

        print_success(f"Generated {len(sessions)} sessions")
        print_info("Sessions created:")
        for i, session in enumerate(sessions, 1):
            print_info(f"  Session {i}: {session.get('session_date', 'N/A')} - {session.get('status', 'N/A')}")

        return True
    else:
        print_error(f"Failed to generate sessions: {response.status_code}")
        return False

def test_06_start_and_complete_session(session_number):
    """Test 6: Start session, add readings, complete session"""
    print_section(f"TEST 6: Conduct Session {session_number}")

    if session_number > len(test_data["session_ids"]):
        print_error(f"Session {session_number} does not exist")
        return False

    request_id = test_data["testing_request_id"]
    session_id = test_data["session_ids"][session_number - 1]

    # Start session
    print_info(f"Starting session {session_number}...")
    response = requests.post(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/start",
        headers=get_auth_header("tester")
    )

    if response.status_code != 200:
        print_error(f"Failed to start session: {response.status_code}")
        return False

    print_success(f"Session {session_number} started")

    # Add 3 readings
    for reading_num in range(1, 4):
        print_info(f"Adding reading {reading_num}...")

        reading_data = {
            "reading_number": reading_num,
            "reading_time": datetime.now().isoformat(),
            "reading_data": {
                "voltage": 11.5 + (reading_num * 0.1),
                "current": 145.0 + (reading_num * 5),
                "temperature": 60 + reading_num,
                "power_factor": 0.92
            },
            "equipment_serial": "METER-2024-001",
            "result_status": "pass" if reading_num < 3 else "warning",
            "remarks": f"Reading {reading_num} - All parameters within range"
        }

        response = requests.post(
            f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/readings",
            headers=get_auth_header("tester"),
            json=reading_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"Failed to add reading {reading_num}: {response.status_code}")
            return False

        print_success(f"Reading {reading_num} added")

    # Complete session
    print_info(f"Completing session {session_number}...")
    response = requests.post(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/complete",
        headers=get_auth_header("tester")
    )

    if response.status_code == 200:
        print_success(f"Session {session_number} completed")
        return True
    else:
        print_error(f"Failed to complete session: {response.status_code}")
        return False

def test_07_view_session_report(session_number):
    """Test 7: View detailed session report"""
    print_section(f"TEST 7: View Session {session_number} Report")

    request_id = test_data["testing_request_id"]
    session_id = test_data["session_ids"][session_number - 1]

    # Get session details
    response = requests.get(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}",
        headers=get_auth_header("approver")
    )

    if response.status_code == 200:
        session = response.json()
        print_success("Session report retrieved")
        print_info(f"  Session Number: {session['session_number']}")
        print_info(f"  Status: {session['status']}")
        print_info(f"  Started: {session.get('started_at', 'N/A')}")
        print_info(f"  Completed: {session.get('completed_at', 'N/A')}")
    else:
        print_error("Failed to get session details")
        return False

    # Get readings
    response = requests.get(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/readings",
        headers=get_auth_header("approver")
    )

    if response.status_code == 200:
        readings = response.json()
        print_success(f"Retrieved {len(readings)} readings")

        for reading in readings:
            status_color = Colors.GREEN if reading['result_status'] == 'pass' else Colors.YELLOW
            print_info(f"  Reading #{reading['reading_number']}: {status_color}{reading['result_status']}{Colors.END}")
            for key, value in reading['reading_data'].items():
                print_info(f"    {key}: {value}")

        return True
    else:
        print_error("Failed to get readings")
        return False

def test_08_add_approver_comment(session_number):
    """Test 8: Approver adds comment to session"""
    print_section(f"TEST 8: Add Approver Comment to Session {session_number}")

    request_id = test_data["testing_request_id"]
    session_id = test_data["session_ids"][session_number - 1]

    comment_text = f"Session {session_number} looks good. All readings are within acceptable parameters. Equipment calibration verified."

    response = requests.post(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/comments",
        headers=get_auth_header("approver"),
        json={"comment": comment_text}
    )

    if response.status_code in [200, 201]:
        print_success("Comment added successfully")

        # Get comments
        response = requests.get(
            f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/comments",
            headers=get_auth_header("approver")
        )

        if response.status_code == 200:
            comments = response.json()
            print_info(f"Total comments: {len(comments)}")
            for comment in comments:
                print_info(f"  {comment['author_name']}: {comment['comment'][:50]}...")
            return True
        else:
            return False
    else:
        print_error(f"Failed to add comment: {response.status_code}")
        return False

def test_09_check_session_statistics(session_number):
    """Test 9: Get session statistics"""
    print_section(f"TEST 9: Session {session_number} Statistics")

    request_id = test_data["testing_request_id"]
    session_id = test_data["session_ids"][session_number - 1]

    response = requests.get(
        f"{BASE_URL}/testing_requests/{request_id}/sessions/{session_id}/statistics",
        headers=get_auth_header("tester")
    )

    if response.status_code == 200:
        stats = response.json()
        print_success("Statistics retrieved")
        print_info(f"  Reading Count: {stats['reading_count']}")
        print_info(f"  Pass Count: {stats['pass_count']}")
        print_info(f"  Fail Count: {stats['fail_count']}")
        print_info(f"  Comment Count: {stats.get('comment_count', 0)}")
        print_info(f"  Duration: {stats.get('duration_minutes', 0)} minutes")
        return True
    else:
        print_error(f"Failed to get statistics: {response.status_code}")
        return False

def test_10_check_auto_transition():
    """Test 10: Check if test auto-transitioned to test_submitted"""
    print_section("TEST 10: Check Auto-Transition to test_submitted")

    request_id = test_data["testing_request_id"]

    response = requests.get(
        f"{BASE_URL}/testing_requests/{request_id}",
        headers=get_auth_header("requester")
    )

    if response.status_code == 200:
        data = response.json()
        status = data['status']

        if status == 'test_submitted':
            print_success("✓ Test auto-transitioned to test_submitted!")
            print_info(f"  Status: {status}")
            print_info("  Test is now in approver queue")
            return True
        else:
            print_error(f"Test status is '{status}', expected 'test_submitted'")
            return False
    else:
        print_error("Failed to get testing request details")
        return False

def test_11_final_approval():
    """Test 11: Result approver approves the test"""
    print_section("TEST 11: Final Approval")

    request_id = test_data["testing_request_id"]

    response = requests.put(
        f"{BASE_URL}/testing_requests/{request_id}/approve",
        headers=get_auth_header("result_approver")
    )

    if response.status_code == 200:
        print_success("Test approved!")

        # Get final status
        response = requests.get(
            f"{BASE_URL}/testing_requests/{request_id}",
            headers=get_auth_header("requester")
        )

        if response.status_code == 200:
            data = response.json()
            print_info(f"  Final Status: {data['status']}")
            return True
        else:
            return False
    else:
        print_error(f"Failed to approve: {response.status_code}")
        return False

# ═════════════════════════════════════════════════════════════════════════════
# MAIN TEST RUNNER
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print_header("MULTI-SESSION TESTING - COMPREHENSIVE TEST SUITE")

    print_info("Prerequisites:")
    print_info("  1. Database tables dropped and recreated")
    print_info("  2. Seed data loaded")
    print_info("  3. Backend running on http://localhost:8001")
    print_info("")
    input("Press Enter to continue...")

    # Step 1: Login all users
    print_section("STEP 1: Login All Users")
    for user_type in users.keys():
        if not login_user(user_type):
            print_error("Failed to login users. Exiting.")
            return

    # Step 2: Get test data (org, equipment type, etc.)
    print_section("STEP 2: Get Test Data")

    # Get organization
    response = requests.get(
        f"{BASE_URL}/organizations",
        headers=get_auth_header("requester")
    )
    if response.status_code == 200 and response.json():
        test_data["organization_id"] = response.json()[0]["id"]
        print_success(f"Organization ID: {test_data['organization_id']}")
    else:
        print_error("No organizations found")
        return

    # Get department for the organization
    response = requests.get(
        f"{BASE_URL}/organizations/{test_data['organization_id']}/departments/",
        headers=get_auth_header("requester")
    )
    if response.status_code == 200 and response.json():
        test_data["department_id"] = response.json()[0]["id"]
        print_success(f"Department ID: {test_data['department_id']}")
    else:
        print_error("No departments found")
        return

    # Get equipment types
    response = requests.get(
        f"{BASE_URL}/testing_requests/equipment_types",
        headers=get_auth_header("requester")
    )
    if response.status_code == 200 and response.json():
        equipment = response.json()[0]
        test_data["equipment_type_id"] = equipment["id"]
        test_data["test_type_id"] = equipment["test_types"][0]["id"] if equipment.get("test_types") else None
        print_success(f"Equipment Type ID: {test_data['equipment_type_id']}")
        print_success(f"Test Type ID: {test_data['test_type_id']}")
    else:
        print_error("No equipment types found")
        return

    # Run test scenarios
    tests_passed = 0
    tests_failed = 0

    test_scenarios = [
        ("Create Multi-Session Request", test_01_create_multi_session_request),
        ("Approve Request", test_02_approve_request),
        ("Assign Tester", test_03_assign_tester),
        ("Tester Accept", test_04_tester_accept),
        ("Auto-Generate Sessions", test_05_auto_generate_sessions),
        ("Conduct Session 1", lambda: test_06_start_and_complete_session(1)),
        ("View Session 1 Report", lambda: test_07_view_session_report(1)),
        ("Add Comment to Session 1", lambda: test_08_add_approver_comment(1)),
        ("Session 1 Statistics", lambda: test_09_check_session_statistics(1)),
        ("Conduct Session 2", lambda: test_06_start_and_complete_session(2)),
        ("Add Comment to Session 2", lambda: test_08_add_approver_comment(2)),
        ("Conduct Session 3", lambda: test_06_start_and_complete_session(3)),
        ("Conduct Session 4", lambda: test_06_start_and_complete_session(4)),
        ("Conduct Session 5", lambda: test_06_start_and_complete_session(5)),
        ("Check Auto-Transition", test_10_check_auto_transition),
        ("Final Approval", test_11_final_approval),
    ]

    for test_name, test_func in test_scenarios:
        try:
            if test_func():
                tests_passed += 1
            else:
                tests_failed += 1
        except Exception as e:
            print_error(f"Exception in {test_name}: {str(e)}")
            tests_failed += 1

        # Small delay between tests
        time.sleep(1)

    # Summary
    print_header("TEST SUMMARY")
    total_tests = tests_passed + tests_failed
    success_rate = (tests_passed / total_tests * 100) if total_tests > 0 else 0

    print(f"\n{Colors.BOLD}Total Tests: {total_tests}{Colors.END}")
    print(f"{Colors.GREEN}Passed: {tests_passed}{Colors.END}")
    print(f"{Colors.RED}Failed: {tests_failed}{Colors.END}")
    print(f"{Colors.CYAN}Success Rate: {success_rate:.1f}%{Colors.END}\n")

    if tests_failed == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}🎉 ALL TESTS PASSED! 🎉{Colors.END}\n")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  SOME TESTS FAILED{Colors.END}\n")

if __name__ == "__main__":
    main()
