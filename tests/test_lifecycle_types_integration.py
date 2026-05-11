"""
tests/test_lifecycle_types_integration.py
==========================================
Lifecycle Types — End-to-End Integration Test Suite

Covers the new dedicated Calibration / Cumulative masters and the
template_key-agnostic result lookup in CalibrationService and CumulativeService.

Flow
----
§1  Auth
§2  GET /testing_requests/lifecycle-types
        — calibration bucket present with Protection Relay + Tri-vector types
        — cumulative bucket present with Circuit Breaker + OLTC types
        — each item carries enable_calibration / enable_cumulative flag
§3  GET /testing_requests/equipment_types
        — enable_calibration flag present on calibration test types
        — enable_cumulative flag present on cumulative test types
§4  Template provisioning
        — 4 new OrgTestTemplates exist (protection_relay_calibration,
          tri_vector_meter_calibration, circuit_breaker_operations, oltc_operations)
        — each has correct lifecycle flag in template_data
§5  Calibration via new template_key (protection_relay_calibration)
        — create request with protection_relay_calibration test_type_id
        — is_calibration=True stamped on request
        — submit result with template_key="protection_relay_calibration"
        — GET /calibration/.../status picks up the result (template_key-agnostic)
        — evaluate() returns non-NOT_CALIBRATED state
§6  Calibration via new template_key (tri_vector_meter_calibration)
        — same flow, different test type
§7  Cumulative via new template_key (circuit_breaker_operations)
        — create request with circuit_breaker_operations test_type_id
        — is_cumulative=True stamped on request
        — submit 2 readings with template_key="circuit_breaker_operations"
        — GET /cumulative/.../lifecycle picks up cumulative value
§8  Cumulative via new template_key (oltc_operations)
        — same flow, different test type
§9  Negative — lifecycle-types unauthenticated → 401/403
§10 Negative — lifecycle-types structure contract (no unknown keys)

Prerequisites:
  1. python tests/clean_and_seed.py
  2. uvicorn main:app --reload --port 8000
  3. POST /org-test-templates/provision/global   (seeds the 4 new templates)
  4. python tests/test_lifecycle_types_integration.py
"""

import sys
import time
from datetime import date, timedelta

import requests
from requests.exceptions import ConnectionError as ReqConnError

BASE     = "http://localhost:8000"
PW_ADMIN = "admin123"
PW       = "TestDept@123"

# ── Retry wrapper ─────────────────────────────────────────────────────────────
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

def check(label, resp, expected_status):
    if resp.status_code == expected_status:
        ok(label, str(resp.status_code))
        return resp.json() if resp.text else {}
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
    r = requests.put(f"{BASE}/testing_requests/{treq_id}/submit", headers=auth(token))
    if r.status_code not in (200, 201):
        fail("_advance_to_accepted: submit", f"{r.status_code} {r.text[:80]}")
        return False
    r = requests.put(f"{BASE}/testing/{treq_id}/accept", headers=auth(token))
    if r.status_code not in (200, 201):
        fail("_advance_to_accepted: accept", f"{r.status_code} {r.text[:80]}")
        return False
    info(f"request {treq_id} advanced to accepted")
    return True

_session_counter = 0

def _create_session(treq_id, token, name="Reading Session"):
    """Create a TestSession for the given request and return its id, or None on failure."""
    global _session_counter
    _session_counter += 1
    r = requests.post(
        f"{BASE}/testing_requests/{treq_id}/sessions/",
        headers=auth(token),
        json={
            "session_number": _session_counter,
            "session_name": name,
            "session_date": str(date.today()) + "T00:00:00Z",
        },
    )
    if r.status_code in (200, 201):
        session_id = r.json().get("id")
        info(f"Created session id={session_id} for request {treq_id}")
        return session_id
    info(f"Session create returned {r.status_code} {r.text[:120]} — submitting without session_id")
    return None


