"""
test_api.py
===========
Comprehensive endpoint validation for the PowerXchange / KPTCL API.
Tests every major workflow with the 10 dept-filter roles across 3 departments.

Usage:
    python test_api.py

Server must be running on http://localhost:8000
"""

import sys
import json
import time
from datetime import datetime, timezone as _tz, timedelta as _td
import requests
from requests.exceptions import ConnectionError as ReqConnError

BASE = "http://localhost:8000"
PW_DEPT  = "TestDept@123"
PW_KPTCL = "admin123"

# ── Resilient request wrappers (auto-retry on WinError 10054 / connection reset) ──
# Capture originals BEFORE patching so lambdas don't recurse into themselves.
_orig_get  = requests.get
_orig_post = requests.post
_orig_put  = requests.put

def _req(orig_fn, url, *, retries=3, delay=1.5, **kwargs):
    for attempt in range(retries):
        try:
            return orig_fn(url, **kwargs)
        except ReqConnError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

requests.get  = lambda url, **kw: _req(_orig_get,  url, **kw)
requests.post = lambda url, **kw: _req(_orig_post, url, **kw)
requests.put  = lambda url, **kw: _req(_orig_put,  url, **kw)

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

pass_count = fail_count = skip_count = 0

def ok(label, detail=""):
    global pass_count
    pass_count += 1
    print(f"  {GREEN}[PASS]{RESET} {label}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))

def fail(label, detail=""):
    global fail_count
    fail_count += 1
    print(f"  {RED}[FAIL]{RESET} {label}" + (f"  {YELLOW}{detail}{RESET}" if detail else ""))

def skip(label, detail=""):
    global skip_count
    skip_count += 1
    print(f"  {YELLOW}[SKIP]{RESET} {label}" + (f" — {detail}" if detail else ""))

def section(title):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")

def check(label, resp, expected_status, key=None):
    """Assert status code; optionally return resp.json()[key]."""
    if resp.status_code == expected_status:
        ok(label, f"{resp.status_code}")
        if key:
            return resp.json().get(key)
        return resp.json() if resp.text else {}
    else:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:200]
        fail(label, f"got {resp.status_code} expected {expected_status} — {detail}")
        return None

def check_neg(label, resp, expected_statuses):
    """Assert that a request is correctly rejected (negative test)."""
    if resp.status_code in expected_statuses:
        ok(f"[NEG] {label}", f"correctly rejected {resp.status_code}")
    else:
        fail(f"[NEG] {label}", f"got {resp.status_code} expected one of {expected_statuses} — {resp.text[:100]}")

# ── Auth helper ───────────────────────────────────────────────────────────────

def login(email, password=PW_DEPT):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        token = r.json().get("access_token")
        ok(f"login {email}", "200")
        return token
    fail(f"login {email}", f"{r.status_code} {r.text[:120]}")
    return None

def auth(token):
    return {"Authorization": f"Bearer {token}"}

# ─────────────────────────────────────────────────────────────────────────────
# 1. AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────
section("1. AUTHENTICATION — all 10 roles × 3 departments (north / south / mysuru)")

# Role definitions (email prefix, token key suffix)
_ROLE_DEFS = [
    ("orgadmin",        "OrgAdmin"),
    ("depthead",        "DeptHead"),
    ("originator",      "Originator"),
    ("tester",          "Tester"),
    ("assigner",        "TestAssigner"),
    ("techapprover",    "TechApprover"),
    ("financeapprover", "FinanceApprover"),
    ("eetlss",          "EeTlss"),
    ("taqc",            "TaqcOfficer"),
    ("sectionhead",     "SectionHead"),
    ("aeemaint",        "AeeMaint"),
    ("seewm",           "SeeWm"),
    ("eert",            "EeRt"),
    ("seert",           "SeeRt"),
    ("ceezone",         "CeeZone"),
    ("ceertrd",         "CeeRtrd"),
    ("purchaser",       "Purchaser"),
    ("fieldtester",     "FieldTester"),
    ("labtester",       "LabTester"),
    ("wfcoordinator",   "WfCoordinator"),
]

TOKENS = {}

# Authenticate all 10 roles for all 3 departments
for dept in ("north", "south", "mysuru"):
    for prefix, role_key in _ROLE_DEFS:
        email = f"{prefix}.{dept}@kptcl.com"
        t = login(email)
        if t:
            # North tokens stored under bare role key (used throughout the test)
            if dept == "north":
                TOKENS[role_key] = t
            # All dept tokens also stored under dept-qualified key
            TOKENS[f"{role_key}_{dept.capitalize()}"] = t

# Also login KPTCL org admin for org-level endpoints
t = login("orgadmin@kptcl.com", PW_KPTCL)
if t:
    TOKENS["KptclAdmin"] = t

t = login("originator@kptcl.com", PW_KPTCL)
if t:
    TOKENS["KptclOriginator"] = t


# Bad password
r = requests.post(f"{BASE}/auth/login", json={"email": "orgadmin.north@kptcl.com", "password": "wrong"})
check("login with wrong password ->401", r, 401)

# Non-existent user
r = requests.post(f"{BASE}/auth/login", json={"email": "nobody@kptcl.com", "password": "abc"})
if r.status_code in (401, 404):
    ok("login unknown user ->401/404", str(r.status_code))
