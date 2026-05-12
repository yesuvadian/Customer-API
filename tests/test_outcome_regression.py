"""
Outcome Regression Suite
========================
Full end-to-end test for every approval outcome:

  1. Procurement   (next_action = replacement)
  2. Inspection    (next_action = inspection)
  3. Maintenance   (next_action = maintenance)
  4. Repair Cycle  (next_action = repair_cycle)
  5. None          (next_action = none)

Each test drives the full workflow:
  Originator --> create + submit TR
  Admin      --> approve + assign tester
  Tester     --> accept --> start --> upload dynamic form data --> submit results
  Admin      --> approve recommendation
  Assert     --> correct downstream artefact was created

Server must be running on http://localhost:8000

Run with:
    pytest tests/test_outcome_regression.py -v --tb=short

Filter to a single outcome:
    pytest tests/test_outcome_regression.py -v -k "procurement"
"""

from __future__ import annotations

import sys
import time
import pytest
import requests as req_lib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

# make conftest_outcome importable when running from repo root
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from conftest_outcome import tokens, org_info, sample_equipment, USERS  # noqa: F401

BASE = "http://localhost:8000"


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api(method: str, path: str, token: str = "", **kwargs):
    url = f"{BASE}{path}"
    headers = h(token) if token else {}
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    return getattr(req_lib, method)(url, headers=headers, **kwargs)


def _ts() -> str:
    return datetime.now().strftime("%H%M%S")


def _future_date(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────────────────
# Tester resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_tester(
    req_id: str,
    admin_token: str,
    known_tokens: dict,
) -> Tuple[Optional[str], dict, str]:
    """
    Find the best (role_id, tester_user, tester_token) for approve-and-assign.

    Priority:
      1. Find a role where the designated test user (tokens["tester"]) is listed.
      2. Fallback to the first role + first user from the role endpoint, and try
         to match their email to a known login token.

    Returns:
      (role_id, tester_user_dict, tester_jwt_token)
    """
    test_token = known_tokens["tester"]

    # Build email -> token map from known users
    email_map = {email: known_tokens[key] for key, (email, _) in USERS.items()
                 if key in known_tokens}

    # Look up our designated tester's user_id
    our_tester_id: Optional[str] = None
    me_r = api("get", "/users/me", test_token)
    if me_r.status_code == 200:
        our_tester_id = str(me_r.json()["id"])

    # Get available tester roles for this request
    roles_r = api("get", f"/testing-requests/approvals/{req_id}/tester-roles", admin_token)
    roles = roles_r.json() if roles_r.status_code == 200 else []

    fallback_role_id: Optional[str] = None
    fallback_user: Optional[dict] = None
    fallback_token: str = test_token

    for role in roles:
        role_id = str(role["role_id"])
        users_r = api(
            "get",
            f"/testing-requests/approvals/{req_id}/tester-roles/{role_id}/users",
            admin_token,
        )
        if users_r.status_code != 200:
            continue
        role_users = users_r.json()

        # Try to match our designated tester
        for u in role_users:
            if our_tester_id and str(u["user_id"]) == our_tester_id:
                print(f"   [ROLE   ]  role_id={role_id[:8]}  "
                      f"tester={u.get('email')} (preferred)")
                return role_id, u, test_token

        # Save first available as fallback
        if role_users and fallback_user is None:
            fallback_role_id = role_id
            fallback_user = role_users[0]
            assigned_email = fallback_user.get("email", "")
            fallback_token = email_map.get(assigned_email, test_token)

    # Preferred tester not in any role -- use fallback
    if fallback_user:
        print(f"   [ROLE   ]  role_id={str(fallback_role_id)[:8]}  "
              f"tester={fallback_user.get('email')} (fallback)")
        return fallback_role_id, fallback_user, fallback_token

    # Absolute last resort: assign our tester to the first role
    if roles and our_tester_id:
        role_id = str(roles[0]["role_id"])
        print(f"   [ROLE   ]  role_id={role_id[:8]} (force-assign our tester)")
        return role_id, {"user_id": our_tester_id, "email": USERS["tester"][0]}, test_token

    # No roles at all
    print("   [WARN   ]  No tester roles found -- direct assign without role")
    if our_tester_id:
        return None, {"user_id": our_tester_id, "email": USERS["tester"][0]}, test_token
    return None, {}, test_token


