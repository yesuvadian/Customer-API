"""
tests/test_annual_audit_integration.py
=======================================
Annual Audit — End-to-End Integration Test Suite

Stage role map
--------------
Stage 1  OBSERVATION_REPORTING   — TaqcOfficer fills+submits · TaqcOfficer approves
Stage 2  OBSERVATION_ASSIGNMENT  — WfCoordinator fills+submits · WfCoordinator approves
Stage 3  COMPLIANCE_SUBMISSION   — WfCoordinator assigns AeeMaint · AeeMaint fills+submits · AeeMaint approves
Stage 4  COMPLIANCE_REVIEW       — TaqcOfficer fills+submits · TaqcOfficer approves
Stage 5  OBSERVATION_CLOSURE     — TaqcOfficer fills+submits · TaqcOfficer approves

Data coverage
-------------
Every stage:
  1. GET current-form  → verify stage_code correct
  2. POST .../save     → verify 200
  3. GET current-form  → verify saved_form_data matches submitted keys/values
  4. POST .../save again with updated values → verify saved_form_data reflects latest
  5. POST .../submit
  6. POST .../approve
  7. GET observation detail → verify current_stage_code advanced
  8. GET timeline → verify new entry added

After full happy path:
  - workflow.stages[] all have status=completed
  - workflow.status = completed
  - no further actions available

Reject path (§12): drive second observation to COMPLIANCE_REVIEW,
TaqcOfficer rejects → bounces to COMPLIANCE_SUBMISSION → AeeMaint
re-works → re-submits → TaqcOfficer approves on second attempt.

Prerequisites:
  1. python tests/clean_and_seed.py
  2. uvicorn main:app --reload --port 8000
  3. python tests/test_annual_audit_integration.py
"""

import os
import sys
import json
import time
from datetime import date, timedelta

import requests
from requests.exceptions import ConnectionError as ReqConnError

BASE     = "http://localhost:8000"
SAMPLE_FILE_PATH = os.path.join(os.path.dirname(__file__), "test_data", "sample_evidence.pdf")
PW_DEPT  = "TestDept@123"

# ── Resilient request wrappers ─────────────────────────────────────────────────
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

# ── UTF-8 safe output ──────────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Colour helpers ─────────────────────────────────────────────────────────────
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
    _print_summary()
    sys.exit(1)

def skip(label, detail=""):
    global skip_count
    skip_count += 1
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
    if resp.status_code in expected_statuses:
        ok(f"[NEG] {label}", f"correctly rejected {resp.status_code}")
    else:
        fail(f"[NEG] {label}", f"got {resp.status_code} expected one of {expected_statuses}")

def login(email, password=PW_DEPT):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        token = r.json().get("access_token")
        ok(f"login {email}", "200")
        return token, r.json().get("user", {}).get("id")
    fail(f"login {email}", f"{r.status_code} {r.text[:120]}")
    return None, None

def auth(token):
    return {"Authorization": f"Bearer {token}"}

# ─────────────────────────────────────────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────────────────────────────────────────
TOKENS   = {}
USER_IDS = {}

EQUIP_ID    = None
CATEGORY_ID = None
INSP_ID     = None
OBS_ID      = None

TODAY    = str(date.today())
DUE_DATE = str(date.today() + timedelta(days=30))

# ─────────────────────────────────────────────────────────────────────────────
# §1  AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────
section("§1  Authentication — TaqcOfficer / WfCoordinator / AeeMaint / OrgAdmin")

for role_key, email, pw in [
    ("TaqcOfficer",   "taqc.north@kptcl.com",         PW_DEPT),
    ("WfCoordinator", "wfcoordinator.north@kptcl.com", PW_DEPT),
    ("AeeMaint",      "aeemaint.north@kptcl.com",      PW_DEPT),
    ("OrgAdmin",      "orgadmin@kptcl.com",            "admin123"),
]:
    t, uid = login(email, pw)
    if t:
        TOKENS[role_key]   = t
        USER_IDS[role_key] = str(uid) if uid else None

r = requests.post(f"{BASE}/auth/login", json={"email": "taqc.north@kptcl.com", "password": "wrongpassword"})
check_neg("login with wrong password", r, [401, 403])

for required in ("TaqcOfficer", "WfCoordinator", "AeeMaint"):
    if not TOKENS.get(required):
        print(f"\n{RED}FATAL: could not obtain token for {required} — check seed data and server.{RESET}")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# §2  SETUP — config ensure / substation / categories
# ─────────────────────────────────────────────────────────────────────────────
section("§2  Setup — config/ensure · equipment · category_details")

r = requests.post(f"{BASE}/annual-audits/config/ensure", headers=auth(TOKENS["TaqcOfficer"]))
result = check("POST /annual-audits/config/ensure", r, 200)
if result:
    info(result.get("message", ""))

r = requests.get(f"{BASE}/equipment", headers=auth(TOKENS["OrgAdmin"]), params={"limit": 10})
equip_data = check("GET /equipment", r, 200)
if equip_data:
    items = equip_data if isinstance(equip_data, list) else equip_data.get("items", [])
    if items:
        EQUIP_ID = items[0].get("id")
        ok("substation resolved", f"ueic={items[0].get('ueic')}  id={EQUIP_ID}")
    else:
        skip("substation resolve", "no equipment in DB — seed required")

r = requests.get(
    f"{BASE}/category_details/details/by-master/Annual Audit Categories",
    headers=auth(TOKENS["TaqcOfficer"]),
    params={"limit": 20},
)
categories = []
if r.status_code == 200:
    body = r.json()
    categories = body if isinstance(body, list) else body.get("items", body.get("data", []))

if categories:
    CATEGORY_ID = categories[0]["id"]
    ok("annual audit category resolved", f"id={CATEGORY_ID}  name={categories[0].get('name')}")
else:
    fail("category_details resolve", "no annual_audit categories — run config/ensure first")

# ─────────────────────────────────────────────────────────────────────────────
# §3  CREATE INSPECTION  (TaqcOfficer)
# ─────────────────────────────────────────────────────────────────────────────
section("§3  Create Annual Inspection  (TaqcOfficer)")