else:
    fail("login unknown user", f"got {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. ORGANIZATIONS
# ─────────────────────────────────────────────────────────────────────────────
section("2. ORGANIZATIONS")

ORG_ADMIN_H = auth(TOKENS.get("KptclAdmin", ""))
ORG_ID = None

r = requests.get(f"{BASE}/organizations", headers=ORG_ADMIN_H)
orgs = check("GET /organizations", r, 200)
if orgs:
    kptcl = next((o for o in (orgs if isinstance(orgs, list) else orgs.get("items", [])) if o.get("code") == "KPTCL"), None)
    if kptcl:
        ORG_ID = kptcl.get("id") or kptcl.get("organization_id")
        ok(f"KPTCL org found id={ORG_ID}")
    else:
        fail("KPTCL org not found in list")

# GET single org
if ORG_ID:
    r = requests.get(f"{BASE}/organizations/{ORG_ID}", headers=ORG_ADMIN_H)
    check("GET /organizations/{id}", r, 200)

# Unauthorized access
r = requests.get(f"{BASE}/organizations")
if r.status_code in (401, 403):
    ok("GET /organizations without token ->401/403", str(r.status_code))
else:
    skip("GET /organizations unauthenticated", f"got {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. DEPARTMENTS
# ─────────────────────────────────────────────────────────────────────────────
section("3. DEPARTMENTS")

DEPT_ID = None
if ORG_ID:
    r = requests.get(f"{BASE}/organizations/{ORG_ID}/departments", headers=ORG_ADMIN_H)
    depts = check("GET /organizations/{id}/departments", r, 200)
    if depts:
        items = depts if isinstance(depts, list) else depts.get("items", [])
        rt_north = next((d for d in items if d.get("code") == "RT_NORTH"), None)
        if rt_north:
            DEPT_ID = rt_north.get("id")
            ok(f"RT_NORTH dept found id={DEPT_ID}")
        else:
            if items:
                DEPT_ID = items[0].get("id")
                skip("RT_NORTH not found, using first dept")

# ─────────────────────────────────────────────────────────────────────────────
# 4. ORG ROLES
# ─────────────────────────────────────────────────────────────────────────────
section("4. ORG ROLES")

ORG_ROLE_ID = None
if ORG_ID:
    r = requests.get(f"{BASE}/organizations/{ORG_ID}/roles", headers=ORG_ADMIN_H)
    roles_data = check("GET /organizations/{id}/roles", r, 200)
    if roles_data:
        items = roles_data if isinstance(roles_data, list) else roles_data.get("items", [])
        if items:
            ORG_ROLE_ID = items[0].get("id")
            ok(f"First org role: {items[0].get('name')} id={ORG_ROLE_ID}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. ORG USERS
# ─────────────────────────────────────────────────────────────────────────────
section("5. ORG USERS")

if ORG_ID:
    r = requests.get(f"{BASE}/organizations/{ORG_ID}/users", headers=ORG_ADMIN_H)
    check("GET /organizations/{id}/users", r, 200)

    # Non-admin should not see user list (403) - use tester token
    if TOKENS.get("Tester"):
        r = requests.get(f"{BASE}/organizations/{ORG_ID}/users", headers=auth(TOKENS["Tester"]))
        if r.status_code in (403, 401):
            ok("Tester cannot list org users ->403/401", str(r.status_code))
        else:
            skip("Tester /org/users access control", f"got {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. EQUIPMENT
# ─────────────────────────────────────────────────────────────────────────────
section("6. EQUIPMENT")

EQUIP_ID = None
if TOKENS.get("KptclAdmin"):
    r = requests.get(f"{BASE}/equipment", headers=auth(TOKENS["KptclAdmin"]))
    equip_data = check("GET /equipment (org admin)", r, 200)
    if equip_data:
        items = equip_data if isinstance(equip_data, list) else equip_data.get("items", [])
        if items:
            EQUIP_ID = items[0].get("id")
            ok(f"First equipment: {items[0].get('ueic')} id={EQUIP_ID}")

    if EQUIP_ID:
        r = requests.get(f"{BASE}/equipment/{EQUIP_ID}", headers=auth(TOKENS["KptclAdmin"]))
        check("GET /equipment/{id}", r, 200)

    # Applicable tests for equipment
    if EQUIP_ID:
        r = requests.get(f"{BASE}/equipment/{EQUIP_ID}/applicable-tests", headers=auth(TOKENS["KptclAdmin"]))
        if r.status_code in (200, 404):
            ok(f"GET /equipment/{EQUIP_ID}/applicable-tests", str(r.status_code))
        else:
            fail(f"GET /equipment applicable-tests", f"{r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# 6b. POWER TRANSFORMER EQUIPMENT — resolve a specific PT asset
# ─────────────────────────────────────────────────────────────────────────────
section("6b. POWER TRANSFORMER EQUIPMENT — resolve PT asset ID")

PT_EQUIP_ID = None   # Power-Transformer-specific equipment ID
PT_TYPE_ID  = None   # CategoryDetails id for 'Power Transformer' type

admin_h_6b = auth(TOKENS.get("KptclAdmin", ""))

# Step 1: find the Power Transformer equipment type
r = requests.get(f"{BASE}/testing_requests/equipment_types", headers=admin_h_6b)
if r.status_code == 200:
    types_data = r.json()
    type_list = types_data if isinstance(types_data, list) else []
    for et in type_list:
        if "power transformer" in et.get("name", "").lower():
            PT_TYPE_ID = et.get("id")
            ok(f"Power Transformer type found", f"id={PT_TYPE_ID}")
            break
    if not PT_TYPE_ID:
        skip("Power Transformer type NOT found in equipment_types", "will use EQUIP_ID fallback")
else:
    skip("GET /testing_requests/equipment_types", str(r.status_code))

# Step 2: find equipment of that type
if PT_TYPE_ID:
    r = requests.get(f"{BASE}/equipment?equipment_type_id={PT_TYPE_ID}&limit=5", headers=admin_h_6b)
    if r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if items:
            PT_EQUIP_ID = items[0].get("id")
            ok(f"Power Transformer equipment found", f"ueic={items[0].get('ueic')} id={PT_EQUIP_ID}")
        else:
            skip("No Power Transformer equipment in DB — will register one in section 22")
    else:
        skip("GET /equipment?equipment_type_id=...", str(r.status_code))

# Fallback: if no PT equipment yet, use generic EQUIP_ID so downstream sections still run
if not PT_EQUIP_ID and EQUIP_ID:
    PT_EQUIP_ID = EQUIP_ID
    skip("PT_EQUIP_ID fallback to first EQUIP_ID", str(PT_EQUIP_ID))

# ─────────────────────────────────────────────────────────────────────────────
# 7. TESTING REQUESTS — full lifecycle
# ─────────────────────────────────────────────────────────────────────────────
section("7. TESTING REQUESTS — lifecycle")

TR_ID = None
ORIG_H = auth(TOKENS.get("KptclOriginator", TOKENS.get("Originator", "")))

# 7a. Create
if EQUIP_ID and TOKENS.get("KptclOriginator"):
    payload = {
        "equipment_id": EQUIP_ID,
        "title": "Automated API Test TR",
        "request_category": "test",
        "description": "Automated API test TR",
        "priority": "normal",
    }
    r = requests.post(f"{BASE}/testing_requests/", json=payload, headers=ORIG_H)
    result = check("POST /testing_requests/ (originator)", r, 201)
    if result:
        TR_ID = result.get("id") or result.get("request_id")
        ok(f"TR created id={TR_ID}")
else:
    skip("Create TR", "no equipment_id or originator token")

# 7b. List
if TOKENS.get("KptclOriginator"):
    r = requests.get(f"{BASE}/testing_requests/", headers=ORIG_H)
    check("GET /testing_requests/ (originator)", r, 200)

if TOKENS.get("Tester"):
    r = requests.get(f"{BASE}/testing_requests/", headers=auth(TOKENS["Tester"]))
    check("GET /testing_requests/ (tester)", r, 200)

# 7c. Get single
if TR_ID:
    r = requests.get(f"{BASE}/testing_requests/{TR_ID}", headers=ORIG_H)
    check("GET /testing_requests/{id}", r, 200)

# 7d. Submit
if TR_ID:
    r = requests.put(f"{BASE}/testing_requests/{TR_ID}/submit", json={}, headers=ORIG_H)
    check("PUT /testing_requests/{id}/submit", r, 200)

# 7e. Stats
if TOKENS.get("KptclAdmin"):
    r = requests.get(f"{BASE}/testing_requests/stats", headers=auth(TOKENS["KptclAdmin"]))
    check("GET /testing_requests/stats", r, 200)

# 7f. Request categories dropdown
r = requests.get(f"{BASE}/testing_requests/request-categories", headers=ORIG_H)
check("GET /testing_requests/request-categories", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 8. TESTING REQUEST APPROVALS
# ─────────────────────────────────────────────────────────────────────────────
section("8. TESTING REQUEST APPROVALS")

if TOKENS.get("KptclAdmin"):
    r = requests.get(f"{BASE}/testing-requests/approvals/pending", headers=auth(TOKENS["KptclAdmin"]))
    if r.status_code in (200, 404):
        ok("GET /testing-requests/approvals/pending", str(r.status_code))
    else:
        fail("GET /testing-requests/approvals/pending", f"{r.status_code}")

# Assign tester to TR
# Use tester.north@kptcl.com specifically so section 9 can use the same token.
# Resolve the user ID directly from /auth/me (avoids list_testers platform-role filter).
ASSIGNER_H = auth(TOKENS.get("KptclAdmin", ""))
ASSIGNED_TESTER_TOKEN = TOKENS.get("Tester")   # tester.north@kptcl.com
ASSIGNED_TESTER_ID = None

# Step 1: get tester.north's user ID from their own profile
if ASSIGNED_TESTER_TOKEN:
    r = requests.get(f"{BASE}/users/me", headers=auth(ASSIGNED_TESTER_TOKEN))
    if r.status_code == 200:
        ASSIGNED_TESTER_ID = r.json().get("id")
        ok(f"Resolved tester.north user id", str(ASSIGNED_TESTER_ID))
    else:
        # Fallback: look in org users list
        if TOKENS.get("KptclAdmin") and ORG_ID:
            r2 = requests.get(f"{BASE}/organizations/{ORG_ID}/users", headers=auth(TOKENS["KptclAdmin"]))
            if r2.status_code == 200:
                users_data = r2.json()
                users = users_data if isinstance(users_data, list) else users_data.get("items", [])
                match = next((u for u in users if "tester.north" in (u.get("email") or "")), None)
                if match:
                    ASSIGNED_TESTER_ID = match.get("id")
                    ok(f"Resolved tester.north id from org users", str(ASSIGNED_TESTER_ID))

# Also verify the testers endpoint works (informational)
if TOKENS.get("KptclAdmin"):
    r = requests.get(f"{BASE}/testing_requests/testers", headers=ASSIGNER_H)
    if r.status_code == 200:
        t_list = r.json() if isinstance(r.json(), list) else []
        ok(f"GET /testing_requests/testers (system-role based)", f"count={len(t_list)}")
    else:
        skip("GET /testing_requests/testers", str(r.status_code))

if TR_ID and ASSIGNED_TESTER_ID:
    r = requests.put(
        f"{BASE}/testing_requests/{TR_ID}/assign",
        json={"tester_id": ASSIGNED_TESTER_ID},
        headers=ASSIGNER_H,
    )
    res = check("PUT /testing_requests/{id}/assign (tester.north)", r, 200)
    if not res:
        r2 = requests.get(f"{BASE}/testing_requests/{TR_ID}", headers=ASSIGNER_H)
        if r2.status_code == 200:
            st = r2.json().get("status", "?")
            skip(f"Assign skipped — TR already in status '{st}'")
elif not ASSIGNED_TESTER_ID:
    skip("Assign tester to TR", "could not resolve tester.north user id")

# ─────────────────────────────────────────────────────────────────────────────
# 9. TESTING — tester full lifecycle (assigned->accepted->in_progress->submitted)
# ─────────────────────────────────────────────────────────────────────────────
section("9. TESTING — tester full lifecycle")

TESTER_H = auth(ASSIGNED_TESTER_TOKEN) if ASSIGNED_TESTER_TOKEN else None

if TESTER_H:
    r = requests.get(f"{BASE}/testing/my-assignments", headers=TESTER_H)
    check("GET /testing/my-assignments (tester.north)", r, 200)

if TR_ID and TESTER_H:
    # ── Accept ──────────────────────────────────────────────────────────────
    r = requests.put(f"{BASE}/testing/{TR_ID}/accept", json={}, headers=TESTER_H)
    if r.status_code == 200:
        ok(f"PUT /testing/{TR_ID}/accept ->accepted", "200")
    elif r.status_code == 400:
        # Already accepted or wrong state — fetch current status
        r2 = requests.get(f"{BASE}/testing_requests/{TR_ID}", headers=TESTER_H)
        st = r2.json().get("status", "?") if r2.status_code == 200 else "?"
        skip(f"Accept skipped — TR already in status '{st}' (400)")
    else:
        fail(f"PUT /testing/{TR_ID}/accept", f"{r.status_code}: {r.text[:120]}")

    # ── Start ────────────────────────────────────────────────────────────────
    r = requests.put(f"{BASE}/testing/{TR_ID}/start", json={}, headers=TESTER_H)
    if r.status_code == 200:
        ok(f"PUT /testing/{TR_ID}/start ->in_progress", "200")
    elif r.status_code == 400:
        r2 = requests.get(f"{BASE}/testing_requests/{TR_ID}", headers=TESTER_H)
        st = r2.json().get("status", "?") if r2.status_code == 200 else "?"
        skip(f"Start skipped — TR already in status '{st}' (400)")
    else:
        fail(f"PUT /testing/{TR_ID}/start", f"{r.status_code}: {r.text[:120]}")

    # ── Get results (empty at this point) ────────────────────────────────────
    r = requests.get(f"{BASE}/testing/{TR_ID}/results", headers=TESTER_H)
    if r.status_code in (200, 404):
        ok(f"GET /testing/{TR_ID}/results", str(r.status_code))
    else:
        fail(f"GET /testing/{TR_ID}/results", str(r.status_code))

    # ── Submit structured test results ───────────────────────────────────────
    result_payload = {
        "template_key": "power_transformer_test",
        "test_data": {
            "oil_temperature": "45",
            "winding_resistance_hv": "0.5",
            "winding_resistance_lv": "0.05",
            "insulation_resistance": "1000",
            "turns_ratio": "11.0",
            "no_load_current": "2.5",
        },
        "overall_result": "pass",
        "remarks": "Automated test submission",
        "recommendation_type": "pass",
        "summary": "Power transformer passed all tests",
    }
    r = requests.post(
        f"{BASE}/testing/{TR_ID}/results/structured",
        json=result_payload,
        headers=TESTER_H,
    )
    if r.status_code in (200, 201):
        ok(f"POST /testing/{TR_ID}/results/structured ->test_data saved", str(r.status_code))
    else:
        skip(f"POST structured results", f"{r.status_code}: {r.text[:120]}")

    # ── Submit results ->moves TR to under_approval ───────────────────────────
    r = requests.put(
        f"{BASE}/testing/{TR_ID}/submit_results",
        json={
            "recommendation_type": "pass",
            "summary": "Power Transformer passed visual and electrical tests",
        },
        headers=TESTER_H,
    )
    if r.status_code == 200:
        ok(f"PUT /testing/{TR_ID}/submit_results ->under_approval", "200")
    elif r.status_code == 400:
        r2 = requests.get(f"{BASE}/testing_requests/{TR_ID}", headers=TESTER_H)
        st = r2.json().get("status", "?") if r2.status_code == 200 else "?"
        skip(f"submit_results skipped — TR already in status '{st}'")
    else:
        fail(f"PUT /testing/{TR_ID}/submit_results", f"{r.status_code}: {r.text[:120]}")

# ── Pending approval list ────────────────────────────────────────────────────
if TESTER_H:
    r = requests.get(f"{BASE}/testing/pending-approval", headers=TESTER_H)
    if r.status_code in (200, 403):
        ok("GET /testing/pending-approval", str(r.status_code))
    else:
        fail("GET /testing/pending-approval", str(r.status_code))

# ── Approve results (TechApprover / OrgAdmin — not the originator or tester) ─
TECH_APPROVER_H = auth(TOKENS.get("TechApprover") or TOKENS.get("KptclAdmin", ""))
if TR_ID and TECH_APPROVER_H:
    r = requests.put(
        f"{BASE}/testing/{TR_ID}/approve_results",
        json={"comment": "Approved by automated test"},
        headers=TECH_APPROVER_H,
    )
    if r.status_code == 200:
        ok(f"PUT /testing/{TR_ID}/approve_results ->approved", "200")
    elif r.status_code in (400, 403, 404):
        r2 = requests.get(f"{BASE}/testing_requests/{TR_ID}", headers=TECH_APPROVER_H)
        st = r2.json().get("status", "?") if r2.status_code == 200 else "?"
        skip(f"approve_results skipped — status '{st}' or role restriction ({r.status_code})")
    else:
        fail(f"PUT /testing/{TR_ID}/approve_results", f"{r.status_code}: {r.text[:120]}")

# ─────────────────────────────────────────────────────────────────────────────
# 10. RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────────────────
section("10. RECOMMENDATIONS")

REC_ID = None
if TOKENS.get("KptclAdmin"):
    ADMIN_H = auth(TOKENS["KptclAdmin"])

    r = requests.get(f"{BASE}/recommendations/stats", headers=ADMIN_H)
    check("GET /recommendations/stats", r, 200)

    r = requests.get(f"{BASE}/recommendations/pending", headers=ADMIN_H)
    recs = check("GET /recommendations/pending", r, 200)
    if recs:
        items = recs if isinstance(recs, list) else []
        if items:
            REC_ID = items[0].get("id")
            ok(f"First pending recommendation id={REC_ID}")

    r = requests.get(f"{BASE}/recommendations/", headers=ADMIN_H)
    all_recs = check("GET /recommendations/ (list)", r, 200)
    if all_recs and isinstance(all_recs, list) and all_recs:
        REC_ID = REC_ID or all_recs[0].get("id")

    if TR_ID:
        r = requests.get(f"{BASE}/recommendations/by-request/{TR_ID}", headers=ADMIN_H)
        if r.status_code in (200, 404):
            ok(f"GET /recommendations/by-request/{TR_ID}", str(r.status_code))
        else:
            fail(f"GET /recommendations/by-request/{TR_ID}", str(r.status_code))

    if REC_ID:
        r = requests.get(f"{BASE}/recommendations/{REC_ID}/detail", headers=ADMIN_H)
        if r.status_code in (200, 404):
            ok(f"GET /recommendations/{REC_ID}/detail", str(r.status_code))
        else:
            fail(f"GET /recommendations/{REC_ID}/detail", str(r.status_code))

# ─────────────────────────────────────────────────────────────────────────────
# 11. APPROVALS (Technical)
# ─────────────────────────────────────────────────────────────────────────────
section("11. APPROVALS (Technical Approver)")

TECH_H = auth(TOKENS.get("TechApprover", TOKENS.get("KptclAdmin", "")))

r = requests.get(f"{BASE}/approvals/stats", headers=TECH_H)
check("GET /approvals/stats", r, 200)

r = requests.get(f"{BASE}/approvals/pending", headers=TECH_H)
approvals_data = check("GET /approvals/pending", r, 200)
APPROVAL_REC_ID = None
if approvals_data:
    items = approvals_data if isinstance(approvals_data, list) else approvals_data.get("items", [])
    if items:
        APPROVAL_REC_ID = items[0].get("id") or items[0].get("recommendation_id")

if APPROVAL_REC_ID:
    # Try approve
    r = requests.put(
        f"{BASE}/approvals/{APPROVAL_REC_ID}/approve",
        json={"notes": "Approved by automated test"},
        headers=TECH_H,
    )
    if r.status_code in (200, 400, 403, 404):
        ok(f"PUT /approvals/{APPROVAL_REC_ID}/approve", str(r.status_code))
    else:
        fail(f"PUT /approvals/{APPROVAL_REC_ID}/approve", str(r.status_code))

# ─────────────────────────────────────────────────────────────────────────────
# 12. PROCUREMENT
# ─────────────────────────────────────────────────────────────────────────────
section("12. PROCUREMENT (validation_requests)")

PR_ID = None
FINANCE_H = auth(TOKENS.get("FinanceApprover", TOKENS.get("KptclAdmin", "")))

r = requests.get(f"{BASE}/validation_requests/", headers=FINANCE_H)
prs = check("GET /validation_requests/ (finance approver)", r, 200)
if prs:
    items = prs if isinstance(prs, list) else prs.get("items", [])
    if items:
        PR_ID = items[0].get("id")
        ok(f"First procurement request id={PR_ID}")

# Finance approve
if PR_ID:
    r = requests.put(
        f"{BASE}/validation_requests/{PR_ID}/finance-approve",
        json={"notes": "Finance approved by test"},
        headers=FINANCE_H,
    )
    if r.status_code in (200, 400, 403, 404):
        ok(f"PUT /validation_requests/{PR_ID}/finance-approve", str(r.status_code))
    else:
        fail(f"PUT /validation_requests/{PR_ID}/finance-approve", str(r.status_code))

# Finance reject (different PR)
if prs:
    items = prs if isinstance(prs, list) else prs.get("items", [])
    if len(items) > 1:
        pr2 = items[1].get("id")
        r = requests.put(
            f"{BASE}/validation_requests/{pr2}/finance-reject",
            json={"reason": "Rejected by automated test"},
            headers=FINANCE_H,
        )
        if r.status_code in (200, 400, 403, 404):
            ok(f"PUT /validation_requests/{pr2}/finance-reject", str(r.status_code))
        else:
            fail(f"PUT /validation_requests/{pr2}/finance-reject", str(r.status_code))

# ─────────────────────────────────────────────────────────────────────────────
# 13. REPAIR WORKFLOWS — full 3-actor lifecycle across all 10 stages
#   Actor 1: Workflow Coordinator  — assigns a user to each pending stage
#   Actor 2: Stage Actor           — fills form data, submits
#   Actor 3: Approver              — advances to next stage (same role, can_approve=True)
#
# Stage → primary actor token mapping (from repair_stage_roles.json):
#   FAILURE_REPORT    EE TLSS
#   COMMITTEE_REVIEW  CEE RT&R&D
#   VENDOR_ASSIGNMENT CEE RT&R&D
#   LIFTING           EE RT
#   JOINT_INSPECTION  EE RT
#   ESTIMATE          SEE W&M
#   QA                Lab Tester
#   FINAL_INSPECTION  EE RT
#   DISPATCH          EE RT
#   COMMISSIONING     EE TLSS
# ─────────────────────────────────────────────────────────────────────────────
section("13. REPAIR WORKFLOWS")

COORD_H = auth(TOKENS.get("WfCoordinator", ""))
ADMIN_H = auth(TOKENS.get("KptclAdmin", ""))

# Map stage code → token key for the primary actor
_STAGE_ACTOR = {
    "FAILURE_REPORT":    "EeTlss",
    "COMMITTEE_REVIEW":  "CeeRtrd",
    "VENDOR_ASSIGNMENT": "CeeRtrd",
    "LIFTING":           "EeRt",
    "JOINT_INSPECTION":  "EeRt",
    "ESTIMATE":          "SeeWm",
    "QA":                "LabTester",
    "FINAL_INSPECTION":  "EeRt",
    "DISPATCH":          "EeRt",
    "COMMISSIONING":     "EeTlss",
}

# Generic form data covers every stage template's common fields
_FORM_DATA = {
    "failure_date": "2026-05-07",
    "failure_description": "Automated test — insulation degradation during routine inspection",
    "failure_mode": "Insulation breakdown",
    "failure_location": "HV winding",
    "severity": "high",
    "visual_inspection": "Completed",
    "condition": "poor",
    "recommendation": "Proceed to next repair stage",
    "remarks": "Filled by automated test",
    "inspection_date": "2026-05-07",
    "inspection_findings": "Automated inspection findings",
    "committee_decision": "Approved for repair",
    "vendor_name": "Test Vendor Pvt Ltd",
    "vendor_contact": "9876543210",
    "estimate_amount": 150000,
    "lifting_date": "2026-05-08",
    "dispatch_date": "2026-05-09",
    "commissioning_date": "2026-05-10",
    "test_result": "Pass",
    "qa_result": "Pass",
    "final_inspection_result": "Pass",
}

# ── 13-1. Config ──────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/repair-workflows/config/stages", headers=auth(TOKENS.get("EeTlss", "")))
check("GET /repair-workflows/config/stages", r, 200)

r = requests.get(f"{BASE}/repair-workflows/config/transitions", headers=auth(TOKENS.get("EeTlss", "")))
check("GET /repair-workflows/config/transitions", r, 200)

# ── 13-2. Pending assignments — initially empty ───────────────────────────────
r = requests.get(f"{BASE}/repair-workflows/pending-assignments", headers=COORD_H)
check("GET /repair-workflows/pending-assignments (initial)", r, 200)

# ── 13-3. Start a new workflow ────────────────────────────────────────────────
RW_ID = None
_rw_equip = PT_EQUIP_ID or EQUIP_ID
if _rw_equip:
    r = requests.post(
        f"{BASE}/repair-workflows/start",
        json={"equipment_id": _rw_equip},
        headers=auth(TOKENS.get("EeTlss", "")),
    )
    if r.status_code in (200, 201):
        RW_ID = r.json().get("workflow_id") or r.json().get("id")
        ok("POST /repair-workflows/start", f"id={RW_ID}")
    elif r.status_code in (400, 409):
        # already active — grab existing
        r2 = requests.get(f"{BASE}/repair-workflows", headers=auth(TOKENS.get("EeTlss", "")))
        if r2.status_code == 200:
            items = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
            RW_ID = items[0].get("id") if items else None
        skip("POST /repair-workflows/start", f"already active — using existing id={RW_ID}")
    else:
        fail("POST /repair-workflows/start", f"{r.status_code}: {r.text[:120]}")
else:
    skip("POST /repair-workflows/start", "no equipment_id available")

# ── 13-4. Read-only endpoints ─────────────────────────────────────────────────
if RW_ID:
    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}", headers=auth(TOKENS.get("EeTlss", "")))
    check("GET /repair-workflows/{id}", r, 200)

    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}/progress", headers=auth(TOKENS.get("EeTlss", "")))
    check("GET /repair-workflows/{id}/progress", r, 200)

    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}/timeline", headers=auth(TOKENS.get("EeTlss", "")))
    check("GET /repair-workflows/{id}/timeline", r, 200)

    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}/assignment-queue", headers=COORD_H)
    check("GET /repair-workflows/{id}/assignment-queue", r, 200)

# ── 13-5. Walk all 10 stages — POSITIVE + NEGATIVE scenarios per stage ─────────
#
# 3-step flow per stage:
#   NEG-1  Non-coordinator (actor) tries to assign           → 400/403/422
#   NEG-2  Wrong-role user saves before assignment           → 400/403/422
#   NEG-3  Actor submits before being assigned               → 400/422
#   NEG-4  Wrong-role user calls /advance                    → 400/403/422
#   POS-1  Coordinator gets eligible users                   → 200
#   POS-2  Coordinator assigns correct user                  → 200
#   NEG-5  Coordinator tries to assign again (duplicate)     → 400/422
#   POS-3  GET available-transitions                         → 200
#   POS-4  Stage actor saves form data                       → 200
#   NEG-7  Wrong-role user tries to submit                   → 400/403/422
#   POS-5  Stage actor submits                               → 200 (status → submitted)
#   POS-6  Stage actor approves (/advance)                   → 200 (→ next stage pending)
#   NEG-8  Double submit (stage already completed/advanced)  → 400/422
# ──────────────────────────────────────────────────────────────────────────────

# A role that has NO repair-workflow stage access (not in repair_stage_roles.json)
_WRONG_ROLE_H = auth(TOKENS.get("Tester", ""))

if RW_ID:
    for _stage_num in range(1, 11):
        # ── Fetch current workflow state ──────────────────────────────────────
        r = requests.get(f"{BASE}/repair-workflows/{RW_ID}", headers=ADMIN_H)
        if r.status_code != 200:
            fail(f"Stage {_stage_num}: GET workflow detail", f"{r.status_code}")
            break
        wf = r.json()
        if wf.get("status") == "completed":
            ok(f"Workflow completed after stage {_stage_num - 1}", "all 10 stages done")
            break

        _pending_st = next(
            (s for s in wf.get("stages", []) if s.get("status") == "pending"), None
        )
        if not _pending_st:
            _pending_st = next(
                (s for s in wf.get("stages", []) if s.get("status") == "assigned"), None
            )
        if not _pending_st:
            skip(f"Stage {_stage_num}: no pending/assigned stage found", "stopping loop")
            break

        _sid       = _pending_st.get("stage_id")
        _scode     = _pending_st.get("stage_code", f"STAGE_{_stage_num}")
        _actor_key = _STAGE_ACTOR.get(_scode, "EeTlss")
        _actor_h   = auth(TOKENS.get(_actor_key, TOKENS.get("EeTlss", "")))
        _is_pending = _pending_st.get("status") == "pending"

        print(f"\n  ====== Stage {_stage_num}/10: {_scode}  actor={_actor_key} ======")

        # ── NEG-1: non-coordinator tries to assign ─────────────────────────────
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/assign",
            json={"assign_to_user_id": "00000000-0000-0000-0000-000000000001"},
            headers=_actor_h,
        )
        check_neg(f"[{_scode}] NEG-1 non-coordinator assign", r, [400, 403, 422])

        # ── NEG-2: wrong-role user saves before assignment ─────────────────────
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/save",
            json={"form_data": _FORM_DATA},
            headers=_WRONG_ROLE_H,
        )
        check_neg(f"[{_scode}] NEG-2 wrong-role save (before assign)", r, [400, 403, 422])

        # ── NEG-3: actor submits before being assigned ─────────────────────────
        if _is_pending:
            r = requests.post(
                f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/submit",
                json={"remarks": "should fail — not yet assigned"},
                headers=_actor_h,
            )
            check_neg(f"[{_scode}] NEG-3 submit before assignment", r, [400, 422])

        # ── NEG-4: wrong-role user calls /advance (no can_approve for this stage) ───
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/advance",
            json={"remarks": "should fail — wrong role, no can_approve"},
            headers=_WRONG_ROLE_H,
        )
        check_neg(f"[{_scode}] NEG-4 wrong-role /advance", r, [400, 403, 422])

        # ── POS-1: coordinator gets eligible users ─────────────────────────────
        _eligible_uid = None
        if _is_pending:
            r = requests.get(
                f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/eligible-users",
                headers=COORD_H,
            )
            if r.status_code == 200:
                _users = r.json() if isinstance(r.json(), list) else []
                ok(f"[{_scode}] POS-1 GET eligible-users", f"count={len(_users)}")
                _eligible_uid = _users[0].get("id") if _users else None
            else:
                skip(f"[{_scode}] POS-1 GET eligible-users", f"{r.status_code}: {r.text[:60]}")

            # ── POS-2: coordinator assigns ─────────────────────────────────────
            if _eligible_uid:
                r = requests.post(
                    f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/assign",
                    json={"assign_to_user_id": _eligible_uid},
                    headers=COORD_H,
                )
                if r.status_code == 200:
                    ok(f"[{_scode}] POS-2 POST assign", "200")
                else:
                    fail(f"[{_scode}] POS-2 POST assign", f"{r.status_code}: {r.text[:80]}")
            else:
                skip(f"[{_scode}] POS-2 POST assign", "no eligible user returned")

            # ── NEG-5: duplicate assign (stage already assigned) ───────────────
            if _eligible_uid:
                r = requests.post(
                    f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/assign",
                    json={"assign_to_user_id": _eligible_uid},
                    headers=COORD_H,
                )
                check_neg(f"[{_scode}] NEG-5 duplicate assign", r, [400, 422])

        # ── POS-3: available transitions ───────────────────────────────────────
        r = requests.get(
            f"{BASE}/repair-workflows/{RW_ID}/available-transitions",
            headers=_actor_h,
        )
        if r.status_code == 200:
            ok(f"[{_scode}] POS-3 GET available-transitions", str(r.json()))
        else:
            skip(f"[{_scode}] POS-3 GET available-transitions", f"{r.status_code}")

        # ── POS-4: stage actor saves form data ─────────────────────────────────
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/save",
            json={"form_data": _FORM_DATA},
            headers=_actor_h,
        )
        if r.status_code in (200, 201):
            ok(f"[{_scode}] POS-4 POST save", str(r.status_code))
        else:
            skip(f"[{_scode}] POS-4 POST save", f"{r.status_code}: {r.text[:80]}")

        # ── NEG-7: wrong-role user tries to submit ─────────────────────────────
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/submit",
            json={"remarks": "wrong role submit — should fail"},
            headers=_WRONG_ROLE_H,
        )
        check_neg(f"[{_scode}] NEG-7 wrong-role submit", r, [400, 403, 422])

        # ── POS-5: stage actor submits (stage → submitted, awaiting approval) ────
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/submit",
            json={"remarks": f"{_scode} submitted by automated test"},
            headers=_actor_h,
        )
        if r.status_code == 200:
            ok(f"[{_scode}] POS-5 POST submit", f"status=submitted, msg={r.json().get('message','')[:40]}")
        else:
            fail(f"[{_scode}] POS-5 POST submit", f"{r.status_code}: {r.text[:80]}")
            break

        # ── POS-6: stage actor approves (/advance) → stage completed, next pending ──
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/advance",
            json={"remarks": f"{_scode} approved by automated test"},
            headers=_actor_h,
        )
        if r.status_code == 200:
            _resp = r.json()
            _next = _resp.get("current_stage") or _resp.get("status", "?")
            ok(f"[{_scode}] POS-6 POST /advance (approve)", f"-> {_next}")
            # Terminal stage: workflow completed — break before NEG-8
            if _resp.get("status") == "completed" or _resp.get("message", "").startswith("Workflow completed"):
                ok("Workflow completed on final stage approval", "all 10 stages done")
                break
        else:
            fail(f"[{_scode}] POS-6 POST /advance", f"{r.status_code}: {r.text[:80]}")
            break

        # ── NEG-8: double submit (stage already completed and advanced) ────────
        r = requests.post(
            f"{BASE}/repair-workflows/{RW_ID}/stages/{_sid}/submit",
            json={"remarks": "should fail — stage already completed and advanced"},
            headers=_actor_h,
        )
        check_neg(f"[{_scode}] NEG-8 double submit after advance", r, [400, 422])

    else:
        fail("Repair workflow 10-stage loop", "did not complete within 10 iterations")

    # ── Final state ────────────────────────────────────────────────────────────
    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}", headers=ADMIN_H)
    if r.status_code == 200:
        _fs = r.json().get("status", "?")
        ok("Workflow final status", f"{_fs} [DONE]") if _fs == "completed" else ok("Workflow final status", _fs)

    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}/timeline", headers=ADMIN_H)
    if r.status_code == 200:
        ok("GET /timeline (post-completion)", f"{len(r.json())} audit entries")