def _post_result(treq_id, token, template_key, test_data, overall_result=None,
                 test_session_id=None):
    payload = {
        "template_key": template_key,
        "overall_result": overall_result or test_data.get("overall_result"),
        "test_data": test_data,
    }
    if test_session_id:
        payload["test_session_id"] = str(test_session_id)
    r = requests.post(
        f"{BASE}/testing/{treq_id}/results/structured",
        headers=auth(token),
        json=payload,
    )
    if r.status_code in (200, 201):
        ok(f"POST results/structured (template_key={template_key})")
    else:
        fail(f"POST results/structured", f"{r.status_code} {r.text[:120]}")
    return r

# ── Shared state ──────────────────────────────────────────────────────────────
TOKEN   = None
USER_ID = None
EQUIP_ID = None

# test_type_id cache keyed by type name
TYPE_IDS: dict = {}

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
# §2  GET /testing_requests/lifecycle-types
# ─────────────────────────────────────────────────────────────────────────────
section("§2  GET /testing_requests/lifecycle-types")

r = requests.get(f"{BASE}/testing_requests/lifecycle-types", headers=auth(TOKEN))
lt = check("GET /testing_requests/lifecycle-types", r, 200)

CAL_TYPES = []
CUM_TYPES = []

if lt:
    CAL_TYPES = lt.get("calibration", [])
    CUM_TYPES = lt.get("cumulative",  [])

    # Calibration bucket
    if CAL_TYPES:
        ok("calibration bucket present", f"count={len(CAL_TYPES)}")
    else:
        fail("calibration bucket present", "empty — run seed.py + provision/global")

    # Cumulative bucket
    if CUM_TYPES:
        ok("cumulative bucket present", f"count={len(CUM_TYPES)}")
    else:
        fail("cumulative bucket present", "empty — run seed.py + provision/global")

    # Expected type names
    cal_names = [t.get("name", "") for t in CAL_TYPES]
    cum_names = [t.get("name", "") for t in CUM_TYPES]

    for expected in ("Protection Relay Calibration and History",
                     "Electronic Tri-vector Meter Calibration"):
        if expected in cal_names:
            ok(f"calibration type present: '{expected}'")
        else:
            fail(f"calibration type present: '{expected}'",
                 f"found: {cal_names}")

    for expected in ("Circuit Breaker Operations Count", "OLTC Operations Count"):
        if expected in cum_names:
            ok(f"cumulative type present: '{expected}'")
        else:
            fail(f"cumulative type present: '{expected}'",
                 f"found: {cum_names}")

    # Flags on calibration items
    for t in CAL_TYPES:
        if t.get("enable_calibration") is True:
            ok(f"enable_calibration=true on '{t['name']}'")
        else:
            fail(f"enable_calibration=true on '{t['name']}'",
                 f"got enable_calibration={t.get('enable_calibration')}")
        # Must NOT carry enable_cumulative
        if not t.get("enable_cumulative"):
            ok(f"enable_cumulative=false on calibration type '{t['name']}'")
        else:
            fail(f"enable_cumulative must be false on calibration type", t['name'])

    # Flags on cumulative items
    for t in CUM_TYPES:
        if t.get("enable_cumulative") is True:
            ok(f"enable_cumulative=true on '{t['name']}'")
        else:
            fail(f"enable_cumulative=true on '{t['name']}'",
                 f"got enable_cumulative={t.get('enable_cumulative')}")
        if not t.get("enable_calibration"):
            ok(f"enable_calibration=false on cumulative type '{t['name']}'")
        else:
            fail(f"enable_calibration must be false on cumulative type", t['name'])

    # Build TYPE_IDS cache
    for t in CAL_TYPES + CUM_TYPES:
        TYPE_IDS[t["name"]] = t["id"]
        info(f"resolved id={t['id']}  name='{t['name']}'")

# ─────────────────────────────────────────────────────────────────────────────
# §3  GET /testing_requests/equipment_types — flags present
# ─────────────────────────────────────────────────────────────────────────────
section("§3  GET /testing_requests/equipment_types — lifecycle flags present")

