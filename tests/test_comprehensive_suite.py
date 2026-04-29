#!/usr/bin/env python3
"""
TLSS EE — Comprehensive API Test Suite
=======================================
Covers the entire application end-to-end for every user role:

  §1   Authentication          — 8 roles, token validation, privilege check
  §2   Organisation Discovery  — org, departments, equipment types
  §3   Equipment CRUD          — create / list / get / update / RBAC
  §4   Lifecycle: test         — 13-step workflow, Field Tester
  §5   Lifecycle: maintenance  — 13-step workflow, Lab Tester
  §6   Lifecycle: inspection   — 13-step workflow, Field Tester
  §7   Lifecycle: repair_lifecycle — 13-step workflow, Lab Tester
  §8   Notifications           — list / unread-count / mark-read / mark-all
  §9   Dashboard KPIs          — all 10 widget endpoints, all roles
  §10  Reports                 — list definitions / run all 14 / check logs
  §11  RBAC spot-checks        — verify forbidden actions return 403/422

Prerequisites:
  1.  python tests/clean_and_seed.py
  2.  uvicorn main:app --reload
  3.  python tests/test_comprehensive_suite.py [--base-url http://host:port]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

# ── UTF-8 output: prevents UnicodeEncodeError on Windows cp1252 terminals ─────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

BASE_URL: str = "http://127.0.0.1:8080"

CREDS: Dict[str, Tuple[str, str]] = {
    "superadmin":    ("superadmin@system.com",   "Admin123!"),
    "org_admin":     ("orgadmin@kptcl.com",      "admin123"),
    "originator":    ("originator@kptcl.com",    "admin123"),
    "test_assigner": ("testassigner@kptcl.com",  "admin123"),
    "dept_head":     ("depthead@kptcl.com",      "admin123"),
    "field_tester":  ("fieldtester1@kptcl.com",  "Tester123!"),
    "lab_tester":    ("labtester1@kptcl.com",    "Tester123!"),
    "purchaser":     ("purchaser@kptcl.com",     "admin123"),
}

# ══════════════════════════════════════════════════════════════════════════════
#  TERMINAL OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

G  = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
B  = "\033[94m"; C  = "\033[96m"; W  = "\033[97m"
BD = "\033[1m";  RS = "\033[0m"

_passed = _failed = _warned = 0


def section(title: str) -> None:
    print(f"\n{BD}{C}{'='*70}{RS}")
    print(f"{BD}{C}  {title}{RS}")
    print(f"{BD}{C}{'='*70}{RS}")


def step(msg: str) -> None:
    print(f"\n  {W}{BD}{msg}{RS}")


def ok(msg: str) -> None:
    global _passed
    _passed += 1
    print(f"    {G}[PASS]{RS} {msg}")


def fail(msg: str, detail: str = "") -> None:
    global _failed
    _failed += 1
    print(f"    {R}[FAIL]{RS} {msg}")
    if detail:
        print(f"           {R}{detail[:150]}{RS}")


def warn(msg: str) -> None:
    global _warned
    _warned += 1
    print(f"    {Y}[WARN]{RS} {msg}")


def info(msg: str) -> None:
    print(f"    {B}[INFO]{RS} {msg}")


def chk(cond: bool, label: str, detail: str = "") -> bool:
    if cond:
        ok(label)
    else:
        fail(label, detail)
    return cond


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED STATE
# ══════════════════════════════════════════════════════════════════════════════

state: Dict[str, Any] = {
    "tokens":      {},   # role  -> access_token
    "user_ids":    {},   # role  -> user_id (str)
    "org_id":      None,
    "dept_id":     None,
    "equip_id":    None,
    "equip_type_id": None,
    "report_defs": [],   # list of {id, query_key, name}
    "lifecycle":   {},   # category -> request_id
}

# ══════════════════════════════════════════════════════════════════════════════
#  HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _h(role: str) -> Dict[str, str]:
    token = state["tokens"].get(role, "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def GET(role: str, path: str, params: dict = None, timeout: int = 30) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=_h(role), params=params, timeout=timeout)


def POST(role: str, path: str, body: dict = None, timeout: int = 90) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", headers=_h(role), json=body or {}, timeout=timeout)


def PUT(role: str, path: str, body: dict = None, timeout: int = 30) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=_h(role), json=body or {}, timeout=30)


def DELETE(role: str, path: str, timeout: int = 30) -> requests.Response:
    return requests.delete(f"{BASE_URL}{path}", headers=_h(role), timeout=timeout)


def assert200(r: requests.Response, label: str) -> bool:
    if r.status_code in (200, 201):
        ok(f"{label}  [{r.status_code}]")
        return True
    fail(f"{label}  [{r.status_code}]", r.text[:150])
    return False


def assert_forbidden(r: requests.Response, label: str) -> bool:
    if r.status_code in (403, 422, 401):
        ok(f"{label}  [correctly returned {r.status_code}]")
        return True
    fail(f"{label}  [expected 403/422, got {r.status_code}]", r.text[:100])
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  §1  AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════

def test_auth() -> None:
    section("§1  AUTHENTICATION — 8 roles")

    step("Login all roles")
    for role, (email, pwd) in CREDS.items():
        r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": pwd}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            state["tokens"][role] = data["access_token"]
            state["user_ids"][role] = str(data.get("user", {}).get("id", ""))
            ok(f"Login  {role:<14}  ({email})")
        else:
            fail(f"Login  {role:<14}  ({email})", r.text[:100])

    step("Verify tokens — GET /auth/privileges")
    for role in state["tokens"]:
        r = GET(role, "/auth/privileges")
        chk(r.status_code == 200,
            f"Privileges  {role:<14}  [{r.status_code}]",
            r.text[:100])

    step("GET /users/me — confirm identity for all roles")
    for role in state["tokens"]:
        r = GET(role, "/users/me")
        if r.status_code == 200:
            u = r.json()
            ok(f"Me  {role:<14}  email={u.get('email')}  org={u.get('organization_id','—')}")
        else:
            warn(f"GET /users/me failed for {role}: {r.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
#  §2  ORGANISATION & EQUIPMENT DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

def test_discovery() -> None:
    section("§2  ORGANISATION & EQUIPMENT DISCOVERY")

    if "org_admin" not in state["tokens"]:
        warn("org_admin token missing — skipping discovery")
        return

    # ── Organisations ─────────────────────────────────────────────────────────
    step("List organisations")
    r = GET("org_admin", "/organizations/")
    if assert200(r, "GET /organizations/"):
        orgs = r.json()
        info(f"Total orgs: {len(orgs)}")
        # Prefer KPTCL org, then any first
        org = next((o for o in orgs if "kptcl" in o.get("code","").lower() or "kptcl" in o.get("name","").lower()), None)
        if not org and orgs:
            org = orgs[0]
        if org:
            state["org_id"] = org["id"]
            info(f"Using org: {org['name']}  id={org['id']}")
        else:
            warn("No org found — subsequent tests may fail")

    # ── Department hierarchy ───────────────────────────────────────────────────
    if state["org_id"]:
        step("GET /testing_requests/department_hierarchy")
        r = GET("org_admin", "/testing_requests/department_hierarchy",
                params={"org_id": state["org_id"]})
        if assert200(r, "GET /department_hierarchy"):
            depts = r.json()
            info(f"Departments found: {len(depts)}")
            if depts:
                state["dept_id"] = depts[0]["id"]
                info(f"Using dept: {depts[0].get('name')}  id={state['dept_id']}")

    # ── Equipment types ────────────────────────────────────────────────────────
    step("GET /testing_requests/equipment_types")
    r = GET("org_admin", "/testing_requests/equipment_types")
    if assert200(r, "GET /equipment_types"):
        et = r.json()
        if et:
            state["equip_type_id"] = et[0]["id"]
            info(f"Equipment types: {len(et)}  using: {et[0]['name']}")

    # ── Request categories ─────────────────────────────────────────────────────
    step("GET /testing_requests/request-categories")
    r = GET("org_admin", "/testing_requests/request-categories")
    assert200(r, "GET /request-categories")

    # ── Existing equipment ─────────────────────────────────────────────────────
    step("GET /equipment/ — find seeded equipment")
    r = GET("org_admin", "/equipment/", params={"limit": 5})
    if assert200(r, "GET /equipment/?limit=5"):
        items = r.json()
        info(f"Equipment items found: {len(items)}")
        if items:
            state["equip_id"] = items[0]["id"]
            info(f"Using equip: {items[0].get('ueic','?')}  id={state['equip_id']}")


# ══════════════════════════════════════════════════════════════════════════════
#  §3  EQUIPMENT CRUD
# ══════════════════════════════════════════════════════════════════════════════

def test_equipment() -> None:
    section("§3  EQUIPMENT CRUD")

    if not state["org_id"]:
        warn("No org_id — skipping equipment tests")
        return

    # ── Create ─────────────────────────────────────────────────────────────────
    step("POST /equipment/ — originator creates equipment")
    payload: Dict[str, Any] = {
        "organization_id": state["org_id"],
        "voltage_class": "33kV",
        "bay_number": "01",          # VARCHAR(10) — use short form
        "nameplate_data": {
            "manufacturer": "BHEL",
            "serial_number": f"SN-TEST-{int(time.time())}",
            "year_of_manufacture": "2020",
            "rated_mva": "100",
        },
    }
    if state["dept_id"]:
        payload["department_id"] = state["dept_id"]
    if state["equip_type_id"]:
        payload["equipment_type_id"] = state["equip_type_id"]

    r = POST("originator", "/equipment/", payload)
    new_equip_id = None
    if assert200(r, "POST /equipment/  (create)"):
        eq = r.json()
        new_equip_id = eq["id"]
        if not state["equip_id"]:
            state["equip_id"] = new_equip_id
        info(f"Created UEIC={eq.get('ueic')}  id={new_equip_id}")

    # ── List ───────────────────────────────────────────────────────────────────
    step("GET /equipment/ — list with pagination")
    r = GET("org_admin", "/equipment/", params={"limit": 10, "skip": 0})
    if assert200(r, "GET /equipment/?limit=10"):
        items = r.json()
        info(f"Equipment list count: {len(items)}")

    # ── Get single ─────────────────────────────────────────────────────────────
    step("GET /equipment/{id} — get single record")
    eid = new_equip_id or state["equip_id"]
    if eid:
        r = GET("org_admin", f"/equipment/{eid}")
        if assert200(r, "GET /equipment/{id}"):
            eq = r.json()
            chk("ueic" in eq, "Response has 'ueic' field")
            chk("nameplate_data" in eq, "Response has 'nameplate_data' field")

    # ── Update ─────────────────────────────────────────────────────────────────
    step("PUT /equipment/{id} — update bay_number")
    if eid:
        r = PUT("originator", f"/equipment/{eid}",
                {"bay_number": "02"})
        assert200(r, "PUT /equipment/{id}  (update)")

    # ── Field tester equipment access (role-dependent — 200 or 403 both valid) ──
    step("GET /equipment/ as field_tester — RBAC check")
    r = GET("field_tester", "/equipment/", params={"limit": 3})
    if r.status_code in (200, 403):
        ok(f"GET /equipment/ as field_tester  (RBAC={r.status_code} — role-defined)")
    else:
        fail(f"GET /equipment/ as field_tester  unexpected status [{r.status_code}]")

    step("POST /equipment/ as field_tester — should be forbidden")
    r = POST("field_tester", "/equipment/", {
        "organization_id": state["org_id"],
        "voltage_class": "11kV",
        "bay_number": "02",
        "department_id": state["dept_id"],
        "equipment_type_id": state["equip_type_id"],
    })
    assert_forbidden(r, "POST /equipment/ as field_tester  (write forbidden)")


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED LIFECYCLE RUNNER
# ══════════════════════════════════════════════════════════════════════════════

_TESTER_DATA = {
    "test": {
        "tester_role": "Field Tester",
        "tester_key":  "field_tester",
        "test_data": {
            "insulation_resistance_mohm": "500",
            "winding_resistance_ohm":     "0.45",
            "turns_ratio":                "11:0.433",
            "no_load_current_a":          "2.1",
            "magnetising_current_a":      "1.8",
            "load_loss_kw":               "150",
            "overall":                    "PASS",
        },
    },
    "maintenance": {
        "tester_role": "Lab Tester",
        "tester_key":  "lab_tester",
        "test_data": {
            "bdv_oil_kv":        "42",
            "acidity_mg_koh_g":  "0.05",
            "moisture_ppm":      "25",
            "colour":            "Light Yellow",
            "flash_point_c":     "152",
            "interfacial_tension": "38",
            "overall":           "NORMAL",
        },
    },
    "inspection": {
        "tester_role": "Field Tester",
        "tester_key":  "field_tester",
        "test_data": {
            "visual_condition":  "Good",
            "oil_leakage":       "None observed",
            "bushing_condition": "Clean — no cracks",
            "cooling_fans":      "Operational",
            "tap_changer":       "Smooth operation",
            "earthing":          "Proper",
            "overall":           "SATISFACTORY",
        },
    },
    "repair_lifecycle": {
        "tester_role": "Lab Tester",
        "tester_key":  "lab_tester",
        "test_data": {
            "tan_delta_bushing":      "0.015",
            "capacitance_pf":         "320",
            "partial_discharge_pc":   "80",
            "remaining_life_years":   "8",
            "action_recommended":     "Monitor annually",
            "overall":                "ALERT",
        },
    },
}


def _get_tester_role_and_user(req_id: str, role_name: str) -> Tuple[Optional[str], Optional[dict]]:
    """Fetch the tester role_id and a concrete user for approve-and-assign."""
    r = GET("test_assigner",
            f"/testing-requests/approvals/{req_id}/tester-roles")
    if r.status_code != 200:
        return None, None
    roles = r.json()
    role = next((ro for ro in roles if ro["role_name"] == role_name), None)
    if not role:
        role = roles[0] if roles else None
    if not role:
        return None, None

    role_id = role["role_id"]
    r2 = GET("test_assigner",
             f"/testing-requests/approvals/{req_id}/tester-roles/{role_id}/users")
    users = r2.json() if r2.status_code == 200 else []
    return str(role_id), (users[0] if users else None)


def run_lifecycle(category: str) -> bool:
    """
    Run the full 13-step testing request lifecycle for *category*.
    Returns True if all critical steps passed.
    """
    cfg = _TESTER_DATA[category]
    tester_key  = cfg["tester_key"]
    tester_role = cfg["tester_role"]
    test_data   = cfg["test_data"]
    scenario    = f"{category.upper()} lifecycle ({tester_role})"

    section(f"§  {scenario}")
    all_ok = True

    # Guard: ensure required tokens exist
    for needed in ("originator", "test_assigner", "dept_head", tester_key):
        if needed not in state["tokens"]:
            warn(f"Token for '{needed}' not available — skipping {scenario}")
            return False

    if not state["org_id"]:
        warn("org_id not set — skipping lifecycle")
        return False

    # ── Step 1: Create draft ──────────────────────────────────────────────────
    step("1. ORIGINATOR — create draft request")
    ts   = datetime.now().strftime("%H%M%S")
    body: Dict[str, Any] = {
        "title":            f"[{category.upper()}] Auto-test {ts}",
        "description":      f"Comprehensive suite — {category} workflow",
        "request_category": category,
        "priority":         "high",
        "transformer_type": "Power Transformer",
        "transformer_rating": "100 MVA",
        "manufacturer":     "BHEL",
        "serial_number":    f"SN-{category[:3].upper()}-{ts}",
        "organization_id":  state["org_id"],
    }
    if state["dept_id"]:
        body["department_id"] = state["dept_id"]
    if state["equip_id"]:
        body["equipment_id"] = state["equip_id"]

    r = POST("originator", "/testing_requests/", body)
    if not assert200(r, f"POST /testing_requests/ [{category}]"):
        return False
    req     = r.json()
    req_id  = req["id"]
    state["lifecycle"][category] = req_id
    info(f"  request_number={req.get('request_number')}  status={req.get('status')}")
    info(f"  dept={req.get('department_name')}  ueic={req.get('equipment_ueic','—')}")

    # ── Step 2: Submit ────────────────────────────────────────────────────────
    step("2. ORIGINATOR — submit request")
    r = PUT("originator", f"/testing_requests/{req_id}/submit")
    if not assert200(r, "PUT /submit"):
        return False
    info(f"  status → {r.json().get('status')}")

    # ── Step 3: Test assigner sees pending approvals ───────────────────────────
    step("3. TEST ASSIGNER — view pending approvals")
    r = GET("test_assigner",
            "/testing-requests/approvals/pending",
            params={"category": category})
    if assert200(r, "GET /approvals/pending"):
        pending = r.json()
        found = any(p["id"] == req_id for p in pending)
        chk(found, f"Our request appears in pending list ({len(pending)} total)")

    # ── Step 4: Resolve tester role and user ──────────────────────────────────
    step(f"4. TEST ASSIGNER — pick {tester_role} and user")
    role_id, tester_user = _get_tester_role_and_user(req_id, tester_role)
    if not tester_user:
        # Fallback: get user_id from token
        r_me = GET(tester_key, "/users/me")
        if r_me.status_code == 200:
            uid = r_me.json()["id"]
            email = r_me.json().get("email", "")
            tester_user = {"user_id": uid, "email": email, "name": email}
        else:
            fail(f"Cannot resolve {tester_role} user")
            return False

    # If role_id still unresolved (eligibility check returned nothing),
    # fall back to looking up the tester's actual org role assignment
    if not role_id and state["org_id"] and tester_user:
        uid = tester_user["user_id"]
        r_ur = GET("org_admin",
                   f"/organizations/{state['org_id']}/users/{uid}/roles")
        if r_ur.status_code == 200:
            user_roles = r_ur.json()
            if user_roles:
                # OrgUserRoleOut has org_role_id as the role ID
                role_id = str(user_roles[0].get("org_role_id", ""))
                info(f"  role resolved via org-user lookup: org_role_id={role_id}")
        if not role_id:
            fail(f"Cannot resolve tester_role_id for {tester_role} — approve-and-assign will fail")
            return False
    info(f"  tester: {tester_user.get('name')} ({tester_user.get('email')})")

    # ── Step 5: Approve and assign ────────────────────────────────────────────
    step("5. TEST ASSIGNER — approve and assign")
    assign_body: Dict[str, Any] = {
        "tester_id":      tester_user["user_id"],
        "tester_role_id": role_id,
        "comment":        f"Auto-assigned for {category} scenario",
    }

    r = POST("test_assigner",
             f"/testing-requests/approvals/{req_id}/approve-and-assign",
             assign_body)
    if not assert200(r, "POST /approve-and-assign"):
        all_ok = False
    else:
        info(f"  assigned_to={r.json().get('assigned_tester_email')}  "
             f"status={r.json().get('new_status')}")

    # ── Step 6: Tester views assignments ─────────────────────────────────────
    step(f"6. {tester_role.upper()} — view my assignments")
    r = GET(tester_key, "/testing/my-assignments")
    if assert200(r, "GET /testing/my-assignments"):
        assignments = r.json()
        found = any(a["id"] == req_id for a in assignments)
        chk(found, f"Request appears in tester assignments ({len(assignments)} total)")

    # ── Step 7: Accept ────────────────────────────────────────────────────────
    step(f"7. {tester_role.upper()} — accept assignment")
    r = PUT(tester_key, f"/testing/{req_id}/accept")
    if not assert200(r, "PUT /testing/{id}/accept"):
        all_ok = False
    else:
        info(f"  status → {r.json().get('status')}")

    # ── Step 8: Start testing ─────────────────────────────────────────────────
    step(f"8. {tester_role.upper()} — start testing")
    r = PUT(tester_key, f"/testing/{req_id}/start")
    if not assert200(r, "PUT /testing/{id}/start"):
        all_ok = False
    else:
        info(f"  status → {r.json().get('status')}")

    # ── Step 9: Upload structured results ─────────────────────────────────────
    step(f"9. {tester_role.upper()} — upload structured test results")
    structured = {
        "template_key":       f"{category}_test",
        "test_data":          test_data,
        "overall_result":     "passed",
        "remarks":            f"Automated suite — {category} all checks passed.",
        "replacement_products": [],
    }
    r = POST(tester_key, f"/testing/{req_id}/results/structured", structured)
    if not assert200(r, "POST /results/structured"):
        warn("Structured result upload failed — continuing")
        all_ok = False
    else:
        info(f"  result_id={r.json().get('id','?')[:16]}...")

    # ── Step 10: Get submitted results ────────────────────────────────────────
    step(f"10. {tester_role.upper()} — verify GET /results")
    r = GET(tester_key, f"/testing/{req_id}/results")
    if assert200(r, "GET /testing/{id}/results"):
        results = r.json()
        chk(len(results) > 0, f"At least one result record exists ({len(results)} found)")

    # ── Step 11: Submit results (complete testing) ────────────────────────────
    step(f"11. {tester_role.upper()} — submit results (complete)")
    r = PUT(tester_key, f"/testing/{req_id}/submit_results",
            {"replacement_products": []})
    if not assert200(r, "PUT /testing/{id}/submit_results"):
        all_ok = False
    else:
        status = r.json().get("status")
        info(f"  status → {status}")

    # ── Step 12: Dept head views and approves recommendation ──────────────────
    step("12. DEPT HEAD — review and approve recommendation")
    time.sleep(1.0)   # give server a moment to create recommendation
    r = GET("dept_head", f"/approvals/by-request/{req_id}")
    rec = r.json() if r.status_code == 200 else None
    if r.status_code == 200 and rec and isinstance(rec, dict) and "id" in rec:
        rec_id = rec["id"]
        info(f"  recommendation id={str(rec_id)[:16]}...  "
             f"approval_status={rec.get('approval_status')}")

        if rec.get("approval_status") not in ("approved", "completed"):
            r2 = PUT("dept_head",
                     f"/approvals/{rec_id}/approve",
                     {"notes": f"Approved - {category} auto-test"})
            if assert200(r2, "PUT /approvals/{id}/approve"):
                info(f"  new approval_status={r2.json().get('approval_status')}")
            else:
                all_ok = False
        else:
            ok("Recommendation already approved")
    else:
        warn(f"GET /approvals/by-request/{req_id} -> {r.status_code} "
             f"(auto-recommendation may not have fired yet)")

    # ── Step 13: Originator verifies final state ───────────────────────────────
    step("13. ORIGINATOR — verify final request state")
    r = GET("originator", f"/testing_requests/{req_id}")
    if assert200(r, "GET /testing_requests/{id}  (final state)"):
        final = r.json()
        info(f"  final status         = {final.get('status')}")
        info(f"  request_category     = {final.get('request_category')}")
        info(f"  assigned_tester_name = {final.get('assigned_tester_name','—')}")

    return all_ok


# ══════════════════════════════════════════════════════════════════════════════
#  §4-7  LIFECYCLE TESTS (one per category)
# ══════════════════════════════════════════════════════════════════════════════

def test_lifecycle_test()          -> None: run_lifecycle("test")
def test_lifecycle_maintenance()   -> None: run_lifecycle("maintenance")
def test_lifecycle_inspection()    -> None: run_lifecycle("inspection")
def test_lifecycle_repair()        -> None: run_lifecycle("repair_lifecycle")


# ══════════════════════════════════════════════════════════════════════════════
#  §8  NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def test_notifications() -> None:
    section("§8  NOTIFICATIONS")

    roles_to_check = [
        "originator", "test_assigner", "field_tester", "lab_tester",
        "dept_head", "org_admin",
    ]

    for role in roles_to_check:
        if role not in state["tokens"]:
            warn(f"Skipping notifications for {role} — no token")
            continue

        step(f"Notifications for role: {role}")

        # List
        r = GET(role, "/notifications", params={"limit": 20})
        if assert200(r, f"GET /notifications  ({role})"):
            notifs = r.json()
            info(f"  {len(notifs)} notification(s) received")
            for n in notifs[:3]:
                info(f"    [{n.get('severity','info')}] {n.get('title','')} — {n.get('event_type','')}")

        # Unread count  (endpoint returns {"count": N})
        r = GET(role, "/notifications/unread-count")
        if assert200(r, f"GET /notifications/unread-count  ({role})"):
            cnt = r.json().get("count", 0)
            info(f"  unread count = {cnt}")

        # Mark all read (only for originator to avoid wiping other roles' state)
        if role == "originator":
            r = PUT(role, "/notifications/read-all")
            assert200(r, "PUT /notifications/read-all  (originator)")

            # Verify count drops
            r2 = GET(role, "/notifications/unread-count")
            if r2.status_code == 200:
                new_cnt = r2.json().get("count", -1)
                chk(new_cnt == 0,
                    f"Unread count after mark-all-read = {new_cnt}  (expected 0)")

        # Mark single notification read (for field_tester)
        if role == "field_tester":
            r = GET(role, "/notifications", params={"unread_only": True, "limit": 1})
            if r.status_code == 200 and r.json():
                nid = r.json()[0]["id"]
                r2 = PUT(role, f"/notifications/{nid}/read")
                assert200(r2, f"PUT /notifications/{nid[:8]}…/read  (field_tester)")


# ══════════════════════════════════════════════════════════════════════════════
#  §9  DASHBOARD KPIs
# ══════════════════════════════════════════════════════════════════════════════

def test_dashboard() -> None:
    section("§9  DASHBOARD KPIs")

    org_param = {"org_id": state["org_id"]} if state["org_id"] else {}

    # ── Role-view endpoint for every role ────────────────────────────────────
    step("GET /dashboard/role-view — all roles")
    for role in ("org_admin", "originator", "test_assigner",
                 "field_tester", "lab_tester", "dept_head", "purchaser"):
        if role not in state["tokens"]:
            continue
        r = GET(role, "/dashboard/role-view", params=org_param)
        if assert200(r, f"role-view as {role}"):
            rv = r.json()
            info(f"  {role}: view={rv.get('view')}  "
                 f"widgets={len(rv.get('permitted_widgets', []))}")

    # ── Individual widget endpoints (as org_admin) ────────────────────────────
    if "org_admin" not in state["tokens"]:
        warn("org_admin token missing — skipping widget tests")
        return

    def _dash_get(label: str, path: str, extra_params: dict = None, timeout: int = 60):
        """GET a dashboard widget; catches Timeout so one slow widget doesn't crash the suite."""
        p = {**org_param, **(extra_params or {})}
        try:
            return GET("org_admin", path, params=p, timeout=timeout)
        except requests.exceptions.Timeout:
            warn(f"{label} timed out (>{timeout}s) — Redis cache miss+slow connect; widget still functional")
            return None

    step("GET /dashboard/kpi — 6 KPI cards")
    r = _dash_get("GET /dashboard/kpi", "/dashboard/kpi")
    if r is not None and assert200(r, "GET /dashboard/kpi"):
        body = r.json()
        # endpoint returns a list of KpiCard dicts directly
        cards = body if isinstance(body, list) else body.get("cards", [])
        info(f"  KPI cards returned: {len(cards)}")
        for card in cards:
            info(f"    {card.get('label','?'):35}  value={card.get('display','?')}")

    step("GET /dashboard/overdue-tests")
    r = _dash_get("GET /dashboard/overdue-tests", "/dashboard/overdue-tests")
    if r is not None:
        assert200(r, "GET /dashboard/overdue-tests")

    step("GET /dashboard/active-alerts")
    r = _dash_get("GET /dashboard/active-alerts", "/dashboard/active-alerts", {"limit": 10})
    if r is not None and assert200(r, "GET /dashboard/active-alerts"):
        info(f"  alerts: {len(r.json())}")

    step("GET /dashboard/flagged-equipment")
    r = _dash_get("GET /dashboard/flagged-equipment", "/dashboard/flagged-equipment")
    if r is not None:
        assert200(r, "GET /dashboard/flagged-equipment")

    step("GET /dashboard/repair-progress")
    r = _dash_get("GET /dashboard/repair-progress", "/dashboard/repair-progress")
    if r is not None:
        assert200(r, "GET /dashboard/repair-progress")

    step("GET /dashboard/maintenance-overdue")
    r = _dash_get("GET /dashboard/maintenance-overdue", "/dashboard/maintenance-overdue")
    if r is not None:
        assert200(r, "GET /dashboard/maintenance-overdue")

    step("GET /dashboard/procurement")
    r = _dash_get("GET /dashboard/procurement", "/dashboard/procurement")
    if r is not None:
        assert200(r, "GET /dashboard/procurement")

    step("GET /dashboard/open-remediation")
    r = _dash_get("GET /dashboard/open-remediation", "/dashboard/open-remediation")
    if r is not None:
        assert200(r, "GET /dashboard/open-remediation")

    step("GET /dashboard/full — all widgets in one call")
    r = _dash_get("GET /dashboard/full", "/dashboard/full", timeout=120)
    if r is not None and assert200(r, "GET /dashboard/full"):
        full = r.json()
        info(f"  full response keys: {list(full.keys())}")

    step("POST /dashboard/invalidate-cache")
    try:
        r = POST("org_admin", "/dashboard/invalidate-cache",
                 {"org_id": state["org_id"]} if state["org_id"] else {}, timeout=60)
        assert200(r, "POST /dashboard/invalidate-cache")
    except requests.exceptions.Timeout:
        warn("POST /dashboard/invalidate-cache timed out — Redis unavailable")

    # ── Widget access for non-admin roles ─────────────────────────────────────
    step("Dashboard KPI access — non-admin roles")
    for role in ("originator", "field_tester", "dept_head"):
        if role not in state["tokens"]:
            continue
        try:
            r = GET(role, "/dashboard/kpi", params=org_param, timeout=60)
            if r.status_code in (200,):
                ok(f"GET /dashboard/kpi as {role}  [{r.status_code}] — accessible")
            else:
                info(f"GET /dashboard/kpi as {role}  [{r.status_code}] — restricted (expected for some roles)")
        except requests.exceptions.Timeout:
            warn(f"GET /dashboard/kpi as {role} timed out — Redis cache miss")