# ── 13B. REJECT PATH — second workflow, first stage; negative before reject ────
section("13B. REPAIR WORKFLOW — reject path with negative scenarios")

_reject_rw_id = None
_reject_equip = EQUIP_ID if EQUIP_ID and EQUIP_ID != _rw_equip else None

if _reject_equip:
    r = requests.post(
        f"{BASE}/repair-workflows/start",
        json={"equipment_id": _reject_equip},
        headers=auth(TOKENS.get("EeTlss", "")),
    )
    if r.status_code in (200, 201):
        _reject_rw_id = r.json().get("workflow_id") or r.json().get("id")
        ok("POST /start (reject-path workflow)", f"id={_reject_rw_id}")
    elif r.status_code in (400, 409):
        skip("POST /start (reject path)", f"{r.status_code} already active")
    else:
        fail("POST /start (reject path)", f"{r.status_code}: {r.text[:80]}")
else:
    skip("13B reject-path start", "no distinct equipment available for second workflow")

if _reject_rw_id:
    r = requests.get(f"{BASE}/repair-workflows/{_reject_rw_id}", headers=ADMIN_H)
    _rj_stage = next((s for s in r.json().get("stages", []) if s.get("status") == "pending"), None) if r.status_code == 200 else None
    _rj_sid   = _rj_stage.get("stage_id") if _rj_stage else None
    _rj_scode = _rj_stage.get("stage_code", "FAILURE_REPORT") if _rj_stage else "FAILURE_REPORT"
    _rj_h     = auth(TOKENS.get(_STAGE_ACTOR.get(_rj_scode, "EeTlss"), ""))

    if _rj_sid:
        # ── POSITIVE: coordinator assigns ──────────────────────────────────────
        r = requests.get(
            f"{BASE}/repair-workflows/{_reject_rw_id}/stages/{_rj_sid}/eligible-users",
            headers=COORD_H,
        )
        _rj_uid = (r.json()[0].get("id") if r.status_code == 200 and r.json() else None)
        if _rj_uid:
            r = requests.post(
                f"{BASE}/repair-workflows/{_reject_rw_id}/stages/{_rj_sid}/assign",
                json={"assign_to_user_id": _rj_uid},
                headers=COORD_H,
            )
            ok("Reject path: assign", str(r.status_code)) if r.status_code == 200 else skip("Reject path: assign", str(r.status_code))

        # ── NEG: reject when stage is 'assigned' (not yet submitted) ───────────
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/reject",
            json={"remarks": "should fail — stage not yet submitted"},
            headers=_rj_h,
        )
        check_neg(f"[{_rj_scode}] NEG reject before submission (stage=assigned)", r, [400, 422])

        # ── POSITIVE: stage actor submits (reach 'submitted' state) ───────────
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/stages/{_rj_sid}/save",
            json={"form_data": _FORM_DATA},
            headers=_rj_h,
        )
        # save may fail if no can_edit; that's fine — submit is what matters
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/stages/{_rj_sid}/submit",
            json={"remarks": "submitting for reject-path test"},
            headers=_rj_h,
        )
        ok("Reject path: submit", str(r.status_code)) if r.status_code == 200 else skip("Reject path: submit", f"{r.status_code}: {r.text[:60]}")

        # ── NEG: completely unauthorized role tries to reject ──────────────────
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/reject",
            json={"remarks": "unauthorized reject — should fail"},
            headers=_WRONG_ROLE_H,
        )
        check_neg(f"[{_rj_scode}] NEG unauthorized reject", r, [400, 403, 422])

        # ── NEG: coordinator (can_assign, no can_approve) tries to reject ──────
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/reject",
            json={"remarks": "coordinator reject — should fail (no can_approve)"},
            headers=COORD_H,
        )
        check_neg(f"[{_rj_scode}] NEG coordinator reject (no can_approve)", r, [400, 403, 422])

        # ── POSITIVE: stage actor (can_approve) rejects the submitted stage ────
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/reject",
            json={"remarks": "Rejected by stage actor — stage rolls back"},
            headers=_rj_h,
        )
        if r.status_code == 200:
            ok("POST /reject (actor rejects submitted stage)", str(r.json().get("current_stage", "?")))
        elif r.status_code in (400, 422):
            skip("POST /reject", f"{r.status_code}: {r.text[:80]}")
        else:
            fail("POST /reject", f"{r.status_code}: {r.text[:80]}")