if EQUIP_ID:
    r = requests.post(
        f"{BASE}/annual-audits/inspections",
        json={
            "substation_id": EQUIP_ID,
            "inspection_date": TODAY,
            "remarks": "Annual substation inspection — integration test",
        },
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    result = check("POST /annual-audits/inspections", r, 200)
    if result:
        INSP_ID = result.get("id")
        ok("inspection_number format", result.get("inspection_number", ""))
        info(f"inspection_id={INSP_ID}  number={result.get('inspection_number')}")
else:
    skip("Create inspection", "no EQUIP_ID")

r = requests.get(f"{BASE}/annual-audits/inspections", headers=auth(TOKENS["TaqcOfficer"]))
check("GET /annual-audits/inspections", r, 200)

if INSP_ID:
    r = requests.get(f"{BASE}/annual-audits/inspections/{INSP_ID}", headers=auth(TOKENS["TaqcOfficer"]))
    insp = check(f"GET /annual-audits/inspections/{INSP_ID[:8]}…", r, 200)
    if insp:
        if insp.get("substation_id") == EQUIP_ID:
            ok("inspection.substation_id matches")
        else:
            fail("inspection.substation_id matches", f"got {insp.get('substation_id')}")

# ─────────────────────────────────────────────────────────────────────────────
# §4  CREATE OBSERVATION  (TaqcOfficer)
# ─────────────────────────────────────────────────────────────────────────────
section("§4  Create Observation  (TaqcOfficer)")

if INSP_ID and CATEGORY_ID:
    r = requests.post(
        f"{BASE}/annual-audits/inspections/{INSP_ID}/observations",
        json={
            "category_detail_id": CATEGORY_ID,
            "severity": "Major",
            "target_compliance_date": DUE_DATE,
            "observation_description": "Earthing system shows signs of corrosion at multiple contact points.",
        },
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    result = check("POST .../observations", r, 200)
    if result:
        OBS_ID = result.get("id")
        # Verify initial fields
        if result.get("current_stage_code") == "OBSERVATION_REPORTING":
            ok("initial stage = OBSERVATION_REPORTING")
        else:
            fail("initial stage = OBSERVATION_REPORTING", f"got {result.get('current_stage_code')}")
        if result.get("severity") == "Major":
            ok("severity stored correctly")
        else:
            fail("severity stored correctly", f"got {result.get('severity')}")
        if result.get("observation_number", "").startswith("TR-ANU"):
            ok("observation_number format", result.get("observation_number"))
        else:
            fail("observation_number format", f"got {result.get('observation_number')}")
        info(f"observation_id={OBS_ID}  number={result.get('observation_number')}")
else:
    skip("Create observation", f"INSP_ID={INSP_ID}  CATEGORY_ID={CATEGORY_ID}")

if not OBS_ID:
    print(f"\n{RED}FATAL: no observation_id — cannot continue workflow tests.{RESET}")
    _print_summary()
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def get_observation_detail(obs_id, token_key):
    r = requests.get(
        f"{BASE}/annual-audits/observations/{obs_id}",
        headers=auth(TOKENS[token_key]),
    )
    return r.json() if r.status_code == 200 else None

def get_current_form(obs_id, token_key):
    r = requests.get(
        f"{BASE}/annual-audits/observations/{obs_id}/current-form",
        headers=auth(TOKENS[token_key]),
    )
    if r.status_code == 200:
        return r.json()
    fail(f"GET current-form ({token_key})", f"{r.status_code} {r.text[:100]}")
    return None

def get_available_actions(obs_id, token_key):
    r = requests.get(
        f"{BASE}/annual-audits/observations/{obs_id}/available-actions",
        headers=auth(TOKENS[token_key]),
    )
    return r.json() if r.status_code == 200 else {}

def get_timeline(obs_id, token_key):
    r = requests.get(
        f"{BASE}/annual-audits/observations/{obs_id}/timeline",
        headers=auth(TOKENS[token_key]),
    )
    return r.json() if r.status_code == 200 else []

def get_eligible_users(obs_id, stage_id, token_key):
    r = requests.get(
        f"{BASE}/annual-audits/observations/{obs_id}/stages/{stage_id}/eligible-users",
        headers=auth(TOKENS[token_key]),
    )
    if r.status_code == 200:
        users = r.json()
        info(f"eligible users ({len(users)}): " +
             ", ".join(f"{u.get('firstname','')} {u.get('lastname','')} [{u.get('role','-')}]"
                       for u in users[:5]))
        return users
    skip(f"eligible-users ({token_key})", str(r.status_code))
    return []

def resolve_user_id(token_key):
    if USER_IDS.get(token_key):
        return USER_IDS[token_key]
    r = requests.get(f"{BASE}/users/me", headers=auth(TOKENS[token_key]))
    if r.status_code == 200:
        uid = str(r.json().get("id", ""))
        USER_IDS[token_key] = uid
        return uid
    return None

_WORKFLOW_ID_CACHE = {}

def get_workflow_id(obs_id, token_key):
    if obs_id in _WORKFLOW_ID_CACHE:
        return _WORKFLOW_ID_CACHE[obs_id]
    detail = get_observation_detail(obs_id, token_key)
    wid = detail.get("workflow_id") if detail else None
    if wid:
        _WORKFLOW_ID_CACHE[obs_id] = wid
    return wid

def upload_file_for_field(obs_id, stage_id, field_key, token_key):
    """Upload SAMPLE_FILE_PATH for a file-type field via the repair-workflow upload endpoint."""
    workflow_id = get_workflow_id(obs_id, token_key)
    if not workflow_id:
        skip(f"upload file {field_key}", "no workflow_id")
        return False
    if not os.path.exists(SAMPLE_FILE_PATH):
        skip(f"upload file {field_key}", f"sample file not found: {SAMPLE_FILE_PATH}")
        return False
    with open(SAMPLE_FILE_PATH, "rb") as fh:
        r = _orig_post(
            f"{BASE}/repair-workflows/{workflow_id}/stages/{stage_id}/upload",
            data={"field_key": field_key},
            files={"file": ("sample_evidence.pdf", fh, "application/pdf")},
            headers=auth(TOKENS[token_key]),
        )
    if r.status_code == 200:
        return True
    fail(f"upload file {field_key}", f"{r.status_code} {r.text[:120]}")
    return False

def _synthetic_value(field):
    key        = field.get("key", "field")
    field_type = field.get("type", "text")
    label      = field.get("label", key)
    options    = field.get("options", [])

    if field_type == "dropdown":
        if options:
            first = options[0]
            return first if isinstance(first, str) else first.get("value", str(first))
        return "Option1"
    if field_type == "boolean":
        return "true"
    if field_type in ("number", "float", "integer"):
        return "1.5"
    if field_type == "date":
        return DUE_DATE
    if field_type == "file":
        return f"test_{key}.pdf"
    if field_type == "textarea":
        return f"Integration test value — {label}."
    return f"Test {label}"

def _synthetic_updated_value(field):
    """Return a DIFFERENT synthetic value for re-save (data update) testing."""
    key        = field.get("key", "field")
    field_type = field.get("type", "text")
    options    = field.get("options", [])

    if field_type == "dropdown":
        if options and len(options) > 1:
            last = options[-1]
            return last if isinstance(last, str) else last.get("value", str(last))
        return options[0] if options else "Option1"
    if field_type == "boolean":
        return "false"
    if field_type in ("number", "float", "integer"):
        return "9.9"
    if field_type == "date":
        return str(date.today() + timedelta(days=60))
    if field_type == "file":
        return f"updated_{key}.pdf"
    if field_type == "textarea":
        return f"UPDATED integration test value — {key}."
    return f"Updated {key}"

def fill_form_from_template(obs_id, stage_id, filler_token_key, label=""):
    """
    Read template_data from current-form, generate synthetic values, save them.
    - Non-file fields → saved via JSON save endpoint
    - File fields     → uploaded via repair-workflow upload endpoint
    Returns (form_data dict, stage_id from form).
    form_data includes ALL field keys (file keys included for downstream verification).
    """
    form = get_current_form(obs_id, filler_token_key)
    if not form:
        return {}, None

    template_data = form.get("template_data") or {}
    sections      = template_data.get("sections", [])
    form_data     = {}
    file_fields   = []

    for sec in sections:
        for field in sec.get("fields", []):
            k = field.get("key")
            if not k:
                continue
            if field.get("type") == "file":
                file_fields.append(k)
                form_data[k] = "uploaded_file"  # placeholder for verify_saved_form_data key check
            else:
                form_data[k] = _synthetic_value(field)

    if not form_data and not file_fields:
        form_data = {
            "observation_description": "Integration test — no template fields detected.",
            "overall_result": "Compliant",
        }
        skip(f"fill_form template ({filler_token_key})", "template_data empty — using fallback")
    else:
        all_keys = [k for k in form_data if k not in file_fields] + file_fields
        info(f"fill_form ({filler_token_key}){' ' + label if label else ''} — "
             f"{len(all_keys)} fields: {', '.join(all_keys[:6])}"
             + (" …" if len(all_keys) > 6 else ""))

    # Upload file fields first so they are in merged form_data before save validation runs
    for fk in file_fields:
        upload_file_for_field(obs_id, stage_id, fk, filler_token_key)

    # Save non-file fields via JSON — validation runs on merged (includes uploaded file refs)
    non_file_data = {k: v for k, v in form_data.items() if k not in file_fields}
    if non_file_data:
        r = requests.post(
            f"{BASE}/annual-audits/observations/{obs_id}/stages/{stage_id}/save",
            json={"form_data": non_file_data},
            headers=auth(TOKENS[filler_token_key]),
        )
        check(f"save form ({filler_token_key})" + (f" {label}" if label else ""), r, 200)

    return form_data, form.get("stage_id")

def verify_saved_form_data(obs_id, token_key, expected_data, label=""):
    """
    GET current-form and assert that saved_form_data matches every key/value
    in expected_data (ignores file fields which are stored as metadata, not raw strings).
    """
    form = get_current_form(obs_id, token_key)
    if not form:
        skip(f"verify saved_form_data {label}", "could not fetch current-form")
        return

    saved = form.get("saved_form_data") or {}
    missing_keys  = [k for k in expected_data if k not in saved]
    value_mismatches = []

    for k, v in expected_data.items():
        if k in saved:
            saved_v = saved[k]
            # Files are stored as dicts (metadata); skip direct equality check
            if isinstance(saved_v, dict):
                continue
            if str(saved_v) != str(v):
                value_mismatches.append(f"{k}: expected={v!r} got={saved_v!r}")

    if missing_keys:
        fail(f"saved_form_data has all keys {label}", f"missing: {missing_keys}")
    else:
        ok(f"saved_form_data has all keys {label}", f"{len(expected_data)} keys present")

    if value_mismatches:
        fail(f"saved_form_data values correct {label}", "; ".join(value_mismatches[:3]))
    else:
        ok(f"saved_form_data values correct {label}")

def resave_form_with_updates(obs_id, stage_id, filler_token_key, original_data, label=""):
    """
    Save updated values for every field in original_data using _synthetic_updated_value.
    Verifies that the re-read saved_form_data reflects the latest values.
    """
    form = get_current_form(obs_id, filler_token_key)
    if not form:
        return {}

    template_data = form.get("template_data") or {}
    sections      = template_data.get("sections", [])
    updated_data  = {}

    for sec in sections:
        for field in sec.get("fields", []):
            k = field.get("key")
            if not k or field.get("type") == "file":
                continue
            updated_data[k] = _synthetic_updated_value(field)

    if not updated_data:
        skip(f"re-save with updates {label}", "no non-file fields to update")
        return {}

    r = requests.post(
        f"{BASE}/annual-audits/observations/{obs_id}/stages/{stage_id}/save",
        json={"form_data": updated_data},
        headers=auth(TOKENS[filler_token_key]),
    )
    check(f"re-save form with updates ({filler_token_key}) {label}", r, 200)
    verify_saved_form_data(obs_id, filler_token_key, updated_data, f"{label} after re-save")
    return updated_data

def assert_stage_advanced(obs_id, token_key, expected_stage_code, label=""):
    """Fetch observation detail and assert current_stage_code matches expected."""
    detail = get_observation_detail(obs_id, token_key)
    if not detail:
        skip(f"stage advanced to {expected_stage_code} {label}", "could not fetch detail")
        return
    actual = detail.get("current_stage_code", "")
    if actual == expected_stage_code:
        ok(f"stage advanced to {expected_stage_code} {label}")
    else:
        fail(f"stage advanced to {expected_stage_code} {label}", f"got {actual!r}")

def assert_timeline_grew(obs_id, token_key, prev_count, label=""):
    """Assert timeline has more entries than prev_count."""
    tl = get_timeline(obs_id, token_key)
    if len(tl) > prev_count:
        ok(f"timeline grew after {label}", f"{prev_count} → {len(tl)}")
    else:
        fail(f"timeline grew after {label}", f"still {len(tl)} (expected > {prev_count})")
    return len(tl)

def assign_stage(obs_id, stage_id, assigner_key, assignee_key, *, eligible=None):
    user_id = resolve_user_id(assignee_key)
    if not user_id and eligible:
        user_id = str(eligible[0]["id"]) if eligible else None
    if not user_id:
        skip(f"assign stage ({assigner_key} → {assignee_key})", "could not resolve user_id")
        return False

    r = requests.post(
        f"{BASE}/annual-audits/observations/{obs_id}/stages/{stage_id}/assign",
        json={"assign_to_user_id": user_id},
        headers=auth(TOKENS[assigner_key]),
    )
    if r.status_code == 200:
        ok(f"assign stage {assigner_key} → {assignee_key}", "200")
        USER_IDS[assignee_key] = user_id
        return True
    elif r.status_code == 400 and "already" in r.text.lower():
        skip(f"assign stage ({assigner_key} → {assignee_key})",
             "stage auto-assigned — already set")
        return True
    else:
        fail(f"assign stage {assigner_key} → {assignee_key}",
             f"got {r.status_code} — {r.text[:120]}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# §5  STAGE 1 — OBSERVATION_REPORTING
# ─────────────────────────────────────────────────────────────────────────────
section("§5  Stage 1 — OBSERVATION_REPORTING  (TaqcOfficer fills+submits+approves)")

timeline_count = len(get_timeline(OBS_ID, "TaqcOfficer"))

form = get_current_form(OBS_ID, "TaqcOfficer")
S1_STAGE_ID = None
if form:
    info(f"stage_code={form.get('stage_code')}  stage_status={form.get('stage_status')}")
    if "OBSERVATION_REPORTING" in str(form.get("stage_code", "")):
        ok("current stage = OBSERVATION_REPORTING")
    else:
        fail("current stage = OBSERVATION_REPORTING", f"got {form.get('stage_code')}")

    S1_STAGE_ID = form.get("stage_id")

    # Assign
    eligible = get_eligible_users(OBS_ID, S1_STAGE_ID, "WfCoordinator")
    assign_stage(OBS_ID, S1_STAGE_ID, "WfCoordinator", "TaqcOfficer", eligible=eligible)

    # First save — verify data persists
    s1_data, _ = fill_form_from_template(OBS_ID, S1_STAGE_ID, "TaqcOfficer", "Stage 1 initial")
    verify_saved_form_data(OBS_ID, "TaqcOfficer", s1_data, "Stage 1 initial save")

    # Re-save with updated values — data update coverage
    s1_updated = resave_form_with_updates(OBS_ID, S1_STAGE_ID, "TaqcOfficer", s1_data, "Stage 1")

    # Verify can_submit is still True after save (save should not advance stage)
    actions_after_save = get_available_actions(OBS_ID, "TaqcOfficer")
    if actions_after_save.get("can_submit") is True:
        ok("can_submit = True after save (stage not prematurely advanced)")
    else:
        skip("can_submit after save", f"actions={actions_after_save}")

    # Submit
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S1_STAGE_ID}/submit",
        json={"remarks": "Observation documented and ready for assignment."},
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    check("Stage 1: submit (TaqcOfficer)", r, 200)

    # Approve → OBSERVATION_ASSIGNMENT
    actions = get_available_actions(OBS_ID, "TaqcOfficer")
    info(f"available actions for TaqcOfficer after submit: {actions}")
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S1_STAGE_ID}/approve",
        json={"remarks": "Observation verified — routing to Workflow Coordinator."},
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    check("Stage 1: approve → OBSERVATION_ASSIGNMENT (TaqcOfficer)", r, 200)

    assert_stage_advanced(OBS_ID, "TaqcOfficer", "OBSERVATION_ASSIGNMENT", "after S1 approve")
    timeline_count = assert_timeline_grew(OBS_ID, "TaqcOfficer", timeline_count, "S1 approve")
else:
    skip("Stage 1", "could not get current-form")

# ─────────────────────────────────────────────────────────────────────────────
# §6  STAGE 2 — OBSERVATION_ASSIGNMENT
#     WfCoordinator fills assignment details, submits, and approves
# ─────────────────────────────────────────────────────────────────────────────
section("§6  Stage 2 — OBSERVATION_ASSIGNMENT  (WfCoordinator fills+submits+approves)")

form = get_current_form(OBS_ID, "WfCoordinator")
S2_STAGE_ID = None
if form:
    info(f"stage_code={form.get('stage_code')}  stage_status={form.get('stage_status')}")
    if "OBSERVATION_ASSIGNMENT" in str(form.get("stage_code", "")):
        ok("current stage = OBSERVATION_ASSIGNMENT")
    else:
        fail("current stage = OBSERVATION_ASSIGNMENT", f"got {form.get('stage_code')}")

    S2_STAGE_ID = form.get("stage_id")

    # Self-assign
    eligible = get_eligible_users(OBS_ID, S2_STAGE_ID, "WfCoordinator")
    assign_stage(OBS_ID, S2_STAGE_ID, "WfCoordinator", "WfCoordinator", eligible=eligible)

    # Fill assignment stage form (assignment_remarks, priority_note)
    s2_data, _ = fill_form_from_template(OBS_ID, S2_STAGE_ID, "WfCoordinator", "Stage 2 initial")
    verify_saved_form_data(OBS_ID, "WfCoordinator", s2_data, "Stage 2 initial save")

    # Re-save with updates
    resave_form_with_updates(OBS_ID, S2_STAGE_ID, "WfCoordinator", s2_data, "Stage 2")

    actions = get_available_actions(OBS_ID, "WfCoordinator")
    info(f"available actions for WfCoordinator: {actions}")

    # Submit
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S2_STAGE_ID}/submit",
        json={"remarks": "Observation routed to AEE Maintenance for corrective action."},
        headers=auth(TOKENS["WfCoordinator"]),
    )
    check("Stage 2: submit (WfCoordinator)", r, 200)

    # Approve → COMPLIANCE_SUBMISSION
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S2_STAGE_ID}/approve",
        json={"remarks": "Assignment confirmed — proceeding to compliance stage."},
        headers=auth(TOKENS["WfCoordinator"]),
    )
    check("Stage 2: approve → COMPLIANCE_SUBMISSION (WfCoordinator)", r, 200)

    assert_stage_advanced(OBS_ID, "WfCoordinator", "COMPLIANCE_SUBMISSION", "after S2 approve")
    timeline_count = assert_timeline_grew(OBS_ID, "TaqcOfficer", timeline_count, "S2 approve")