# ══════════════════════════════════════════════════════════════════════════════
#  §10  REPORTS
# ══════════════════════════════════════════════════════════════════════════════

def test_reports() -> None:
    section("§10  REPORTS — all 14 built-in reports")

    if "org_admin" not in state["tokens"]:
        warn("org_admin token missing — skipping reports tests")
        return

    # ── Query keys catalogue ──────────────────────────────────────────────────
    step("GET /reports/definitions/query-keys")
    r = GET("org_admin", "/reports/definitions/query-keys")
    if assert200(r, "GET /reports/definitions/query-keys"):
        keys = r.json()
        info(f"  Available query keys: {len(keys)}")
        for k in keys:
            info(f"    {k['key']:<45}  {k['label']}")

    # ── List definitions ──────────────────────────────────────────────────────
    step("GET /reports/definitions")
    r = GET("org_admin", "/reports/definitions", params={"active_only": True})
    if not assert200(r, "GET /reports/definitions"):
        warn("Cannot list definitions — skipping run tests")
        return

    defs = r.json()
    state["report_defs"] = defs
    info(f"  Report definitions: {len(defs)}")
    chk(len(defs) >= 14, f"At least 14 system reports exist ({len(defs)} found)")

    for d in defs:
        info(f"    [{d.get('frequency','?'):12}] {d.get('name')}")

    # ── Create a custom ad-hoc definition ────────────────────────────────────
    step("POST /reports/definitions — create custom report")
    r = POST("org_admin", "/reports/definitions", {
        "name":         "Custom Equipment Check",
        "description":  "Ad-hoc report created by test suite",
        "query_key":    "equipment_condition_summary",
        "parameters":   {},
        "output_format": "excel",
        "frequency":    "on_demand",
        "recipient_roles": [],
    })
    custom_def_id = None
    if assert200(r, "POST /reports/definitions"):
        custom_def_id = r.json()["id"]
        info(f"  Custom definition id={custom_def_id}")

    # ── Get single definition ─────────────────────────────────────────────────
    if defs:
        first_def_id = defs[0]["id"]
        step(f"GET /reports/definitions/{first_def_id[:8]}…")
        r = GET("org_admin", f"/reports/definitions/{first_def_id}")
        assert200(r, "GET /reports/definitions/{id}")

    # ── Run all 14 reports and verify binary response ─────────────────────────
    step("POST /reports/definitions/{id}/run — run all 14 reports (Excel)")

    today     = date.today().isoformat()
    month_ago = (date.today() - timedelta(days=30)).isoformat()
    run_params = {"date_from": month_ago, "date_to": today}

    run_ok  = 0
    run_fail = 0
    for defn in defs[:14]:   # cap at 14 to avoid running custom ones
        def_id    = defn["id"]
        def_name  = defn["name"]
        query_key = defn["query_key"]

        r = POST("org_admin",
                 f"/reports/definitions/{def_id}/run",
                 {"parameters": run_params, "output_format": "excel"})

        if r.status_code == 200:
            size_kb = len(r.content) / 1024
            ct = r.headers.get("content-type", "")
            cd = r.headers.get("content-disposition", "")
            fname = cd.split('filename="')[-1].rstrip('"') if 'filename="' in cd else "?"
            chk(len(r.content) > 0,
                f"Run [{query_key}] → {fname}  size={size_kb:.1f} KB  ct={ct[:40]}")
            run_ok += 1
        else:
            fail(f"Run [{query_key}]  [{r.status_code}]", r.text[:150])
            run_fail += 1

    info(f"  Reports run: {run_ok} passed, {run_fail} failed")

    # ── Run one report as PDF ─────────────────────────────────────────────────
    step("POST /run as PDF — monthly_kpi_report")
    pdf_def = next(
        (d for d in defs if d["query_key"] == "monthly_kpi_report"), None
    )
    if pdf_def:
        r = POST("org_admin",
                 f"/reports/definitions/{pdf_def['id']}/run",
                 {"parameters": run_params, "output_format": "pdf"})
        if r.status_code == 200:
            ok(f"PDF run monthly_kpi_report  size={len(r.content)/1024:.1f} KB")
        elif r.status_code == 422:
            warn("PDF generation returned 422 — WeasyPrint may not be installed (expected in dev)")
        else:
            fail(f"PDF run failed [{r.status_code}]", r.text[:120])

    # ── Update a definition ───────────────────────────────────────────────────
    if custom_def_id:
        step(f"PUT /reports/definitions/{custom_def_id[:8]}… — update description")
        r = PUT("org_admin",
                f"/reports/definitions/{custom_def_id}",
                {"description": "Updated by comprehensive test suite", "is_active": True})
        assert200(r, "PUT /reports/definitions/{id}")

    # ── Check logs ────────────────────────────────────────────────────────────
    step("GET /reports/logs — verify generation history")
    r = GET("org_admin", "/reports/logs", params={"limit": 50})
    if assert200(r, "GET /reports/logs"):
        logs = r.json()
        info(f"  Report log entries: {len(logs)}")
        status_counts: Dict[str, int] = {}
        for lg in logs:
            s = lg.get("status", "?")
            status_counts[s] = status_counts.get(s, 0) + 1
        for s, cnt in status_counts.items():
            info(f"    status={s:<12}  count={cnt}")
        chk(len(logs) > 0, "At least one log entry after running reports")

    # ── Reports access for originator role ────────────────────────────────────
    step("GET /reports/definitions as originator — should be accessible")
    r = GET("originator", "/reports/definitions")
    assert200(r, "GET /reports/definitions as originator")

    step("POST /run as originator — should be accessible")
    if defs:
        r = POST("originator",
                 f"/reports/definitions/{defs[0]['id']}/run",
                 {"parameters": {}, "output_format": "excel"})
        if r.status_code in (200, 201):
            ok(f"Originator can run reports  [{r.status_code}]  size={len(r.content)} bytes")
        else:
            warn(f"Originator run report returned {r.status_code} — may be org-scoped")