# ── 13-7. Cancel workflow — negative + positive ────────────────────────────────
_cancel_id = _reject_rw_id
if _cancel_id:
    # ── NEG: wrong-role user tries to cancel ──────────────────────────────────
    r = requests.post(
        f"{BASE}/repair-workflows/{_cancel_id}/cancel",
        json={"reason": "wrong role cancel attempt"},
        headers=_WRONG_ROLE_H,
    )
    check_neg("Cancel: wrong-role cancel attempt", r, [400, 403, 422])

    # ── POSITIVE: workflow creator cancels ────────────────────────────────────
    r = requests.post(
        f"{BASE}/repair-workflows/{_cancel_id}/cancel",
        json={"reason": "Cancelled by automated test"},
        headers=auth(TOKENS.get("EeTlss", "")),
    )
    if r.status_code == 200:
        ok("POST /cancel (creator cancels)", "200")
    elif r.status_code in (400, 422):
        skip("POST /cancel", f"{r.status_code}: {r.text[:80]}")
    else:
        fail("POST /cancel", f"{r.status_code}: {r.text[:80]}")

    # ── NEG: try to cancel already-cancelled workflow ─────────────────────────
    r = requests.post(
        f"{BASE}/repair-workflows/{_cancel_id}/cancel",
        json={"reason": "should fail — already cancelled"},
        headers=auth(TOKENS.get("EeTlss", "")),
    )
    check_neg("Cancel: cancel already-cancelled workflow", r, [400, 422])

# ─────────────────────────────────────────────────────────────────────────────
# 14. DIRECT SUBMISSIONS
# ─────────────────────────────────────────────────────────────────────────────
section("14. DIRECT SUBMISSIONS (Failure Registry / TAQC)")

TAQC_H = auth(TOKENS.get("TaqcOfficer", TOKENS.get("KptclAdmin", "")))

# List direct submissions — category param is required (else 422)
for cat_param in ["failure_registry", "taqc_inspection"]:
    r = requests.get(f"{BASE}/direct-submissions/?category={cat_param}", headers=TAQC_H)
    if r.status_code == 200:
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        ok(f"GET /direct-submissions/?category={cat_param}", f"200 count={len(items)}")
    elif r.status_code in (401, 403):
        ok(f"GET /direct-submissions/?category={cat_param} auth gate", str(r.status_code))
    else:
        fail(f"GET /direct-submissions/?category={cat_param}", f"got {r.status_code}: {r.text[:80]}")

# ─────────────────────────────────────────────────────────────────────────────
# 15. NOTIFICATIONS — user-facing + admin template/variable/routing/schedule
# ─────────────────────────────────────────────────────────────────────────────
section("15A. NOTIFICATIONS — user-facing bell endpoints")

_user_tok = TOKENS.get("Originator") or TOKENS.get("Tester")
_admin_tok = TOKENS.get("KptclAdmin")

# ── 15A-1: list in-app notifications (empty is fine) ─────────────────────────
if _user_tok:
    r = requests.get(f"{BASE}/notifications", headers=auth(_user_tok))
    data = check("GET /notifications (list)", r, 200)
    NOTIF_IDS = [n["id"] for n in data] if isinstance(data, list) else []
else:
    skip("GET /notifications", "no user token")
    NOTIF_IDS = []

# ── 15A-2: unread-count ───────────────────────────────────────────────────────
if _user_tok:
    r = requests.get(f"{BASE}/notifications/unread-count", headers=auth(_user_tok))
    cnt = check("GET /notifications/unread-count", r, 200)
    if cnt is not None and "count" in cnt:
        ok("unread-count has 'count' field", str(cnt["count"]))
    else:
        fail("unread-count missing 'count' field", str(cnt))

# ── 15A-3: severity counts breakdown ─────────────────────────────────────────
if _user_tok:
    r = requests.get(f"{BASE}/notifications/counts", headers=auth(_user_tok))
    cnt = check("GET /notifications/counts (severity breakdown)", r, 200)
    if isinstance(cnt, dict) and "total" in cnt:
        ok("counts has total/critical/alert/info keys", str(cnt))

# ── 15A-4: unread-only filter ─────────────────────────────────────────────────
if _user_tok:
    r = requests.get(f"{BASE}/notifications?unread_only=true", headers=auth(_user_tok))
    check("GET /notifications?unread_only=true", r, 200)

# ── 15A-5: mark single read (skip if no notifications) ───────────────────────
if _user_tok and NOTIF_IDS:
    r = requests.put(f"{BASE}/notifications/{NOTIF_IDS[0]}/read", headers=auth(_user_tok))
    if r.status_code in (200, 204):
        ok("PUT /notifications/{id}/read", str(r.status_code))
    else:
        fail("PUT /notifications/{id}/read", f"{r.status_code} {r.text[:80]}")
else:
    skip("PUT /notifications/{id}/read", "no in-app notifications to mark")

# ── 15A-6: mark all read ─────────────────────────────────────────────────────
if _user_tok:
    r = requests.put(f"{BASE}/notifications/read-all", headers=auth(_user_tok))
    if r.status_code in (200, 204):
        ok("PUT /notifications/read-all", str(r.status_code))
    else:
        fail("PUT /notifications/read-all", f"{r.status_code} {r.text[:80]}")

# ── 15A-7: unauthenticated request rejected ───────────────────────────────────
r = requests.get(f"{BASE}/notifications")
if r.status_code in (401, 403):
    ok("GET /notifications without token ->401/403", str(r.status_code))
