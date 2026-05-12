"""
Shared fixtures for outcome regression tests.
Run against the live server on http://localhost:8000
"""
import time
import pytest
import requests as req_lib

BASE = "http://localhost:8000"

# ── Users that must exist in the DB (seeded via seed.py) ─────────────────────
USERS = {
    "originator": ("originator@kptcl.com",    "admin123"),
    "admin":      ("orgadmin@kptcl.com",       "admin123"),
    "tester":     ("fieldtester1@kptcl.com",   "Tester123!"),
}


def wait_for_server(timeout: int = 30, interval: float = 2.0) -> bool:
    """
    Poll the health endpoint until the server responds or timeout expires.
    Used as an autouse fixture so every test class waits if the server reloaded.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = req_lib.get(f"{BASE}/testing_requests/stats",
                            headers={"Authorization": "Bearer dummy"},
                            timeout=3)
            # Any response (even 401) means the server is up
            if r.status_code < 600:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


@pytest.fixture(autouse=True, scope="class")
def ensure_server_up():
    """Wait for the API server before each test class executes."""
    ok = wait_for_server(timeout=30)
    if not ok:
        pytest.skip("API server on :8000 is not responding -- start uvicorn first")


# ── Colour / tag helpers used in test output ──────────────────────────────────
def _login(email: str, password: str) -> str:
    r = req_lib.post(f"{BASE}/token", data={"username": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:120]}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def tokens():
    """Log in all 4 users once per test session and return token dict."""
    t = {}
    for key, (email, pwd) in USERS.items():
        try:
            t[key] = _login(email, pwd)
        except AssertionError as e:
            pytest.skip(str(e))
    return t


@pytest.fixture(scope="session")
def org_info(tokens):
    """Return (org_id, dept_id) for KPTCL (or first available org)."""
    hdrs = {"Authorization": f"Bearer {tokens['admin']}"}
    r = req_lib.get(f"{BASE}/organizations/", headers=hdrs)
    assert r.status_code == 200, f"Cannot list orgs: {r.status_code}"
    orgs = r.json()
    org = next((o for o in orgs if o.get("code") == "KPTCL"), orgs[0] if orgs else None)
    assert org, "No organisation found in DB — run seed.py first"

    org_id = org["id"]
    # Fetch department tree
    r2 = req_lib.get(
        f"{BASE}/testing_requests/department_hierarchy?org_id={org_id}", headers=hdrs
    )
    depts = r2.json() if r2.status_code == 200 else []
    dept_id = depts[0]["id"] if depts else None
    return org_id, dept_id


@pytest.fixture(scope="session")
def sample_equipment(tokens):
    """Return first equipment asset (or None)."""
    hdrs = {"Authorization": f"Bearer {tokens['admin']}"}
    r = req_lib.get(f"{BASE}/equipment/?limit=1", headers=hdrs)
    items = r.json() if r.status_code == 200 else []
    return items[0] if items else None