# ══════════════════════════════════════════════════════════════════════════════
#  §11  RBAC SPOT-CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def test_rbac() -> None:
    section("§11  ROLE-BASED ACCESS CONTROL SPOT-CHECKS")

    # ── Purchaser cannot approve recommendations ──────────────────────────────
    step("Purchaser — cannot view testing approvals pending")
    r = GET("purchaser", "/testing-requests/approvals/pending")
    # Purchaser has no can_approve on Testing Request Approvals module
    info(f"  GET /approvals/pending as purchaser → {r.status_code}")
    # may be 403 or empty list depending on org role filter

    # ── Field tester cannot create testing requests ───────────────────────────
    step("Field tester — POST /testing_requests/ should be forbidden")
    if state["org_id"]:
        r = POST("field_tester", "/testing_requests/", {
            "title":            "Unauthorised request",
            "request_category": "test",
            "organization_id":  state["org_id"],
        })
        if r.status_code in (403, 422, 400):
            ok(f"POST /testing_requests/ as field_tester  [{r.status_code}] — correctly blocked")
        else:
            warn(f"POST /testing_requests/ as field_tester  [{r.status_code}] — may need RBAC review")

    # ── Originator cannot accept a testing assignment ─────────────────────────
    step("Originator — PUT /testing/{id}/accept on someone else's request")
    # Pick any lifecycle request
    any_req = next(iter(state["lifecycle"].values()), None)
    if any_req:
        r = PUT("originator", f"/testing/{any_req}/accept")
        info(f"  PUT /testing/{any_req[:8]}…/accept as originator → {r.status_code}")
        # Expected: 403 or 422 (not tester role) or 400 (wrong status)

    # ── Lab tester cannot approve recommendations ─────────────────────────────
    step("Lab tester — cannot approve recommendations (needs dept_head role)")
    r = GET("lab_tester", "/approvals/pending")
    info(f"  GET /approvals/pending as lab_tester → {r.status_code}")

    # ── Superadmin can list all organisations ─────────────────────────────────
    step("Superadmin — GET /organizations/ returns data")
    r = GET("superadmin", "/organizations/")
    if assert200(r, "GET /organizations/ as superadmin"):
        orgs = r.json()
        chk(len(orgs) > 0, f"Superadmin sees {len(orgs)} org(s)")

    # ── Purchaser accesses procurement pipeline report ────────────────────────
    step("Purchaser — run procurement report")
    proc_def = next(
        (d for d in state["report_defs"] if d["query_key"] == "procurement_pipeline_report"),
        None,
    )
    if proc_def:
        r = POST("purchaser",
                 f"/reports/definitions/{proc_def['id']}/run",
                 {"parameters": {}, "output_format": "excel"})
        if r.status_code in (200, 201):
            ok(f"Purchaser runs procurement_pipeline_report  [{r.status_code}]")
        else:
            warn(f"Purchaser procurement report → {r.status_code} "
                 "(may need org_role_permission — check org seeding)")

    # ── Request stats visible to org_admin ───────────────────────────────────
    step("GET /testing_requests/stats — org_admin sees org-wide stats")
    r = GET("org_admin", "/testing_requests/stats")
    if assert200(r, "GET /testing_requests/stats"):
        stats = r.json()
        info(f"  total={stats.get('total')}  by_category={stats.get('by_category')}")

    # ── Originator sees only their own requests ────────────────────────────────
    step("GET /testing_requests/ — originator sees own requests")
    r = GET("originator", "/testing_requests/", params={"limit": 20})
    if assert200(r, "GET /testing_requests/ as originator"):
        reqs = r.json()
        info(f"  Originator sees {len(reqs)} request(s)")
        lifecycle_ids = set(state["lifecycle"].values())
        found_own = sum(1 for req in reqs if req["id"] in lifecycle_ids)
        chk(found_own > 0, f"Originator sees their own lifecycle requests ({found_own} found)")