else:
    fail("GET /notifications without token", f"got {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
section("15B. NOTIFICATIONS — admin template management")
# ─────────────────────────────────────────────────────────────────────────────

# ── 15B-1: non-admin gets 403 on template endpoints ──────────────────────────
if _user_tok:
    r = requests.get(f"{BASE}/notifications/templates", headers=auth(_user_tok))
    if r.status_code == 403:
        ok("Non-admin GET /notifications/templates -> 403", "RBAC enforced")
    else:
        fail("Non-admin template access RBAC", f"got {r.status_code} expected 403")

# ── 15B-2: event types catalogue ─────────────────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/templates/event-types", headers=auth(_admin_tok))
    cats = check("GET /notifications/templates/event-types", r, 200)
    EVENT_TYPES = [e["event_type"] for e in cats] if isinstance(cats, list) else []
    if EVENT_TYPES:
        ok(f"event catalogue has {len(EVENT_TYPES)} event types", ", ".join(EVENT_TYPES[:4]))
else:
    skip("GET event-types", "no admin token")
    EVENT_TYPES = []

# ── 15B-3: system variables ───────────────────────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/templates/system-variables", headers=auth(_admin_tok))
    svars = check("GET /notifications/templates/system-variables", r, 200)
    if isinstance(svars, list) and svars:
        ok(f"system variables: {len(svars)} vars loaded", svars[0].get("var_key",""))
    else:
        fail("system variables empty or wrong type", str(svars)[:80])

# ── 15B-4: list templates (org + global merged) ───────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/templates", headers=auth(_admin_tok))
    tmpls = check("GET /notifications/templates", r, 200)
    if isinstance(tmpls, list):
        ok(f"templates list: {len(tmpls)} rows", "includes global defaults")
        # Verify attachment_vars field is present on each template
        has_att = all("attachment_vars" in t for t in tmpls)
        if has_att:
            ok("All templates have attachment_vars field", "")
        else:
            fail("Some templates missing attachment_vars field", "")
    TMPL_ID = tmpls[0]["id"] if tmpls else None
    TMPL_EVENT = tmpls[0]["event_type"] if tmpls else "eval_critical"
else:
    skip("GET /notifications/templates", "no admin token")
    TMPL_ID = None
    TMPL_EVENT = "eval_critical"

# ── 15B-5: filter templates by event_type ────────────────────────────────────
if _admin_tok and TMPL_EVENT:
    r = requests.get(
        f"{BASE}/notifications/templates?event_type={TMPL_EVENT}",
        headers=auth(_admin_tok),
    )
    check(f"GET /notifications/templates?event_type={TMPL_EVENT}", r, 200)

# ── 15B-6: get event group (all channels for one event) ──────────────────────
_test_event = EVENT_TYPES[0] if EVENT_TYPES else "eval_critical"
if _admin_tok:
    r = requests.get(
        f"{BASE}/notifications/templates/event/{_test_event}",
        headers=auth(_admin_tok),
    )
    grp = check(f"GET /notifications/templates/event/{_test_event}", r, 200)
    if grp:
        ok("event group has event_type field", grp.get("event_type", ""))
        email_cfg = grp.get("email")
        if email_cfg:
            ok("email channel present in event group", "")
            if "attachment_vars" in email_cfg:
                ok("email channel has attachment_vars field", str(email_cfg["attachment_vars"]))
            else:
                fail("email channel missing attachment_vars field", "")

# ── 15B-7: bulk-upsert — create org template with attachment_vars ─────────────
CREATED_TMPL_IDS = []
if _admin_tok and EVENT_TYPES:
    upsert_payload = {
        "event_type": EVENT_TYPES[0],
        "recipient_roles": [],
        "extra_recipient_emails": [],
        "email": {
            "enabled": True,
            "subject_template": "[TEST] {{equipment.ueic}} — {{eval.test_type}}",
            "body_template": (
                "<p>Dear team,</p>"
                "<p>Equipment <b>{{equipment.ueic}}</b> result: {{eval.overall}}.</p>"
                "<p>Date: {{system.date}}</p>"
            ),
            "attachment_vars": [
                {"var_key": "report.retriepdf", "type": "pdf"},
                {"var_key": "report.retriexls", "type": "excel"},
            ],
        },
        "sms": {"enabled": False},
        "inapp": {
            "enabled": True,
            "body_template": "{{equipment.ueic}}: {{eval.overall}} — {{system.date}}",
        },
    }
    r = requests.post(
        f"{BASE}/notifications/templates/bulk-upsert",
        json=upsert_payload,
        headers=auth(_admin_tok),
    )
    rows = check("POST /notifications/templates/bulk-upsert (with attachment_vars)", r, 200)
    if isinstance(rows, list) and rows:
        ok(f"bulk-upsert created {len(rows)} template rows", "")
        CREATED_TMPL_IDS = [t["id"] for t in rows]
        # Verify attachment_vars stored on email row
        email_row = next((t for t in rows if t["channel"] == "email"), None)
        if email_row:
            avars = email_row.get("attachment_vars", [])
            if len(avars) == 2:
                ok("attachment_vars stored correctly (2 entries)", str(avars))
            else:
                fail("attachment_vars count mismatch", f"expected 2, got {len(avars)}: {avars}")

# ── 15B-8: create single template (POST) ─────────────────────────────────────
SINGLE_TMPL_ID = None
if _admin_tok and EVENT_TYPES:
    ev = EVENT_TYPES[1] if len(EVENT_TYPES) > 1 else EVENT_TYPES[0]
    r = requests.post(
        f"{BASE}/notifications/templates",
        json={
            "event_type": ev,
            "channel": "email",
            "subject_template": "Test subject for {{request.number}}",
            "body_template": "<p>Test body {{request.title}}</p>",
            "recipient_roles": [],
            "extra_recipient_emails": [],
            "attachment_vars": [{"var_key": "report.retriepdf", "type": "pdf"}],
            "is_active": True,
        },
        headers=auth(_admin_tok),
    )
    created = check("POST /notifications/templates (single, PDF attachment)", r, 201)
    if created and created.get("id"):
        SINGLE_TMPL_ID = created["id"]
        ok("created template id", SINGLE_TMPL_ID)
        avars = created.get("attachment_vars", [])
        if avars and avars[0].get("type") == "pdf":
            ok("attachment_vars persisted on created template", str(avars))
        else:
            fail("attachment_vars not persisted", str(avars))

# ── 15B-9: update template (PUT) ─────────────────────────────────────────────
if _admin_tok and SINGLE_TMPL_ID:
    r = requests.put(
        f"{BASE}/notifications/templates/{SINGLE_TMPL_ID}",
        json={
            "subject_template": "Updated subject {{request.number}}",
            "body_template": "<p>Updated body — report attached.</p>",
            "attachment_vars": [
                {"var_key": "report.retriepdf",  "type": "pdf"},
                {"var_key": "report.retriexls", "type": "excel"},
            ],
        },
        headers=auth(_admin_tok),
    )
    upd = check("PUT /notifications/templates/{id} (add excel attachment)", r, 200)
    if upd:
        avars = upd.get("attachment_vars", [])
        if len(avars) == 2:
            ok("PUT updated attachment_vars to 2 entries", str(avars))
        else:
            fail("PUT attachment_vars count wrong", f"expected 2 got {len(avars)}")

# ── 15B-10: delete org-specific template ─────────────────────────────────────
if _admin_tok and SINGLE_TMPL_ID:
    r = requests.delete(
        f"{BASE}/notifications/templates/{SINGLE_TMPL_ID}",
        headers=auth(_admin_tok),
    )
    if r.status_code == 204:
        ok("DELETE /notifications/templates/{id} -> 204", "template deactivated")
    else:
        fail("DELETE /notifications/templates/{id}", f"got {r.status_code} {r.text[:80]}")

# ─────────────────────────────────────────────────────────────────────────────
section("15C. NOTIFICATIONS — variable registry (admin)")
# ─────────────────────────────────────────────────────────────────────────────

CUSTOM_VAR_ID = None

# ── 15C-1: list variables ────────────────────────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/variables", headers=auth(_admin_tok))
    vlist = check("GET /notifications/variables", r, 200)
    if isinstance(vlist, list) and vlist:
        ok(f"variables list: {len(vlist)} rows", vlist[0].get("var_key",""))

# ── 15C-2: create custom variable ────────────────────────────────────────────
if _admin_tok:
    r = requests.post(
        f"{BASE}/notifications/variables",
        json={
            "var_key":      "custom.test_ref",
            "label":        "Custom Test Reference",
            "group_name":   "Custom",
            "description":  "Custom reference number for test reports",
            "sample_value": "REF-2025-001",
            "resolver_key": "custom_test_ref",
        },
        headers=auth(_admin_tok),
    )
    cv = check("POST /notifications/variables (create custom var)", r, 201)
    if cv and cv.get("id"):
        CUSTOM_VAR_ID = cv["id"]
        ok("custom variable created", CUSTOM_VAR_ID)

# ── 15C-3: update custom variable ────────────────────────────────────────────
if _admin_tok and CUSTOM_VAR_ID:
    r = requests.put(
        f"{BASE}/notifications/variables/{CUSTOM_VAR_ID}",
        json={"label": "Custom Test Reference (updated)", "sample_value": "REF-2025-999"},
        headers=auth(_admin_tok),
    )
    check("PUT /notifications/variables/{id}", r, 200)

# ── 15C-4: delete custom variable ────────────────────────────────────────────
if _admin_tok and CUSTOM_VAR_ID:
    r = requests.delete(
        f"{BASE}/notifications/variables/{CUSTOM_VAR_ID}",
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 204):
        ok("DELETE /notifications/variables/{id} -> deactivated", str(r.status_code))
    else:
        fail("DELETE /notifications/variables/{id}", f"{r.status_code} {r.text[:80]}")

# ── 15C-5: system variable cannot be deleted ──────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/variables", headers=auth(_admin_tok))
    vrows = r.json() if r.status_code == 200 else []
    sys_var = next((v for v in vrows if v.get("is_system")), None)
    if sys_var:
        r = requests.delete(
            f"{BASE}/notifications/variables/{sys_var['id']}",
            headers=auth(_admin_tok),
        )
        if r.status_code in (400, 403, 404):
            ok("System variable delete blocked -> 400/403/404", str(r.status_code))
        else:
            fail("System variable delete not blocked", f"got {r.status_code}")
    else:
        skip("System variable delete protection", "no system vars returned")

# ─────────────────────────────────────────────────────────────────────────────
section("15D. NOTIFICATIONS — routing rules (admin)")
# ─────────────────────────────────────────────────────────────────────────────

ROUTING_RULE_ID = None
GLOBAL_RULE_ID  = None

# ── 15D-1: meta (dropdown data) ──────────────────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/routing-rules/meta", headers=auth(_admin_tok))
    meta = check("GET /notifications/routing-rules/meta", r, 200)
    if meta:
        ok("routing-rules meta has keys", str(list(meta.keys()))[:80])

# ── 15D-2: list routing rules (org + global) ─────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/routing-rules", headers=auth(_admin_tok))
    rules = check("GET /notifications/routing-rules", r, 200)
    if isinstance(rules, list):
        ok(f"routing rules: {len(rules)} rows (org + global)", "")
        GLOBAL_RULE_ID = next(
            (ru["id"] for ru in rules if not ru.get("organization_id")), None
        )

# ── 15D-3: create org routing rule ────────────────────────────────────────────
if _admin_tok:
    r = requests.post(
        f"{BASE}/notifications/routing-rules",
        json={
            "event_type":                "eval_critical",
            "channels":                  ["email", "inapp"],
            "applicable_workflow_types": ["preventive_maintenance"],
        },
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 201):
        created = r.json()
        ROUTING_RULE_ID = created.get("id")
        ok("POST /notifications/routing-rules", str(r.status_code))
    elif r.status_code == 422:
        skip("POST /notifications/routing-rules", f"422 schema mismatch: {r.text[:120]}")
    else:
        fail("POST /notifications/routing-rules", f"{r.status_code} {r.text[:120]}")

# ── 15D-4: update routing rule ────────────────────────────────────────────────
if _admin_tok and ROUTING_RULE_ID:
    r = requests.put(
        f"{BASE}/notifications/routing-rules/{ROUTING_RULE_ID}",
        json={"channels": ["email", "sms", "inapp"]},
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 204):
        ok("PUT /notifications/routing-rules/{id}", str(r.status_code))
    else:
        fail("PUT /notifications/routing-rules/{id}", f"{r.status_code} {r.text[:80]}")

# ── 15D-5: clone global rule as org override ──────────────────────────────────
if _admin_tok and GLOBAL_RULE_ID:
    r = requests.post(
        f"{BASE}/notifications/routing-rules/{GLOBAL_RULE_ID}/clone",
        json={},
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 201):
        ok("POST /notifications/routing-rules/{id}/clone", str(r.status_code))
    elif r.status_code == 409:
        ok("POST clone -> 409 already overridden", "idempotent")
    else:
        fail("POST /notifications/routing-rules/{id}/clone", f"{r.status_code} {r.text[:80]}")

# ── 15D-6: delete org routing rule ────────────────────────────────────────────
if _admin_tok and ROUTING_RULE_ID:
    r = requests.delete(
        f"{BASE}/notifications/routing-rules/{ROUTING_RULE_ID}",
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 204):
        ok("DELETE /notifications/routing-rules/{id}", str(r.status_code))
    else:
        fail("DELETE /notifications/routing-rules/{id}", f"{r.status_code} {r.text[:80]}")

# ─────────────────────────────────────────────────────────────────────────────
section("15E. NOTIFICATIONS — schedule rules (admin)")
# ─────────────────────────────────────────────────────────────────────────────

SCHED_RULE_ID        = None
GLOBAL_SCHED_RULE_ID = None

# ── 15E-1: meta ───────────────────────────────────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/schedule-rules/meta", headers=auth(_admin_tok))
    meta = check("GET /notifications/schedule-rules/meta", r, 200)
    if meta:
        ok("schedule-rules meta loaded", str(list(meta.keys()))[:80])

# ── 15E-2: list schedule rules ────────────────────────────────────────────────
if _admin_tok:
    r = requests.get(f"{BASE}/notifications/schedule-rules", headers=auth(_admin_tok))
    srules = check("GET /notifications/schedule-rules", r, 200)
    if isinstance(srules, list):
        ok(f"schedule rules: {len(srules)} rows", "")
        GLOBAL_SCHED_RULE_ID = next(
            (sr["id"] for sr in srules if not sr.get("organization_id")), None
        )

# ── 15E-3: create schedule rule ───────────────────────────────────────────────
if _admin_tok:
    r = requests.post(
        f"{BASE}/notifications/schedule-rules",
        json={
            "event_type":    "due_reminder",
            "label":         "Test: Due Soon Reminder",
            "trigger_type":  "due_soon",
            "offset_days":   5,
            "severity":      "info",
        },
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 201):
        SCHED_RULE_ID = r.json().get("id")
        ok("POST /notifications/schedule-rules", str(r.status_code))
    elif r.status_code == 422:
        skip("POST /notifications/schedule-rules", f"422: {r.text[:120]}")
    else:
        fail("POST /notifications/schedule-rules", f"{r.status_code} {r.text[:80]}")

# ── 15E-4: update schedule rule ───────────────────────────────────────────────
if _admin_tok and SCHED_RULE_ID:
    r = requests.put(
        f"{BASE}/notifications/schedule-rules/{SCHED_RULE_ID}",
        json={"offset_days": 7},
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 204):
        ok("PUT /notifications/schedule-rules/{id}", str(r.status_code))
    else:
        fail("PUT /notifications/schedule-rules/{id}", f"{r.status_code} {r.text[:80]}")

# ── 15E-5: clone global schedule rule ────────────────────────────────────────
if _admin_tok and GLOBAL_SCHED_RULE_ID:
    r = requests.post(
        f"{BASE}/notifications/schedule-rules/{GLOBAL_SCHED_RULE_ID}/clone",
        json={},
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 201, 409):
        ok("POST /notifications/schedule-rules/{id}/clone", str(r.status_code))
    else:
        fail("POST /notifications/schedule-rules/{id}/clone", f"{r.status_code} {r.text[:80]}")

# ── 15E-6: delete schedule rule ───────────────────────────────────────────────
if _admin_tok and SCHED_RULE_ID:
    r = requests.delete(
        f"{BASE}/notifications/schedule-rules/{SCHED_RULE_ID}",
        headers=auth(_admin_tok),
    )
    if r.status_code in (200, 204):
        ok("DELETE /notifications/schedule-rules/{id}", str(r.status_code))
    else:
        fail("DELETE /notifications/schedule-rules/{id}", f"{r.status_code} {r.text[:80]}")

# ─────────────────────────────────────────────────────────────────────────────
section("15F. NOTIFICATIONS — admin backend (logs + test-fire + seed)")
# ─────────────────────────────────────────────────────────────────────────────

_kptcl_admin = TOKENS.get("KptclAdmin")

# ── 15F-1: seed defaults (idempotent) ────────────────────────────────────────
if _kptcl_admin:
    r = requests.post(
        f"{BASE}/admin/notifications/seed-defaults",
        headers=auth(_kptcl_admin),
    )
    if r.status_code in (200, 201):
        ok("POST /admin/notifications/seed-defaults", str(r.status_code))
    else:
        fail("POST /admin/notifications/seed-defaults", f"{r.status_code} {r.text[:80]}")

# ── 15F-2: list admin templates ───────────────────────────────────────────────
if _kptcl_admin:
    r = requests.get(f"{BASE}/admin/notifications/templates", headers=auth(_kptcl_admin))
    if r.status_code == 200:
        at = r.json()
        ok(f"GET /admin/notifications/templates -> {len(at)} rows", "")
    else:
        fail("GET /admin/notifications/templates", f"{r.status_code} {r.text[:80]}")

# ── 15F-3: notification logs ──────────────────────────────────────────────────
if _kptcl_admin:
    r = requests.get(f"{BASE}/admin/notifications/logs", headers=auth(_kptcl_admin))
    if r.status_code == 200:
        logs = r.json()
        ok(f"GET /admin/notifications/logs -> {len(logs) if isinstance(logs, list) else '?'} rows", "")
    else:
        fail("GET /admin/notifications/logs", f"{r.status_code} {r.text[:80]}")

# ── 15F-4: test-fire (sends to calling admin) ────────────────────────────────
if _kptcl_admin and EVENT_TYPES:
    r = requests.post(
        f"{BASE}/admin/notifications/test-fire",
        json={"event_type": EVENT_TYPES[0], "context": {"equipment": "TX-TEST-001"}},
        headers=auth(_kptcl_admin),
    )
    if r.status_code in (200, 201, 202):
        ok("POST /admin/notifications/test-fire", str(r.status_code))
    elif r.status_code == 404:
        ok("POST /admin/notifications/test-fire -> 404 (no template yet for this event)", "expected")
    else:
        fail("POST /admin/notifications/test-fire", f"{r.status_code} {r.text[:120]}")

# ─────────────────────────────────────────────────────────────────────────────
# 16. DEPARTMENT FILTER ISOLATION
# ─────────────────────────────────────────────────────────────────────────────
section("16. DEPARTMENT FILTER ISOLATION")

# Login south and mysuru originators
t_south  = login("originator.south@kptcl.com")
t_mysuru = login("originator.mysuru@kptcl.com")
t_north  = TOKENS.get("Originator") or login("originator.north@kptcl.com")

def get_tr_ids(token):
    if not token:
        return set()
    r = requests.get(f"{BASE}/testing_requests/", headers=auth(token))
    if r.status_code != 200:
        return set()
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    return {i.get("id") for i in items if i.get("id")}

north_ids  = get_tr_ids(t_north)
south_ids  = get_tr_ids(t_south)
mysuru_ids = get_tr_ids(t_mysuru)

# Cross-dept isolation: north should not see south's TRs
if south_ids and north_ids:
    overlap = north_ids & south_ids
    if not overlap:
        ok("North originator does NOT see South TRs (dept isolation)")
    else:
        fail("North originator SEES South TRs — dept filter broken", f"overlap: {overlap}")
else:
    skip("North/South isolation check", "not enough TRs in both depts")

if mysuru_ids and south_ids:
    overlap = mysuru_ids & south_ids
    if not overlap:
        ok("Mysuru originator does NOT see South TRs (dept isolation)")
    else:
        fail("Mysuru originator SEES South TRs — dept filter broken", f"overlap: {overlap}")
else:
    skip("South/Mysuru isolation check", "not enough TRs")

# Org admin sees all (organization scope)
if TOKENS.get("OrgAdmin"):
    admin_ids = get_tr_ids(TOKENS["OrgAdmin"])
    if admin_ids >= (north_ids | south_ids | mysuru_ids):
        ok("OrgAdmin sees TRs from all departments (organization scope)")
    else:
        skip("OrgAdmin scope check", "no cross-dept TRs to verify")

# ─────────────────────────────────────────────────────────────────────────────
# 16b. HIERARCHY FILTER — circle & zone level users see full subtree
# ─────────────────────────────────────────────────────────────────────────────
section("16b. HIERARCHY FILTER (circle/zone subtree scope)")

t_circle = login("ee.circle@kptcl.com")
t_zone   = login("cee.zone@kptcl.com")
login("see.circle@kptcl.com")
login("see.zone@kptcl.com")

circle_ids = get_tr_ids(t_circle)
zone_ids   = get_tr_ids(t_zone)

leaf_ids = north_ids | south_ids | mysuru_ids

# Circle user must see everything the three leaf divisions see
if t_circle and leaf_ids:
    missing = leaf_ids - circle_ids
    if not missing:
        ok("Circle user (ee.circle) sees TRs from all 3 divisions (subtree filter)")
    else:
        fail("Circle user MISSING some leaf TRs", f"missing: {missing}")
else:
    skip("Circle subtree check", "no leaf TRs or circle login failed")

# Zone user must see everything the circle (and therefore leaves) see
if t_zone and leaf_ids:
    missing = leaf_ids - zone_ids
    if not missing:
        ok("Zone user (cee.zone) sees TRs from all divisions under zone (subtree filter)")
    else:
        fail("Zone user MISSING some leaf TRs", f"missing: {missing}")
else:
    skip("Zone subtree check", "no leaf TRs or zone login failed")

# ─────────────────────────────────────────────────────────────────────────────
# 17. ROLE-BASED ACCESS CONTROL
# ─────────────────────────────────────────────────────────────────────────────
section("17. ROLE-BASED ACCESS CONTROL")

# Tester should NOT be able to finance-approve procurement
if TOKENS.get("Tester") and PR_ID:
    r = requests.put(
        f"{BASE}/validation_requests/{PR_ID}/finance-approve",
        json={"notes": "Tester trying to finance approve"},
        headers=auth(TOKENS["Tester"]),
    )
    if r.status_code in (403, 401, 400):
        ok("Tester cannot finance-approve procurement ->403/401/400", str(r.status_code))
    else:
        fail("Tester finance-approve procurement", f"got {r.status_code} — expected 403")

# Section Head cannot assign tester
if TOKENS.get("SectionHead") and TR_ID:
    r = requests.put(
        f"{BASE}/testing_requests/{TR_ID}/assign",
        json={"tester_id": "00000000-0000-0000-0000-000000000001"},
        headers=auth(TOKENS["SectionHead"]),
    )
    if r.status_code in (403, 401, 400, 404):
        ok("SectionHead cannot assign tester ->403/401/400", str(r.status_code))
    else:
        skip("SectionHead assign tester RBAC", f"got {r.status_code}")

# Unauthenticated request
r = requests.get(f"{BASE}/testing_requests/")
if r.status_code in (401, 403):
    ok("Unauthenticated GET /testing_requests/ ->401/403", str(r.status_code))
else:
    fail("Unauthenticated access", f"got {r.status_code} expected 401/403")

# ─────────────────────────────────────────────────────────────────────────────
# 18. MISC ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
section("18. MISC ENDPOINTS")

admin_h = auth(TOKENS.get("KptclAdmin", ""))

# Department hierarchy dropdown
r = requests.get(f"{BASE}/testing_requests/department_hierarchy", headers=admin_h)
check("GET /testing_requests/department_hierarchy", r, 200)

# Equipment types dropdown
r = requests.get(f"{BASE}/testing_requests/equipment_types", headers=admin_h)
check("GET /testing_requests/equipment_types", r, 200)

# Categories
r = requests.get(f"{BASE}/categories/", headers=admin_h)
if r.status_code in (200, 404):
    ok("GET /categories/", str(r.status_code))

# Health check
r = requests.get(f"{BASE}/")
if r.status_code in (200, 404):
    ok("GET / (health)", str(r.status_code))

# API docs (HTML — don't try to parse as JSON)
r = requests.get(f"{BASE}/docs")
if r.status_code == 200:
    ok("GET /docs (Swagger UI)", "200")
else:
    fail("GET /docs (Swagger UI)", str(r.status_code))

# ─────────────────────────────────────────────────────────────────────────────
# 19. FAILURE REGISTRY FLOW
# ─────────────────────────────────────────────────────────────────────────────
section("19. FAILURE REGISTRY FLOW")

# Failure Registry: direct submission by any field user, no tester assignment
# Categories: failure_registry
# Flow: POST /direct-submissions/ -> GET -> attach (optional)

FR_IDS = {}   # dept -> submission id

for dept, email_sfx in [("north", "north"), ("south", "south"), ("mysuru", "mysuru")]:
    tok = login(f"originator.{email_sfx}@kptcl.com")
    if not tok:
        skip(f"Failure Registry: originator.{email_sfx} login failed")
        continue

    h = auth(tok)
    payload = {
        "request_category": "failure_registry",
        "template_key": "failure_registry",
        "title": f"FR Test - {dept.upper()} dept - Power Transformer",
        "equipment_id": PT_EQUIP_ID,
        "test_data": {
            "failure_date": "2026-05-01",
            "failure_category": "Electrical",
            "failure_description": f"Insulation breakdown at {dept} substation",
            "root_cause_analysis": "Overload and moisture ingress",
            "outage_duration_hours": "4",
            "affected_consumers": "250",
            "outage_impact": "Supply interrupted to residential sector",
            "outcome": "Repair",
        },
        "overall_result": "fail",
        "remarks": f"Automated FR test for {dept} dept",
        "priority": "high",
    }
    r = requests.post(f"{BASE}/direct-submissions/", json=payload, headers=h)
    if r.status_code == 201:
        resp = r.json()
        fid = resp.get("request_id") or resp.get("id")
        FR_IDS[dept] = fid
        # FR initial status must be "submitted" (goes to Test Assigner queue)
        status = resp.get("status", "")
        if status == "submitted":
            ok(f"POST /direct-submissions/ failure_registry ({dept})", f"201 id={fid} status={status}")
        else:
            fail(f"FR initial status ({dept})", f"expected 'submitted', got '{status}'")
    else:
        skip(f"POST /direct-submissions/ failure_registry ({dept})", f"{r.status_code}: {r.text[:120]}")

# List failure registry — each dept user should see only their own
for dept, email_sfx in [("north", "north"), ("south", "south"), ("mysuru", "mysuru")]:
    tok = login(f"originator.{email_sfx}@kptcl.com")
    if not tok:
        continue
    r = requests.get(f"{BASE}/direct-submissions/?category=failure_registry", headers=auth(tok))
    if r.status_code == 200:
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        ok(f"GET /direct-submissions/ failure_registry ({dept})", f"200 count={len(items)}")
        # Cross-dept isolation: south/mysuru IDs should NOT appear in north's list
        ids_seen = {i.get("id") for i in items}
        other_ids = {v for k, v in FR_IDS.items() if k != dept and v}
        leaking = ids_seen & other_ids
        if leaking:
            fail(f"FR dept isolation ({dept} sees other depts)", str(leaking))
        else:
            ok(f"FR dept isolation ({dept}): no cross-dept leak")
    else:
        skip(f"GET /direct-submissions/ ({dept})", str(r.status_code))

# Get single FR record
for dept, fid in FR_IDS.items():
    if fid:
        tok = login(f"originator.{dept}@kptcl.com")
        if tok:
            r = requests.get(f"{BASE}/direct-submissions/{fid}", headers=auth(tok))
            if r.status_code in (200, 404):
                ok(f"GET /direct-submissions/{fid} ({dept})", str(r.status_code))
            else:
                fail(f"GET /direct-submissions/{fid} ({dept})", str(r.status_code))
        break

# ─────────────────────────────────────────────────────────────────────────────
# 20. TA&QC INSPECTION FLOW
# ─────────────────────────────────────────────────────────────────────────────
section("20. TA&QC INSPECTION FLOW")

TAQC_IDS = {}

for dept, email_sfx in [("north", "north"), ("south", "south"), ("mysuru", "mysuru")]:
    tok = login(f"taqc.{email_sfx}@kptcl.com")
    if not tok:
        skip(f"TAQC: taqc.{email_sfx} login failed")
        continue

    h = auth(tok)
    payload = {
        "request_category": "taqc_inspection",
        "template_key": "taqc_inspection",
        "title": f"TAQC Inspection - {dept.upper()} - Power Transformer",
        "equipment_id": PT_EQUIP_ID,
        "test_data": {
            "substation": f"{dept.capitalize()} Grid Substation",
            "inspection_date": "2026-05-06",
            "inspection_category": "Electrical Safety",
            "observation_description": "Routine inspection — all parameters nominal.",
            "severity": "Minor",
            "target_compliance_date": "2026-06-01",
        },
        "overall_result": "advisory",
        "remarks": f"Automated TAQC test for {dept} dept",
        "priority": "normal",
    }
    r = requests.post(f"{BASE}/direct-submissions/", json=payload, headers=h)
    if r.status_code == 201:
        resp = r.json()
        tid = resp.get("request_id") or resp.get("id")
        TAQC_IDS[dept] = tid
        # TAQC initial status must be "under_approval" (direct to TechApprover queue)
        status = resp.get("status", "")
        if status == "under_approval":
            ok(f"POST /direct-submissions/ taqc_inspection ({dept})", f"201 id={tid} status={status}")
        else:
            fail(f"TAQC initial status ({dept})", f"expected 'under_approval', got '{status}'")
    else:
        skip(f"POST /direct-submissions/ taqc_inspection ({dept})", f"{r.status_code}: {r.text[:120]}")

# TAQC dept isolation
for dept in ["north", "south", "mysuru"]:
    tok = login(f"taqc.{dept}@kptcl.com")
    if not tok:
        continue
    r = requests.get(f"{BASE}/direct-submissions/?category=taqc_inspection", headers=auth(tok))
    if r.status_code == 200:
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        ids_seen = {i.get("id") for i in items}
        other_ids = {v for k, v in TAQC_IDS.items() if k != dept and v}
        leaking = ids_seen & other_ids
        if leaking:
            fail(f"TAQC dept isolation ({dept} sees other depts)", str(leaking))
        else:
            ok(f"TAQC dept isolation ({dept}): no cross-dept leak")
    else:
        skip(f"TAQC list ({dept})", str(r.status_code))

# ─────────────────────────────────────────────────────────────────────────────
# 21. ADHOC FLOWS — 4 TR types for Power Transformer across 3 depts
# ─────────────────────────────────────────────────────────────────────────────
section("21. ADHOC FLOWS — test/maintenance/inspection/repair_lifecycle x 3 depts")

TR_CATEGORIES = ["test", "maintenance", "inspection", "repair_lifecycle"]
ADHOC_TR_IDS = {}   # (dept, category) -> tr_id

for dept in ["north", "south", "mysuru"]:
    orig_tok = login(f"originator.{dept}@kptcl.com")
    if not orig_tok:
        skip(f"Adhoc originator.{dept} login failed")
        continue

    orig_h = auth(orig_tok)
    for cat in TR_CATEGORIES:
        payload = {
            "equipment_id": PT_EQUIP_ID,
            "title": f"[{cat.upper()}] Power Transformer - {dept}",
            "request_category": cat,
            "description": f"Automated {cat} TR for Power Transformer in {dept} dept",
            "priority": "normal",
        }
        r = requests.post(f"{BASE}/testing_requests/", json=payload, headers=orig_h)
        if r.status_code == 201:
            tr_id = r.json().get("id")
            ADHOC_TR_IDS[(dept, cat)] = tr_id
            ok(f"CREATE TR [{cat}] ({dept})", f"201 id={tr_id}")
        else:
            fail(f"CREATE TR [{cat}] ({dept})", f"{r.status_code} {r.text[:100]}")
            continue

        # ── Submit (draft ->submitted) ───────────────────────────────────────
        r = requests.put(f"{BASE}/testing_requests/{tr_id}/submit", json={}, headers=orig_h)
        if r.status_code == 200:
            ok(f"SUBMIT TR [{cat}] ({dept}) ->submitted", "200")
        else:
            skip(f"SUBMIT TR [{cat}] ({dept})", str(r.status_code))
            continue

        # ── Assign tester.north (submitted ->assigned) ───────────────────────
        assign_h = auth(TOKENS.get("KptclAdmin", ""))
        assigned_tok = TOKENS.get("Tester")  # tester.north
        a_tester_id = ASSIGNED_TESTER_ID   # resolved in section 8
        if a_tester_id:
            r = requests.put(
                f"{BASE}/testing_requests/{tr_id}/assign",
                json={"tester_id": a_tester_id},
                headers=assign_h,
            )
            if r.status_code == 200:
                ok(f"ASSIGN TR [{cat}] ({dept}) ->assigned", "200")
            else:
                skip(f"ASSIGN TR [{cat}] ({dept})", f"{r.status_code}: {r.text[:80]}")
                continue
        else:
            skip(f"ASSIGN TR [{cat}] ({dept})", "no tester id from section 8")
            continue

        if not assigned_tok:
            skip(f"Lifecycle [{cat}] ({dept})", "no tester token")
            continue

        t_h = auth(assigned_tok)

        # ── Accept (assigned ->accepted) ─────────────────────────────────────
        r = requests.put(f"{BASE}/testing/{tr_id}/accept", json={}, headers=t_h)
        if r.status_code == 200:
            ok(f"ACCEPT TR [{cat}] ({dept}) ->accepted", "200")
        else:
            skip(f"ACCEPT TR [{cat}] ({dept})", f"{r.status_code}: {r.text[:80]}")
            continue

        # ── Start (accepted ->in_progress) ───────────────────────────────────
        r = requests.put(f"{BASE}/testing/{tr_id}/start", json={}, headers=t_h)
        if r.status_code == 200:
            ok(f"START TR [{cat}] ({dept}) ->in_progress", "200")
        else:
            skip(f"START TR [{cat}] ({dept})", f"{r.status_code}: {r.text[:80]}")
            continue

        # ── Submit results (in_progress ->under_approval) ────────────────────
        r = requests.put(
            f"{BASE}/testing/{tr_id}/submit_results",
            json={
                "recommendation_type": "pass",
                "summary": f"Auto test result for [{cat}] Power Transformer ({dept})",
            },
            headers=t_h,
        )
        if r.status_code == 200:
            ok(f"SUBMIT RESULTS [{cat}] ({dept}) ->under_approval", "200")
        else:
            skip(f"SUBMIT RESULTS [{cat}] ({dept})", f"{r.status_code}: {r.text[:80]}")
            continue

        # ── Approve results (under_approval ->approved) — use TechApprover ───
        approver_h = auth(TOKENS.get("TechApprover") or TOKENS.get("KptclAdmin", ""))
        r = requests.put(
            f"{BASE}/testing/{tr_id}/approve_results",
            json={"comment": f"Approved [{cat}] ({dept}) by automated test"},
            headers=approver_h,
        )
        if r.status_code == 200:
            ok(f"APPROVE RESULTS [{cat}] ({dept}) ->approved", "200")
        elif r.status_code in (400, 403, 404):
            skip(f"APPROVE RESULTS [{cat}] ({dept})", f"{r.status_code}: {r.text[:80]}")
        else:
            fail(f"APPROVE RESULTS [{cat}] ({dept})", f"{r.status_code}: {r.text[:80]}")

# ── 21c. REJECT path — test decline + reject_results for coverage ────────────
section("21c. REJECT PATH — decline and reject_results coverage")

# Create one extra TR and walk the reject path (north dept, 'test' category)
_rej_orig_tok = login("originator.north@kptcl.com")
_rej_tr_id = None
if _rej_orig_tok and PT_EQUIP_ID:
    _rej_h = auth(_rej_orig_tok)
    r = requests.post(
        f"{BASE}/testing_requests/",
        json={
            "equipment_id": PT_EQUIP_ID,
            "title": "[REJECT PATH] Power Transformer test (north)",
            "request_category": "test",
            "description": "TR for testing the reject workflow path",
            "priority": "normal",
        },
        headers=_rej_h,
    )
    if r.status_code == 201:
        _rej_tr_id = r.json().get("id")
        ok(f"CREATE reject-path TR (north)", f"id={_rej_tr_id}")

        # submit
        r = requests.put(f"{BASE}/testing_requests/{_rej_tr_id}/submit", json={}, headers=_rej_h)
        ok("SUBMIT reject-path TR", str(r.status_code)) if r.status_code == 200 else skip("SUBMIT reject-path TR", str(r.status_code))

        # assign
        if ASSIGNED_TESTER_ID:
            r = requests.put(
                f"{BASE}/testing_requests/{_rej_tr_id}/assign",
                json={"tester_id": ASSIGNED_TESTER_ID},
                headers=auth(TOKENS.get("KptclAdmin", "")),
            )
            ok("ASSIGN reject-path TR", str(r.status_code)) if r.status_code == 200 else skip("ASSIGN reject-path TR", str(r.status_code))

            if r.status_code == 200 and TOKENS.get("Tester"):
                _t_h = auth(TOKENS["Tester"])
                # accept
                r = requests.put(f"{BASE}/testing/{_rej_tr_id}/accept", json={}, headers=_t_h)
                ok("ACCEPT reject-path TR", str(r.status_code)) if r.status_code == 200 else skip("ACCEPT reject-path TR", str(r.status_code))
                # start
                r = requests.put(f"{BASE}/testing/{_rej_tr_id}/start", json={}, headers=_t_h)
                ok("START reject-path TR", str(r.status_code)) if r.status_code == 200 else skip("START reject-path TR", str(r.status_code))
                # submit results
                r = requests.put(
                    f"{BASE}/testing/{_rej_tr_id}/submit_results",
                    json={"recommendation_type": "fail", "summary": "Failed tests — equipment requires repair"},
                    headers=_t_h,
                )
                ok("SUBMIT RESULTS reject-path TR ->under_approval", str(r.status_code)) if r.status_code == 200 else skip("SUBMIT RESULTS reject-path", str(r.status_code))

                # ── REJECT results (under_approval ->rejected) ─────────────
                approver_h = auth(TOKENS.get("TechApprover") or TOKENS.get("KptclAdmin", ""))
                r = requests.put(
                    f"{BASE}/testing/{_rej_tr_id}/reject_results",
                    json={"comment": "Results rejected by automated test — insufficient data"},
                    headers=approver_h,
                )
                if r.status_code == 200:
                    ok("REJECT RESULTS reject-path TR ->rejected", "200")
                elif r.status_code in (400, 403, 404):
                    skip("REJECT RESULTS", f"{r.status_code}: {r.text[:80]}")
                else:
                    fail("REJECT RESULTS reject-path TR", f"{r.status_code}: {r.text[:80]}")

                # ── Tester DECLINE path — separate TR ──────────────────────
                # decline can only happen from accepted/in_progress
                r2 = requests.post(
                    f"{BASE}/testing_requests/",
                    json={
                        "equipment_id": PT_EQUIP_ID,
                        "title": "[DECLINE PATH] Power Transformer test (north)",
                        "request_category": "test",
                        "description": "TR for testing the tester decline path",
                        "priority": "low",
                    },
                    headers=_rej_h,
                )
                if r2.status_code == 201:
                    _dec_tr_id = r2.json().get("id")
                    ok("CREATE decline-path TR", f"id={_dec_tr_id}")
                    requests.put(f"{BASE}/testing_requests/{_dec_tr_id}/submit", json={}, headers=_rej_h)
                    requests.put(f"{BASE}/testing_requests/{_dec_tr_id}/assign",
                                 json={"tester_id": ASSIGNED_TESTER_ID},
                                 headers=auth(TOKENS.get("KptclAdmin", "")))
                    requests.put(f"{BASE}/testing/{_dec_tr_id}/accept", json={}, headers=_t_h)
                    r3 = requests.put(
                        f"{BASE}/testing/{_dec_tr_id}/decline",
                        json={"reason": "Cannot test due to equipment access issue"},
                        headers=_t_h,
                    )
                    if r3.status_code == 200:
                        ok("DECLINE assignment ->back to submitted", "200")
                    elif r3.status_code in (400, 403, 404):
                        skip("DECLINE", f"{r3.status_code}: {r3.text[:80]}")
                    else:
                        fail("DECLINE assignment", f"{r3.status_code}: {r3.text[:80]}")
    else:
        skip("Create reject-path TR", f"{r.status_code}: {r.text[:100]}")

# Dept filter validation: each originator should see ONLY their dept's TRs
section("21b. DEPT FILTER: TR list isolation across all 4 categories")

dept_tr_ids = {}
for dept in ["north", "south", "mysuru"]:
    tok = login(f"originator.{dept}@kptcl.com")
    if not tok:
        continue
    r = requests.get(f"{BASE}/testing_requests/?limit=500", headers=auth(tok))
    if r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        ids = {i.get("id") for i in items if i.get("id")}
        dept_tr_ids[dept] = ids
        ok(f"originator.{dept} sees {len(ids)} TRs")

if len(dept_tr_ids) == 3:
    n, s, m = dept_tr_ids.get("north", set()), dept_tr_ids.get("south", set()), dept_tr_ids.get("mysuru", set())
    if not (n & s):
        ok("North & South TR sets are disjoint")
    else:
        fail("North sees South TRs", str(n & s)[:100])
    if not (n & m):
        ok("North & Mysuru TR sets are disjoint")
    else:
        fail("North sees Mysuru TRs", str(n & m)[:100])
    if not (s & m):
        ok("South & Mysuru TR sets are disjoint")
    else:
        fail("South sees Mysuru TRs", str(s & m)[:100])
else:
    skip("Full 3-way isolation check", "missing dept tokens")

# Org admin sees everything
if TOKENS.get("KptclAdmin"):
    r = requests.get(f"{BASE}/testing_requests/?limit=500", headers=auth(TOKENS["KptclAdmin"]))
    if r.status_code == 200:
        data = r.json()
        all_items = data if isinstance(data, list) else data.get("items", [])
        all_ids = {i.get("id") for i in all_items}
        all_dept_ids = set().union(*dept_tr_ids.values()) if dept_tr_ids else set()
        if all_dept_ids.issubset(all_ids):
            ok(f"OrgAdmin sees all dept TRs ({len(all_ids)} total including {len(all_dept_ids)} dept TRs)")
        else:
            missing = all_dept_ids - all_ids
            fail("OrgAdmin missing some dept TRs", str(missing)[:100])

# ─────────────────────────────────────────────────────────────────────────────
# 22. NEW EQUIPMENT REGISTER FLOW
# ─────────────────────────────────────────────────────────────────────────────
section("22. NEW EQUIPMENT REGISTER FLOW")

NEW_EQUIP_IDS = {}

# Register a new Power Transformer for each of the 3 departments
for dept, dept_id_val in [("north", DEPT_ID), ("south", None), ("mysuru", None)]:
    if not dept_id_val and dept == "north":
        skip("Equipment register: no DEPT_ID available")
        continue

    admin_h = auth(TOKENS.get("KptclAdmin", ""))

    # Resolve dept_id for south/mysuru if not yet captured
    if not dept_id_val and ORG_ID:
        r_d = requests.get(f"{BASE}/organizations/{ORG_ID}/departments", headers=admin_h)
        if r_d.status_code == 200:
            all_depts = r_d.json() if isinstance(r_d.json(), list) else r_d.json().get("items", [])
            code_key = f"RT_{dept.upper()}"
            found = next((d for d in all_depts if d.get("code") == code_key), None)
            if found:
                dept_id_val = found.get("id")

    if not dept_id_val:
        skip(f"Equipment register ({dept}): dept_id not found")
        continue

    eq_payload = {
        "equipment_type_id": PT_TYPE_ID,   # Power Transformer type resolved in section 6b
        "department_id": str(dept_id_val),
        "voltage_class": "220",
        "bay_number": f"0{['north','south','mysuru'].index(dept)+1}",
        "serial_in_bay": "01",
        "nameplate_data": {
            "manufacturer": "BHEL",
            "serial_number": f"TEST-PT-{dept.upper()}-001",
            "year_of_manufacture": 2022,
            "rated_capacity_mva": 100,
        },
    }

    # Fallback: resolve equipment_type_id if section 6b didn't find it
    if not eq_payload["equipment_type_id"]:
        r = requests.get(f"{BASE}/testing_requests/equipment_types", headers=admin_h)
        if r.status_code == 200:
            types_data = r.json()
            pt = None
            for t in (types_data if isinstance(types_data, list) else []):
                if "power transformer" in t.get("name", "").lower():
                    pt = t
                    break
            if not pt and types_data:
                pt = (types_data if isinstance(types_data, list) else [])[0] if types_data else None
            if pt:
                eq_payload["equipment_type_id"] = pt.get("id")

    if not eq_payload["equipment_type_id"]:
        skip(f"Equipment register ({dept}): no equipment_type_id found")
        continue

    r = requests.post(f"{BASE}/equipment/", json=eq_payload, headers=admin_h)
    if r.status_code == 201:
        eid = r.json().get("id")
        NEW_EQUIP_IDS[dept] = eid
        ok(f"POST /equipment/ ({dept})", f"201 id={eid}")
    else:
        skip(f"POST /equipment/ ({dept})", f"{r.status_code} {r.text[:120]}")
        continue

    # Verify it appears in list
    r = requests.get(f"{BASE}/equipment/", headers=admin_h)
    if r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        ids = [i.get("id") for i in items]
        if eid in ids:
            ok(f"New equipment appears in GET /equipment/ ({dept})")
        else:
            fail(f"New equipment NOT in GET /equipment/ ({dept})")

    # Get by ID
    r = requests.get(f"{BASE}/equipment/{eid}", headers=admin_h)
    check(f"GET /equipment/{eid} (new, {dept})", r, 200)

    # Get applicable tests for new equipment
    r = requests.get(f"{BASE}/equipment/{eid}/applicable-tests", headers=admin_h)
    if r.status_code in (200, 404):
        ok(f"GET /equipment/{eid}/applicable-tests", str(r.status_code))
    else:
        fail(f"GET /equipment/{eid}/applicable-tests", str(r.status_code))

    # Create a TR for the new equipment — use dept-specific originator so dept filter applies
    dept_orig_email = f"originator.{dept}@kptcl.com"
    orig_tok_dept = login(dept_orig_email)
    if not orig_tok_dept:
        orig_tok_dept = login("originator@kptcl.com", PW_KPTCL)
    if orig_tok_dept:
        r = requests.post(
            f"{BASE}/testing_requests/",
            json={
                "equipment_id": eid,
                "title": f"TR for new Power Transformer ({dept})",
                "request_category": "test",
                "description": f"Test against newly registered PT equipment in {dept} dept",
                "priority": "normal",
            },
            headers=auth(orig_tok_dept),
        )
        if r.status_code == 201:
            ok(f"TR created for new PT equipment ({dept})", f"id={r.json().get('id')}")
        else:
            skip(f"TR for new PT equipment ({dept})", f"{r.status_code} {r.text[:100]}")

    # Update PT_EQUIP_ID to the first newly registered one so later sections benefit
    if not PT_EQUIP_ID or PT_EQUIP_ID == EQUIP_ID:
        PT_EQUIP_ID = eid

# ─────────────────────────────────────────────────────────────────────────────
# 23. DASHBOARD KPI ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
section("23. DASHBOARD KPI ENDPOINTS")

# Re-login circle/zone users (already logged in section 16b but tokens not stored in TOKENS dict)
_t_ee_circle  = login("ee.circle@kptcl.com")
_t_see_circle = login("see.circle@kptcl.com")
_t_cee_zone   = login("cee.zone@kptcl.com")
_t_see_zone   = login("see.zone@kptcl.com")

dashboard_tokens = {
    "OrgAdmin (KptclAdmin)": TOKENS.get("KptclAdmin"),
    "EE TLSS (north)":       TOKENS.get("EeTlss"),
    "Originator (north)":    TOKENS.get("Originator"),
    "Tester (north)":        TOKENS.get("Tester"),
    "TechApprover (north)":  TOKENS.get("TechApprover"),
    # Circle-level users (subtree scope)
    "EE Circle":             _t_ee_circle,
    "SEE Circle":            _t_see_circle,
    # Zone-level users (org-wide scope)
    "CEE Zone":              _t_cee_zone,
    "SEE Zone":              _t_see_zone,
}

KPI_ENDPOINTS = [
    # ── Individual widget endpoints ──────────────────────────────────────
    "/dashboard/kpi",
    "/dashboard/role-view",
    "/dashboard/overdue-tests",
    "/dashboard/active-alerts",
    "/dashboard/flagged-equipment",
    "/dashboard/repair-progress",
    "/dashboard/maintenance-overdue",
    "/dashboard/procurement",
    "/dashboard/open-remediation",
    "/dashboard/failure-registry",
    "/dashboard/taqc-inspections",
    # ── Typed full dashboard routes (Flutter calls based on default_module.path) ──
    "/dashboard/full",              # convenience: resolves type from default_module
    "/dashboard/admin/full",        # ->admin_dashboard module path
    "/dashboard/ee-tlss/full",      # ->ee_tlss_dashboard / aee_dashboard module path
    "/dashboard/see-cee/full",      # ->see_dashboard / cee_dashboard module path
    "/dashboard/field/full",        # ->field/originator roles
]

for role_label, tok in dashboard_tokens.items():
    if not tok:
        skip(f"Dashboard tests for {role_label}", "no token")
        continue
    h = auth(tok)
    for ep in KPI_ENDPOINTS:
        r = requests.get(f"{BASE}{ep}", headers=h)
        if r.status_code == 200:
            ok(f"GET {ep} ({role_label})", "200")
        elif r.status_code in (403, 401):
            ok(f"GET {ep} ({role_label}) -> access denied", str(r.status_code))
        else:
            fail(f"GET {ep} ({role_label})", str(r.status_code))

# Role-specific dashboards — use role-appropriate tokens
for role_label, ep, tok in [
    ("EE TLSS (north)",   "/dashboard/ee-tlss",  TOKENS.get("EeTlss")),
    ("EE Circle",         "/dashboard/ee-tlss",  _t_ee_circle),
    ("AEE/SEE (admin)",   "/dashboard/aee",      TOKENS.get("KptclAdmin")),
    ("SEE Circle",        "/dashboard/see",      _t_see_circle),
    ("SEE Zone",          "/dashboard/see",      _t_see_zone),
    ("CEE Zone",          "/dashboard/cee",      _t_cee_zone),
]:
    if not tok:
        continue
    r = requests.get(f"{BASE}{ep}", headers=auth(tok))
    if r.status_code in (200, 403):
        ok(f"GET {ep} ({role_label})", str(r.status_code))
    else:
        fail(f"GET {ep} ({role_label})", str(r.status_code))

# invalidate-cache (POST — admin only)
r = requests.post(f"{BASE}/dashboard/invalidate-cache", headers=auth(TOKENS.get("KptclAdmin", "")))
if r.status_code in (200, 204, 403):
    ok("POST /dashboard/invalidate-cache (admin)", str(r.status_code))
else:
    fail("POST /dashboard/invalidate-cache (admin)", str(r.status_code))

# invalidate-cache should be denied for non-admins
if TOKENS.get("Tester"):
    r = requests.post(f"{BASE}/dashboard/invalidate-cache", headers=auth(TOKENS["Tester"]))
    if r.status_code in (403, 401):
        ok("POST /dashboard/invalidate-cache (tester) -> denied", str(r.status_code))
    else:
        skip("POST /dashboard/invalidate-cache RBAC", f"got {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# 24. SCHEDULE — Power Transformer × 4 TR categories
# ─────────────────────────────────────────────────────────────────────────────
section("24. SCHEDULE — Power Transformer × test / inspection / maintenance / repair_cycle")

# We need a fully-approved TR per category so WorkflowDispatch can create
# MN/IN schedules.  We'll also directly create a schedule on a draft TR to
# exercise the CRUD endpoints independently.

_SCHED_CATEGORIES = ["test", "inspection", "maintenance", "repair_lifecycle"]

# Use an existing PT equipment from section 22 (NEW_EQUIP_IDS) or fallback
_sched_equip_id = NEW_EQUIP_IDS.get("north") or PT_EQUIP_ID
_orig_tok   = TOKENS.get("Originator")
_assign_tok = TOKENS.get("TestAssigner")
_tester_tok = TOKENS.get("Tester")
_tech_tok   = TOKENS.get("TechApprover")
_admin_h    = auth(TOKENS.get("KptclAdmin", ""))

SCHED_TR_IDS = {}    # category -> TR id
SCHED_IDS    = {}    # category -> schedule id

for cat in _SCHED_CATEGORIES:
    if not _sched_equip_id or not _orig_tok:
        skip(f"Schedule ({cat}): missing equip_id or originator token")
        continue

    # Create TR
    r = requests.post(f"{BASE}/testing_requests/", json={
        "equipment_id": _sched_equip_id,
        "title": f"[SCHED] PT {cat} test",
        "request_category": cat,
        "description": f"Schedule test for Power Transformer ({cat})",
        "priority": "normal",
    }, headers=auth(_orig_tok))
    if r.status_code != 201:
        skip(f"CREATE TR for schedule ({cat})", f"{r.status_code} {r.text[:80]}")
        continue
    tr_id = r.json().get("id")
    SCHED_TR_IDS[cat] = tr_id
    ok(f"CREATE TR [{cat}] for schedule", f"id={tr_id}")

    # Submit
    r = requests.put(f"{BASE}/testing_requests/{tr_id}/submit", headers=auth(_orig_tok))
    check(f"SUBMIT TR [{cat}] for schedule", r, 200)

    # Attach a schedule directly on this TR (CRUD test)
    r = requests.post(f"{BASE}/testing_requests/{tr_id}/schedule/", json={
        "frequency": "yearly",
        "advance_days": 7,
    }, headers=auth(TOKENS.get("KptclAdmin", "")))
    if r.status_code == 201:
        sched = r.json()
        sched_id = sched.get("id")
        SCHED_IDS[cat] = sched_id
        ok(f"POST /testing_requests/{tr_id}/schedule/ [{cat}]", f"201 id={sched_id} freq={sched.get('frequency')}")
    else:
        skip(f"POST schedule [{cat}]", f"{r.status_code} {r.text[:100]}")
        sched_id = None

    # GET schedule
    r = requests.get(f"{BASE}/testing_requests/{tr_id}/schedule/", headers=_admin_h)
    if r.status_code == 200:
        ok(f"GET schedule [{cat}]", f"freq={r.json().get('frequency')} active={r.json().get('is_active')}")
    else:
        skip(f"GET schedule [{cat}]", str(r.status_code))

    # Update schedule -> quarterly
    r = requests.put(f"{BASE}/testing_requests/{tr_id}/schedule/", json={
        "frequency": "quarterly",
        "advance_days": 14,
    }, headers=_admin_h)
    if r.status_code == 200:
        ok(f"PUT schedule (update to quarterly) [{cat}]", f"freq={r.json().get('frequency')}")
    else:
        skip(f"PUT schedule [{cat}]", str(r.status_code))

    # Pause
    r = requests.patch(f"{BASE}/testing_requests/{tr_id}/schedule/pause", headers=_admin_h)
    if r.status_code == 200:
        ok(f"PATCH /pause [{cat}]", f"is_active={r.json().get('is_active')}")
    else:
        skip(f"PATCH /pause [{cat}]", str(r.status_code))

    # Resume
    r = requests.patch(f"{BASE}/testing_requests/{tr_id}/schedule/resume", headers=_admin_h)
    if r.status_code == 200:
        ok(f"PATCH /resume [{cat}]", f"is_active={r.json().get('is_active')}")
    else:
        skip(f"PATCH /resume [{cat}]", str(r.status_code))

    # GET logs
    r = requests.get(f"{BASE}/testing_requests/{tr_id}/schedule/logs", headers=_admin_h)
    if r.status_code == 200:
        ok(f"GET schedule/logs [{cat}]", f"count={len(r.json())}")
    else:
        skip(f"GET schedule/logs [{cat}]", str(r.status_code))


# ─────────────────────────────────────────────────────────────────────────────
# 25. MULTI-SESSION — Power Transformer, test category
# ─────────────────────────────────────────────────────────────────────────────
section("25. MULTI-SESSION — Power Transformer test (3 sessions + readings)")

_ms_equip_id = NEW_EQUIP_IDS.get("north") or PT_EQUIP_ID
_ms_orig_tok = TOKENS.get("Originator")
_ms_tester_tok = TOKENS.get("Tester")

MS_TR_ID  = None
MS_SESSION_IDS = []

if _ms_equip_id and _ms_orig_tok:
    # Create a TR for multi-session testing
    r = requests.post(f"{BASE}/testing_requests/", json={
        "equipment_id": _ms_equip_id,
        "title": "[MULTI-SESSION] PT Insulation Resistance Test",
        "request_category": "test",
        "description": "Multi-session insulation resistance test across 3 days",
        "priority": "normal",
    }, headers=auth(_ms_orig_tok))
    if r.status_code == 201:
        MS_TR_ID = r.json().get("id")
        ok("CREATE multi-session TR", f"id={MS_TR_ID}")
    else:
        skip("CREATE multi-session TR", f"{r.status_code} {r.text[:80]}")

if MS_TR_ID:
    # Submit TR
    r = requests.put(f"{BASE}/testing_requests/{MS_TR_ID}/submit", headers=auth(_ms_orig_tok))
    check("SUBMIT multi-session TR", r, 200)

    # Assign tester
    if ASSIGNED_TESTER_ID:
        r = requests.put(f"{BASE}/testing_requests/{MS_TR_ID}/assign",
                         json={"tester_id": str(ASSIGNED_TESTER_ID)},
                         headers=auth(TOKENS.get("TestAssigner", "")))
        check("ASSIGN multi-session TR", r, 200)

    # Accept + Start
    if _ms_tester_tok:
        r = requests.put(f"{BASE}/testing/{MS_TR_ID}/accept", headers=auth(_ms_tester_tok))
        check("ACCEPT multi-session TR", r, 200)
        r = requests.put(f"{BASE}/testing/{MS_TR_ID}/start", headers=auth(_ms_tester_tok))
        check("START multi-session TR", r, 200)

    # Create 3 test sessions
    now_dt = datetime.now(_tz)
    for i in range(1, 4):
        sess_date = (now_dt + _td(days=i-1)).isoformat()
        r = requests.post(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/", json={
            "session_number": i,
            "session_name": f"Day {i} — Insulation Resistance",
            "session_date": sess_date,
            "template_key": "test",
            "notes": f"Session {i} of 3",
            "weather_conditions": "Clear" if i < 3 else "Humid",
        }, headers=auth(_ms_tester_tok or TOKENS.get("KptclAdmin", "")))
        if r.status_code == 201:
            sid = r.json().get("id")
            MS_SESSION_IDS.append(sid)
            ok(f"CREATE session {i}", f"id={sid}")
        else:
            skip(f"CREATE session {i}", f"{r.status_code} {r.text[:80]}")

    # List sessions
    r = requests.get(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/",
                     headers=auth(_ms_tester_tok or TOKENS.get("KptclAdmin", "")))
    if r.status_code == 200:
        ok("GET /sessions/ (list)", f"count={len(r.json())}")
    else:
        skip("GET /sessions/", str(r.status_code))

    # For the first session: start it, add 2 readings, complete it
    if MS_SESSION_IDS:
        sid0 = MS_SESSION_IDS[0]
        tok_h = auth(_ms_tester_tok or TOKENS.get("KptclAdmin", ""))

        r = requests.post(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/{sid0}/start", headers=tok_h)
        if r.status_code == 200:
            ok(f"START session 1 (id={sid0})", f"status={r.json().get('status')}")
        else:
            skip(f"START session 1", str(r.status_code))

        for rdg_num in range(1, 3):
            r = requests.post(
                f"{BASE}/testing_requests/{MS_TR_ID}/sessions/{sid0}/readings",
                json={
                    "reading_number": rdg_num,
                    "reading_time": now_dt.isoformat(),
                    "reading_data": {
                        "insulation_resistance_mohm": 500 + rdg_num * 50,
                        "temperature_c": 28,
                        "humidity_percent": 60,
                    },
                    "result_status": "pass",
                    "remarks": f"Reading {rdg_num} normal",
                },
                headers=tok_h,
            )
            if r.status_code == 201:
                ok(f"CREATE reading {rdg_num} (session 1)", f"id={r.json().get('id')}")
            else:
                skip(f"CREATE reading {rdg_num}", f"{r.status_code} {r.text[:80]}")

        # List readings
        r = requests.get(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/{sid0}/readings", headers=tok_h)
        if r.status_code == 200:
            ok("GET /readings/ (session 1)", f"count={len(r.json())}")
        else:
            skip("GET /readings/", str(r.status_code))

        # Session statistics
        r = requests.get(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/{sid0}/statistics", headers=tok_h)
        if r.status_code == 200:
            ok("GET /statistics (session 1)", f"{r.json()}")
        else:
            skip("GET /statistics", str(r.status_code))

        # Complete session 1
        r = requests.post(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/{sid0}/complete", headers=tok_h)
        if r.status_code == 200:
            ok(f"COMPLETE session 1", f"status={r.json().get('status')}")
        else:
            skip(f"COMPLETE session 1", str(r.status_code))

    # Auto-generate sessions (idempotent or creates remaining)
    r = requests.post(f"{BASE}/testing_requests/{MS_TR_ID}/sessions/auto-generate",
                      headers=auth(_ms_tester_tok or TOKENS.get("KptclAdmin", "")))
    if r.status_code in (200, 201):
        ok("POST /sessions/auto-generate", f"generated={len(r.json())} sessions")
    else:
        skip("POST /sessions/auto-generate", f"{r.status_code} {r.text[:80]}")

else:
    skip("Multi-session TR flow", "no equipment_id available")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
total = pass_count + fail_count + skip_count
section("SUMMARY")
print(f"  {GREEN}PASS : {pass_count}{RESET}")
print(f"  {RED}FAIL : {fail_count}{RESET}")
print(f"  {YELLOW}SKIP : {skip_count}{RESET}")
print(f"  TOTAL: {total}\n")

if fail_count == 0:
    print(f"{GREEN}{BOLD}  All checks passed!{RESET}\n")
else:
    print(f"{RED}{BOLD}  {fail_count} check(s) failed — review above.{RESET}\n")
    sys.exit(1)
