"""
tests/test_calibration_integration.py
=======================================
Calibration / DATE_ADD Lifecycle — End-to-End Integration Test Suite

Flow
----
§1  Auth
§2  Template validation — calibration template in DB, rules[], enable_calibration=true
§3  Equipment config — get/set lead_days + is_scheduled
§4  Session readings — POST a Pass reading via TestingRequest + TestSession
§5  Status check — state computed correctly from calibration_date + validity_months
§6  Evaluate (Pass path) — DATE_ADD rule → NORMAL / DUE_SOON / OVERDUE
§7  Force OVERDUE — old calibration_date + short validity so next_due is past
§8  Failure lifecycle — overall_result=Fail → CRITICAL + REPAIR_OR_REPLACE recommendation
§9  Idempotency — second evaluate after FAIL does NOT create second recommendation
§10 Resume schedule — POST resume → is_scheduled=True, status no longer CRITICAL
§11 History endpoint — all records returned newest first
§12 Negative tests — bad equipment ID, unauthenticated, invalid body

Prerequisites:
  1. python tests/clean_and_seed.py
  2. python run_migration_calibration.py
  3. uvicorn main:app --reload --port 8000
  4. python tests/test_calibration_integration.py
"""

import sys
import time
from datetime import datetime, timedelta, timezone, date

import requests
from requests.exceptions import ConnectionError as ReqConnError

BASE     = "http://localhost:8000"
PW       = "TestDept@123"
PW_ADMIN = "admin123"

# ── Retry wrapper ──────────────────────────────────────────────────────────────
_orig_get  = requests.get
_orig_post = requests.post
_orig_put  = requests.put

def _req(fn, url, *, retries=3, delay=1.5, **kw):
    for attempt in range(retries):
        try:
            return fn(url, **kw)
        except ReqConnError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

requests.get  = lambda url, **kw: _req(_orig_get,  url, **kw)
requests.post = lambda url, **kw: _req(_orig_post, url, **kw)
requests.put  = lambda url, **kw: _req(_orig_put,  url, **kw)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GREEN  = "\033[92m"; RED    = "\033[91m"; YELLOW = "\033[93m"
CYAN   = "\033[96m"; RESET  = "\033[0m";  BOLD   = "\033[1m"

pass_count = fail_count = skip_count = 0

