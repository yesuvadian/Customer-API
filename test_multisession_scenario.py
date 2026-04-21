# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
SEACMS Multi-Session Test Scenario
====================================
Steps:
  1. Update IR test template — pi_value column → calculated (ratio(ir_value_10min, ir_value_1min))
     + column_summaries (avg PI, avg IR1, avg IR10)
  2. Create a testing request (1 day, 3 sessions)
  3. Approve and assign tester
  4. Tester accepts + starts
  5. Tester enters 3 sessions of data (save × 3) — auto-creates TestSession rows
  6. Check /sessions/ endpoint + AEE dashboard before submit
  7. Submit test results
  8. Check AEE + EE-TLSS dashboard after submit
"""

import requests, json, time
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8080"
H_JSON   = {"Content-Type": "application/json"}

# KPTCL org users (password = admin123 for all KPTCL seed users)
USERS = {
    "requester":       {"email": "originator@kptcl.com",   "password": "admin123"},
    "approver":        {"email": "testassigner@kptcl.com", "password": "admin123"},
    # see.rt@kptcl.com has "SEE RT" role — matches tester-roles returned by approval endpoint
    "tester":          {"email": "see.rt@kptcl.com",       "password": "admin123"},
    "result_approver": {"email": "orgadmin@kptcl.com",     "password": "admin123"},
}
TOKENS = {}

IR_TEMPLATE_ID = "be04a246-8ca0-436e-8b8f-141f803b3308"   # insulation_resistance_test

# ─── colours ─────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[94m"; E = "\033[0m"; BOLD = "\033[1m"
def ok(t):   print(f"{G}✓ {t}{E}")
def err(t):  print(f"{R}✗ {t}{E}")
def info(t): print(f"{Y}  {t}{E}")
def hdr(t):  print(f"\n{C}{BOLD}{'═'*70}{E}\n{C}{BOLD}  {t}{E}\n{C}{BOLD}{'═'*70}{E}")
def sec(t):  print(f"\n{B}{BOLD}── {t} {'─'*(65-len(t))}{E}")

# ─── helpers ─────────────────────────────────────────────────────────────────
def login(role):
    u = USERS[role]
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": u["email"], "password": u["password"]})
    if r.status_code == 200:
        TOKENS[role] = r.json()["access_token"]
        ok(f"Login [{role}]  {u['email']}")
        return True
    err(f"Login failed [{role}]: {r.status_code} {r.text[:120]}")
    return False

def auth(role):
    return {**H_JSON, "Authorization": f"Bearer {TOKENS[role]}"}

def jprint(label, d, keys=None):
    if keys:
        d = {k: d[k] for k in keys if k in d}
    info(f"{label}: {json.dumps(d, indent=2, default=str)}")

# ─── STEP 1: Verify template has calculated pi_value + column_summaries ───────
# The template is now seeded with these values in test_templates.py.
# This step verifies the DB reflects the correct structure; if an older seed is
# present it self-heals by applying the update via the Template Designer API
# (same call the UI makes when the admin saves changes in Template Designer).
def step1_update_template():
    sec("STEP 1 — Verify IR template: pi_value=calculated + column_summaries")

    r = requests.get(f"{BASE_URL}/org-test-templates/{IR_TEMPLATE_ID}", headers=auth("requester"))
    if r.status_code != 200:
        err(f"Fetch template failed: {r.status_code}")
        return False

    tmpl = r.json()
    td   = tmpl["template_data"]

    # Check current state
    already_correct = False
    needs_fix = False
    for sec_block in td.get("sections", []):
        for field in sec_block.get("fields", []):
            if field.get("key") == "ir_readings" and field.get("type") == "table":
                for col in field.get("columns", []):
                    if col.get("key") == "pi_value":
                        if col.get("type") == "calculated" and col.get("formula"):
                            already_correct = True
                            info(f"  pi_value already calculated  formula={col['formula']}")
                        else:
                            needs_fix = True
                            info("  pi_value is plain number — applying fix via Template Designer API")
                            col["type"]    = "calculated"
                            col["formula"] = "ratio(ir_value_10min, ir_value_1min)"
                # Ensure column_summaries are set
                if not field.get("column_summaries"):
                    needs_fix = True
                    field["column_summaries"] = {
                        "ir_value_1min":  "avg",
                        "ir_value_10min": "avg",
                        "pi_value":       "avg",
                    }
                    info("  column_summaries missing — adding avg for IR1/IR10/PI")
                else:
                    info(f"  column_summaries already set: {field['column_summaries']}")

    if already_correct and not needs_fix:
        ok("Template already has correct structure (no update needed)")
        return True

    # Apply fix via same API endpoint the Template Designer UI uses
    r2 = requests.put(
        f"{BASE_URL}/org-test-templates/{IR_TEMPLATE_ID}",
        headers=auth("result_approver"),
        json={"template_data": td},
    )
    if r2.status_code in (200, 201):
        ok(f"Template updated via Template Designer API  (HTTP {r2.status_code})")
        # Verify round-trip
        r3 = requests.get(f"{BASE_URL}/org-test-templates/{IR_TEMPLATE_ID}", headers=auth("requester"))
        for sb in r3.json()["template_data"]["sections"]:
            for f in sb.get("fields", []):
                if f.get("key") == "ir_readings":
                    for c in f.get("columns", []):
                        if c.get("key") == "pi_value":
                            info(f"  Verified pi_value type={c['type']} formula={c.get('formula')}")
                    info(f"  Verified column_summaries={f.get('column_summaries')}")
        return True
    else:
        err(f"Template update failed: {r2.status_code}  {r2.text[:200]}")
        return False

# ─── STEP 2: Create testing request ──────────────────────────────────────────
STATE = {}

def step2_create_request():
    sec("STEP 2 — Create testing request (IR test, 1 day, 3 planned sessions)")

    # Get equipment types
    r = requests.get(f"{BASE_URL}/testing_requests/equipment_types", headers=auth("requester"))
    eq_types = r.json()
    info(f"Equipment types available: {[e['name'] for e in eq_types[:5]]}")

    # Pick Current Transformer (has CT Insulation test) or first with tests
    eq = next((e for e in eq_types if "current transformer" in e["name"].lower()), None)
    if not eq:
        eq = next((e for e in eq_types if e.get("tests")), eq_types[0])
    STATE["equipment_type_id"] = eq["id"]

    # Pick test type — prefer insulation/IR test
    tests = eq.get("tests", eq.get("test_types", []))
    tt = next((t for t in tests if "insulation" in t["name"].lower()), None)
    if not tt and tests:
        tt = tests[0]
    STATE["test_type_id"] = tt["id"] if tt else None
    info(f"Equipment type: {eq['name']}  |  Test type: {tt['name'] if tt else 'none'}")

    # NOTE: department_id is optional — dropdown returns empty, hierarchy returns org IDs
    # which are not valid department IDs. Skip it to avoid FK violation.
    info("Department: skipped (no org_departments seeded)")

    payload = {
        "title": "Transformer IR Test — 3-Session Multisession Scenario",
        "description": "Insulation resistance test across 3 sessions on the same day to validate PI calculation and session tracing",
        "equipment_type_id": STATE["equipment_type_id"],
        "test_type_id": STATE["test_type_id"],
        "priority": "high",
        "request_category": "maintenance",
        "due_date": (datetime.now() + timedelta(days=3)).isoformat(),
    }

    r = requests.post(f"{BASE_URL}/testing_requests/", headers=auth("requester"), json=payload)
    if r.status_code in (200, 201):
        d = r.json()
        STATE["request_id"] = d["id"]
        ok(f"Request created  id={d['id']}  status={d['status']}")
        return True
    err(f"Create request failed: {r.status_code}  {r.text[:300]}")
    return False

# ─── STEP 3: Submit + approve + assign ────────────────────────────────────────
def step3_approve_assign():
    sec("STEP 3 — Submit → Approve → Assign tester")
    rid = STATE["request_id"]

    # Submit
    r = requests.put(f"{BASE_URL}/testing_requests/{rid}/submit", headers=auth("requester"))
    if r.status_code not in (200, 201):
        err(f"Submit failed: {r.status_code} {r.text[:200]}")
        return False
    ok("Request submitted")

    # Get tester user id
    r = requests.get(f"{BASE_URL}/users/me", headers=auth("tester"))
    if r.status_code != 200:
        err("Cannot get tester user id"); return False
    STATE["tester_id"] = r.json()["id"]
    info(f"Tester user id: {STATE['tester_id']}")

    # Get tester roles for this request
    r = requests.get(
        f"{BASE_URL}/testing-requests/approvals/{rid}/tester-roles",
        headers=auth("approver")
    )
    if r.status_code != 200 or not r.json():
        err(f"Tester roles failed: {r.status_code}  {r.text[:200]}")
        return False
    roles = r.json()
    info(f"Available tester roles: {[rr['role_name'] for rr in roles]}")

    # Find which role our tester user actually has
    # Use: GET /testing-requests/approvals/{rid}/tester-roles/{role_id}/users
    chosen_role = None
    for role in roles:
        r_check = requests.get(
            f"{BASE_URL}/testing-requests/approvals/{rid}/tester-roles/{role['role_id']}/users",
            headers=auth("approver"),
        )
        if r_check.status_code == 200:
            testers_in_role = r_check.json()
            match = next((t for t in testers_in_role if t.get("user_id", t.get("id")) == STATE["tester_id"]), None)
            if match:
                chosen_role = role
                info(f"Tester found in role: {role['role_name']}")
                break
    if not chosen_role:
        # Fallback: look for "SEE RT" role specifically
        chosen_role = next((rr for rr in roles if "SEE" in rr["role_name"]), roles[0])
        info(f"Tester not auto-matched; using role: {chosen_role['role_name']}")
    STATE["tester_role_id"] = chosen_role["role_id"]
    info(f"Using tester role: {chosen_role['role_name']}")

    # Approve + assign
    r = requests.post(
        f"{BASE_URL}/testing-requests/approvals/{rid}/approve-and-assign",
        headers=auth("approver"),
        json={"tester_id": STATE["tester_id"], "tester_role_id": STATE["tester_role_id"]},
    )
    if r.status_code in (200, 201):
        ok("Approved and tester assigned")
        return True
    err(f"Approve-assign failed: {r.status_code}  {r.text[:300]}")
    return False

# ─── STEP 4: Tester accepts + starts ─────────────────────────────────────────
def step4_tester_accept_start():
    sec("STEP 4 — Tester accepts and starts")
    rid = STATE["request_id"]

    r = requests.put(f"{BASE_URL}/testing/{rid}/accept", headers=auth("tester"))
    if r.status_code not in (200, 201):
        err(f"Accept failed: {r.status_code} {r.text[:200]}"); return False
    ok("Assignment accepted")

    r = requests.put(f"{BASE_URL}/testing/{rid}/start", headers=auth("tester"))
    if r.status_code not in (200, 201):
        err(f"Start failed: {r.status_code} {r.text[:200]}"); return False
    ok("Testing started → in_progress")
    return True

# ─── STEP 5: Tester saves 3 sessions ─────────────────────────────────────────
SESSION_DATA = [
    # Session 1 — Morning readings
    {
        "winding": "HV-LV",
        "ir_1min_vals":  [250, 180, 220],   # one per phase/row
        "ir_10min_vals": [450, 310, 390],
        "points": ["HV to LV & E", "LV to HV & E", "HV+LV to E"],
    },
    # Session 2 — Afternoon cross-check
    {
        "winding": "HV-LV",
        "ir_1min_vals":  [260, 185, 225],
        "ir_10min_vals": [470, 320, 400],
        "points": ["HV to LV & E", "LV to HV & E", "HV+LV to E"],
    },
    # Session 3 — Final readings after oil temp stabilised
    {
        "winding": "HV-LV",
        "ir_1min_vals":  [280, 200, 240],
        "ir_10min_vals": [510, 350, 430],
        "points": ["HV to LV & E", "LV to HV & E", "HV+LV to E"],
    },
]

def step5_tester_sessions():
    sec("STEP 5 — Tester saves 3 sessions (each save auto-creates TestSession row)")
    rid = STATE["request_id"]
    tmpl_key = "insulation_resistance_test"

    for session_num, sdata in enumerate(SESSION_DATA, 1):
        info(f"\n  --- Session {session_num} ---")

        # Build table rows with PI already calculated client-side
        # (In the real app Flutter calculates; here we simulate it)
        rows = []
        for i, (pt, ir1, ir10) in enumerate(zip(
            sdata["points"], sdata["ir_1min_vals"], sdata["ir_10min_vals"]
        )):
            pi = round(ir10 / ir1, 2) if ir1 else 0
            rows.append({
                "winding":           sdata["winding"],
                "measurement_point": pt,
                "ir_value_1min":     ir1,
                "ir_value_10min":    ir10,
                "pi_value":          pi,     # calculated: ratio(ir_value_10min, ir_value_1min)
                "row_result":        "Pass" if pi >= 1.5 else "Fail",
            })
            info(f"    Row {i+1}: {pt}  IR1={ir1}  IR10={ir10}  PI={pi}")

        avg_pi = round(sum(r["pi_value"] for r in rows) / len(rows), 2)
        overall = "pass" if avg_pi >= 1.5 else "fail"

        payload = {
            "template_key": tmpl_key,
            "test_data": {
                "equipment_make":    "Siemens",
                "equipment_serial":  "TRF-2024-KPTCL-001",
                "megger_make":       "Megger MIT1025",
                "test_voltage":      "5000V",
                "temperature":       28 + session_num,
                "humidity":          65,
                "ir_readings":       rows,
                "min_acceptable_ir": 100,
                "overall_remarks":   f"Session {session_num} readings — avg PI={avg_pi}",
            },
            "overall_result":  overall,
            "remarks":         f"Session {session_num} of 3  (avg PI={avg_pi})",
        }

        r = requests.post(
            f"{BASE_URL}/testing/{rid}/results/structured",
            headers=auth("tester"),
            json=payload,
        )
        if r.status_code in (200, 201):
            ok(f"Session {session_num} saved  (HTTP {r.status_code})  overall={overall}  avg_pi={avg_pi}")
        else:
            err(f"Session {session_num} save failed: {r.status_code}  {r.text[:300]}")
            return False

        time.sleep(0.5)   # slight gap so timestamps differ

    return True

# ─── STEP 6: Check sessions + dashboard BEFORE submit ─────────────────────────
def step6_check_before_submit():
    sec("STEP 6 — Check /sessions/ + AEE dashboard  (BEFORE submit)")
    rid = STATE["request_id"]

    # Sessions endpoint
    r = requests.get(
        f"{BASE_URL}/testing_requests/{rid}/sessions/",
        headers=auth("tester")
    )
    if r.status_code == 200:
        sessions = r.json()
        ok(f"/sessions/  →  {len(sessions)} session(s) found")
        for s in sessions:
            info(f"  #{s['session_number']}  date={s['session_date']}  status={s['status']}  tpl={s.get('template_key','')}")
    else:
        err(f"/sessions/ failed: {r.status_code}  {r.text[:200]}")

    # AEE dashboard
    r = requests.get(f"{BASE_URL}/dashboard/aee", headers=auth("approver"))
    if r.status_code == 200:
        d = r.json()
        ok("AEE dashboard loaded")
        info(f"  KPIs: {d['kpis']}")
        for a in d.get("assignments", []):
            if STATE["request_id"] in str(a.get("id", "")):
                info(f"  *** Our request in assignments: {a}")
                break
        else:
            info("  (our request may not be in top-10 AEE assignments)")
            for a in d.get("assignments", [])[:3]:
                info(f"  sample assignment: sessions={a.get('session_count',0)}  last={a.get('last_session_date','—')}  status={a.get('status')}")
    else:
        err(f"AEE dashboard failed: {r.status_code}")

    # Test results snapshot
    r = requests.get(f"{BASE_URL}/testing/{rid}/results", headers=auth("tester"))
    if r.status_code == 200:
        results = r.json()
        ok(f"/results/  →  {len(results)} result row(s)")
        for res in results:
            info(f"  template_key={res.get('template_key')}  overall={res.get('overall_result')}  rows={len(res.get('test_data',{}).get('ir_readings',[]))}")
    return True

# ─── STEP 7: Submit test results ─────────────────────────────────────────────
def step7_submit():
    sec("STEP 7 — Tester submits test results")
    rid = STATE["request_id"]

    r = requests.put(f"{BASE_URL}/testing/{rid}/submit_results", headers=auth("tester"))
    if r.status_code in (200, 201):
        d = r.json()
        ok(f"Results submitted  status={d.get('status')}  request_number={d.get('request_number')}")
        # Check recommendation created
        STATE["post_submit_status"] = d.get("status")
        return True
    err(f"Submit failed: {r.status_code}  {r.text[:300]}")
    return False

# ─── STEP 8: Check dashboards AFTER submit ────────────────────────────────────
def step8_check_after_submit():
    sec("STEP 8 — Check AEE + EE-TLSS dashboard  (AFTER submit)")
    rid = STATE["request_id"]

    # Verify request status
    r = requests.get(f"{BASE_URL}/testing_requests/{rid}", headers=auth("requester"))
    if r.status_code == 200:
        st = r.json().get("status")
        ok(f"Request status → {st}")
    else:
        err(f"Request fetch failed: {r.status_code}")

    # Sessions after submit
    r = requests.get(f"{BASE_URL}/testing_requests/{rid}/sessions/", headers=auth("tester"))
    if r.status_code == 200:
        ok(f"Final session count: {len(r.json())}")

    # AEE dashboard
    r = requests.get(f"{BASE_URL}/dashboard/aee", headers=auth("approver"))
    if r.status_code == 200:
        d = r.json()
        ok("AEE dashboard (post-submit)")
        info(f"  KPIs: {d['kpis']}")
    else:
        err(f"AEE failed: {r.status_code}")

    # EE-TLSS dashboard
    r = requests.get(f"{BASE_URL}/dashboard/ee-tlss", headers=auth("result_approver"))
    if r.status_code == 200:
        d = r.json()
        ok("EE-TLSS dashboard (post-submit)")
        kpis = d["kpis"]
        info(f"  test_compliance    = {kpis.get('test_compliance')}%")
        info(f"  overdue_tests      = {kpis.get('overdue_tests')}")
        info(f"  alert_critical     = {kpis.get('alert_critical')}")
        info(f"  open_remediation   = {kpis.get('open_remediation')}")
        info(f"  maintenance_compl  = {kpis.get('maintenance_compliance')}%")
    else:
        err(f"EE-TLSS failed: {r.status_code}  {r.text[:200]}")

    return True

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    hdr("SEACMS MULTI-SESSION SCENARIO — 3 sessions / IR test / calculated PI")

    # Login all roles
    sec("LOGIN")
    for role in USERS:
        if not login(role):
            err("Aborting — login failed"); return

    steps = [
        ("Update template (calculated pi_value)",  step1_update_template),
        ("Create testing request",                 step2_create_request),
        ("Submit → Approve → Assign tester",       step3_approve_assign),
        ("Tester accepts + starts",                step4_tester_accept_start),
        ("Tester saves 3 sessions",                step5_tester_sessions),
        ("Check sessions + dashboard (pre-submit)",step6_check_before_submit),
        ("Submit test results",                    step7_submit),
        ("Check dashboard (post-submit)",          step8_check_after_submit),
    ]

    passed = failed = 0
    for name, fn in steps:
        try:
            result = fn()
            if result: passed += 1
            else:      failed += 1
        except Exception as ex:
            err(f"Exception in [{name}]: {ex}")
            import traceback; traceback.print_exc()
            failed += 1
        time.sleep(0.3)

    hdr("RESULTS")
    total = passed + failed
    print(f"\n  {G if failed==0 else Y}Passed: {passed}/{total}{E}")
    print(f"  {R if failed else G}Failed: {failed}/{total}{E}")
    if failed == 0:
        print(f"\n  {G}{BOLD}🎉  ALL STEPS PASSED{E}\n")
    else:
        print(f"\n  {Y}{BOLD}⚠  SOME STEPS FAILED — check output above{E}\n")

if __name__ == "__main__":
    main()