r = requests.get(f"{BASE}/testing_requests/equipment_types", headers=auth(TOKEN))
eq_types = check("GET /testing_requests/equipment_types", r, 200)

if eq_types:
    # Flatten all test types across all equipment masters and categories
    all_types = []
    for master in (eq_types if isinstance(eq_types, list) else []):
        tbc = master.get("types_by_category", {})
        for cat_list in tbc.values():
            all_types.extend(cat_list if isinstance(cat_list, list) else [])
        # Legacy "tests" field
        all_types.extend(master.get("tests", []))

    all_names = [t.get("name", "") for t in all_types]
    info(f"total test types across all masters: {len(all_types)}")

    # Check that any calibration-flagged types have the flag set
    cal_flagged = [t for t in all_types if t.get("enable_calibration") is True]
    cum_flagged  = [t for t in all_types if t.get("enable_cumulative")  is True]

    if cal_flagged:
        ok(f"enable_calibration=true types found in equipment_types",
           f"count={len(cal_flagged)}")
        for t in cal_flagged:
            info(f"  calibration type: '{t['name']}'")
    else:
        fail("enable_calibration=true types found in equipment_types",
             "none — check list_equipment_types() template lookup")

    if cum_flagged:
        ok(f"enable_cumulative=true types found in equipment_types",
           f"count={len(cum_flagged)}")
        for t in cum_flagged:
            info(f"  cumulative type: '{t['name']}'")
    else:
        fail("enable_cumulative=true types found in equipment_types",
             "none — check list_equipment_types() template lookup")

    # Verify flag fields are always present (not missing key)
    missing_flag = [t for t in all_types
                    if "enable_calibration" not in t or "enable_cumulative" not in t]
    if not missing_flag:
        ok("all test type items carry enable_calibration + enable_cumulative keys")
    else:
        fail("all test type items carry lifecycle flag keys",
             f"{len(missing_flag)} items missing flag — first: {missing_flag[0].get('name')}")

# ─────────────────────────────────────────────────────────────────────────────
# §4  Template provisioning — 4 new OrgTestTemplates exist
# ─────────────────────────────────────────────────────────────────────────────
section("§4  Template provisioning — 4 new OrgTestTemplates in DB")

EXPECTED_TEMPLATES = {
    "protection_relay_calibration":  {"flag": "enable_calibration", "rule": "DATE_ADD"},
    "tri_vector_meter_calibration":  {"flag": "enable_calibration", "rule": "DATE_ADD"},
    "circuit_breaker_operations":    {"flag": "enable_cumulative",  "rule": "CUMULATIVE_DIFF"},
    "oltc_operations":               {"flag": "enable_cumulative",  "rule": "CUMULATIVE_DIFF"},
}

for tkey, meta in EXPECTED_TEMPLATES.items():
    r = requests.get(
        f"{BASE}/org-test-templates/",
        headers=auth(TOKEN),
        params={"limit": 200},
    )
    templates = []
    if r.status_code == 200:
        body = r.json()
        templates = body if isinstance(body, list) else body.get("items", body.get("data", []))

    matched = next((t for t in templates if t.get("template_key") == tkey), None)
    if matched:
        ok(f"OrgTestTemplate exists: '{tkey}'", f"id={matched.get('id')}")
        tdata = matched.get("template_data", {})
        flag = meta["flag"]
        rule_type = meta["rule"]

        if tdata.get(flag) is True:
            ok(f"  {flag}=true in template_data")
        else:
            fail(f"  {flag}=true in template_data",
                 f"got {tdata.get(flag)} — run POST /org-test-templates/provision/global")

        rules = tdata.get("rules", [])
        if rules:
            ok(f"  rules[] present", f"count={len(rules)}")
            if rules[0].get("type") == rule_type:
                ok(f"  rule type={rule_type}")
            else:
                fail(f"  rule type={rule_type}", f"got {rules[0].get('type')}")
        else:
            fail(f"  rules[] present", "missing — run provision/global")

        if tdata.get("multi_session") is True:
            ok(f"  multi_session=true")
        else:
            fail(f"  multi_session=true", f"got {tdata.get('multi_session')}")
    else:
        fail(f"OrgTestTemplate exists: '{tkey}'",
             "not found — run POST /org-test-templates/provision/global")