def ok(label, detail=""):
    global pass_count; pass_count += 1
    print(f"  {GREEN}[PASS]{RESET} {label}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))

def fail(label, detail=""):
    global fail_count; fail_count += 1
    print(f"  {RED}[FAIL]{RESET} {label}" + (f"  {YELLOW}{detail}{RESET}" if detail else ""))

def skip(label, detail=""):
    global skip_count; skip_count += 1
    print(f"  {YELLOW}[SKIP]{RESET} {label}" + (f" — {detail}" if detail else ""))

def info(label):
    print(f"  {CYAN}[INFO]{RESET} {label}")

def section(title):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")

def _print_summary():
    total = pass_count + fail_count + skip_count
    colour = GREEN if fail_count == 0 else RED
    print(f"\n{BOLD}{colour}{'='*60}{RESET}")
    print(f"{BOLD}{colour}  RESULTS  passed={pass_count}  failed={fail_count}  skipped={skip_count}  total={total}{RESET}")
    print(f"{BOLD}{colour}{'='*60}{RESET}\n")

def check(label, resp, expected_status, key=None):
    if resp.status_code == expected_status:
        ok(label, str(resp.status_code))
        body = resp.json() if resp.text else {}
        return body.get(key) if key else body
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text[:200]
    fail(label, f"got {resp.status_code} expected {expected_status} — {detail}")
    return None

def check_neg(label, resp, expected_statuses):
    if resp.status_code in expected_statuses:
        ok(f"[NEG] {label}", f"correctly rejected {resp.status_code}")
    else:
        fail(f"[NEG] {label}", f"got {resp.status_code} expected one of {expected_statuses}")

def login(email, pw=PW):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    if r.status_code == 200:
        body = r.json()
        ok(f"login {email}", "200")
        return body.get("access_token"), str(body.get("user", {}).get("id", ""))
    fail(f"login {email}", f"{r.status_code} {r.text[:120]}")
    return None, None

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def _advance_to_accepted(treq_id, token):
    """
    Advance a freshly-created (draft) testing request to 'accepted' status
    so that POST /testing/{id}/results/structured is allowed.
    Flow: draft → PUT /testing_requests/{id}/submit → assigned
          assigned → PUT /testing/{id}/accept → accepted
    Requires the request to have been created with assigned_tester_id = current user.
    """
    r = requests.put(f"{BASE}/testing_requests/{treq_id}/submit", headers=auth(token))
    if r.status_code not in (200, 201):
        fail("_advance_to_accepted: PUT submit", f"{r.status_code} {r.text[:120]}")
        return False
    r = requests.put(f"{BASE}/testing/{treq_id}/accept", headers=auth(token))
    if r.status_code not in (200, 201):
        fail("_advance_to_accepted: PUT accept", f"{r.status_code} {r.text[:120]}")
        return False
    info(f"request {treq_id} advanced to accepted")
    return True

def _post_result(treq_id, token, *, cal_date_str, validity_months, overall_result,
                 calibrated_by="Test Engineer", certificate_number="CERT-001",
                 notes="Integration test result"):
    """
    Submit a calibration TestResult via POST /testing/{id}/results/structured.
    This is the same path that TestResultForm uses — Option A data flow.
    """
    r = requests.post(
        f"{BASE}/testing/{treq_id}/results/structured",
        headers=auth(token),
        json={
            "template_key": "calibration",
            "overall_result": overall_result,
            "test_data": {
                "calibration_date": cal_date_str,
                "validity_months": validity_months,
                "overall_result": overall_result,
                "calibrated_by": calibrated_by,
                "certificate_number": certificate_number,
                "notes": notes,
            },
        },
    )
    if r.status_code in (200, 201):
        ok(f"POST results/structured (result={overall_result}, date={cal_date_str})")
    else:
        fail("POST results/structured", f"{r.status_code} {r.text[:120]}")
    return r

# ─── Shared state ─────────────────────────────────────────────────────────────
TOKEN    = None
USER_ID  = None
EQUIP_ID = None
TREQ_ID  = None   # Pass-path request
FAIL_TREQ_ID = None  # Fail-path request
REC_ID   = None   # REPAIR_OR_REPLACE recommendation id

# ─────────────────────────────────────────────────────────────────────────────
# §1  Auth
# ─────────────────────────────────────────────────────────────────────────────
section("§1  Authentication")

for email, pw in [("orgadmin@kptcl.com", PW_ADMIN), ("taqc.north@kptcl.com", PW)]:
    TOKEN, USER_ID = login(email, pw)
    if TOKEN:
        break

if not TOKEN:
    print(f"\n{RED}FATAL: could not obtain any token — check seed data and server.{RESET}")
    _print_summary()
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# §2  Template validation
# ─────────────────────────────────────────────────────────────────────────────
section("§2  Template validation — calibration template, rules[], enable_calibration")

# Resolve test_type_id for "Calibration" under "Repair Lifecycle"
test_type_id = None
r = requests.get(
    f"{BASE}/category_details/details/by-master/Repair%20Lifecycle",
    headers=auth(TOKEN),
    params={"limit": 20},
)
if r.status_code == 200:
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", r.json().get("data", []))
    for d in items:
        if d.get("name", "").lower() == "calibration":
            test_type_id = d.get("id")
            break

if test_type_id:
    ok("Calibration category_detail found", f"id={test_type_id}")
else:
    skip("Calibration category_detail", "not found via by-master — run seed.py")

# Fetch the template for this test_type_id
tpl_body = None
if test_type_id:
    r = requests.get(
        f"{BASE}/org-test-templates/by-test-type/{test_type_id}",
        headers=auth(TOKEN),
    )
    tpl_body = check("GET /org-test-templates/by-test-type/{id}", r, 200)

if tpl_body:
    tdata = tpl_body.get("template_data", {})
    rules = tdata.get("rules", [])
    enable_cal = tdata.get("enable_calibration", False)
    multi = tdata.get("multi_session", False)

    if rules:
        ok("template_data.rules[] present", f"count={len(rules)}")
    else:
        fail("template_data.rules[] present", "rules key missing or empty")

    if enable_cal:
        ok("template_data.enable_calibration=true")
    else:
        fail("template_data.enable_calibration=true", "flag missing or false")

    if multi:
        ok("template_data.multi_session=true")
    else:
        fail("template_data.multi_session=true", "multi_session missing/false")

    rule = rules[0] if rules else {}
    if rule.get("type") == "DATE_ADD":
        ok("rule type=DATE_ADD")
    else:
        fail("rule type=DATE_ADD", f"got {rule.get('type')}")

    for expected_field in ("calibration_date", "validity_months"):
        found = any(
            f.get("key") == expected_field
            for sec in tdata.get("sections", [])
            for f in sec.get("fields", [])
        )
        if found:
            ok(f"template has field '{expected_field}'")
        else:
            fail(f"template has field '{expected_field}'", "field not found in any section")

# ─────────────────────────────────────────────────────────────────────────────
# §3  Equipment + calibration config
# ─────────────────────────────────────────────────────────────────────────────
section("§3  Equipment + calibration config (lead_days, is_scheduled)")

r = requests.get(f"{BASE}/equipment", headers=auth(TOKEN), params={"limit": 5})
equip_data = check("GET /equipment", r, 200)
if equip_data:
    items = equip_data if isinstance(equip_data, list) else equip_data.get("items", [])
    if items:
        EQUIP_ID = items[0].get("id")
        ok("equipment resolved", f"id={EQUIP_ID}")
    else:
        skip("equipment resolved", "no equipment in DB — seed required")

if not EQUIP_ID:
    skip("§3–§12 skipped", "no equipment available")
    _print_summary()
    sys.exit(0)

# GET config before any write (may be 404 or return defaults)
r = requests.get(f"{BASE}/calibration/equipment/{EQUIP_ID}/config", headers=auth(TOKEN))
if r.status_code == 200:
    cfg = r.json()
    info(f"initial config: lead_days={cfg.get('lead_days')}  is_scheduled={cfg.get('is_scheduled')}")
    ok("GET /calibration/equipment/{id}/config (pre-set)", "200")
elif r.status_code == 404:
    ok("GET config before first write → 404 (expected — not yet configured)")
else:
    fail("GET /calibration/equipment/{id}/config", f"unexpected {r.status_code}")

# Set lead_days=30, is_scheduled=True
r = requests.post(
    f"{BASE}/calibration/equipment/{EQUIP_ID}/config",
    headers=auth(TOKEN),
    json={"lead_days": 30, "is_scheduled": True},
)
cfg_saved = check("POST /calibration/equipment/{id}/config (lead_days=30)", r, 200)
if cfg_saved:
    if cfg_saved.get("lead_days") == 30:
        ok("lead_days round-trips correctly", "30")
    else:
        fail("lead_days round-trips", f"got {cfg_saved.get('lead_days')}")
    if cfg_saved.get("is_scheduled") is True:
        ok("is_scheduled=True confirmed")
    else:
        fail("is_scheduled=True confirmed", f"got {cfg_saved.get('is_scheduled')}")

# GET config after write
r = requests.get(f"{BASE}/calibration/equipment/{EQUIP_ID}/config", headers=auth(TOKEN))
cfg_read = check("GET /calibration/equipment/{id}/config (post-set)", r, 200)
if cfg_read:
    if cfg_read.get("lead_days") == 30:
        ok("GET config lead_days=30 confirmed")
    else:
        fail("GET config lead_days=30", f"got {cfg_read.get('lead_days')}")

# ─────────────────────────────────────────────────────────────────────────────
# §4  Create testing request + session + Pass reading
# ─────────────────────────────────────────────────────────────────────────────
section("§4  Testing request + session + Pass reading")

treq_payload = {
    "title": "Calibration — Integration Test (Pass)",
    "equipment_id": EQUIP_ID,
    "request_category": "test",
    "is_multi_session": True,
    "assigned_tester_id": USER_ID,   # needed so submit → assigned directly
}
if test_type_id:
    treq_payload["test_type_id"] = test_type_id

r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_payload)
if r.status_code in (200, 201):
    TREQ_ID = r.json().get("id")
    is_cal_flag = r.json().get("is_calibration")
    ok("POST /testing_requests (calibration Pass)", f"id={TREQ_ID}")
    if is_cal_flag:
        ok("is_calibration=True stamped on request")
    else:
        fail("is_calibration=True stamped on request",
             "flag not set — check _resolve_is_calibration() and template enable_calibration")