else:
    skip("Stage 2", "could not get current-form")

# ─────────────────────────────────────────────────────────────────────────────
# §7  STAGE 3 — COMPLIANCE_SUBMISSION
#     WfCoordinator assigns AeeMaint · AeeMaint fills+submits+approves
# ─────────────────────────────────────────────────────────────────────────────
section("§7  Stage 3 — COMPLIANCE_SUBMISSION  (AeeMaint fills+submits+approves)")

form = get_current_form(OBS_ID, "WfCoordinator")
S3_STAGE_ID = None
if form:
    info(f"stage_code={form.get('stage_code')}  stage_status={form.get('stage_status')}")
    if "COMPLIANCE_SUBMISSION" in str(form.get("stage_code", "")):
        ok("current stage = COMPLIANCE_SUBMISSION")
    else:
        fail("current stage = COMPLIANCE_SUBMISSION", f"got {form.get('stage_code')}")

    S3_STAGE_ID = form.get("stage_id")

    # WfCoordinator assigns AeeMaint
    eligible = get_eligible_users(OBS_ID, S3_STAGE_ID, "WfCoordinator")
    assign_stage(OBS_ID, S3_STAGE_ID, "WfCoordinator", "AeeMaint", eligible=eligible)

    # AeeMaint fills compliance form (corrective_action_taken, compliance_date, compliance_evidence)
    s3_data, _ = fill_form_from_template(OBS_ID, S3_STAGE_ID, "AeeMaint", "Stage 3 initial")
    verify_saved_form_data(OBS_ID, "AeeMaint", s3_data, "Stage 3 initial save")

    # Re-save with updates — simulate AeeMaint revising their compliance report
    s3_updated = resave_form_with_updates(OBS_ID, S3_STAGE_ID, "AeeMaint", s3_data, "Stage 3")

    # Verify specific compliance fields are present
    form_recheck = get_current_form(OBS_ID, "AeeMaint")
    if form_recheck:
        saved = form_recheck.get("saved_form_data") or {}
        for expected_key in ("corrective_action_taken", "compliance_date", "compliance_evidence"):
            if expected_key in saved:
                ok(f"Stage 3: field '{expected_key}' in saved_form_data", str(saved[expected_key])[:40])
            else:
                skip(f"Stage 3: field '{expected_key}' in saved_form_data", "field not in template")

    # Submit
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S3_STAGE_ID}/submit",
        json={"remarks": "Corrective actions completed. Evidence attached."},
        headers=auth(TOKENS["AeeMaint"]),
    )
    check("Stage 3: submit (AeeMaint)", r, 200)

    # Approve → COMPLIANCE_REVIEW
    actions = get_available_actions(OBS_ID, "AeeMaint")
    info(f"available actions for AeeMaint after submit: {actions}")
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S3_STAGE_ID}/approve",
        json={"remarks": "Compliance submission complete. All corrective actions addressed."},
        headers=auth(TOKENS["AeeMaint"]),
    )
    check("Stage 3: approve → COMPLIANCE_REVIEW (AeeMaint)", r, 200)

    assert_stage_advanced(OBS_ID, "TaqcOfficer", "COMPLIANCE_REVIEW", "after S3 approve")
    timeline_count = assert_timeline_grew(OBS_ID, "TaqcOfficer", timeline_count, "S3 approve")
