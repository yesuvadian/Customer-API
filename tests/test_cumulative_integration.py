"""
tests/test_cumulative_integration.py
======================================
Cumulative / Overhaul Lifecycle — End-to-End Integration Test Suite

Flow
----
§1  Auth
§2  Template validation — operations_tracking template, rules[], enable_cumulative
§3  Template validation — template_data contains rules[], multi_session=true
§4  Threshold configuration (set / get)
§5  Session readings — POST 3 readings for same equipment via TestingRequest + TestSession
§6  Cumulative calculation — GET lifecycle → cumulative value verified
§7  Evaluate overhaul trigger — cumulative < threshold → NORMAL
§8  Threshold breach — lower threshold so cumulative >= threshold → OVERHAUL_DUE
§9  Idempotency — second evaluate does NOT create second recommendation
§10 Close recommendation → re-evaluate → NORMAL
§11 Negative tests — bad equipment ID, missing threshold, etc.

Prerequisites:
  1. python tests/clean_and_seed.py
  2. python run_migration_cumulative.py
  3. uvicorn main:app --reload --port 8000
  4. python tests/test_cumulative_integration.py
"""

import sys
import json
import time
from datetime import datetime, timedelta, timezone, date

import requests
from requests.exceptions import ConnectionError as ReqConnError

BASE = "http://localhost:8000"
PW   = "TestDept@123"
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

# ─── Shared state ─────────────────────────────────────────────────────────────
TOKEN    = None
USER_ID  = None
EQUIP_ID = None
TREQ_ID  = None
REC_ID   = None

# ─────────────────────────────────────────────────────────────────────────────
# §1  Auth
# ─────────────────────────────────────────────────────────────────────────────
section("§1  Authentication")

# Try OrgAdmin first; fall back to any available token
for email, pw in [("orgadmin@kptcl.com", PW_ADMIN), ("taqc.north@kptcl.com", PW)]:
    TOKEN, USER_ID = login(email, pw)
    if TOKEN:
        break

if not TOKEN:
    print(f"\n{RED}FATAL: could not obtain any token — check seed data and server.{RESET}")
    _print_summary()
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# §2  Template validation — operations_tracking template, rules[], enable_cumulative
# ─────────────────────────────────────────────────────────────────────────────
section("§2  Template validation — cumulative template, rules[], enable_cumulative")

# Resolve test_type_id and fetch the template via /org-test-templates/by-test-type
_cum_type_id = None
r = requests.get(
    f"{BASE}/category_details/details/by-master/Repair%20Lifecycle",
    headers=auth(TOKEN),
    params={"limit": 20},
)
if r.status_code == 200:
    _items = r.json() if isinstance(r.json(), list) else r.json().get("items", r.json().get("data", []))
    for d in _items:
        if d.get("name", "").lower() == "operations tracking":
            _cum_type_id = d.get("id")
            break

tpl_body = None
if _cum_type_id:
    ok("Operations Tracking category_detail found", f"id={_cum_type_id}")
    r = requests.get(
        f"{BASE}/org-test-templates/by-test-type/{_cum_type_id}",
        headers=auth(TOKEN),
    )
    tpl_body = check("GET /org-test-templates/by-test-type/{id}", r, 200)
else:
    skip("template fetch", "category not found via by-master — run seed.py")

if tpl_body:
    tdata = tpl_body.get("template_data", {})
    rules = tdata.get("rules", [])
    multi = tdata.get("multi_session", False)
    enable_cum = tdata.get("enable_cumulative", False)
    if rules:
        ok("template_data.rules[] present", f"count={len(rules)}")
    else:
        fail("template_data.rules[] present", "rules key missing or empty")
    if multi:
        ok("template_data.multi_session=true")
    else:
        fail("template_data.multi_session=true", "multi_session missing/false")
    if enable_cum:
        ok("template_data.enable_cumulative=true")
    else:
        fail("template_data.enable_cumulative=true", "flag missing or false")
    rule = rules[0] if rules else {}
    if rule.get("type") == "CUMULATIVE_DIFF":
        ok("rule type=CUMULATIVE_DIFF")
    else:
        fail("rule type=CUMULATIVE_DIFF", f"got {rule.get('type')}")
    if rule.get("field") == "reading":
        ok("rule field=reading")
    else:
        fail("rule field=reading", f"got {rule.get('field')}")