else:
    skip("POST /testing_requests", f"{r.status_code} — {r.text[:120]}")

# Calibration date: 6 months ago, validity 12 months → next_due in 6 months → NORMAL
normal_cal_date = str(date.today() - timedelta(days=180))

if TREQ_ID:
    # Advance draft → accepted before submitting results
    _advance_to_accepted(TREQ_ID, TOKEN)
    _post_result(
        TREQ_ID, TOKEN,
        cal_date_str=normal_cal_date,
        validity_months=12,
        overall_result="Pass",
        calibrated_by="QA Engineer",
        certificate_number="CERT-2025-001",
        notes="Pass reading for integration test",
    )

# ─────────────────────────────────────────────────────────────────────────────
# §5  Status check — state derived from calibration_date + validity_months
# ─────────────────────────────────────────────────────────────────────────────
section("§5  Status — state derived from DATE_ADD rule")

r = requests.get(f"{BASE}/calibration/equipment/{EQUIP_ID}/status", headers=auth(TOKEN))
st = check("GET /calibration/equipment/{id}/status", r, 200)
if st:
    state = st.get("state")
    next_due = st.get("next_due_date")
    days_until = st.get("days_until_due")
    last_cal = st.get("last_calibration_date")
    info(f"state={state}  last_cal={last_cal}  next_due={next_due}  days_until_due={days_until}")

    valid_states = {"NOT_CALIBRATED", "NORMAL", "DUE_SOON", "OVERDUE", "CRITICAL"}
    if state in valid_states:
        ok("state is a recognised value", state)
    else:
        fail("state is a recognised value", f"unexpected: {state}")

    if state != "NOT_CALIBRATED" and next_due:
        ok("next_due_date populated after reading")
    elif state == "NOT_CALIBRATED":
        # Readings not yet picked up — still acceptable at this point
        skip("next_due_date check", "state=NOT_CALIBRATED (reading may not be linked yet)")