# ─────────────────────────────────────────────────────────────────────────────
# §5  Calibration via protection_relay_calibration template_key
# ─────────────────────────────────────────────────────────────────────────────
section("§5  Calibration — protection_relay_calibration template_key")

# Resolve equipment
r = requests.get(f"{BASE}/equipment", headers=auth(TOKEN), params={"limit": 5})
equip_data = check("GET /equipment", r, 200)
if equip_data:
    items = equip_data if isinstance(equip_data, list) else equip_data.get("items", [])
    if items:
        EQUIP_ID = items[0].get("id")
        ok("equipment resolved", f"id={EQUIP_ID}")
    else:
        skip("equipment resolved", "no equipment in DB")

if not EQUIP_ID:
    skip("§5–§8 skipped", "no equipment available")
    _print_summary()
    sys.exit(0)

pr_cal_type_id = TYPE_IDS.get("Protection Relay Calibration and History")
if not pr_cal_type_id:
    skip("§5 skipped", "Protection Relay Calibration test_type_id not resolved")
else:
    treq_payload = {
        "title": "Protection Relay Cal — Lifecycle Test",
        "equipment_id": EQUIP_ID,
        "request_category": "maintenance",
        "is_multi_session": True,
        "test_type_id": pr_cal_type_id,
        "assigned_tester_id": USER_ID,
    }
    r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_payload)
    pr_treq_id = None
    if r.status_code in (200, 201):
        body = r.json()
        pr_treq_id = body.get("id")
        ok("POST /testing_requests (Protection Relay Cal)", f"id={pr_treq_id}")
        if body.get("is_calibration") is True:
            ok("is_calibration=True stamped on request")
        else:
            fail("is_calibration=True stamped on request",
                 "flag not set — check _resolve_is_calibration() + template enable_calibration")
        if body.get("is_multi_session") is True:
            ok("is_multi_session=True stamped on request")
        else:
            fail("is_multi_session=True stamped on request",
                 f"got {body.get('is_multi_session')}")
    else:
        fail("POST /testing_requests (Protection Relay Cal)",
             f"{r.status_code} {r.text[:120]}")

    if pr_treq_id:
        _advance_to_accepted(pr_treq_id, TOKEN)
        cal_date = str(date.today() - timedelta(days=90))
        _post_result(
            pr_treq_id, TOKEN,
            template_key="protection_relay_calibration",
            overall_result="Pass",
            test_data={
                "calibration_date": cal_date,
                "validity_months": 12,
                "overall_result": "Pass",
                "calibrated_by": "Test Lab A",
                "certificate_number": "CERT-PR-001",
                "relay_make": "ABB",
                "relay_model": "REF615",
            },
        )

        # CalibrationService must find result despite non-"calibration" template_key
        r = requests.get(
            f"{BASE}/calibration/equipment/{EQUIP_ID}/status",
            headers=auth(TOKEN),
        )
        st = check("GET /calibration/status after protection_relay_calibration result", r, 200)
        if st:
            state = st.get("state")
            info(f"state={state}  last_cal={st.get('last_calibration_date')}")
            if state != "NOT_CALIBRATED":
                ok("CalibrationService found result (template_key-agnostic)", state)
            else:
                fail("CalibrationService found result (template_key-agnostic)",
                     "state=NOT_CALIBRATED — service still filtering by old template_key")

        # Evaluate
        r = requests.post(
            f"{BASE}/calibration/equipment/{EQUIP_ID}/evaluate",
            headers=auth(TOKEN),
        )
        ev = check("POST /calibration/evaluate after protection_relay_calibration", r, 200)
        if ev:
            state = ev.get("state")
            if state in ("NORMAL", "DUE_SOON", "OVERDUE"):
                ok(f"evaluate → {state} (not NOT_CALIBRATED)", state)
            else:
                fail("evaluate must return non-NOT_CALIBRATED state", f"got {state}")