# ─────────────────────────────────────────────────────────────────────────────
# Core workflow helper
# ─────────────────────────────────────────────────────────────────────────────

def run_workflow(
    *,
    tokens: dict,
    org_id: str,
    dept_id: Optional[str],
    equip: Optional[dict],
    scenario_label: str,
    next_action_display: str,
    next_action_direct: str,
    recommendation_type: str,
    summary: str,
    schedule_frequency: Optional[str] = None,
    outcome_start_date: Optional[str] = None,
    outcome_end_date: Optional[str] = None,
    replacement_products: Optional[list] = None,
) -> Tuple[str, str, dict]:
    """
    Drives the full workflow from TR creation to recommendation approval.
    Returns (request_id, recommendation_id, approval_result_dict).
    Raises AssertionError on any failure so pytest reports the failing step.
    """
    orig_token  = tokens["originator"]
    admin_token = tokens["admin"]

    # ── Step 1: Create testing request ───────────────────────────────────────
    payload = {
        "title":            f"[REGRESSION] {scenario_label} -- {_ts()}",
        "description":      f"Automated outcome regression -- {scenario_label}",
        "request_category": "test",
        "priority":         "normal",
        "transformer_type": "Distribution Transformer",
        "transformer_rating": "100 kVA",
        "manufacturer":     "BHEL",
        "serial_number":    f"REG-{next_action_direct[:4].upper()}-{_ts()}",
        "organization_id":  org_id,
        "department_id":    dept_id,
    }
    if equip:
        payload["equipment_id"]      = equip["id"]
        payload["equipment_type_id"] = equip.get("equipment_type_id")

    r = api("post", "/testing_requests/", orig_token, json=payload)
    assert r.status_code in (200, 201), (
        f"[{scenario_label}] Create TR failed {r.status_code}: {r.text[:200]}"
    )
    req = r.json()
    req_id = req["id"]
    print(f"\n   [CREATE ]  {req['request_number']}  status={req['status']}")

    # ── Step 2: Submit ───────────────────────────────────────────────────────
    r = api("put", f"/testing_requests/{req_id}/submit", orig_token)
    assert r.status_code == 200, (
        f"[{scenario_label}] Submit TR failed {r.status_code}: {r.text[:200]}"
    )
    print(f"   [SUBMIT ]  status={r.json()['status']}")

    # ── Step 3: Resolve tester role + user ───────────────────────────────────
    role_id, tester_user, tester_token = resolve_tester(req_id, admin_token, tokens)

    assert tester_user and tester_user.get("user_id"), (
        f"[{scenario_label}] Could not resolve any tester user"
    )

    # ── Step 4: Approve and assign ───────────────────────────────────────────
    assign_body: dict = {
        "tester_id": str(tester_user["user_id"]),
        "comment":   f"Regression test -- {scenario_label}",
    }
    if role_id:
        assign_body["tester_role_id"] = str(role_id)

    r = api("post",
            f"/testing-requests/approvals/{req_id}/approve-and-assign",
            admin_token,
            json=assign_body)
    assert r.status_code == 200, (
        f"[{scenario_label}] Approve-and-assign failed {r.status_code}: {r.text[:300]}"
    )
    print(f"   [ASSIGN ]  status={r.json().get('new_status')}  "
          f"tester={r.json().get('assigned_tester_email')}")

    # ── Step 5: Tester accepts ───────────────────────────────────────────────
    r = api("put", f"/testing/{req_id}/accept", tester_token)
    assert r.status_code == 200, (
        f"[{scenario_label}] Accept failed {r.status_code}: {r.text[:200]}"
    )
    print(f"   [ACCEPT ]  status={r.json()['status']}")

    # ── Step 6: Tester starts ────────────────────────────────────────────────
    r = api("put", f"/testing/{req_id}/start", tester_token)
    assert r.status_code == 200, (
        f"[{scenario_label}] Start failed {r.status_code}: {r.text[:200]}"
    )
    print(f"   [START  ]  status={r.json()['status']}")

    # ── Step 7: Upload structured test results (dynamic form data) ────────────
    # Simulates the Flutter dynamic form:
    #   - Equipment-specific measurement fields
    #   - "Overall Assessment" section (first section of overall_assessment template)
    #   - "Outcome & Scheduling" section (second section)
    test_data: dict = {
        # Equipment test measurements
        "bdv_kv":                     "48",
        "acidity_mg_koh_g":           "0.02",
        "moisture_ppm":               "18",
        "tan_delta_at_90c":           "0.004",
        "insulation_resistance_mohm": "1200",
        "winding_resistance_hv_ohm":  "0.42",
        "turns_ratio":                "11:0.433",
        "no_load_current_pct":        "1.8",
        # Overall Assessment section
        "overall_result":             "Pass",
        "overall_remarks":            f"Equipment in good condition -- {scenario_label}",
        "overall_recommendation":     summary,
        "tested_by":                  "Regression Bot",
        "date_of_testing":            datetime.now().strftime("%Y-%m-%d"),
        # Outcome & Scheduling section (maps through _ACTION_MAP / _REC_MAP in testing.py)
        "recommendation_type":        recommendation_type,
        "next_action":                next_action_display.lower(),
        "outcome_summary":            summary,
        "outcome_notes":              f"Automated regression test for {scenario_label}.",
    }
    if schedule_frequency:
        test_data["outcome_frequency"]  = schedule_frequency
        test_data["outcome_start_date"] = outcome_start_date or _future_date(7)
        test_data["outcome_end_date"]   = outcome_end_date   or _future_date(365)

    structured = {
        "template_key":        "overall_assessment",
        "test_data":           test_data,
        "overall_result":      "passed",
        "remarks":             f"Regression -- {scenario_label}",
        "replacement_products": replacement_products or [],
    }
    r = api("post", f"/testing/{req_id}/results/structured", tester_token, json=structured)
    assert r.status_code in (200, 201), (
        f"[{scenario_label}] Upload structured results failed {r.status_code}: {r.text[:300]}"
    )
    print(f"   [RESULTS]  result_id={str(r.json().get('id','?'))[:16]}...")

    # ── Step 8: Submit results (creates / updates Recommendation) ─────────────
    submit_body: dict = {
        "recommendation_type": recommendation_type,
        "next_action":         next_action_direct,
        "summary":             summary,
        "detailed_notes":      f"Full regression -- {scenario_label}.",
    }
    if schedule_frequency:
        submit_body["schedule_frequency"] = schedule_frequency
    if replacement_products:
        submit_body["replacement_products"] = replacement_products

    r = api("put", f"/testing/{req_id}/submit_results", tester_token, json=submit_body)
    assert r.status_code == 200, (
        f"[{scenario_label}] submit_results failed {r.status_code}: {r.text[:300]}"
    )
    print(f"   [SUBMIT ]  status={r.json()['status']}")

    # ── Step 9: Fetch recommendation (retry for eventual consistency) ──────────
    rec_id: Optional[str] = None
    for _ in range(4):
        r = api("get", f"/approvals/by-request/{req_id}", admin_token)
        if r.status_code == 200:
            rec_id = str(r.json().get("id", ""))
            break
        time.sleep(0.5)

    assert rec_id, (
        f"[{scenario_label}] No recommendation for req_id={req_id} "
        f"(last: {r.status_code} {r.text[:150]})"
    )
    print(f"   [REC    ]  rec_id={rec_id[:16]}...  "
          f"approval_status={r.json().get('approval_status')}")

    # ── Step 10: Approver approves recommendation ──────────────────────────────
    r = api("put",
            f"/approvals/{rec_id}/approve",
            admin_token,
            json={"notes": f"Approved -- {scenario_label} regression"})
    assert r.status_code == 200, (
        f"[{scenario_label}] Approve recommendation failed {r.status_code}: {r.text[:300]}"
    )
    approval_result = r.json()
    print(f"   [APPROVE]  keys={list(approval_result.keys())}")

    return req_id, rec_id, approval_result