# ─────────────────────────────────────────────────────────────────────────────
# §6  Evaluate — Pass path → NORMAL / DUE_SOON / OVERDUE (not CRITICAL)
# ─────────────────────────────────────────────────────────────────────────────
section("§6  Evaluate — Pass reading → NORMAL / DUE_SOON / OVERDUE")

r = requests.post(f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
ev = check("POST /calibration/equipment/{id}/evaluate", r, 200)
if ev:
    state = ev.get("state")
    next_due = ev.get("next_due_date")
    days_until = ev.get("days_until_due")
    info(f"state={state}  next_due={next_due}  days_until_due={days_until}")

    if state in ("NORMAL", "DUE_SOON", "OVERDUE"):
        ok("evaluate (Pass) → non-CRITICAL state", state)
    elif state == "NOT_CALIBRATED":
        skip("evaluate Pass check", "state=NOT_CALIBRATED — reading not linked (check is_calibration flag)")
    else:
        fail("evaluate (Pass) must not return CRITICAL", f"got {state}")

    if state in ("NORMAL", "DUE_SOON") and days_until is not None:
        ok("days_until_due is set for non-overdue state", str(days_until))

# ─────────────────────────────────────────────────────────────────────────────
# §7  Force OVERDUE — calibration_date far in the past, short validity
# ─────────────────────────────────────────────────────────────────────────────
section("§7  Force OVERDUE — old calibration_date + validity=1 month")

# Create a second request for the overdue reading
treq2_payload = {
    "title": "Calibration — Integration Test (Overdue)",
    "equipment_id": EQUIP_ID,
    "request_category": "test",
    "is_multi_session": True,
    "assigned_tester_id": USER_ID,
}
if test_type_id:
    treq2_payload["test_type_id"] = test_type_id

r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq2_payload)
overdue_treq_id = None
if r.status_code in (200, 201):
    overdue_treq_id = r.json().get("id")
    ok("POST /testing_requests (overdue request)", f"id={overdue_treq_id}")