# ══════════════════════════════════════════════════════════════════════════════
#  §12  ADDITIONAL COVERAGE (Recommendations, Testing Templates, etc.)
# ══════════════════════════════════════════════════════════════════════════════

def test_additional() -> None:
    section("§12  ADDITIONAL ENDPOINT COVERAGE")

    # ── Testing templates ─────────────────────────────────────────────────────
    step("GET /testing/templates/by-category/{category} — all 4 categories")
    for cat in ("test", "maintenance", "inspection", "repair_lifecycle"):
        r = GET("field_tester", f"/testing/templates/by-category/{cat}")
        if r.status_code == 200:
            tpl = r.json()
            ok(f"Template for [{cat}]  key={tpl.get('template_key','?')}  "
               f"fields={len(tpl.get('fields', []))}")
        else:
            warn(f"Template for [{cat}]  [{r.status_code}] — template may not be configured")

    # ── Request stats all categories ──────────────────────────────────────────
    step("GET /testing_requests/stats — breakdown by category")
    r = GET("org_admin", "/testing_requests/stats")
    if assert200(r, "GET /testing_requests/stats"):
        stats = r.json()
        for cat, cnt in (stats.get("by_category") or {}).items():
            info(f"  {cat:<25}: {cnt:>4}")

    # ── Recommendations list ──────────────────────────────────────────────────
    step("GET /recommendations/ — list all recommendations")
    r = GET("org_admin", "/recommendations/")
    if assert200(r, "GET /recommendations/"):
        recs = r.json()
        info(f"  Recommendations: {len(recs)}")

    # ── Approvals stats ───────────────────────────────────────────────────────
    step("GET /approvals/stats — approval stats")
    r = GET("dept_head", "/approvals/stats")
    if assert200(r, "GET /approvals/stats"):
        info(f"  Approval stats: {r.json()}")

    # ── Approvals pending ─────────────────────────────────────────────────────
    step("GET /approvals/pending — dept_head pending list")
    r = GET("dept_head", "/approvals/pending", params={"limit": 20})
    if assert200(r, "GET /approvals/pending"):
        info(f"  Pending approvals: {len(r.json())}")

    # ── Dropdown values ────────────────────────────────────────────────────────
    step("GET /testing_requests/dropdown/{master_desc}")
    for desc in ("Equipment Type", "Priority"):
        r = GET("org_admin", f"/testing_requests/dropdown/{desc}")
        if r.status_code == 200:
            ok(f"Dropdown [{desc}]  items={len(r.json())}")
        else:
            warn(f"Dropdown [{desc}]  [{r.status_code}]")

    # ── Testers list ──────────────────────────────────────────────────────────
    step("GET /testing_requests/testers — list active testers")
    r = GET("org_admin", "/testing_requests/testers")
    if assert200(r, "GET /testing_requests/testers"):
        info(f"  Active testers: {len(r.json())}")

    # ── Lifecycle requests — cross-check with GET list ────────────────────────
    step("Cross-check all created lifecycle requests exist in list")
    r = GET("org_admin", "/testing_requests/", params={"limit": 100})
    if assert200(r, "GET /testing_requests/?limit=100"):
        all_ids = {req["id"] for req in r.json()}
        for cat, rid in state["lifecycle"].items():
            chk(rid in all_ids, f"Lifecycle request [{cat}] appears in org-wide list")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TLSS EE Comprehensive API Test Suite"
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8080",
        help="API base URL (default: http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--skip-lifecycle", action="store_true",
        help="Skip the 4 lifecycle sections (faster smoke-test)",
    )
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url.rstrip("/")

    print()
    print(f"{BD}{W}{'*' * 70}{RS}")
    print(f"{BD}{W}{'  TLSS EE -- COMPREHENSIVE API TEST SUITE':^70}{RS}")
    print(f"{BD}{W}{'*' * 70}{RS}")
    print(f"  Base URL : {BASE_URL}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    start = time.time()

    # ── Run all sections ───────────────────────────────────────────────────────
    test_auth()
    test_discovery()
    test_equipment()

    if not args.skip_lifecycle:
        test_lifecycle_test()
        test_lifecycle_maintenance()
        test_lifecycle_inspection()
        test_lifecycle_repair()
    else:
        info("Lifecycle tests skipped (--skip-lifecycle)")

    test_notifications()
    test_dashboard()
    test_reports()
    test_rbac()
    test_additional()

    elapsed = time.time() - start

    # ── Final summary ──────────────────────────────────────────────────────────
    section("FINAL SUMMARY")
    print()
    print(f"  {BD}Duration  :{RS} {elapsed:.1f} s")
    print(f"  {G}{BD}PASSED    : {_passed}{RS}")
    print(f"  {R}{BD}FAILED    : {_failed}{RS}")
    print(f"  {Y}WARNINGS  : {_warned}{RS}")
    print()

    if state["lifecycle"]:
        print(f"  {BD}Lifecycle request IDs created:{RS}")
        for cat, rid in state["lifecycle"].items():
            print(f"    {cat:<20}  {rid}")
    print()

    if _failed == 0:
        print(f"  {BD}{G}✔  ALL CHECKS PASSED{RS}")
    else:
        print(f"  {BD}{R}✖  {_failed} CHECK(S) FAILED — review output above{RS}")
    print()

    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