# ─────────────────────────────────────────────────────────────────────────────
# §6  Calibration via tri_vector_meter_calibration template_key
# ─────────────────────────────────────────────────────────────────────────────
section("§6  Calibration — tri_vector_meter_calibration template_key")

tv_cal_type_id = TYPE_IDS.get("Electronic Tri-vector Meter Calibration")
if not tv_cal_type_id:
    skip("§6 skipped", "Electronic Tri-vector Meter Calibration test_type_id not resolved")
else:
    treq_payload = {
        "title": "Tri-vector Meter Cal — Lifecycle Test",
        "equipment_id": EQUIP_ID,
        "request_category": "maintenance",
        "is_multi_session": True,
        "test_type_id": tv_cal_type_id,
        "assigned_tester_id": USER_ID,
    }
    r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_payload)
    tv_treq_id = None
    if r.status_code in (200, 201):
        body = r.json()
        tv_treq_id = body.get("id")
        ok("POST /testing_requests (Tri-vector Meter Cal)", f"id={tv_treq_id}")
        if body.get("is_calibration") is True:
            ok("is_calibration=True stamped")
        else:
            fail("is_calibration=True stamped",
                 "flag not set — check _resolve_is_calibration()")
    else:
        fail("POST /testing_requests (Tri-vector Meter Cal)",
             f"{r.status_code} {r.text[:120]}")

    if tv_treq_id:
        _advance_to_accepted(tv_treq_id, TOKEN)
        cal_date = str(date.today() - timedelta(days=30))
        _post_result(
            tv_treq_id, TOKEN,
            template_key="tri_vector_meter_calibration",
            overall_result="Pass",
            test_data={
                "calibration_date": cal_date,
                "validity_months": 24,
                "overall_result": "Pass",
                "meter_make": "Secure",
                "meter_model": "3340",
                "meter_serial": "SN-9001",
                "meter_class": "Class 0.5S",
                "ct_ratio": "100/1",
                "pt_ratio": "110/110V",
                "kWh_error_pct": 0.1,
                "kVAh_error_pct": 0.2,
                "kVARh_error_pct": 0.15,
            },
        )

        r = requests.get(
            f"{BASE}/calibration/equipment/{EQUIP_ID}/status",
            headers=auth(TOKEN),
        )
        st = check("GET /calibration/status after tri_vector_meter_calibration result", r, 200)
        if st:
            state = st.get("state")
            info(f"state={state}  last_cal={st.get('last_calibration_date')}")
            if state != "NOT_CALIBRATED":
                ok("CalibrationService found tri-vector result (template_key-agnostic)", state)
            else:
                fail("CalibrationService found tri-vector result",
                     "state=NOT_CALIBRATED — template_key filter still active")

# ─────────────────────────────────────────────────────────────────────────────
# §7  Cumulative via circuit_breaker_operations template_key
# ─────────────────────────────────────────────────────────────────────────────
section("§7  Cumulative — circuit_breaker_operations template_key")

# Set a threshold first
r = requests.post(
    f"{BASE}/cumulative/equipment/{EQUIP_ID}/threshold",
    headers=auth(TOKEN),
    json={"threshold_value": 5000},
)
if r.status_code == 200:
    ok("POST /cumulative/equipment/{id}/threshold (5000)", "200")
else:
    info(f"threshold set: {r.status_code} (may already exist)")

cb_type_id = TYPE_IDS.get("Circuit Breaker Operations Count")
if not cb_type_id:
    skip("§7 skipped", "Circuit Breaker Operations Count test_type_id not resolved")