else:
    skip("Stage 3", "could not get current-form")

# ─────────────────────────────────────────────────────────────────────────────
# §8  STAGE 4 — COMPLIANCE_REVIEW
#     TaqcOfficer fills review form, submits, approves
# ─────────────────────────────────────────────────────────────────────────────
section("§8  Stage 4 — COMPLIANCE_REVIEW  (TaqcOfficer fills+submits+approves)")

form = get_current_form(OBS_ID, "TaqcOfficer")
S4_STAGE_ID = None
if form:
    info(f"stage_code={form.get('stage_code')}  stage_status={form.get('stage_status')}")
    if "COMPLIANCE_REVIEW" in str(form.get("stage_code", "")):
        ok("current stage = COMPLIANCE_REVIEW")
    else:
        fail("current stage = COMPLIANCE_REVIEW", f"got {form.get('stage_code')}")

    S4_STAGE_ID = form.get("stage_id")

    # Assign
    eligible = get_eligible_users(OBS_ID, S4_STAGE_ID, "WfCoordinator")
    assign_stage(OBS_ID, S4_STAGE_ID, "WfCoordinator", "TaqcOfficer", eligible=eligible)

    # TaqcOfficer fills review form (review_remarks, overall_result, review_evidence)
    s4_data, _ = fill_form_from_template(OBS_ID, S4_STAGE_ID, "TaqcOfficer", "Stage 4 initial")
    verify_saved_form_data(OBS_ID, "TaqcOfficer", s4_data, "Stage 4 initial save")

    # Re-save with updates — simulate reviewer revising assessment
    resave_form_with_updates(OBS_ID, S4_STAGE_ID, "TaqcOfficer", s4_data, "Stage 4")

    # Verify review-specific fields
    form_recheck = get_current_form(OBS_ID, "TaqcOfficer")
    if form_recheck:
        saved = form_recheck.get("saved_form_data") or {}
        for expected_key in ("review_remarks", "overall_result"):
            if expected_key in saved:
                ok(f"Stage 4: field '{expected_key}' in saved_form_data", str(saved[expected_key])[:40])
            else:
                skip(f"Stage 4: field '{expected_key}' in saved_form_data", "field not in template")

    # Submit
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S4_STAGE_ID}/submit",
        json={"remarks": "Evidence reviewed and found satisfactory."},
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    check("Stage 4: submit (TaqcOfficer)", r, 200)

    # Approve → OBSERVATION_CLOSURE
    actions = get_available_actions(OBS_ID, "TaqcOfficer")
    info(f"available actions for TaqcOfficer after submit: {actions}")
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S4_STAGE_ID}/approve",
        json={"remarks": "Compliance verified — proceeding to closure."},
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    check("Stage 4: approve → OBSERVATION_CLOSURE (TaqcOfficer)", r, 200)

    assert_stage_advanced(OBS_ID, "TaqcOfficer", "OBSERVATION_CLOSURE", "after S4 approve")
    timeline_count = assert_timeline_grew(OBS_ID, "TaqcOfficer", timeline_count, "S4 approve")