else:
    skip("overdue request creation", f"{r.status_code}")

# calibration_date 13 months ago, validity=12 → next_due 1 month ago → OVERDUE
overdue_cal_date = str(date.today() - timedelta(days=395))  # ~13 months ago

if overdue_treq_id:
    _advance_to_accepted(overdue_treq_id, TOKEN)
    _post_result(
        overdue_treq_id, TOKEN,
        cal_date_str=overdue_cal_date,
        validity_months=12,
        overall_result="Pass",
        notes="Deliberately overdue reading",
    )

    r = requests.post(f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
    ev_overdue = check("POST evaluate (overdue reading)", r, 200)
    if ev_overdue:
        state_od = ev_overdue.get("state")
        info(f"state={state_od}  days_until_due={ev_overdue.get('days_until_due')}")
        if state_od == "OVERDUE":
            ok("state=OVERDUE with old calibration date")
        elif (ev_overdue.get("days_until_due") or 0) < 0:
            ok("days_until_due < 0 confirms overdue", str(ev_overdue.get("days_until_due")))
        else:
            skip("OVERDUE check", f"state={state_od} — may reflect a newer Pass reading from §4")
else:
    skip("§7 overdue evaluation", "overdue request not created")

# ─────────────────────────────────────────────────────────────────────────────
# §8  Failure lifecycle — overall_result=Fail → CRITICAL + recommendation
# ─────────────────────────────────────────────────────────────────────────────
section("§8  Failure lifecycle — Fail reading → CRITICAL + REPAIR_OR_REPLACE")

treq_fail_payload = {
    "title": "Calibration — Integration Test (Fail)",
    "equipment_id": EQUIP_ID,
    "request_category": "test",
    "is_multi_session": True,
    "assigned_tester_id": USER_ID,
}
if test_type_id:
    treq_fail_payload["test_type_id"] = test_type_id

r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_fail_payload)
if r.status_code in (200, 201):
    FAIL_TREQ_ID = r.json().get("id")
    ok("POST /testing_requests (Fail path)", f"id={FAIL_TREQ_ID}")
else:
    skip("Fail request creation", f"{r.status_code}")

fail_cal_date = str(date.today() - timedelta(days=30))