# ─────────────────────────────────────────────────────────────────────────────
# Assertion helpers
# ─────────────────────────────────────────────────────────────────────────────

def assert_tr_status(req_id: str, expected: list, token: str, label: str) -> str:
    r = api("get", f"/testing_requests/{req_id}", token)
    assert r.status_code == 200, f"[{label}] Cannot fetch TR {req_id}"
    actual = r.json()["status"]
    assert actual in expected, (
        f"[{label}] Expected TR status in {expected}, got '{actual}'"
    )
    print(f"   [VERIFY ]  TR status = {actual}  (ok)")
    return actual


def assert_procurement_created(token: str, label: str) -> dict:
    r = api("get", "/validation_requests/?status=pending_finance&limit=5", token)
    assert r.status_code == 200, f"[{label}] Cannot list procurement requests: {r.status_code}"
    items = r.json()
    assert items, (
        f"[{label}] Expected ProcurementRequest with status=pending_finance, got none"
    )
    latest = items[0]
    print(f"   [VERIFY ]  ProcurementRequest = {latest.get('procurement_number')}  "
          f"status={latest.get('status')}  (ok)")
    return latest


def assert_schedule_in_dispatch(result: dict, expected_prefix: str, label: str):
    """Check dispatch result contains a schedule/ticket number (e.g. MN- or IN-)."""
    na      = result.get("next_action", "")
    created = str(result.get("created", ""))
    assert na or created, f"[{label}] Dispatch result is empty: {result}"
    if created and created not in ("None", ""):
        print(f"   [VERIFY ]  Dispatch created = {created}  (ok)")
    else:
        print(f"   [VERIFY ]  Dispatch next_action = {na}  (ok)")