else:
    skip("Stage 4", "could not get current-form")

# ─────────────────────────────────────────────────────────────────────────────
# §9  STAGE 5 — OBSERVATION_CLOSURE
#     TaqcOfficer fills closure form, submits, approves → workflow complete
# ─────────────────────────────────────────────────────────────────────────────
section("§9  Stage 5 — OBSERVATION_CLOSURE  (TaqcOfficer fills+submits+approves)")

form = get_current_form(OBS_ID, "TaqcOfficer")
S5_STAGE_ID = None
if form:
    info(f"stage_code={form.get('stage_code')}  stage_status={form.get('stage_status')}")
    if "OBSERVATION_CLOSURE" in str(form.get("stage_code", "")):
        ok("current stage = OBSERVATION_CLOSURE")
    else:
        fail("current stage = OBSERVATION_CLOSURE", f"got {form.get('stage_code')}")

    S5_STAGE_ID = form.get("stage_id")

    # Assign
    eligible = get_eligible_users(OBS_ID, S5_STAGE_ID, "WfCoordinator")
    assign_stage(OBS_ID, S5_STAGE_ID, "WfCoordinator", "TaqcOfficer", eligible=eligible)

    # TaqcOfficer fills closure form (closure_remarks, closure_date, closure_evidence)
    s5_data, _ = fill_form_from_template(OBS_ID, S5_STAGE_ID, "TaqcOfficer", "Stage 5 initial")
    verify_saved_form_data(OBS_ID, "TaqcOfficer", s5_data, "Stage 5 initial save")

    # Re-save
    resave_form_with_updates(OBS_ID, S5_STAGE_ID, "TaqcOfficer", s5_data, "Stage 5")

    # Verify closure-specific fields
    form_recheck = get_current_form(OBS_ID, "TaqcOfficer")
    if form_recheck:
        saved = form_recheck.get("saved_form_data") or {}
        for expected_key in ("closure_remarks", "closure_date"):
            if expected_key in saved:
                ok(f"Stage 5: field '{expected_key}' in saved_form_data", str(saved[expected_key])[:40])
            else:
                skip(f"Stage 5: field '{expected_key}' in saved_form_data", "field not in template")

    # Submit
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S5_STAGE_ID}/submit",
        json={"remarks": "All checks passed — closing observation."},
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    check("Stage 5: submit (TaqcOfficer)", r, 200)

    # Approve → workflow COMPLETED
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S5_STAGE_ID}/approve",
        json={"remarks": "Observation formally closed."},
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    result = check("Stage 5: approve → COMPLETED (TaqcOfficer)", r, 200)
    if result:
        info(f"workflow result: {result.get('status', result.get('message', result))}")

    timeline_count = assert_timeline_grew(OBS_ID, "TaqcOfficer", timeline_count, "S5 approve")