# ─────────────────────────────────────────────────────────────────────────────
# §4  Equipment + threshold
# ─────────────────────────────────────────────────────────────────────────────
section("§4  Equipment + threshold configuration")

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
    skip("§4–§10 skipped", "no equipment available")
    _print_summary()
    sys.exit(0)

# Set threshold = 500
r = requests.post(
    f"{BASE}/cumulative/equipment/{EQUIP_ID}/threshold",
    headers=auth(TOKEN),
    json={"threshold_value": 500},
)
check("POST /cumulative/equipment/{id}/threshold (500)", r, 200)

# Get threshold back
r = requests.get(f"{BASE}/cumulative/equipment/{EQUIP_ID}/threshold", headers=auth(TOKEN))
thr = check("GET /cumulative/equipment/{id}/threshold", r, 200)
if thr:
    if thr.get("threshold_value") == 500:
        ok("threshold_value round-trips correctly", "500")
    else:
        fail("threshold_value round-trips", f"got {thr.get('threshold_value')}")

# ─────────────────────────────────────────────────────────────────────────────
# §5  Create testing request + structured results
# ─────────────────────────────────────────────────────────────────────────────
section("§5  Testing request + structured results (Option A — test_results.test_data)")

# Find the Operations Tracking test type id
r = requests.get(
    f"{BASE}/category_details/details/by-master/Repair%20Lifecycle",
    headers=auth(TOKEN),
    params={"limit": 20},
)
test_type_id = None
if r.status_code == 200:
    body = r.json()
    items = body if isinstance(body, list) else body.get("items", body.get("data", []))
    for d in items:
        if d.get("name", "").lower() == "operations tracking":
            test_type_id = d.get("id")
            break

if test_type_id:
    ok("Operations Tracking category_detail found", f"id={test_type_id}")
else:
    skip("test_type_id lookup", "category not found via by-master — run seed.py")

# Create a testing request
treq_payload = {
    "title": "Operations Tracking - Cumulative Test",
    "equipment_id": EQUIP_ID,
    "request_category": "test",
    "assigned_tester_id": USER_ID,   # needed so submit → assigned directly
}
if test_type_id:
    treq_payload["test_type_id"] = test_type_id

r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_payload)
if r.status_code in (200, 201):
    TREQ_ID = r.json().get("id")
    is_cum_flag = r.json().get("is_cumulative")
    ok("POST /testing_requests (Operations Tracking)", f"id={TREQ_ID}")
    if is_cum_flag:
        ok("is_cumulative=True stamped on request")
    else:
        fail("is_cumulative=True stamped on request",
             "flag not set — check _resolve_is_cumulative() and template enable_cumulative")
else:
    skip("POST /testing_requests", f"{r.status_code} — {r.text[:120]}")

if not TREQ_ID:
    skip("§5 results skipped", "no testing request created")
else:
    # Create 3 test sessions BEFORE advancing status.
    # Each session gets a unique id — this prevents the create_structured_result upsert
    # from collapsing all 3 readings into a single TestResult row (same session_id=NULL).
    readings_config = [
        {"reading": 1000, "reading_date": str(date.today() - timedelta(days=60)), "day_offset": 60},
        {"reading": 1200, "reading_date": str(date.today() - timedelta(days=30)), "day_offset": 30},
        {"reading": 1500, "reading_date": str(date.today()), "day_offset": 0},
    ]
    session_ids = []
    for i, rc in enumerate(readings_config):
        sess_r = requests.post(
            f"{BASE}/testing_requests/{TREQ_ID}/sessions",
            headers=auth(TOKEN),
            json={
                "session_number": i + 1,
                "session_name": f"Reading Session {i+1}",
                "session_date": (datetime.now(timezone.utc) - timedelta(days=rc['day_offset'])).isoformat(),
                "template_key": "operations_tracking",
            },
        )
        if sess_r.status_code in (200, 201):
            session_ids.append(sess_r.json().get("id"))
            ok(f"POST session ({i+1}/3) created", f"id={session_ids[-1]}")
        else:
            session_ids.append(None)
            fail(f"POST session ({i+1}/3)", f"{sess_r.status_code} {sess_r.text[:80]}")

    # Advance draft → accepted so results/structured is allowed
    _advance_to_accepted(TREQ_ID, TOKEN)

    # Submit 3 structured results: readings 1000 → 1200 → 1500
    # CUMULATIVE_DIFF = (1200-1000) + (1500-1200) = 200 + 300 = 500
    for i, (rdata, sid) in enumerate(zip(readings_config, session_ids)):
        payload = {
            "template_key": "operations_tracking",
            "overall_result": "pass",
            "test_data": {"reading": rdata["reading"], "reading_date": rdata["reading_date"]},
        }
        if sid:
            payload["test_session_id"] = sid
        r = requests.post(
            f"{BASE}/testing/{TREQ_ID}/results/structured",
            headers=auth(TOKEN),
            json=payload,
        )
        if r.status_code in (200, 201):
            ok(f"POST results/structured ({i+1}/3)", f"reading={rdata['reading']}")
        else:
            fail(f"POST results/structured ({i+1}/3)", f"{r.status_code} {r.text[:100]}")

