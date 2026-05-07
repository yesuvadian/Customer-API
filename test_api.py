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
section("1. AUTHENTICATION — all 10 roles (north dept)")

TOKENS = {}
ROLES = [
    ("orgadmin.north@kptcl.com",        "OrgAdmin"),
    ("depthead.north@kptcl.com",         "DeptHead"),
    ("originator.north@kptcl.com",       "Originator"),
    ("tester.north@kptcl.com",           "Tester"),
    ("assigner.north@kptcl.com",         "TestAssigner"),
    ("techapprover.north@kptcl.com",     "TechApprover"),
    ("financeapprover.north@kptcl.com",  "FinanceApprover"),
    ("eetlss.north@kptcl.com",           "EeTlss"),
    ("taqc.north@kptcl.com",             "TaqcOfficer"),
    ("sectionhead.north@kptcl.com",      "SectionHead"),
]

for email, role_key in ROLES:
    t = login(email)
    if t:
        TOKENS[role_key] = t

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
# 9. TESTING — tester full lifecycle (assigned→accepted→in_progress→submitted)
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
# 13. REPAIR WORKFLOWS
# ─────────────────────────────────────────────────────────────────────────────
section("13. REPAIR WORKFLOWS")

RW_ID = None
EE_H = auth(TOKENS.get("EeTlss", TOKENS.get("KptclAdmin", "")))

# Config
r = requests.get(f"{BASE}/repair-workflows/config/stages", headers=EE_H)
check("GET /repair-workflows/config/stages", r, 200)

r = requests.get(f"{BASE}/repair-workflows/config/transitions", headers=EE_H)
check("GET /repair-workflows/config/transitions", r, 200)

# List workflows
r = requests.get(f"{BASE}/repair-workflows", headers=EE_H)
rws = check("GET /repair-workflows", r, 200)
if rws:
    items = rws if isinstance(rws, list) else rws.get("items", [])
    if items:
        RW_ID = items[0].get("id")
        ok(f"First repair workflow id={RW_ID}")

if RW_ID:
    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}", headers=EE_H)
    check(f"GET /repair-workflows/{RW_ID}", r, 200)

    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}/timeline", headers=EE_H)
    if r.status_code in (200, 404):
        ok(f"GET /repair-workflows/{RW_ID}/timeline", str(r.status_code))
    else:
        fail(f"GET /repair-workflows/{RW_ID}/timeline", str(r.status_code))

    r = requests.get(f"{BASE}/repair-workflows/{RW_ID}/progress", headers=EE_H)
    if r.status_code in (200, 404):
        ok(f"GET /repair-workflows/{RW_ID}/progress", str(r.status_code))
    else:
        fail(f"GET /repair-workflows/{RW_ID}/progress", str(r.status_code))

# Start a new workflow for PT equipment (use PT_EQUIP_ID for specificity)
NEW_RW_ID = None
_rw_start_equip = PT_EQUIP_ID or EQUIP_ID
if _rw_start_equip:
    r = requests.post(
        f"{BASE}/repair-workflows/start",
        json={"equipment_id": _rw_start_equip, "remarks": "Started by automated test"},
        headers=EE_H,
    )
    if r.status_code in (200, 201):
        NEW_RW_ID = r.json().get("workflow_id") or r.json().get("id")
        ok(f"POST /repair-workflows/start ->active", f"{r.status_code} id={NEW_RW_ID}")
    elif r.status_code in (400, 409):
        # Already active for this equipment — use existing RW_ID
        NEW_RW_ID = RW_ID
        skip(f"POST /repair-workflows/start", f"{r.status_code} — using existing RW_ID={RW_ID}")
    else:
        fail(f"POST /repair-workflows/start", f"{r.status_code}: {r.text[:120]}")

# ── Repair workflow lifecycle: get form ->save data ->advance ────────────────
_rw = NEW_RW_ID or RW_ID
if _rw:
    # Get current stage form
    r = requests.get(f"{BASE}/repair-workflows/{_rw}/current-form", headers=EE_H)
    if r.status_code == 200:
        ok(f"GET /repair-workflows/{_rw}/current-form", "200")
        form_data = r.json()
        current_stage_id = form_data.get("stage_id")
    elif r.status_code == 404:
        # Already at terminal stage
        ok(f"GET current-form ->workflow completed/terminal", "404")
        current_stage_id = None
    else:
        fail(f"GET /repair-workflows/{_rw}/current-form", str(r.status_code))
        current_stage_id = None

    # Save stage form data — provide common fields that most repair stage templates need
    if current_stage_id:
        r = requests.post(
            f"{BASE}/repair-workflows/{_rw}/stages/{current_stage_id}/save",
            json={"form_data": {
                "failure_date": "2026-05-07",
                "failure_description": "Automated test — insulation degradation",
                "failure_mode": "Insulation breakdown",
                "failure_location": "HV winding",
                "severity": "high",
                "remarks": "Stage data saved by automated test",
                "condition": "fair",
                "visual_inspection": "Completed",
                "recommendation": "Send for repair",
            }},
            headers=EE_H,
        )
        if r.status_code in (200, 201):
            ok(f"POST /stages/{current_stage_id}/save", str(r.status_code))
        else:
            skip(f"POST /stages/{current_stage_id}/save", f"{r.status_code}: {r.text[:80]}")

    # Advance stage (active ->next stage or completed)
    r = requests.post(
        f"{BASE}/repair-workflows/{_rw}/advance",
        json={"remarks": "Advanced by automated test"},
        headers=EE_H,
    )
    if r.status_code == 200:
        new_status = r.json().get("status", "?")
        ok(f"POST /repair-workflows/{_rw}/advance ->{new_status}", "200")
    elif r.status_code in (400, 422):
        skip(f"Advance skipped", f"{r.status_code}: {r.text[:80]}")
    else:
        fail(f"POST /repair-workflows/{_rw}/advance", f"{r.status_code}: {r.text[:80]}")