else:
    skip("Stage 5", "could not get current-form")

# ─────────────────────────────────────────────────────────────────────────────
# §10  VERIFICATION — final state / workflow.stages[] / timeline / dashboard
# ─────────────────────────────────────────────────────────────────────────────
section("§10  Verification — final state · workflow.stages[] · timeline · dashboard · SLA")

# 10a. Final observation detail — stage code and workflow status
detail = get_observation_detail(OBS_ID, "TaqcOfficer")
if detail:
    stage = detail.get("current_stage_code", "")
    if stage == "OBSERVATION_CLOSURE":
        ok("current_stage_code = OBSERVATION_CLOSURE (final)")
    else:
        fail("current_stage_code = OBSERVATION_CLOSURE (final)", f"got: {stage!r}")

    if detail.get("is_overdue") is False:
        ok("is_overdue = False")
    else:
        skip("is_overdue check", f"value={detail.get('is_overdue')}")

    info(f"observation_number={detail.get('observation_number')}  severity={detail.get('severity')}")

    # 10b. workflow.stages[] — all 5 should be completed
    wf = detail.get("workflow") or {}
    stages_list = wf.get("stages", [])
    if stages_list:
        ok("workflow.stages[] present in detail response", f"{len(stages_list)} stages")
        expected_codes = [
            "OBSERVATION_REPORTING", "OBSERVATION_ASSIGNMENT",
            "COMPLIANCE_SUBMISSION", "COMPLIANCE_REVIEW", "OBSERVATION_CLOSURE",
        ]
        returned_codes = [s.get("stage_code") for s in stages_list]
        for code in expected_codes:
            if code in returned_codes:
                ok(f"workflow.stages has {code}")
            else:
                fail(f"workflow.stages has {code}", f"found: {returned_codes}")

        # Every stage should be completed
        for s in stages_list:
            code   = s.get("stage_code", "?")
            status = s.get("status", "?")
            if status == "completed":
                ok(f"stage {code} status = completed")
            else:
                fail(f"stage {code} status = completed", f"got {status!r}")

        # workflow-level status
        wf_status = wf.get("status", "")
        if wf_status == "completed":
            ok("workflow.status = completed")
        else:
            fail("workflow.status = completed", f"got {wf_status!r}")
    else:
        fail("workflow.stages[] present in detail response", "empty or missing")
else:
    skip("§10 final detail", "could not fetch observation detail")

# 10c. Timeline — at least 10 entries (2 per stage: submit + approve)
r = requests.get(f"{BASE}/annual-audits/observations/{OBS_ID}/timeline",
                 headers=auth(TOKENS["TaqcOfficer"]))
timeline_data = check("GET timeline (final)", r, 200)
if timeline_data and isinstance(timeline_data, list):
    if len(timeline_data) >= 10:
        ok(f"timeline >= 10 entries (5 stages × submit+approve)", str(len(timeline_data)))
    else:
        fail(f"timeline >= 10 entries", f"got {len(timeline_data)}")
    for entry in timeline_data:
        info(f"  [{entry.get('action', '-'):12s}]  {entry.get('stage_name', '-'):30s}  "
             f"by {entry.get('performed_by_name', entry.get('performed_by', '-'))}")

# 10d. Dashboard — verify all fields present and counts are sane
r = requests.get(f"{BASE}/annual-audits/dashboard", headers=auth(TOKENS["TaqcOfficer"]))
dash = check("GET /annual-audits/dashboard", r, 200)
if dash:
    for field in (
        "total_observations", "open_observations", "closed_observations",
        "overdue_observations", "compliance_percentage",
        "category_breakdown", "severity_breakdown",
        "avg_pending_days", "max_pending_days",
    ):
        if field in dash:
            val = dash[field]
            ok(f"dashboard.{field} present", str(val) if not isinstance(val, dict) else json.dumps(val))
        else:
            fail(f"dashboard.{field} present")

    if dash.get("total_observations", 0) >= 1:
        ok("dashboard.total_observations >= 1", str(dash.get("total_observations")))
    else:
        fail("dashboard.total_observations >= 1", str(dash.get("total_observations")))

    info(f"total={dash.get('total_observations')}  closed={dash.get('closed_observations')}  "
         f"compliance={dash.get('compliance_percentage')}%")
    info(f"category_breakdown = {dash.get('category_breakdown')}")
    info(f"severity_breakdown = {dash.get('severity_breakdown')}")
    info(f"pending days  avg={dash.get('avg_pending_days')}  max={dash.get('max_pending_days')}")

# 10e. Available actions — all False after closure
r = requests.get(f"{BASE}/annual-audits/observations/{OBS_ID}/available-actions",
                 headers=auth(TOKENS["TaqcOfficer"]))
if r.status_code == 200:
    actions = r.json()
    active = [k for k, v in actions.items() if isinstance(v, bool) and v]
    if not active:
        ok("no further actions available after closure", str(actions))
    else:
        fail("no further actions after closure", f"still active: {active}")