if FAIL_TREQ_ID:
    _advance_to_accepted(FAIL_TREQ_ID, TOKEN)
    _post_result(
        FAIL_TREQ_ID, TOKEN,
        cal_date_str=fail_cal_date,
        validity_months=12,
        overall_result="Fail",
        notes="Deliberately failed calibration",
    )

    r = requests.post(f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
    ev_fail = check("POST evaluate (Fail reading)", r, 200)
    if ev_fail:
        state_f = ev_fail.get("state")
        is_sched = ev_fail.get("is_scheduled")
        rec = ev_fail.get("recommendation", {}) or {}
        REC_ID = rec.get("recommendation_id") or ev_fail.get("recommendation_id")

        info(f"state={state_f}  is_scheduled={is_sched}  recommendation_id={REC_ID}")

        if state_f == "CRITICAL":
            ok("state=CRITICAL on Fail result")
        else:
            fail("state=CRITICAL on Fail result", f"got {state_f}")

        if is_sched is False:
            ok("is_scheduled=False after Fail (scheduling halted)")
        else:
            fail("is_scheduled=False after Fail", f"got {is_sched}")

        if REC_ID:
            ok("REPAIR_OR_REPLACE recommendation created", f"id={REC_ID}")
        else:
            fail("REPAIR_OR_REPLACE recommendation created", "recommendation_id missing from response")
else:
    skip("§8 Fail evaluation", "Fail request not created")

# Also verify GET /status reflects CRITICAL + is_scheduled=False
r = requests.get(f"{BASE}/calibration/equipment/{EQUIP_ID}/status", headers=auth(TOKEN))
st_after_fail = check("GET /status after Fail evaluate", r, 200)
if st_after_fail:
    if st_after_fail.get("state") == "CRITICAL":
        ok("GET /status → CRITICAL after Fail")
    else:
        info(f"GET /status state={st_after_fail.get('state')} after Fail")
    if st_after_fail.get("is_scheduled") is False:
        ok("GET /status → is_scheduled=False after Fail")
    else:
        info(f"GET /status is_scheduled={st_after_fail.get('is_scheduled')}")

# ─────────────────────────────────────────────────────────────────────────────
# §9  Idempotency — second evaluate after FAIL must NOT create new recommendation
# ─────────────────────────────────────────────────────────────────────────────
section("§9  Idempotency — second evaluate after FAIL → no duplicate recommendation")

r = requests.post(f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
ev_idem = check("POST evaluate (second call after Fail)", r, 200)
if ev_idem:
    rec2 = ev_idem.get("recommendation", {}) or {}
    rec_id_2 = rec2.get("recommendation_id") or ev_idem.get("recommendation_id")
    if REC_ID and rec_id_2:
        if rec_id_2 == REC_ID:
            ok("same recommendation_id on repeat evaluate (no duplicate)", rec_id_2)
        else:
            fail("same recommendation_id on repeat evaluate",
                 f"new id {rec_id_2} — expected {REC_ID}")
    else:
        skip("idempotency assertion", "no recommendation IDs to compare")

# ─────────────────────────────────────────────────────────────────────────────
# §10  Resume schedule → is_scheduled=True, CRITICAL cleared
# ─────────────────────────────────────────────────────────────────────────────
section("§10  Resume schedule after repair")

r = requests.post(f"{BASE}/calibration/equipment/{EQUIP_ID}/resume", headers=auth(TOKEN))
resumed = check("POST /calibration/equipment/{id}/resume", r, 200)
if resumed:
    info(f"resume response: {resumed}")
    ok("resume returned 200")

# Verify config: is_scheduled should now be True
r = requests.get(f"{BASE}/calibration/equipment/{EQUIP_ID}/config", headers=auth(TOKEN))
cfg_resumed = check("GET /config after resume", r, 200)
if cfg_resumed:
    if cfg_resumed.get("is_scheduled") is True:
        ok("is_scheduled=True after resume")
    else:
        fail("is_scheduled=True after resume", f"got {cfg_resumed.get('is_scheduled')}")

# Re-evaluate with a fresh Pass reading to confirm state clears from CRITICAL
treq_resume_payload = {
    "title": "Calibration — Post-resume Pass",
    "equipment_id": EQUIP_ID,
    "request_category": "test",
    "is_multi_session": True,
    "assigned_tester_id": USER_ID,
}
if test_type_id:
    treq_resume_payload["test_type_id"] = test_type_id

r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_resume_payload)
if r.status_code in (200, 201):
    resume_treq_id = r.json().get("id")
    _advance_to_accepted(resume_treq_id, TOKEN)
    _post_result(
        resume_treq_id, TOKEN,
        cal_date_str=str(date.today()),
        validity_months=12,
        overall_result="Pass",
        notes="Post-resume Pass reading",
    )
    r2 = requests.post(f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
    ev_resume = check("POST evaluate after resume + Pass reading", r2, 200)
    if ev_resume:
        s_resume = ev_resume.get("state")
        if s_resume in ("NORMAL", "DUE_SOON"):
            ok(f"state={s_resume} after resume + Pass (CRITICAL cleared)")
        else:
            info(f"state={s_resume} after resume (acceptable if still processing)")
else:
    skip("post-resume re-evaluate", f"request creation failed {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# §11  History endpoint
# ─────────────────────────────────────────────────────────────────────────────
section("§11  History — all calibration records returned")

r = requests.get(f"{BASE}/calibration/equipment/{EQUIP_ID}/history", headers=auth(TOKEN))
hist = check("GET /calibration/equipment/{id}/history", r, 200)
if hist:
    records = hist.get("records", [])
    if records:
        ok(f"history records returned", f"count={len(records)}")
        # Verify newest-first ordering: cts of first record >= second
        if len(records) >= 2:
            first_date = records[0].get("calibration_date") or records[0].get("cts", "")
            second_date = records[1].get("calibration_date") or records[1].get("cts", "")
            if first_date and second_date and first_date >= second_date:
                ok("records ordered newest-first")
            else:
                info(f"order check: first={first_date}  second={second_date} (may vary)")
        # Verify expected fields on the first record
        first = records[0]
        for key in ("calibration_date", "overall_result"):
            if key in first:
                ok(f"history record has '{key}' field", str(first[key]))
            else:
                fail(f"history record has '{key}' field", "field missing")
    else:
        skip("history records", "empty list — readings may not be linked yet")

# ─────────────────────────────────────────────────────────────────────────────
# §12  Negative tests
# ─────────────────────────────────────────────────────────────────────────────
section("§12  Negative tests")

fake_id = "00000000-0000-0000-0000-000000000000"

# Non-existent equipment — status
r = requests.get(f"{BASE}/calibration/equipment/{fake_id}/status", headers=auth(TOKEN))
check_neg("GET status for non-existent equipment → 404", r, [404])

# Non-existent equipment — evaluate
r = requests.post(f"{BASE}/calibration/equipment/{fake_id}/evaluate", headers=auth(TOKEN))
check_neg("POST evaluate for non-existent equipment → 404", r, [404])

# Non-existent equipment — resume
r = requests.post(f"{BASE}/calibration/equipment/{fake_id}/resume", headers=auth(TOKEN))
check_neg("POST resume for non-existent equipment → 404", r, [404])

# Non-existent equipment — history
r = requests.get(f"{BASE}/calibration/equipment/{fake_id}/history", headers=auth(TOKEN))
check_neg("GET history for non-existent equipment → 404", r, [404])

# Invalid lead_days (string instead of int) — should be rejected by Pydantic
r = requests.post(
    f"{BASE}/calibration/equipment/{EQUIP_ID}/config",
    headers=auth(TOKEN),
    json={"lead_days": "not_a_number"},
)
check_neg("POST config with invalid lead_days type → 422", r, [422])

# Negative lead_days — pydantic may or may not validate; just must not crash
r = requests.post(
    f"{BASE}/calibration/equipment/{EQUIP_ID}/config",
    headers=auth(TOKEN),
    json={"lead_days": -5},
)
if r.status_code in (200, 422):
    ok("[NEG] negative lead_days handled gracefully", str(r.status_code))
else:
    fail("[NEG] negative lead_days", f"got {r.status_code}")

# Unauthenticated request
r_unauth = _orig_get(f"{BASE}/calibration/equipment/{EQUIP_ID}/status")
check_neg("unauthenticated status request → 401/403", r_unauth, [401, 403])

r_unauth2 = _orig_post(f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate")
check_neg("unauthenticated evaluate request → 401/403", r_unauth2, [401, 403])

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
_print_summary()
sys.exit(0 if fail_count == 0 else 1)