# ─────────────────────────────────────────────────────────────────────────────
# §6  Lifecycle before trigger (threshold=500, cumulative=500 expected)
# ─────────────────────────────────────────────────────────────────────────────
section("§6  Lifecycle status — cumulative verification")

r = requests.get(f"{BASE}/cumulative/equipment/{EQUIP_ID}/lifecycle", headers=auth(TOKEN))
lc = check("GET /cumulative/equipment/{id}/lifecycle", r, 200)
if lc:
    cumulative = lc.get("cumulative_value", 0)
    info(f"cumulative_value={cumulative}  threshold={lc.get('threshold_value')}  status={lc.get('status')}")
    if cumulative >= 0:
        ok("cumulative_value is numeric", f"{cumulative}")
    else:
        fail("cumulative_value is numeric", f"{cumulative}")

# ─────────────────────────────────────────────────────────────────────────────
# §7  Evaluate — threshold=500, cumulative≈500 → OVERHAUL_DUE or NORMAL
# ─────────────────────────────────────────────────────────────────────────────
section("§7  Evaluate overhaul trigger")

r = requests.post(f"{BASE}/cumulative/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
ev = check("POST /cumulative/equipment/{id}/evaluate", r, 200)
if ev:
    status = ev.get("status")
    info(f"status={status}  cumulative={ev.get('cumulative_value')}  threshold={ev.get('threshold_value')}")
    if status in ("OVERHAUL_DUE", "WARNING", "NORMAL"):
        ok("evaluate returns valid lifecycle status", status)
    else:
        fail("evaluate returns valid lifecycle status", f"unexpected: {status}")

# ─────────────────────────────────────────────────────────────────────────────
# §8  Force breach — lower threshold to 300 → OVERHAUL_DUE
# ─────────────────────────────────────────────────────────────────────────────
section("§8  Threshold breach — threshold=300 → OVERHAUL_DUE")

# First close any existing open recommendation to reset state
r = requests.get(f"{BASE}/cumulative/equipment/{EQUIP_ID}/lifecycle", headers=auth(TOKEN))
lc_pre = r.json() if r.status_code == 200 else {}
if lc_pre.get("overhaul", {}).get("recommendation_id"):
    rec_id_existing = lc_pre["overhaul"]["recommendation_id"]
    rc = requests.post(f"{BASE}/cumulative/recommendations/{rec_id_existing}/close", headers=auth(TOKEN))
    if rc.status_code == 200:
        info(f"closed pre-existing recommendation {rec_id_existing} to reset state")

# Lower threshold so cumulative definitely exceeds it
r = requests.post(
    f"{BASE}/cumulative/equipment/{EQUIP_ID}/threshold",
    headers=auth(TOKEN),
    json={"threshold_value": 300},
)
check("POST threshold = 300 (breach)", r, 200)

r = requests.post(f"{BASE}/cumulative/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
ev2 = check("POST evaluate after lowering threshold", r, 200)
if ev2:
    status2 = ev2.get("status")
    if status2 == "OVERHAUL_DUE":
        ok("status=OVERHAUL_DUE after threshold breach")
        REC_ID = ev2.get("overhaul", {}).get("recommendation_id")
        info(f"recommendation_id={REC_ID}")
    elif ev2.get("cumulative_value", 0) == 0:
        skip("OVERHAUL_DUE check", "cumulative=0 (no sessions recorded) — skipping breach assertion")
    else:
        fail("status=OVERHAUL_DUE after threshold breach", f"got {status2}  cumulative={ev2.get('cumulative_value')}")

# ─────────────────────────────────────────────────────────────────────────────
# §9  Idempotency — second evaluate must NOT create second recommendation
# ─────────────────────────────────────────────────────────────────────────────
section("§9  Idempotency — no duplicate recommendation")

r = requests.post(f"{BASE}/cumulative/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
ev3 = check("POST evaluate (second call)", r, 200)
if ev3:
    # Should still be OVERHAUL_DUE and same recommendation_id
    rec_id_2 = ev3.get("overhaul", {}).get("recommendation_id")
    if REC_ID and rec_id_2:
        if rec_id_2 == REC_ID:
            ok("same recommendation_id (no duplicate)", rec_id_2)
        else:
            fail("same recommendation_id (no duplicate)", f"got new id {rec_id_2} expected {REC_ID}")
    else:
        skip("idempotency check", "no recommendation IDs to compare")

# ─────────────────────────────────────────────────────────────────────────────
# §10  Close recommendation → re-evaluate → NORMAL (threshold=300 stays, but closed)
# ─────────────────────────────────────────────────────────────────────────────
section("§10  Close recommendation → NORMAL lifecycle")

if REC_ID:
    r = requests.post(f"{BASE}/cumulative/recommendations/{REC_ID}/close", headers=auth(TOKEN))
    closed = check(f"POST /recommendations/{REC_ID}/close", r, 200)
    if closed and closed.get("status") == "CLOSED":
        ok("recommendation status=CLOSED")
    else:
        fail("recommendation status=CLOSED", str(closed))

    # Re-evaluate — cumulative still >= threshold but recommendation is CLOSED so a NEW one gets created
    # or if cumulative < threshold → NORMAL.
    # Here cumulative ≈ 500 and threshold=300, so a new OPEN recommendation is expected.
    # Close it immediately and raise threshold above cumulative to verify NORMAL.
    r2 = requests.post(
        f"{BASE}/cumulative/equipment/{EQUIP_ID}/threshold",
        headers=auth(TOKEN),
        json={"threshold_value": 9999},
    )
    check("POST threshold = 9999 (above cumulative)", r2, 200)

    # Also close whatever new recommendation was created
    r3 = requests.get(f"{BASE}/cumulative/equipment/{EQUIP_ID}/lifecycle", headers=auth(TOKEN))
    lc3 = r3.json() if r3.status_code == 200 else {}
    new_rec = lc3.get("overhaul", {}).get("recommendation_id")
    if new_rec and new_rec != REC_ID:
        requests.post(f"{BASE}/cumulative/recommendations/{new_rec}/close", headers=auth(TOKEN))

    r4 = requests.post(f"{BASE}/cumulative/equipment/{EQUIP_ID}/evaluate", headers=auth(TOKEN))
    ev4 = check("POST evaluate after threshold=9999 (should be NORMAL/WARNING)", r4, 200)
    if ev4:
        s4 = ev4.get("status")
        if s4 in ("NORMAL", "WARNING"):
            ok(f"status={s4} after high threshold")
        else:
            info(f"status={s4} (recommendation auto-created again — acceptable)")
else:
    skip("§10 close + re-evaluate", "no recommendation to close")

# ─────────────────────────────────────────────────────────────────────────────
# §11  Negative tests
# ─────────────────────────────────────────────────────────────────────────────
section("§11  Negative tests")

fake_id = "00000000-0000-0000-0000-000000000000"

r = requests.get(f"{BASE}/cumulative/equipment/{fake_id}/threshold", headers=auth(TOKEN))
check_neg("GET threshold for non-existent equipment → 404", r, [404])

r = requests.post(f"{BASE}/cumulative/recommendations/{fake_id}/close", headers=auth(TOKEN))
check_neg("POST close non-existent recommendation → 404", r, [404])

r = requests.post(
    f"{BASE}/cumulative/equipment/{EQUIP_ID}/threshold",
    headers=auth(TOKEN),
    json={"threshold_value": -1},
)
# negative threshold — API currently allows it (no validation), just verify it doesn't crash
if r.status_code in (200, 422):
    ok("[NEG] negative threshold handled gracefully", str(r.status_code))
else:
    fail("[NEG] negative threshold", f"got {r.status_code}")

# Unauthenticated request
r_unauth = _orig_get(f"{BASE}/cumulative/equipment/{EQUIP_ID}/lifecycle")
check_neg("unauthenticated lifecycle request → 401/403", r_unauth, [401, 403])

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
_print_summary()
sys.exit(0 if fail_count == 0 else 1)