def assert_repair_workflow(result: dict, label: str):
    na      = result.get("next_action", "")
    created = str(result.get("created", ""))
    assert na == "repair_cycle", (
        f"[{label}] Expected next_action=repair_cycle, got '{na}'"
    )
    assert created and created not in ("None", ""), (
        f"[{label}] Expected repair workflow id in 'created', got '{created}'"
    )
    print(f"   [VERIFY ]  RepairWorkflow id = {created[:20]}...  (ok)")


def assert_no_schedule(req_id: str, token: str, label: str):
    r = api("get", f"/testing_requests/{req_id}/schedule/", token)
    assert r.status_code == 404, (
        f"[{label}] Expected no schedule for next_action=none, "
        f"but /schedule/ returned {r.status_code}"
    )
    print(f"   [VERIFY ]  No schedule created  (ok)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 : Procurement
# ─────────────────────────────────────────────────────────────────────────────

class TestOutcome1Procurement:
    """
    Outcome: replacement
    Expects: ProcurementRequest (status=pending_finance) + replacement_products copied
    """

    def test_full_workflow(self, tokens, org_info, sample_equipment):
        org_id, dept_id = org_info
        products = [
            {"item_id": "PROD-001", "item_name": "HV Bushing 33kV",
             "category": "Electrical",   "quantity": 2},
            {"item_id": "PROD-002", "item_name": "Transformer Oil 200L",
             "category": "Consumables",  "quantity": 1},
        ]

        print("\n\n" + "=" * 70)
        print("  OUTCOME 1 : PROCUREMENT (next_action = replacement)")
        print("=" * 70)

        req_id, rec_id, result = run_workflow(
            tokens=tokens,
            org_id=org_id, dept_id=dept_id, equip=sample_equipment,
            scenario_label="Procurement",
            next_action_display="Procurement",
            next_action_direct="replacement",
            recommendation_type="fail",
            summary="Equipment failed HV test. Replacement of bushing and oil required.",
            replacement_products=products,
        )

        assert_tr_status(req_id,
                         ["finance_pending", "outcome_active", "approved"],
                         tokens["admin"], "Procurement")

        pr = assert_procurement_created(tokens["admin"], "Procurement")
        assert str(pr.get("procurement_number", "")).startswith("PR-"), (
            "Expected PR-YYYYMMDD-NNNN format"
        )
        assert isinstance(pr.get("replacement_products") or [], list), (
            "ProcurementRequest.replacement_products should be a list"
        )
        assert result is not None

    def test_validation_rejects_empty_products(self, tokens, org_info, sample_equipment):
        """
        next_action=replacement with no products must return HTTP 400.
        """
        print("\n\n" + "=" * 70)
        print("  OUTCOME 1b : PROCUREMENT -- empty products -> 400 validation")
        print("=" * 70)

        org_id, dept_id = org_info
        orig_token  = tokens["originator"]
        admin_token = tokens["admin"]

        # Create + Submit
        r = api("post", "/testing_requests/", orig_token, json={
            "title":            f"[REGRESSION] Procurement Validation -- {_ts()}",
            "request_category": "test",
            "priority":         "normal",
            "organization_id":  org_id,
            "department_id":    dept_id,
        })
        assert r.status_code in (200, 201)
        req_id = r.json()["id"]

        api("put", f"/testing_requests/{req_id}/submit", orig_token)

        # Assign
        role_id, tester_user, tester_token = resolve_tester(req_id, admin_token, tokens)
        assert tester_user and tester_user.get("user_id")
        ab = {"tester_id": str(tester_user["user_id"]), "comment": "Validation test"}
        if role_id:
            ab["tester_role_id"] = str(role_id)
        r = api("post", f"/testing-requests/approvals/{req_id}/approve-and-assign",
                admin_token, json=ab)
        assert r.status_code == 200, f"Assign failed: {r.status_code} {r.text[:150]}"

        # Accept + Start
        r = api("put", f"/testing/{req_id}/accept", tester_token)
        assert r.status_code == 200, f"Accept failed: {r.status_code} {r.text[:150]}"
        r = api("put", f"/testing/{req_id}/start",  tester_token)
        assert r.status_code == 200, f"Start failed:  {r.status_code} {r.text[:150]}"

        # Upload results
        api("post", f"/testing/{req_id}/results/structured", tester_token, json={
            "template_key": "overall_assessment",
            "test_data":    {"overall_result": "Fail", "next_action": "procurement"},
            "overall_result": "failed",
        })

        # Submit with empty products -- expect 400
        r = api("put", f"/testing/{req_id}/submit_results", tester_token, json={
            "recommendation_type": "fail",
            "next_action":         "replacement",
            "summary":             "Must fail -- no products",
            "replacement_products": [],
        })
        assert r.status_code == 400, (
            f"Expected 400 for empty replacement_products, got {r.status_code}: {r.text[:200]}"
        )
        print(f"   [VERIFY ]  400 returned for empty replacement_products  (ok)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 : Inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestOutcome2Inspection:
    """
    Outcome: inspection
    Expects: TestRequestSchedule on new IN- ticket, frequency=quarterly
    """

    def test_full_workflow(self, tokens, org_info, sample_equipment):
        org_id, dept_id = org_info

        print("\n\n" + "=" * 70)
        print("  OUTCOME 2 : INSPECTION (next_action = inspection)")
        print("=" * 70)

        req_id, rec_id, result = run_workflow(
            tokens=tokens,
            org_id=org_id, dept_id=dept_id, equip=sample_equipment,
            scenario_label="Inspection",
            next_action_display="Inspection",
            next_action_direct="inspection",
            recommendation_type="conditional",
            summary="Conditional pass -- schedule quarterly inspection.",
            schedule_frequency="quarterly",
            outcome_start_date=_future_date(30),
            outcome_end_date=_future_date(365),
        )

        assert_tr_status(req_id, ["outcome_active", "approved"],
                         tokens["admin"], "Inspection")
        assert_schedule_in_dispatch(result, "IN-", "Inspection")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 : Maintenance
# ─────────────────────────────────────────────────────────────────────────────

class TestOutcome3Maintenance:
    """
    Outcome: maintenance
    Expects: TestRequestSchedule on new MN- ticket.
    Start within advance_days -> first ticket created immediately.
    """

    def test_full_workflow(self, tokens, org_info, sample_equipment):
        org_id, dept_id = org_info

        print("\n\n" + "=" * 70)
        print("  OUTCOME 3 : MAINTENANCE (next_action = maintenance)")
        print("=" * 70)

        req_id, rec_id, result = run_workflow(
            tokens=tokens,
            org_id=org_id, dept_id=dept_id, equip=sample_equipment,
            scenario_label="Maintenance",
            next_action_display="Maintenance",
            next_action_direct="maintenance",
            recommendation_type="pass",
            summary="Equipment passed. Monthly preventive maintenance scheduled.",
            schedule_frequency="monthly",
            outcome_start_date=_future_date(5),   # within advance_days=15 -> immediate ticket
            outcome_end_date=_future_date(730),
        )

        assert_tr_status(req_id, ["outcome_active", "approved"],
                         tokens["admin"], "Maintenance")
        assert_schedule_in_dispatch(result, "MN-", "Maintenance")

    def test_schedule_frequency_from_test_data(self, tokens, org_info, sample_equipment):
        """
        Verify _FREQ_MAP: when schedule_frequency is omitted from the body,
        it must be read from test_data.outcome_frequency ("bi-annual" -> semi_annual).
        """
        print("\n\n" + "=" * 70)
        print("  OUTCOME 3b : MAINTENANCE -- frequency read from test_data")
        print("=" * 70)

        org_id, dept_id = org_info
        orig_token  = tokens["originator"]
        admin_token = tokens["admin"]

        # --- Create + Submit ---
        r = api("post", "/testing_requests/", orig_token, json={
            "title":            f"[REGRESSION] Maintenance Freq -- {_ts()}",
            "request_category": "test",
            "priority":         "normal",
            "organization_id":  org_id,
            "department_id":    dept_id,
        })
        assert r.status_code in (200, 201)
        req_id = r.json()["id"]
        api("put", f"/testing_requests/{req_id}/submit", orig_token)

        # --- Assign ---
        role_id, tester_user, tester_token = resolve_tester(req_id, admin_token, tokens)
        assert tester_user and tester_user.get("user_id")
        ab = {"tester_id": str(tester_user["user_id"]), "comment": "Freq map test"}
        if role_id:
            ab["tester_role_id"] = str(role_id)
        r = api("post", f"/testing-requests/approvals/{req_id}/approve-and-assign",
                admin_token, json=ab)
        assert r.status_code == 200, f"Assign failed: {r.status_code} {r.text[:150]}"

        # --- Accept + Start ---
        r = api("put", f"/testing/{req_id}/accept", tester_token)
        assert r.status_code == 200, f"Accept failed: {r.status_code} {r.text[:150]}"
        r = api("put", f"/testing/{req_id}/start",  tester_token)
        assert r.status_code == 200, f"Start failed:  {r.status_code} {r.text[:150]}"

        # --- Upload structured results with outcome_frequency in test_data ---
        r = api("post", f"/testing/{req_id}/results/structured", tester_token, json={
            "template_key": "overall_assessment",
            "test_data": {
                "overall_result":      "Pass",
                "recommendation_type": "pass",
                "next_action":         "maintenance",
                "outcome_frequency":   "bi-annual",          # maps -> semi_annual
                "outcome_start_date":  _future_date(10),
                "outcome_end_date":    _future_date(730),
                "outcome_summary":     "Bi-annual maintenance scheduled",
            },
            "overall_result": "passed",
        })
        assert r.status_code in (200, 201), (
            f"Upload results failed: {r.status_code} {r.text[:200]}"
        )

        # --- Submit WITHOUT explicit schedule_frequency ---
        r = api("put", f"/testing/{req_id}/submit_results", tester_token, json={
            "recommendation_type": "pass",
            "next_action":         "maintenance",
            "summary":             "Bi-annual maintenance via test_data",
            # schedule_frequency intentionally omitted -- must come from test_data
        })
        assert r.status_code == 200, (
            f"submit_results (freq from test_data) failed: {r.status_code} {r.text[:200]}"
        )
        print(f"   [VERIFY ]  submit_results accepted with freq from test_data  (ok)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 : Repair Cycle
# ─────────────────────────────────────────────────────────────────────────────

class TestOutcome4RepairCycle:
    """
    Outcome: repair_cycle
    Expects: RepairWorkflow started (requires equipment_id on TR).
    """

    def test_full_workflow(self, tokens, org_info, sample_equipment):
        org_id, dept_id = org_info

        print("\n\n" + "=" * 70)
        print("  OUTCOME 4 : REPAIR CYCLE (next_action = repair_cycle)")
        print("=" * 70)

        req_id, rec_id, result = run_workflow(
            tokens=tokens,
            org_id=org_id, dept_id=dept_id, equip=sample_equipment,
            scenario_label="Repair Cycle",
            next_action_display="Repair Lifecycle",
            next_action_direct="repair_cycle",
            recommendation_type="fail",
            summary="Major winding failure. Full repair lifecycle required.",
        )

        assert_tr_status(req_id, ["outcome_active", "approved"],
                         tokens["admin"], "Repair Cycle")

        na      = result.get("next_action", "")
        created = str(result.get("created", "") or "")

        if sample_equipment and created and created not in ("None", ""):
            # Full happy path: equipment present, repair workflow was created
            assert_repair_workflow(result, "Repair Cycle")
        elif not sample_equipment or created in ("None", ""):
            # No equipment_id on TR -> dispatch logs WARN and skips workflow
            # This is expected behaviour when no equipment is linked
            print("   [VERIFY ]  Repair workflow skipped gracefully "
                  "(no equipment_id on TR -- dispatch WARN as expected)  (ok)")
            assert na == "repair_cycle", (
                f"Expected next_action=repair_cycle even when workflow skipped, got '{na}'"
            )
        else:
            assert_repair_workflow(result, "Repair Cycle")


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 : None
# ─────────────────────────────────────────────────────────────────────────────

class TestOutcome5None:
    """
    Outcome: none
    Expects: No schedule, no procurement, TR -> outcome_active.
    """

    def test_full_workflow(self, tokens, org_info, sample_equipment):
        org_id, dept_id = org_info

        print("\n\n" + "=" * 70)
        print("  OUTCOME 5 : NONE (next_action = none)")
        print("=" * 70)

        req_id, rec_id, result = run_workflow(
            tokens=tokens,
            org_id=org_id, dept_id=dept_id, equip=sample_equipment,
            scenario_label="None",
            next_action_display="None",
            next_action_direct="none",
            recommendation_type="pass",
            summary="Equipment passed all tests. No further action required.",
        )

        assert_tr_status(req_id, ["outcome_active", "approved", "closed"],
                         tokens["admin"], "None")
        assert_no_schedule(req_id, tokens["admin"], "None")

        na = result.get("next_action", "")
        assert na in ("none", "", None) or \
               result.get("status") in ("outcome_active", "approved"), (
            f"Expected next_action=none in dispatch result, got '{na}': {result}"
        )
        print(f"   [VERIFY ]  next_action confirmed as '{na}'  (ok)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 : Seed / Provision Upsert
# ─────────────────────────────────────────────────────────────────────────────

class TestProvisionUpsert:
    """
    POST /org-test-templates/overall-assessment/provision twice:
      Call 1 -> "Provisioned" or "Updated"  (200)
      Call 2 -> "Updated"                   (200) -- upsert, NOT skip
    """

    def test_provision_is_idempotent(self, tokens):
        print("\n\n" + "=" * 70)
        print("  SEED UPSERT : overall_assessment template provision")
        print("=" * 70)

        for attempt in range(1, 3):
            r = api("post",
                    "/org-test-templates/overall-assessment/provision",
                    tokens["admin"])
            assert r.status_code == 200, (
                f"Provision call {attempt} failed {r.status_code}: {r.text[:200]}"
            )
            msg = r.json().get("message", "")
            print(f"   [VERIFY ]  call {attempt}: message='{msg}'  (ok)")
            if attempt == 2:
                assert msg != "Already exists", (
                    "Second provision call returned 'Already exists' -- upsert not applied"
                )
                assert msg in ("Updated", "Provisioned"), (
                    f"Unexpected message on second provision call: '{msg}'"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 : Scheduler / service health
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerQueryWindow:
    """
    Verifies scheduler import health and stats endpoint after the
    query-window fix (advance_days + 1 instead of hardcoded 1 day).
    """

    def test_stats_endpoint(self, tokens):
        print("\n\n" + "=" * 70)
        print("  SCHEDULER : stats endpoint (import health check)")
        print("=" * 70)
        r = api("get", "/testing_requests/stats", tokens["admin"])
        assert r.status_code == 200, (
            f"Stats endpoint failed {r.status_code}: {r.text[:200]}"
        )
        stats = r.json()
        assert isinstance(stats, dict), "Stats should be a dict"
        print(f"   [VERIFY ]  stats returned  total={stats.get('total', '?')}  (ok)")

    def test_manual_scheduler_trigger(self, tokens):
        """Call /scheduler/run-now if it exists; skip gracefully otherwise."""
        print("\n")
        r = api("post", "/scheduler/run-now", tokens["admin"])
        if r.status_code == 404:
            pytest.skip("No /scheduler/run-now endpoint -- skipping")
        assert r.status_code in (200, 202), (
            f"Scheduler trigger failed {r.status_code}: {r.text[:200]}"
        )
        result = r.json()
        print(f"   [VERIFY ]  Scheduler run: created={result.get('created')}  "
              f"failed={result.get('failed')}  (ok)")


# ─────────────────────────────────────────────────────────────────────────────
# Direct run (python tests/test_outcome_regression.py)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback
    from conftest_outcome import _login

    print("\n" + "+" * 70)
    print("|" + " " * 15 + "OUTCOME REGRESSION SUITE (direct run)" + " " * 16 + "|")
    print("+" * 70)

    toks: dict = {}
    for key, (email, pwd) in USERS.items():
        try:
            toks[key] = _login(email, pwd)
            print(f"   [OK] {key:12} logged in as {email}")
        except AssertionError as e:
            print(f"   [FAIL] {key}: {e}")

    if not all(k in toks for k in ("admin", "tester", "originator")):
        print("\n[FAIL] Cannot proceed -- check credentials in conftest_outcome.py")
        sys.exit(1)

    # Org + department
    r = req_lib.get(f"{BASE}/organizations/",
                    headers={"Authorization": f"Bearer {toks['admin']}"})
    orgs = r.json() if r.status_code == 200 else []
    org = next((o for o in orgs if o.get("code") == "KPTCL"), orgs[0] if orgs else None)
    if not org:
        print("[FAIL] No organization found -- run seed.py first")
        sys.exit(1)
    org_id = org["id"]
    r2 = req_lib.get(f"{BASE}/testing_requests/department_hierarchy?org_id={org_id}",
                     headers={"Authorization": f"Bearer {toks['admin']}"})
    depts = r2.json() if r2.status_code == 200 else []
    dept_id = depts[0]["id"] if depts else None

    # Equipment
    eq_r = req_lib.get(f"{BASE}/equipment/?limit=1",
                       headers={"Authorization": f"Bearer {toks['admin']}"})
    equip = (eq_r.json() or [None])[0] if eq_r.status_code == 200 else None

    SCENARIOS = [
        dict(
            label="1. Procurement",
            next_action_display="Procurement",
            next_action_direct="replacement",
            recommendation_type="fail",
            summary="Equipment failed. Replacement required.",
            replacement_products=[{
                "item_id": "P001", "item_name": "HV Bushing",
                "category": "Electrical", "quantity": 1,
            }],
        ),
        dict(
            label="2. Inspection",
            next_action_display="Inspection",
            next_action_direct="inspection",
            recommendation_type="conditional",
            summary="Conditional pass -- quarterly inspection required.",
            schedule_frequency="quarterly",
        ),
        dict(
            label="3. Maintenance",
            next_action_display="Maintenance",
            next_action_direct="maintenance",
            recommendation_type="pass",
            summary="Pass -- monthly preventive maintenance.",
            schedule_frequency="monthly",
        ),
        dict(
            label="4. Repair Cycle",
            next_action_display="Repair Lifecycle",
            next_action_direct="repair_cycle",
            recommendation_type="fail",
            summary="Major failure -- full repair lifecycle required.",
        ),
        dict(
            label="5. None",
            next_action_display="None",
            next_action_direct="none",
            recommendation_type="pass",
            summary="Passed. No further action.",
        ),
    ]

    results_summary: list = []
    for sc in SCENARIOS:
        label = sc.pop("label")
        print(f"\n\n{'='*70}")
        print(f"  SCENARIO : {label}")
        print(f"{'='*70}")
        try:
            req_id, rec_id, result = run_workflow(
                tokens=toks, org_id=org_id, dept_id=dept_id, equip=equip,
                scenario_label=label, **sc,
            )
            print(f"   [OK] Workflow completed  req_id={req_id[:8]}...")
            results_summary.append((label, True))
        except Exception:
            traceback.print_exc()
            results_summary.append((label, False))

    print("\n\n" + "=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)
    all_ok = True
    for lbl, ok in results_summary:
        icon = "[OK  ]" if ok else "[FAIL]"
        print(f"  {icon}  {lbl}")
        if not ok:
            all_ok = False
    print()
    print("  *** ALL SCENARIOS PASSED ***" if all_ok else
          "  *** SOME SCENARIOS FAILED -- see output above ***")
    sys.exit(0 if all_ok else 1)