else:
    treq_payload = {
        "title": "CB Operations — Lifecycle Test",
        "equipment_id": EQUIP_ID,
        "request_category": "maintenance",
        "is_multi_session": True,
        "test_type_id": cb_type_id,
        "assigned_tester_id": USER_ID,
    }
    r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_payload)
    cb_treq_id = None
    if r.status_code in (200, 201):
        body = r.json()
        cb_treq_id = body.get("id")
        ok("POST /testing_requests (CB Operations)", f"id={cb_treq_id}")
        if body.get("is_cumulative") is True:
            ok("is_cumulative=True stamped on request")
        else:
            fail("is_cumulative=True stamped on request",
                 "flag not set — check _resolve_is_cumulative() + template enable_cumulative")
        if body.get("is_multi_session") is True:
            ok("is_multi_session=True stamped on request")
        else:
            fail("is_multi_session=True stamped", f"got {body.get('is_multi_session')}")
    else:
        fail("POST /testing_requests (CB Operations)",
             f"{r.status_code} {r.text[:120]}")

    if cb_treq_id:
        _advance_to_accepted(cb_treq_id, TOKEN)

        # Submit 2 readings: 1000 → 1200 → cumulative diff = 200
        # Each reading MUST have its own test_session_id so the upsert does not
        # overwrite the first row (upsert key = request_id + template_key + session_id).
        for reading_val, reading_date_offset in [(1000, 10), (1200, 5)]:
            sid = _create_session(cb_treq_id, TOKEN, f"CB Reading {reading_val}")
            _post_result(
                cb_treq_id, TOKEN,
                template_key="circuit_breaker_operations",
                overall_result="Pass",
                test_session_id=sid,
                test_data={
                    "reading": reading_val,
                    "reading_date": str(date.today() - timedelta(days=reading_date_offset)),
                    "breaker_make": "ABB",
                    "breaker_type": "SF6",
                    "notes": f"Reading {reading_val}",
                },
            )

        # CumulativeService must find results despite non-"operations_tracking" template_key
        r = requests.get(
            f"{BASE}/cumulative/equipment/{EQUIP_ID}/lifecycle",
            headers=auth(TOKEN),
        )
        lc = check("GET /cumulative/lifecycle after circuit_breaker_operations results", r, 200)
        if lc:
            cumval = lc.get("cumulative_value", 0)
            info(f"cumulative_value={cumval}  status={lc.get('status')}")
            if cumval > 0:
                ok("CumulativeService found CB readings (template_key-agnostic)",
                   f"cumulative={cumval}")
            else:
                fail("CumulativeService found CB readings",
                     "cumulative_value=0 — service still filtering by old template_key")

        # Evaluate
        r = requests.post(
            f"{BASE}/cumulative/equipment/{EQUIP_ID}/evaluate",
            headers=auth(TOKEN),
        )
        ev = check("POST /cumulative/evaluate after CB operations", r, 200)
        if ev:
            status = ev.get("status")
            ok(f"evaluate returned status={status}", status)

# ─────────────────────────────────────────────────────────────────────────────
# §8  Cumulative via oltc_operations template_key
# ─────────────────────────────────────────────────────────────────────────────
section("§8  Cumulative — oltc_operations template_key")

oltc_type_id = TYPE_IDS.get("OLTC Operations Count")
if not oltc_type_id:
    skip("§8 skipped", "OLTC Operations Count test_type_id not resolved")