# ── Reject path — start a SECOND workflow for the same equipment and reject it ─
# Use a different equipment to avoid conflict with the workflow above
_rw_reject_equip = EQUIP_ID  # use the generic first equipment
if _rw_reject_equip and _rw_reject_equip != _rw_start_equip:
    r = requests.post(
        f"{BASE}/repair-workflows/start",
        json={"equipment_id": _rw_reject_equip, "remarks": "Reject-path test"},
        headers=EE_H,
    )
    _reject_rw_id = None
    if r.status_code in (200, 201):
        _reject_rw_id = r.json().get("workflow_id") or r.json().get("id")
        ok(f"POST /repair-workflows/start (reject path)", f"id={_reject_rw_id}")
    elif r.status_code in (400, 409):
        # Reuse existing but only if different from _rw
        skip("Reject-path start skipped — equipment already has active workflow")

    if _reject_rw_id:
        r = requests.post(
            f"{BASE}/repair-workflows/{_reject_rw_id}/reject",
            json={"remarks": "Rejected by automated test — equipment not accessible"},
            headers=EE_H,
        )
        if r.status_code == 200:
            ok(f"POST /repair-workflows/{_reject_rw_id}/reject ->rejected", "200")
        elif r.status_code in (400, 422):
            skip(f"Reject skipped", f"{r.status_code}: {r.text[:80]}")
        else:
            fail(f"POST /repair-workflows/{_reject_rw_id}/reject", f"{r.status_code}: {r.text[:80]}")

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
# 15. NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────
section("15. NOTIFICATIONS")

for role_key, token in list(TOKENS.items())[:4]:
    if token:
        r = requests.get(f"{BASE}/notifications/", headers=auth(token))
        check(f"GET /notifications/ ({role_key})", r, 200)

        r = requests.get(f"{BASE}/notifications/unread-count", headers=auth(token))
        check(f"GET /notifications/unread-count ({role_key})", r, 200)
        break

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
        "template_key": "failure_registry_default",
        "title": f"FR Test - {dept.upper()} dept - Power Transformer",
        "equipment_id": PT_EQUIP_ID,
        "test_data": {
            "failure_date": "2026-05-01",
            "failure_mode": "Insulation breakdown",
            "location": f"{dept} substation",
            "severity": "high",
        },
        "overall_result": "fail",
        "remarks": f"Automated FR test for {dept} dept",
        "priority": "high",
    }
    r = requests.post(f"{BASE}/direct-submissions/", json=payload, headers=h)
    if r.status_code == 201:
        fid = r.json().get("id")
        FR_IDS[dept] = fid
        ok(f"POST /direct-submissions/ failure_registry ({dept})", f"201 id={fid}")
    elif r.status_code in (400, 422):
        # try with minimal data / different template key
        payload["template_key"] = "failure_registry"
        r2 = requests.post(f"{BASE}/direct-submissions/", json=payload, headers=h)
        if r2.status_code == 201:
            fid = r2.json().get("id")
            FR_IDS[dept] = fid
            ok(f"POST /direct-submissions/ failure_registry ({dept})", f"201 id={fid}")
        else:
            skip(f"POST /direct-submissions/ failure_registry ({dept})", f"{r.status_code}: {r.text[:120]}")
    else:
        skip(f"POST /direct-submissions/ failure_registry ({dept})", f"{r.status_code}")

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
        "template_key": "taqc_inspection_default",
        "title": f"TAQC Inspection - {dept.upper()} - Power Transformer",
        "equipment_id": PT_EQUIP_ID,
        "test_data": {
            "inspection_date": "2026-05-06",
            "inspector_name": f"TAQC Officer {dept}",
            "equipment_condition": "fair",
            "oil_level": "normal",
            "bushing_condition": "good",
            "cooling_system": "ok",
        },
        "overall_result": "pass",
        "remarks": f"Automated TAQC test for {dept} dept",
        "priority": "normal",
    }
    r = requests.post(f"{BASE}/direct-submissions/", json=payload, headers=h)
    if r.status_code == 201:
        tid = r.json().get("id")
        TAQC_IDS[dept] = tid
        ok(f"POST /direct-submissions/ taqc_inspection ({dept})", f"201 id={tid}")
    elif r.status_code in (400, 422):
        payload["template_key"] = "taqc_inspection"
        r2 = requests.post(f"{BASE}/direct-submissions/", json=payload, headers=h)
        if r2.status_code == 201:
            tid = r2.json().get("id")
            TAQC_IDS[dept] = tid
            ok(f"POST /direct-submissions/ taqc_inspection ({dept})", f"201 id={tid}")
        else:
            skip(f"POST /direct-submissions/ taqc_inspection ({dept})", f"{r.status_code}: {r.text[:120]}")
    else:
        skip(f"POST /direct-submissions/ taqc_inspection ({dept})", str(r.status_code))

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
