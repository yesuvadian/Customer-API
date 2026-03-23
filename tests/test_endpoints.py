#!/usr/bin/env python3
"""
API Endpoints Testing Script
Tests critical endpoints to verify they work correctly
"""

import requests
import json
import sys
from time import sleep

BASE_URL = "http://localhost:8000"

# ANSI colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_success(msg):
    print(f"{GREEN}✓{RESET} {msg}")

def print_error(msg):
    print(f"{RED}✗{RESET} {msg}")

def print_info(msg):
    print(f"{BLUE}ℹ{RESET} {msg}")

def print_warning(msg):
    print(f"{YELLOW}⚠{RESET} {msg}")

# Store token globally
access_token = None

def test_server_health():
    """Test if server is running"""
    print("\n" + "="*60)
    print("TEST 1: Server Health Check")
    print("="*60)

    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            print_success("Server is running")
            return True
        else:
            print_error(f"Server returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print_error("Cannot connect to server. Is it running?")
        print_info(f"Start server with: python main.py")
        return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_login():
    """Test login endpoint"""
    global access_token

    print("\n" + "="*60)
    print("TEST 2: Login as Engineer")
    print("="*60)

    url = f"{BASE_URL}/auth/login"
    payload = {
        "email": "engineer@kptcl.com",
        "password": "admin123"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            print_success(f"Login successful")
            print_info(f"User: {data.get('user', {}).get('firstname')} {data.get('user', {}).get('lastname')}")
            print_info(f"Email: {data.get('user', {}).get('email')}")
            print_info(f"Token: {access_token[:50]}...")
            return True
        else:
            print_error(f"Login failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_get_current_user():
    """Test get current user endpoint"""
    print("\n" + "="*60)
    print("TEST 3: Get Current User")
    print("="*60)

    if not access_token:
        print_error("No access token. Login first.")
        return False

    url = f"{BASE_URL}/users/me"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            print_success("User data retrieved")
            print_info(f"ID: {data.get('id')}")
            print_info(f"Name: {data.get('firstname')} {data.get('lastname')}")
            print_info(f"Email: {data.get('email')}")
            print_info(f"Department ID: {data.get('department_id')}")
            print_info(f"Organization ID: {data.get('organization_id')}")
            return True
        else:
            print_error(f"Failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_list_testing_requests():
    """Test list testing requests endpoint"""
    print("\n" + "="*60)
    print("TEST 4: List Testing Requests")
    print("="*60)

    if not access_token:
        print_error("No access token. Login first.")
        return False

    url = f"{BASE_URL}/testing_requests/"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else 0
            print_success(f"Retrieved {count} testing requests")
            if count > 0:
                print_info(f"First request ID: {data[0].get('id')}")
            return True
        else:
            print_error(f"Failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_get_organizations():
    """Test list organizations endpoint"""
    print("\n" + "="*60)
    print("TEST 5: List Organizations")
    print("="*60)

    if not access_token:
        print_error("No access token. Login first.")
        return False

    url = f"{BASE_URL}/organizations/"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else 0
            print_success(f"Retrieved {count} organizations")
            if count > 0:
                org = data[0]
                print_info(f"Organization: {org.get('name')}")
                print_info(f"Code: {org.get('code')}")
                print_info(f"ID: {org.get('id')}")
            return True
        else:
            print_error(f"Failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_get_departments():
    """Test list departments endpoint"""
    print("\n" + "="*60)
    print("TEST 6: List Departments (KPTCL)")
    print("="*60)

    if not access_token:
        print_error("No access token. Login first.")
        return False

    # First get org ID
    url = f"{BASE_URL}/organizations/"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print_error("Cannot get organizations")
            return False

        orgs = response.json()
        if not orgs:
            print_warning("No organizations found")
            return False

        org_id = orgs[0].get('id')

        # Now get departments
        url = f"{BASE_URL}/organizations/{org_id}/departments/"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else 0
            print_success(f"Retrieved {count} departments")

            # Show hierarchy
            if count > 0:
                print_info("Department Hierarchy:")
                for dept in data[:5]:  # Show first 5
                    print(f"  - {dept.get('name')} (Level {dept.get('hierarchy_level', 'N/A')})")
            return True
        else:
            print_error(f"Failed: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_workload_stats():
    """Test tester workload stats endpoint"""
    print("\n" + "="*60)
    print("TEST 7: Tester Workload Statistics")
    print("="*60)

    if not access_token:
        print_error("No access token. Login first.")
        return False

    url = f"{BASE_URL}/tester-assignment/workload-stats"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            testers = data.get('testers', [])
            print_success(f"Retrieved workload stats for {len(testers)} testers")

            for tester in testers:
                print_info(f"Tester: {tester.get('name')}")
                print(f"    Active: {tester.get('active_requests', 0)}")
                print(f"    Completed: {tester.get('completed_requests', 0)}")
            return True
        else:
            print_error(f"Failed: {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_workflows():
    """Test list workflows endpoint"""
    print("\n" + "="*60)
    print("TEST 8: List Workflows")
    print("="*60)

    if not access_token:
        print_error("No access token. Login first.")
        return False

    url = f"{BASE_URL}/workflows/"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else 0
            print_success(f"Retrieved {count} workflows")

            if count > 0:
                wf = data[0]
                print_info(f"Workflow: {wf.get('name')}")
                print_info(f"Type: {wf.get('workflow_type')}")
                print_info(f"States: {wf.get('states_count', 'N/A')}")
            return True
        else:
            print_error(f"Failed: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("  API ENDPOINTS TESTING")
    print("="*70)
    print(f"Target: {BASE_URL}")
    print()

    results = []

    # Test 1: Server health
    results.append(("Server Health", test_server_health()))

    if not results[0][1]:
        print("\n" + "="*70)
        print_error("Server is not running. Cannot continue tests.")
        print_info("Start server with: python main.py")
        print("="*70)
        return

    # Test 2: Login
    results.append(("Login", test_login()))

    if not results[1][1]:
        print("\n" + "="*70)
        print_error("Login failed. Cannot continue tests.")
        print_info("Check database is seeded: run reset_and_seed_local.ps1")
        print("="*70)
        return

    # Run remaining tests
    results.append(("Get Current User", test_get_current_user()))
    results.append(("List Testing Requests", test_list_testing_requests()))
    results.append(("List Organizations", test_get_organizations()))
    results.append(("List Departments", test_get_departments()))
    results.append(("Workload Statistics", test_workload_stats()))
    results.append(("List Workflows", test_workflows()))

    # Summary
    print("\n" + "="*70)
    print("  TEST SUMMARY")
    print("="*70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        color = GREEN if result else RED
        print(f"{color}{status:6}{RESET} {test_name}")

    print("="*70)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print_success("All tests passed!")
    else:
        print_error(f"{total - passed} test(s) failed")

    print("="*70)

if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
        sys.exit(1)
