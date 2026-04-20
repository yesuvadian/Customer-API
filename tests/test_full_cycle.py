"""
Full 4-User-Type Testing Request Lifecycle
============================================================
Users:
  1. ORIGINATOR   originator@kptcl.com   admin123
  2. ORG ADMIN    orgadmin@kptcl.com     admin123  (approves + assigns)
  3. FIELD TESTER fieldtester1@kptcl.com Tester123!
  4. LAB TESTER   labtester1@kptcl.com   Tester123!

Request categories tested:
  test | maintenance | inspection | repair_lifecycle
============================================================
"""
import requests
import json
from datetime import datetime, timezone

BASE = "http://localhost:8000"

# ── Colour helpers ────────────────────────────────────────────────────────────
OK   = "[OK]"
FAIL = "[FAIL]"
INFO = "[INFO]"
WARN = "[WARN]"

def section(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")

def step(msg):
    print(f"\n  >> {msg}")

def log(tag, msg):
    print(f"     {tag} {msg}")

# ── Auth ──────────────────────────────────────────────────────────────────────
def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()["access_token"]
    log(FAIL, f"Login failed for {email}: {r.status_code} {r.text[:80]}")
    return None

def h(token):
    return {"Authorization": f"Bearer {token}"}

def call(method, url, token=None, **kwargs):
    headers = h(token) if token else {}
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    r = getattr(requests, method)(url, headers=headers, **kwargs)
    return r

# ── Setup helpers ─────────────────────────────────────────────────────────────
def get_org_and_dept(admin_token):
    r = call("get", f"{BASE}/organizations/", admin_token)
    orgs = r.json() if r.status_code == 200 else []
    org = next((o for o in orgs if o.get("code") == "KPTCL"), orgs[0] if orgs else None)
    if not org:
        return None, None
    org_id = org["id"]
    # Use /testing_requests/department_hierarchy to get a leaf dept
    r2 = call("get", f"{BASE}/testing_requests/department_hierarchy?org_id={org_id}", admin_token)
    depts = r2.json() if r2.status_code == 200 else []
    dept_id = depts[0]["id"] if depts else None
    return org_id, dept_id

def get_equipment(admin_token):
    r = call("get", f"{BASE}/equipment/?limit=1", admin_token)
    items = r.json() if r.status_code == 200 else []
    return items[0] if items else None

def get_tester_role_and_user(admin_token, request_id, role_name="Field Tester"):
    r = call("get", f"{BASE}/testing-requests/approvals/{request_id}/tester-roles", admin_token)
    if r.status_code != 200:
        return None, None
    roles = r.json()
    role = next((ro for ro in roles if ro["role_name"] == role_name), None)
    if not role:
        # fallback: pick any role
        role = roles[0] if roles else None
    if not role:
        return None, None
    role_id = role["role_id"]
    r2 = call("get", f"{BASE}/testing-requests/approvals/{request_id}/tester-roles/{role_id}/users", admin_token)
    users = r2.json() if r2.status_code == 200 else []
    user = users[0] if users else None
    return role_id, user

# ── Core lifecycle function ───────────────────────────────────────────────────
def run_lifecycle(
    scenario_name,
    category,
    originator_token,
    admin_token,
    tester_email,
    tester_password,
    tester_role_name,
    org_id,
    dept_id,
    equip=None,
    test_data_payload=None,
):
    section(f"{scenario_name}  [category={category}]")
    passed = True

    # ── Step 1: Originator creates draft ──────────────────────────────────────
    step("ORIGINATOR: Create draft testing request")
    payload = {
        "title": f"[{category.upper()}] {scenario_name}",
        "description": f"Automated E2E test for {category} workflow",
        "request_category": category,
        "priority": "high",
        "transformer_type": "Power Transformer",
        "transformer_rating": "100 MVA",
        "manufacturer": "BHEL",
        "serial_number": f"SN-{category[:4].upper()}-{datetime.now().strftime('%H%M%S')}",
        "organization_id": org_id,
        "department_id": dept_id,
    }
    if equip:
        payload["equipment_id"] = equip["id"]
        payload["equipment_type_id"] = equip.get("equipment_type_id")

    r = call("post", f"{BASE}/testing_requests/", originator_token, json=payload)
    if r.status_code not in (200, 201):
        log(FAIL, f"Create failed {r.status_code}: {r.text[:100]}")
        return False
    req = r.json()
    req_id = req["id"]
    log(OK, f"Created  {req['request_number']}  status={req['status']}  category={req['request_category']}")
    log(INFO, f"         UEIC={req.get('equipment_ueic')}  dept={req.get('department_name')}")

    # ── Step 2: Originator submits ────────────────────────────────────────────
    step("ORIGINATOR: Submit request")
    r = call("put", f"{BASE}/testing_requests/{req_id}/submit", originator_token)
    if r.status_code != 200:
        log(FAIL, f"Submit failed {r.status_code}: {r.text[:100]}")
        return False
    log(OK, f"Submitted  new status={r.json()['status']}")

    # ── Step 3: Admin sees pending approvals ──────────────────────────────────
    step("ORG ADMIN: Check pending approvals")
    r = call("get", f"{BASE}/testing-requests/approvals/pending?category={category}", admin_token)
    pending = r.json() if r.status_code == 200 else []
    found = any(p["id"] == req_id for p in pending)
    log(OK if found else WARN, f"Pending list has {len(pending)} item(s). Our request found={found}")

    # ── Step 4: Admin picks tester role + user ────────────────────────────────
    step(f"ORG ADMIN: Pick {tester_role_name} role and user")
    role_id, tester_user = get_tester_role_and_user(admin_token, req_id, tester_role_name)
    if not tester_user:
        log(WARN, f"{tester_role_name} users not found via roles endpoint, using direct assign")
        # Fallback: login as tester to get their ID
        tt = login(tester_email, tester_password)
        if not tt:
            log(FAIL, "Tester login failed — cannot proceed")
            return False
        me_r = call("get", f"{BASE}/users/me", tt)
        if me_r.status_code == 200:
            tester_user = {"user_id": me_r.json()["id"], "email": tester_email, "name": tester_email}
        else:
            log(FAIL, "Cannot fetch tester user ID")
            return False
    else:
        log(OK, f"Role={tester_role_name}  user={tester_user['name']} ({tester_user['email']})")

    # ── Step 5: Admin approve-and-assign ─────────────────────────────────────
    step("ORG ADMIN: Approve and assign to tester")
    assign_body = {
        "tester_id": tester_user["user_id"],
        "comment": f"Approved for {tester_role_name} - {scenario_name}",
    }
    if role_id:
        assign_body["tester_role_id"] = str(role_id)

    r = call("post", f"{BASE}/testing-requests/approvals/{req_id}/approve-and-assign", admin_token, json=assign_body)
    if r.status_code != 200:
        log(FAIL, f"Approve-and-assign failed {r.status_code}: {r.text[:150]}")
        return False
    result = r.json()
    log(OK, f"Assigned to {result.get('assigned_tester_email')}  status={result.get('new_status')}")

    # ── Step 6: Tester logs in and sees assignment ────────────────────────────
    step(f"TESTER ({tester_email}): Login and view assignment")
    tester_token = login(tester_email, tester_password)
    if not tester_token:
        log(FAIL, f"Tester login failed")
        return False
    log(OK, f"Logged in as {tester_email}")

    r = call("get", f"{BASE}/testing/my-assignments", tester_token)
    assignments = r.json() if r.status_code == 200 else []
    found_assign = any(a["id"] == req_id for a in assignments)
    log(OK if found_assign else WARN, f"My-assignments: {len(assignments)} items, our request found={found_assign}")

    # ── Step 7: Tester accepts ────────────────────────────────────────────────
    step("TESTER: Accept request")
    r = call("put", f"{BASE}/testing/{req_id}/accept", tester_token)
    if r.status_code != 200:
        log(FAIL, f"Accept failed {r.status_code}: {r.text[:100]}")
        return False
    log(OK, f"Accepted  status={r.json()['status']}")

    # ── Step 8: Tester starts ─────────────────────────────────────────────────
    step("TESTER: Start testing")
    r = call("put", f"{BASE}/testing/{req_id}/start", tester_token)
    if r.status_code != 200:
        log(FAIL, f"Start failed {r.status_code}: {r.text[:100]}")
        return False
    log(OK, f"Started   status={r.json()['status']}")

    # ── Step 9: Tester uploads structured results ─────────────────────────────
    step("TESTER: Upload structured test results")
    if test_data_payload is None:
        test_data_payload = {
            "bdv_kv": "45",
            "acidity_mg_koh": "0.03",
            "moisture_ppm": "22",
            "tan_delta": "0.003",
            "overall": "NORMAL",
        }
    structured = {
        "template_key": f"{category}_test",
        "test_data": test_data_payload,
        "overall_result": "passed",
        "remarks": f"All {category} checks passed. Automated test.",
        "replacement_products": [],
    }
    r = call("post", f"{BASE}/testing/{req_id}/results/structured", tester_token, json=structured)
    if r.status_code not in (200, 201):
        log(FAIL, f"Upload results failed {r.status_code}: {r.text[:100]}")
        passed = False
    else:
        log(OK, f"Results uploaded  result_id={r.json().get('id','?')[:16]}...")

    # ── Step 10: Tester submits results ───────────────────────────────────────
    step("TESTER: Submit results (complete testing)")
    r = call("put", f"{BASE}/testing/{req_id}/submit_results", tester_token,
             json={"replacement_products": []})
    if r.status_code != 200:
        log(FAIL, f"Submit results failed {r.status_code}: {r.text[:100]}")
        return False
    status_after = r.json()["status"]
    log(OK, f"Submitted  status={status_after}")

    # ── Step 11: Admin / approver sees recommendation ─────────────────────────
    step("ORG ADMIN: View and approve recommendation")
    r = call("get", f"{BASE}/approvals/by-request/{req_id}", admin_token)
    if r.status_code != 200:
        log(WARN, f"No recommendation yet ({r.status_code}) — skipping approval step")
    else:
        rec = r.json()
        rec_id = rec["id"]
        rec_status = rec.get("approval_status")
        log(OK, f"Recommendation found  id={str(rec_id)[:16]}...  approval_status={rec_status}")

        if rec_status not in ("approved", "completed"):
            r2 = call("put", f"{BASE}/approvals/{rec_id}/approve", admin_token,
                      json={"notes": f"Approved by admin — {scenario_name}"})
            if r2.status_code == 200:
                log(OK, f"Recommendation approved  new_status={r2.json().get('approval_status')}")
            else:
                log(WARN, f"Approve recommendation returned {r2.status_code}: {r2.text[:80]}")

    # ── Step 12: Verify final state ───────────────────────────────────────────
    step("ORIGINATOR: Verify final request state")
    r = call("get", f"{BASE}/testing_requests/{req_id}", originator_token)
    if r.status_code == 200:
        final = r.json()
        log(OK, f"Final status         = {final['status']}")
        log(INFO, f"request_category     = {final['request_category']}")
        log(INFO, f"equipment_ueic       = {final.get('equipment_ueic')}")
        log(INFO, f"assigned_tester_name = {final.get('assigned_tester_name')}")
    else:
        log(FAIL, f"Could not fetch final state {r.status_code}")
        passed = False

    if passed:
        log(OK, f"SCENARIO PASSED")
    else:
        log(FAIL, f"SCENARIO HAD ERRORS — see above")
    return passed


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "+"*65)
    print("|" + " "*15 + "4-USER-TYPE E2E TEST SUITE" + " "*22 + "|")
    print("+"*65)
    print("""
  Users:
    1. ORIGINATOR   originator@kptcl.com   admin123
    2. ORG ADMIN    orgadmin@kptcl.com     admin123
    3. FIELD TESTER fieldtester1@kptcl.com Tester123!
    4. LAB TESTER   labtester1@kptcl.com   Tester123!
""")

    # ── Login all 4 users ────────────────────────────────────────────────────
    section("LOGIN — 4 User Types")
    tokens = {}

    users = [
        ("originator",   "originator@kptcl.com",    "admin123"),
        ("admin",        "orgadmin@kptcl.com",       "admin123"),
        ("fieldtester",  "fieldtester1@kptcl.com",   "Tester123!"),
        ("labtester",    "labtester1@kptcl.com",      "Tester123!"),
    ]
    for key, email, pwd in users:
        t = login(email, pwd)
        if t:
            tokens[key] = t
            log(OK, f"{key:15} logged in as {email}")
        else:
            log(FAIL, f"{key:15} login FAILED for {email}")

    if "admin" not in tokens or "originator" not in tokens:
        print("\n[FAIL] Cannot proceed — admin/originator login failed")
        return

    # ── Shared setup ─────────────────────────────────────────────────────────
    section("SETUP — Org, Department, Equipment")
    org_id, dept_id = get_org_and_dept(tokens["admin"])
    log(OK if org_id else FAIL, f"org_id  = {org_id}")
    log(OK if dept_id else WARN, f"dept_id = {dept_id}")

    equip = get_equipment(tokens["admin"])
    log(OK if equip else WARN,
        f"equipment = {equip['ueic'] if equip else 'none (will use manual fields)'}")

    if not org_id:
        print("[FAIL] No org found — cannot continue")
        return

    # ── Originator token (use admin if originator doesn't exist) ─────────────
    orig_token = tokens.get("originator") or tokens["admin"]

    # ── Run 4 scenarios — each with different category + tester type ─────────
    results = []

    # Scenario A: test category  → Field Tester
    if "fieldtester" in tokens:
        ok = run_lifecycle(
            scenario_name="Routine Test — Field Tester",
            category="test",
            originator_token=orig_token,
            admin_token=tokens["admin"],
            tester_email="fieldtester1@kptcl.com",
            tester_password="Tester123!",
            tester_role_name="Field Tester",
            org_id=org_id,
            dept_id=dept_id,
            equip=equip,
            test_data_payload={
                "insulation_resistance_mohm": "500",
                "winding_resistance_ohm": "0.45",
                "turns_ratio": "11:0.433",
                "no_load_current_a": "2.1",
                "overall": "PASS",
            },
        )
        results.append(("A. test      -> Field Tester",  ok))
    else:
        log(WARN, "Skipping Field Tester scenario (login failed)")

    # Scenario B: maintenance category  → Lab Tester
    if "labtester" in tokens:
        ok = run_lifecycle(
            scenario_name="Preventive Maintenance — Lab Tester",
            category="maintenance",
            originator_token=orig_token,
            admin_token=tokens["admin"],
            tester_email="labtester1@kptcl.com",
            tester_password="Tester123!",
            tester_role_name="Lab Tester",
            org_id=org_id,
            dept_id=dept_id,
            equip=equip,
            test_data_payload={
                "bdv_oil_kv": "42",
                "acidity_mg_koh_g": "0.05",
                "moisture_ppm": "25",
                "colour": "Light Yellow",
                "flash_point_c": "152",
                "overall": "NORMAL",
            },
        )
        results.append(("B. maintenance -> Lab Tester", ok))
    else:
        log(WARN, "Skipping Lab Tester maintenance scenario (login failed)")

    # Scenario C: inspection category  → Field Tester
    if "fieldtester" in tokens:
        ok = run_lifecycle(
            scenario_name="Annual Inspection — Field Tester",
            category="inspection",
            originator_token=orig_token,
            admin_token=tokens["admin"],
            tester_email="fieldtester1@kptcl.com",
            tester_password="Tester123!",
            tester_role_name="Field Tester",
            org_id=org_id,
            dept_id=dept_id,
            equip=None,  # manual fields only
            test_data_payload={
                "visual_condition": "Good",
                "oil_leakage": "None",
                "bushing_condition": "No cracks",
                "cooling_fans": "Operational",
                "tap_changer": "Smooth operation",
                "overall": "SATISFACTORY",
            },
        )
        results.append(("C. inspection  -> Field Tester", ok))

    # Scenario D: repair_lifecycle category  → Lab Tester
    if "labtester" in tokens:
        ok = run_lifecycle(
            scenario_name="Bushing Repair / Lifecycle — Lab Tester",
            category="repair_lifecycle",
            originator_token=orig_token,
            admin_token=tokens["admin"],
            tester_email="labtester1@kptcl.com",
            tester_password="Tester123!",
            tester_role_name="Lab Tester",
            org_id=org_id,
            dept_id=dept_id,
            equip=equip,
            test_data_payload={
                "tan_delta_bushing": "0.015",
                "capacitance_pf": "320",
                "partial_discharge_pc": "80",
                "remaining_life_years": "8",
                "action_recommended": "Monitor annually",
                "overall": "ALERT",
            },
        )
        results.append(("D. repair_lifecycle -> Lab Tester", ok))

    # ── Final summary ─────────────────────────────────────────────────────────
    section("FINAL SUMMARY")
    print()
    all_ok = True
    for name, passed in results:
        icon = OK if passed else FAIL
        print(f"  {icon}  {name}")
        if not passed:
            all_ok = False

    print()
    # Stats snapshot
    r = call("get", f"{BASE}/testing_requests/stats", tokens["admin"])
    if r.status_code == 200:
        stats = r.json()
        print(f"  Total requests in org : {stats.get('total')}")
        by_cat = stats.get("by_category", {})
        for cat, cnt in by_cat.items():
            bar = "#" * min(cnt, 30)
            print(f"    {cat:25}: {cnt:3}  {bar}")

    print()
    if all_ok:
        print("  *** ALL SCENARIOS PASSED ***")
    else:
        print("  *** SOME SCENARIOS FAILED — see output above ***")
    print()


if __name__ == "__main__":
    main()