else:
    treq_payload = {
        "title": "OLTC Operations — Lifecycle Test",
        "equipment_id": EQUIP_ID,
        "request_category": "maintenance",
        "is_multi_session": True,
        "test_type_id": oltc_type_id,
        "assigned_tester_id": USER_ID,
    }
    r = requests.post(f"{BASE}/testing_requests/", headers=auth(TOKEN), json=treq_payload)
    oltc_treq_id = None
    if r.status_code in (200, 201):
        body = r.json()
        oltc_treq_id = body.get("id")
        ok("POST /testing_requests (OLTC Operations)", f"id={oltc_treq_id}")
        if body.get("is_cumulative") is True:
            ok("is_cumulative=True stamped on OLTC request")
        else:
            fail("is_cumulative=True stamped on OLTC request",
                 "flag not set — check _resolve_is_cumulative()")
    else:
        fail("POST /testing_requests (OLTC Operations)",
             f"{r.status_code} {r.text[:120]}")

    if oltc_treq_id:
        _advance_to_accepted(oltc_treq_id, TOKEN)

        for reading_val, reading_date_offset in [(50000, 20), (50800, 10)]:
            sid = _create_session(oltc_treq_id, TOKEN, f"OLTC Reading {reading_val}")
            _post_result(
                oltc_treq_id, TOKEN,
                template_key="oltc_operations",
                overall_result="Pass",
                test_session_id=sid,
                test_data={
                    "reading": reading_val,
                    "reading_date": str(date.today() - timedelta(days=reading_date_offset)),
                    "oltc_make": "MR",
                    "oltc_type": "Motor-operated OLTC",
                    "notes": f"OLTC counter {reading_val}",
                },
            )

        r = requests.get(
            f"{BASE}/cumulative/equipment/{EQUIP_ID}/lifecycle",
            headers=auth(TOKEN),
        )
        lc = check("GET /cumulative/lifecycle after oltc_operations results", r, 200)
        if lc:
            cumval = lc.get("cumulative_value", 0)
            info(f"cumulative_value={cumval}  status={lc.get('status')}")
            if cumval > 0:
                ok("CumulativeService found OLTC readings (template_key-agnostic)",
                   f"cumulative={cumval}")
            else:
                fail("CumulativeService found OLTC readings",
                     "cumulative_value=0 — service still filtering by old template_key")

# ─────────────────────────────────────────────────────────────────────────────
# §9  Negative — lifecycle-types unauthenticated
# ─────────────────────────────────────────────────────────────────────────────
section("§9  Negative tests")

r = _orig_get(f"{BASE}/testing_requests/lifecycle-types")
check_neg("GET lifecycle-types unauthenticated → 401/403", r, [401, 403])

# Verify response structure — must have exactly "calibration" and "cumulative" keys
r = requests.get(f"{BASE}/testing_requests/lifecycle-types", headers=auth(TOKEN))
if r.status_code == 200:
    body = r.json()
    if set(body.keys()) == {"calibration", "cumulative"}:
        ok("lifecycle-types response has exactly {calibration, cumulative} keys")
    else:
        fail("lifecycle-types response structure",
             f"unexpected keys: {set(body.keys())}")

    # Every item must have id, name, category_type
    for bucket_key, items in body.items():
        for item in items:
            for field in ("id", "name", "category_type"):
                if field not in item:
                    fail(f"lifecycle item missing field '{field}'",
                         f"bucket={bucket_key} item={item.get('name')}")
                    break
            else:
                continue
        else:
            ok(f"all {bucket_key} items have required fields (id, name, category_type)")

# ─────────────────────────────────────────────────────────────────────────────
# §10 category_type=maintenance on all lifecycle items
# ─────────────────────────────────────────────────────────────────────────────
section("§10  All lifecycle types carry category_type=maintenance")

r = requests.get(f"{BASE}/testing_requests/lifecycle-types", headers=auth(TOKEN))
if r.status_code == 200:
    body = r.json()
    all_items = body.get("calibration", []) + body.get("cumulative", [])
    wrong = [t for t in all_items if t.get("category_type") != "maintenance"]
    if not wrong:
        ok("all lifecycle types have category_type=maintenance",
           f"count={len(all_items)}")
    else:
        fail("all lifecycle types have category_type=maintenance",
             f"{len(wrong)} wrong: {[t['name'] for t in wrong]}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
_print_summary()
sys.exit(0 if fail_count == 0 else 1)