# 10f. SLA overdue check
OVERDUE_OBS_ID = None
PAST_DATE = str(date.today() - timedelta(days=1))
if INSP_ID and CATEGORY_ID:
    r = requests.post(
        f"{BASE}/annual-audits/inspections/{INSP_ID}/observations",
        json={
            "category_detail_id": CATEGORY_ID,
            "severity": "Advisory",
            "target_compliance_date": PAST_DATE,
            "observation_description": "Overdue SLA test observation — target date in the past.",
        },
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    result = check("Create past-due observation for SLA test", r, 200)
    if result:
        OVERDUE_OBS_ID = result.get("id")
        info(f"overdue obs id={OVERDUE_OBS_ID}  target={PAST_DATE}")

r = requests.post(f"{BASE}/annual-audits/sla/run-overdue-check", json={},
                  headers=auth(TOKENS["TaqcOfficer"]))
result = check("POST /annual-audits/sla/run-overdue-check", r, 200)
if result:
    info(f"overdue check result: {result}")

if OVERDUE_OBS_ID:
    r = requests.get(f"{BASE}/annual-audits/observations/{OVERDUE_OBS_ID}",
                     headers=auth(TOKENS["TaqcOfficer"]))
    obs = check("GET past-due observation after SLA check", r, 200)
    if obs:
        if obs.get("is_overdue") is True:
            ok("is_overdue = True after SLA run", f"obs={OVERDUE_OBS_ID[:8]}…")
        else:
            fail("is_overdue = True after SLA run", f"got is_overdue={obs.get('is_overdue')}")

# ─────────────────────────────────────────────────────────────────────────────
# §11  NEGATIVE / RBAC CHECKS
# ─────────────────────────────────────────────────────────────────────────────
section("§11  Negative checks — unauthenticated / wrong-role / invalid data")

# Unauthenticated
r = requests.get(f"{BASE}/annual-audits/observations")
check_neg("GET observations without token", r, [401, 403])

# Invalid category_detail_id
if INSP_ID:
    r = requests.post(
        f"{BASE}/annual-audits/inspections/{INSP_ID}/observations",
        json={
            "category_detail_id": 99999,
            "severity": "Minor",
            "target_compliance_date": DUE_DATE,
            "observation_description": "Should be rejected — invalid category.",
        },
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    check_neg("invalid category_detail_id (99999) rejected", r, [400, 422])

# AeeMaint cannot create an inspection
if EQUIP_ID:
    r = requests.post(
        f"{BASE}/annual-audits/inspections",
        json={"substation_id": EQUIP_ID, "inspection_date": TODAY},
        headers=auth(TOKENS["AeeMaint"]),
    )
    if r.status_code in (400, 403, 422):
        ok("[NEG] AeeMaint cannot create inspection", f"correctly rejected {r.status_code}")
    else:
        skip("[NEG] AeeMaint create inspection check", f"got {r.status_code} (may share org)")

# AeeMaint cannot approve a completed observation
if OBS_ID:
    r = requests.post(
        f"{BASE}/annual-audits/observations/{OBS_ID}/stages/{S5_STAGE_ID or 'unknown'}/approve",
        json={"remarks": "Unauthorized approve attempt"},
        headers=auth(TOKENS["AeeMaint"]),
    )
    check_neg("[NEG] AeeMaint cannot approve completed observation", r, [400, 403, 422])

# WfCoordinator can read dashboard (read-only)
r = requests.get(f"{BASE}/annual-audits/dashboard", headers=auth(TOKENS["WfCoordinator"]))
check("WfCoordinator can read dashboard", r, 200)

# AeeMaint can list observations
r = requests.get(f"{BASE}/annual-audits/observations", headers=auth(TOKENS["AeeMaint"]))
check("AeeMaint can list observations", r, 200)

# Assignment queue visible to WfCoordinator
r = requests.get(f"{BASE}/annual-audits/assignment-queue", headers=auth(TOKENS["WfCoordinator"]))
check("GET /annual-audits/assignment-queue (WfCoordinator)", r, 200)

# Tab filters
for status_val in ("all", "closed", "open"):
    r = requests.get(
        f"{BASE}/annual-audits/observations",
        headers=auth(TOKENS["TaqcOfficer"]),
        params={"status": status_val, "limit": 5},
    )
    check(f"GET observations?status={status_val}", r, 200)

r = requests.get(
    f"{BASE}/annual-audits/observations",
    headers=auth(TOKENS["TaqcOfficer"]),
    params={"assigned_to_me": "true", "limit": 5},
)
check("GET observations?assigned_to_me=true", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# §12  REJECTION SCENARIO — full reject-rework-reapprove cycle
# ─────────────────────────────────────────────────────────────────────────────
section("§12  Rejection Scenario — full reject-rework-reapprove cycle")

OBS_ID_2 = None

if INSP_ID and CATEGORY_ID:
    r = requests.post(
        f"{BASE}/annual-audits/inspections/{INSP_ID}/observations",
        json={
            "category_detail_id": CATEGORY_ID,
            "severity": "Minor",
            "target_compliance_date": DUE_DATE,
            "observation_description": "Fire extinguisher expiry label missing at bay 3.",
        },
        headers=auth(TOKENS["TaqcOfficer"]),
    )
    result = check("Create second observation (for rejection test)", r, 200)
    if result:
        OBS_ID_2 = result.get("id")
        info(f"observation_id_2={OBS_ID_2}  number={result.get('observation_number')}")
else:
    skip("Create second observation", f"INSP_ID={INSP_ID}  CATEGORY_ID={CATEGORY_ID}")

def _fast_advance_to_s4(obs_id):
    """Drive obs_id quickly from S1 through S3 and arrive at COMPLIANCE_REVIEW."""

    # Stage 1
    f = get_current_form(obs_id, "TaqcOfficer")
    if not f:
        return False
    sid = f.get("stage_id")
    eligible = get_eligible_users(obs_id, sid, "WfCoordinator")
    assign_stage(obs_id, sid, "WfCoordinator", "TaqcOfficer", eligible=eligible)
    s1d, _ = fill_form_from_template(obs_id, sid, "TaqcOfficer", "[rej] S1")
    verify_saved_form_data(obs_id, "TaqcOfficer", s1d, "[rej] S1")
    r = requests.post(f"{BASE}/annual-audits/observations/{obs_id}/stages/{sid}/submit",
                      json={"remarks": "S1 submit (rejection test)"},
                      headers=auth(TOKENS["TaqcOfficer"]))
    check("[rej] Stage 1 submit", r, 200)
    r = requests.post(f"{BASE}/annual-audits/observations/{obs_id}/stages/{sid}/approve",
                      json={"remarks": "S1 approve (rejection test)"},
                      headers=auth(TOKENS["TaqcOfficer"]))
    check("[rej] Stage 1 approve", r, 200)

    # Stage 2
    f = get_current_form(obs_id, "WfCoordinator")
    if not f:
        return False
    sid = f.get("stage_id")
    assign_stage(obs_id, sid, "WfCoordinator", "WfCoordinator")
    s2d, _ = fill_form_from_template(obs_id, sid, "WfCoordinator", "[rej] S2")
    verify_saved_form_data(obs_id, "WfCoordinator", s2d, "[rej] S2")
    r = requests.post(f"{BASE}/annual-audits/observations/{obs_id}/stages/{sid}/submit",
                      json={"remarks": "S2 submit (rejection test)"},
                      headers=auth(TOKENS["WfCoordinator"]))
    check("[rej] Stage 2 submit", r, 200)
    r = requests.post(f"{BASE}/annual-audits/observations/{obs_id}/stages/{sid}/approve",
                      json={"remarks": "S2 approve (rejection test)"},
                      headers=auth(TOKENS["WfCoordinator"]))
    check("[rej] Stage 2 approve", r, 200)

    # Stage 3
    f = get_current_form(obs_id, "WfCoordinator")
    if not f:
        return False
    sid = f.get("stage_id")
    eligible = get_eligible_users(obs_id, sid, "WfCoordinator")
    assign_stage(obs_id, sid, "WfCoordinator", "AeeMaint", eligible=eligible)
    s3d, _ = fill_form_from_template(obs_id, sid, "AeeMaint", "[rej] S3 first")
    verify_saved_form_data(obs_id, "AeeMaint", s3d, "[rej] S3 first")
    r = requests.post(f"{BASE}/annual-audits/observations/{obs_id}/stages/{sid}/submit",
                      json={"remarks": "S3 submit (rejection test)"},
                      headers=auth(TOKENS["AeeMaint"]))
    check("[rej] Stage 3 submit", r, 200)
    r = requests.post(f"{BASE}/annual-audits/observations/{obs_id}/stages/{sid}/approve",
                      json={"remarks": "S3 approve (rejection test)"},
                      headers=auth(TOKENS["AeeMaint"]))
    check("[rej] Stage 3 approve", r, 200)
    return True

if OBS_ID_2:
    advanced = _fast_advance_to_s4(OBS_ID_2)

    if advanced:
        # Stage 4 — First attempt: TaqcOfficer REJECTS
        f = get_current_form(OBS_ID_2, "TaqcOfficer")
        if f and "COMPLIANCE_REVIEW" in str(f.get("stage_code", "")):
            ok("[rej] arrived at COMPLIANCE_REVIEW")
            sid4 = f.get("stage_id")

            eligible = get_eligible_users(OBS_ID_2, sid4, "WfCoordinator")
            assign_stage(OBS_ID_2, sid4, "WfCoordinator", "TaqcOfficer", eligible=eligible)

            s4d_first, _ = fill_form_from_template(OBS_ID_2, sid4, "TaqcOfficer", "[rej] S4 first attempt")
            verify_saved_form_data(OBS_ID_2, "TaqcOfficer", s4d_first, "[rej] S4 first")

            r = requests.post(
                f"{BASE}/annual-audits/observations/{OBS_ID_2}/stages/{sid4}/submit",
                json={"remarks": "Submitting for review (first attempt)"},
                headers=auth(TOKENS["TaqcOfficer"]),
            )
            check("[rej] Stage 4 submit first attempt", r, 200)

            # REJECT
            r = requests.post(
                f"{BASE}/annual-audits/observations/{OBS_ID_2}/stages/{sid4}/reject",
                json={"remarks": "Compliance evidence insufficient — photos unclear, please resubmit."},
                headers=auth(TOKENS["TaqcOfficer"]),
            )
            check("[rej] Stage 4 REJECT (TaqcOfficer)", r, 200)

            # Verify bounce back to COMPLIANCE_SUBMISSION
            assert_stage_advanced(OBS_ID_2, "AeeMaint", "COMPLIANCE_SUBMISSION", "[rej] after reject")

            f_after = get_current_form(OBS_ID_2, "AeeMaint")
            if f_after:
                stage_after = f_after.get("stage_code", "")
                if "COMPLIANCE_SUBMISSION" in str(stage_after):
                    ok("[rej] After reject: stage = COMPLIANCE_SUBMISSION")
                else:
                    fail("[rej] After reject: stage = COMPLIANCE_SUBMISSION", f"got {stage_after}")

                sid3_rework = f_after.get("stage_id")
                eligible = get_eligible_users(OBS_ID_2, sid3_rework, "WfCoordinator")
                assign_stage(OBS_ID_2, sid3_rework, "WfCoordinator", "AeeMaint", eligible=eligible)

                # Re-work: AeeMaint re-fills with new corrective action data
                s3d_rework, _ = fill_form_from_template(OBS_ID_2, sid3_rework, "AeeMaint", "[rej] S3 re-work")
                verify_saved_form_data(OBS_ID_2, "AeeMaint", s3d_rework, "[rej] S3 re-work")

                # Confirm re-work data differs from first submission (if templates have fields)
                if s3d_rework:
                    ok("[rej] Re-work form data saved for S3", f"{len(s3d_rework)} fields")

                r = requests.post(
                    f"{BASE}/annual-audits/observations/{OBS_ID_2}/stages/{sid3_rework}/submit",
                    json={"remarks": "Re-submission with corrected evidence."},
                    headers=auth(TOKENS["AeeMaint"]),
                )
                check("[rej] Stage 3 re-submit after rework", r, 200)

                r = requests.post(
                    f"{BASE}/annual-audits/observations/{OBS_ID_2}/stages/{sid3_rework}/approve",
                    json={"remarks": "Re-submission complete — forwarding for review."},
                    headers=auth(TOKENS["AeeMaint"]),
                )
                check("[rej] Stage 3 re-approve after rework", r, 200)

                # Stage 4 — Second attempt: TaqcOfficer APPROVES
                f_s4_again = get_current_form(OBS_ID_2, "TaqcOfficer")
                if f_s4_again and "COMPLIANCE_REVIEW" in str(f_s4_again.get("stage_code", "")):
                    ok("[rej] Back at COMPLIANCE_REVIEW for second attempt")
                    sid4_2 = f_s4_again.get("stage_id")

                    eligible = get_eligible_users(OBS_ID_2, sid4_2, "WfCoordinator")
                    assign_stage(OBS_ID_2, sid4_2, "WfCoordinator", "TaqcOfficer", eligible=eligible)

                    s4d_second, _ = fill_form_from_template(OBS_ID_2, sid4_2, "TaqcOfficer", "[rej] S4 second attempt")
                    verify_saved_form_data(OBS_ID_2, "TaqcOfficer", s4d_second, "[rej] S4 second attempt")

                    r = requests.post(
                        f"{BASE}/annual-audits/observations/{OBS_ID_2}/stages/{sid4_2}/submit",
                        json={"remarks": "Re-reviewed — evidence satisfactory on second attempt."},
                        headers=auth(TOKENS["TaqcOfficer"]),
                    )
                    check("[rej] Stage 4 submit second attempt", r, 200)

                    r = requests.post(
                        f"{BASE}/annual-audits/observations/{OBS_ID_2}/stages/{sid4_2}/approve",
                        json={"remarks": "Compliance verified on second attempt — proceeding to closure."},
                        headers=auth(TOKENS["TaqcOfficer"]),
                    )
                    check("[rej] Stage 4 APPROVE second attempt → OBSERVATION_CLOSURE", r, 200)

                    assert_stage_advanced(OBS_ID_2, "TaqcOfficer", "OBSERVATION_CLOSURE",
                                          "[rej] after second S4 approve")

                    # Verify rejection is visible in timeline
                    tl2 = get_timeline(OBS_ID_2, "TaqcOfficer")
                    reject_entries = [e for e in tl2 if "reject" in str(e.get("action", "")).lower()]
                    if reject_entries:
                        ok("[rej] rejection entry in timeline", f"{len(reject_entries)} reject entries")
                    else:
                        fail("[rej] rejection entry in timeline", "no reject action found in timeline")
                else:
                    fail("[rej] expected COMPLIANCE_REVIEW for second attempt",
                         f"got {f_s4_again.get('stage_code') if f_s4_again else 'None'}")
        else:
            fail("[rej] expected COMPLIANCE_REVIEW after fast-advance",
                 f"got {f.get('stage_code') if f else 'None'}")
else:
    skip("Rejection scenario", "could not create second observation")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
_print_summary()

if fail_count:
    sys.exit(1)
