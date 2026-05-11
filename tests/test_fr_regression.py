"""
Failure Register (FR) Regression Suite
=======================================
Comprehensive API regression tests for the Failure Register module.

Covers:
  A. FR Submission  -- POST/GET /direct-submissions/
  B. FR Attachment  -- POST/GET /direct-submissions/{id}/attach
  C. Pass-1 Approval -- POST /testing-requests/approvals/{id}/initial-approve
  D. Pass-2 Assign   -- POST /testing-requests/approvals/{id}/approve-and-assign
  E. FR Rejection    -- POST /testing-requests/approvals/{id}/reject
  F. All 6 Outcomes  -- full workflow -> recommendation -> approve
       1. Test        (next_action=test)
       2. Procurement (next_action=replacement)
       3. Repair      (next_action=repair_cycle)
       4. Inspection  (next_action=inspection)
       5. Maintenance (next_action=maintenance)
       6. None        (next_action=none)
  G. Negative Cases  -- auth, validation, wrong-state errors

Server must be running on http://localhost:8000

Run all:
    pytest tests/test_fr_regression.py -v --tb=short

Run one group:
    pytest tests/test_fr_regression.py -v -k "Outcome"
    pytest tests/test_fr_regression.py -v -k "Negative"
"""

from __future__ import annotations

import io
import sys
import time
import pytest
import requests as req_lib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from conftest_outcome import tokens, org_info, sample_equipment, USERS  # noqa: F401

BASE = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api(method: str, path: str, token: str = "", **kwargs):
    url = f"{BASE}{path}"
    headers = h(token) if token else {}
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    return getattr(req_lib, method)(url, headers=headers, **kwargs)


def _ts() -> str:
    return datetime.now().strftime("%H%M%S%f")[:10]


def _future(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# FR creation helper
# ---------------------------------------------------------------------------

def create_fr(
    token: str,
    org_id: str,
    dept_id: Optional[str] = None,
    equip_id: Optional[str] = None,
    *,
    title: Optional[str] = None,
    priority: str = "normal",
    extra_test_data: Optional[dict] = None,
) -> dict:
    """
    POST /direct-submissions/ with category=failure_registry.
    Returns the 201 response dict.
    """
    test_data = {
        "failure_date":            _today_str(),
        "failure_category":        "Electrical",
        "failure_description":     "Insulation breakdown detected during patrol",
        "root_cause_analysis":     "Age-related degradation of HV bushing",
        "outage_duration_hours":   4,
        "affected_consumers":      120,
        "outage_impact":           "Partial supply disruption to residential zone",
        "outcome":                 "Under investigation",
    }
    if extra_test_data:
        test_data.update(extra_test_data)

    body = {
        "request_category": "failure_registry",
        "template_key":     "failure_registry",
        "title":            title or f"[FR-REG] Insulation Failure -- {_ts()}",
        "test_data":        test_data,
        "organization_id":  org_id,
        "overall_result":   "fail",
        "remarks":          "Urgent attention required",
        "priority":         priority,
    }
    if dept_id:
        body["department_id"] = dept_id
    if equip_id:
        body["equipment_id"] = equip_id

    r = api("post", "/direct-submissions/", token, json=body)
    return r


def _initial_approve(fr_id: str, token: str):
    return api("post", f"/testing-requests/approvals/{fr_id}/initial-approve", token)


def _reject(req_id: str, token: str, comment: str = "Not enough information provided"):
    return api(
        "post",
        f"/testing-requests/approvals/{req_id}/reject",
        token,
        json={"rejection_comment": comment},
    )


# ---------------------------------------------------------------------------
# Tester resolution (reused from outcome regression suite)
# ---------------------------------------------------------------------------

def resolve_tester(
    req_id: str,
    admin_token: str,
    known_tokens: dict,
) -> Tuple[Optional[str], dict, str]:
    test_token = known_tokens["tester"]
    email_map = {
        email: known_tokens[key]
        for key, (email, _) in USERS.items()
        if key in known_tokens
    }
    our_tester_id: Optional[str] = None
    me_r = api("get", "/users/me", test_token)
    if me_r.status_code == 200:
        our_tester_id = str(me_r.json()["id"])

    roles_r = api(
        "get",
        f"/testing-requests/approvals/{req_id}/tester-roles",
        admin_token,
    )
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
        for u in role_users:
            if our_tester_id and str(u["user_id"]) == our_tester_id:
                return role_id, u, test_token
        if role_users and fallback_user is None:
            fallback_role_id = role_id
            fallback_user = role_users[0]
            fallback_token = email_map.get(fallback_user.get("email", ""), test_token)

    if fallback_user:
        return fallback_role_id, fallback_user, fallback_token
    if roles and our_tester_id:
        role_id = str(roles[0]["role_id"])
        return role_id, {"user_id": our_tester_id, "email": USERS["tester"][0]}, test_token
    if our_tester_id:
        return None, {"user_id": our_tester_id, "email": USERS["tester"][0]}, test_token
    return None, {}, test_token


# ---------------------------------------------------------------------------
# Full FR workflow helper (FR -> initial-approve -> assign -> test -> outcome)
# ---------------------------------------------------------------------------

def run_fr_workflow(
    *,
    tokens: dict,
    org_id: str,
    dept_id: Optional[str],
    equip: Optional[dict],
    label: str,
    next_action_display: str,   # as sent in form test_data (display label)
    next_action_direct: str,    # enum value for direct body field
    recommendation_type: str = "fail",
    summary: str = "FR regression outcome test",
    schedule_frequency: Optional[str] = None,
    outcome_start_date: Optional[str] = None,
    outcome_end_date: Optional[str] = None,
    replacement_products: Optional[list] = None,
) -> Tuple[str, str, dict]:
    """
    Drives the full FR lifecycle:
      1. Create FR (direct submission)
      2. Pass-1: initial-approve -> child TR created
      3. Pass-2: approve-and-assign child TR to tester
      4. Tester: accept -> start -> upload results -> submit
      5. Tech approver: approve recommendation
    Returns (fr_id, recommendation_id, dispatch_result).
    """
    admin_token = tokens["admin"]

    # -- Step 1: Submit FR ---------------------------------------------------
    r_fr = create_fr(
        tokens["originator"],
        org_id,
        dept_id,
        equip["id"] if equip else None,
        title=f"[FR-REG] {label} -- {_ts()}",
        priority="high",
    )
    assert r_fr.status_code == 201, (
        f"[{label}] FR create failed {r_fr.status_code}: {r_fr.text[:300]}"
    )
    fr = r_fr.json()
    fr_id = fr["request_id"]
    print(f"\n   [FR-CREATE]  {fr['request_number']}  status={fr['status']}")

    # -- Step 2: Pass-1 initial-approve -> child TR --------------------------
    r_ia = _initial_approve(fr_id, admin_token)
    assert r_ia.status_code == 200, (
        f"[{label}] initial-approve failed {r_ia.status_code}: {r_ia.text[:300]}"
    )
    ia = r_ia.json()
    assert ia["success"] is True
    print(f"   [PASS-1  ]  {ia['message'][:80]}")

    # Child TR ID is returned directly by initial-approve (child_tr_id field)
    child_tr_id: Optional[str] = ia.get("child_tr_id")
    child_tr_num: str = ia.get("child_tr_number", "")

    # Fallback: search recent submitted TRs if older server doesn't return child_tr_id
    if not child_tr_id:
        list_r = api("get", "/testing_requests/?limit=50", admin_token)
        if list_r.status_code == 200:
            for tr in list_r.json():
                if str(tr.get("source_failure_id") or "") == str(fr_id):
                    child_tr_id = tr["id"]
                    child_tr_num = tr["request_number"]
                    break

    assert child_tr_id, (
        f"[{label}] Child TR with source_failure_id={fr_id} not found"
    )
    print(f"   [CHILD-TR]  {child_tr_num}  id={child_tr_id[:8]}")

    # -- Step 3: Pass-2 approve-and-assign child TR --------------------------
    role_id, tester_user, tester_token = resolve_tester(child_tr_id, admin_token, tokens)
    assert tester_user and tester_user.get("user_id"), (
        f"[{label}] Could not resolve tester"
    )

    assign_body: dict = {
        "tester_id": str(tester_user["user_id"]),
        "comment":   f"FR regression -- {label}",
    }
    if role_id:
        assign_body["tester_role_id"] = str(role_id)

    r_assign = api(
        "post",
        f"/testing-requests/approvals/{child_tr_id}/approve-and-assign",
        admin_token,
        json=assign_body,
    )
    assert r_assign.status_code == 200, (
        f"[{label}] assign failed {r_assign.status_code}: {r_assign.text[:300]}"
    )
    print(f"   [ASSIGN  ]  tester={r_assign.json().get('assigned_tester_email')}")

    # -- Step 4: Tester accepts + starts -------------------------------------
    r = api("put", f"/testing/{child_tr_id}/accept", tester_token)
    assert r.status_code == 200, (
        f"[{label}] accept failed {r.status_code}: {r.text[:200]}"
    )
    r = api("put", f"/testing/{child_tr_id}/start", tester_token)
    assert r.status_code == 200, (
        f"[{label}] start failed {r.status_code}: {r.text[:200]}"
    )
    print(f"   [IN-PROG ]  status={r.json()['status']}")

    # -- Step 5: Upload structured result ------------------------------------
    test_data: dict = {
        "overall_result":         "Fail",
        "overall_remarks":        f"Critical failure confirmed -- {label}",
        "overall_recommendation": summary,
        "next_action":            next_action_display,
        "recommendation_type":    recommendation_type,
    }
    if schedule_frequency:
        test_data["outcome_frequency"]   = schedule_frequency
        test_data["outcome_start_date"]  = outcome_start_date or _future(10)
        test_data["outcome_end_date"]    = outcome_end_date or _future(365)

    r = api(
        "post",
        f"/testing/{child_tr_id}/results/structured",
        tester_token,
        json={
            "template_key": "overall_assessment",
            "test_data":    test_data,
            "overall_result": "fail",
            "remarks": f"FR regression -- {label}",
        },
    )
    assert r.status_code in (200, 201), (
        f"[{label}] structured result failed {r.status_code}: {r.text[:300]}"
    )
    print(f"   [RESULT  ]  stored")

    # -- Step 6: Submit results (creates recommendation) ---------------------
    submit_body: dict = {
        "recommendation_type": recommendation_type,
        "summary":             summary,
        "next_action":         next_action_direct,
    }
    if schedule_frequency:
        submit_body["schedule_frequency"] = schedule_frequency
    if replacement_products:
        submit_body["replacement_products"] = replacement_products

    r = api(
        "put",
        f"/testing/{child_tr_id}/submit_results",
        tester_token,
        json=submit_body,
    )
    assert r.status_code == 200, (
        f"[{label}] submit_results failed {r.status_code}: {r.text[:300]}"
    )
    print(f"   [SUBMIT  ]  status={r.json().get('status')}")

    # -- Step 7: Fetch recommendation ----------------------------------------
    # The testing_requests detail endpoint does not embed recommendations;
    # use /approvals/pending (which lists all pending recommendations) and
    # filter by testing_request_id == child_tr_id.
    pending_r = api("get", "/approvals/pending?limit=100", admin_token)
    assert pending_r.status_code == 200, (
        f"[{label}] fetch pending approvals failed {pending_r.status_code}"
    )
    pending = pending_r.json()
    recs = [
        p for p in pending
        if str(p.get("testing_request_id") or "") == str(child_tr_id)
    ]
    assert recs, f"[{label}] No recommendation created (searched {len(pending)} pending items)"
    rec_id = str(recs[-1]["id"])
    print(f"   [REC     ]  id={rec_id[:8]}  next_action={recs[-1].get('next_action')}")

    # -- Step 8: Approve recommendation --------------------------------------
    approve_body: dict = {"notes": f"FR regression -- {label}"}
    if schedule_frequency and next_action_direct in ("maintenance", "inspection", "repair_cycle"):
        approve_body["schedule_start_date"] = outcome_start_date or _future(10)
        approve_body["schedule_end_date"]   = outcome_end_date   or _future(365)
        approve_body["schedule_frequency"]  = schedule_frequency

    r = api("put", f"/approvals/{rec_id}/approve", admin_token, json=approve_body)
    assert r.status_code == 200, (
        f"[{label}] approve_rec failed {r.status_code}: {r.text[:300]}"
    )
    result = r.json()
    print(
        f"   [APPROVE ]  next_action={result.get('next_action')}  "
        f"created={result.get('created')}  status={result.get('status')}"
    )
    return fr_id, rec_id, result


# ===========================================================================
# A. FR Submission Tests
# ===========================================================================

class TestFRSubmission:
    """POST /direct-submissions/ and GET /direct-submissions/"""

    def test_create_fr_basic(self, tokens, org_info):
        """Positive: create a basic FR with mandatory fields."""
        org_id, dept_id = org_info
        r = create_fr(tokens["admin"], org_id, dept_id)
        assert r.status_code == 201, f"Expected 201 got {r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body["request_number"].startswith("FR-")
        assert body["status"] == "submitted"
        assert body["request_category"] == "failure_registry"
        print(f"\n   [OK] FR created: {body['request_number']}")

    def test_create_fr_with_equipment(self, tokens, org_info, sample_equipment):
        """Positive: create FR linked to equipment."""
        org_id, dept_id = org_info
        equip_id = sample_equipment["id"] if sample_equipment else None
        r = create_fr(tokens["originator"], org_id, dept_id, equip_id)
        assert r.status_code == 201, f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body["request_number"].startswith("FR-")
        print(f"\n   [OK] FR with equipment: {body['request_number']}")

    def test_create_fr_priority_critical(self, tokens, org_info):
        """Positive: FR with critical priority."""
        org_id, dept_id = org_info
        r = create_fr(tokens["admin"], org_id, dept_id, priority="critical")
        assert r.status_code == 201, f"{r.status_code}: {r.text[:200]}"
        print(f"\n   [OK] Critical FR: {r.json()['request_number']}")

    def test_create_fr_rich_test_data(self, tokens, org_info):
        """Positive: FR with full test_data payload."""
        org_id, dept_id = org_info
        r = create_fr(
            tokens["admin"],
            org_id,
            dept_id,
            extra_test_data={
                "failure_category":    "Mechanical",
                "outage_duration_hours": 24,
                "affected_consumers":  850,
                "root_cause_analysis": "Bushing porcelain cracked due to thermal cycling",
                "immediate_action_taken": "Isolator operated, load transferred",
            },
        )
        assert r.status_code == 201
        print(f"\n   [OK] Rich FR: {r.json()['request_number']}")

    def test_list_fr_submissions(self, tokens, org_info):
        """Positive: list FR submissions."""
        # ensure at least one exists
        create_fr(tokens["admin"], org_info[0], org_info[1])
        r = api("get", "/direct-submissions/?category=failure_registry", tokens["admin"])
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        items = r.json()
        assert isinstance(items, list)
        assert len(items) >= 1
        # all returned items must be failure_registry
        for item in items[:5]:
            assert item.get("request_category") == "failure_registry", (
                f"Expected failure_registry got {item.get('request_category')}"
            )
        print(f"\n   [OK] Listed {len(items)} FR submissions")

    def test_list_fr_own_only(self, tokens, org_info):
        """Positive: own_only=true returns only current user's submissions."""
        r = api(
            "get",
            "/direct-submissions/?category=failure_registry&own_only=true",
            tokens["originator"],
        )
        assert r.status_code == 200
        print(f"\n   [OK] own_only returned {len(r.json())} submissions")

    def test_get_fr_detail(self, tokens, org_info):
        """Positive: fetch single FR by ID."""
        org_id, dept_id = org_info
        fr_r = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = fr_r.json()["request_id"]

        r = api("get", f"/direct-submissions/{fr_id}", tokens["admin"])
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        assert str(body["id"]) == str(fr_id)
        assert body["request_category"] == "failure_registry"
        print(f"\n   [OK] FR detail: {body['request_number']}")

    def test_list_fr_pagination(self, tokens, org_info):
        """Positive: skip/limit pagination works."""
        r = api(
            "get",
            "/direct-submissions/?category=failure_registry&skip=0&limit=2",
            tokens["admin"],
        )
        assert r.status_code == 200
        assert len(r.json()) <= 2
        print(f"\n   [OK] pagination skip=0 limit=2 -> {len(r.json())} items")


# ===========================================================================
# B. FR Attachment Tests
# ===========================================================================

class TestFRAttachment:
    """POST /direct-submissions/{id}/attach and GET /{id}/attachment"""

    def _make_fr(self, tokens, org_info) -> str:
        org_id, dept_id = org_info
        r = create_fr(tokens["admin"], org_id, dept_id)
        assert r.status_code == 201
        return r.json()["request_id"]

    def test_upload_text_attachment(self, tokens, org_info):
        """Positive: upload a plain-text file as attachment."""
        fr_id = self._make_fr(tokens, org_info)
        file_content = b"Root Cause Analysis Report\n\nPreliminary findings: bushing failure."
        r = req_lib.post(
            f"{BASE}/direct-submissions/{fr_id}/attach",
            headers=h(tokens["admin"]),
            files={"file": ("rca_report.txt", io.BytesIO(file_content), "text/plain")},
        )
        assert r.status_code == 200, f"Attach failed {r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body.get("file_name") == "rca_report.txt"
        print(f"\n   [OK] Attachment uploaded: {body.get('file_name')}")

    def test_upload_pdf_attachment(self, tokens, org_info):
        """Positive: upload a minimal PDF-like binary blob."""
        fr_id = self._make_fr(tokens, org_info)
        fake_pdf = b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj"
        r = req_lib.post(
            f"{BASE}/direct-submissions/{fr_id}/attach",
            headers=h(tokens["admin"]),
            files={"file": ("report.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert r.status_code == 200, f"PDF attach failed {r.status_code}: {r.text[:300]}"
        print(f"\n   [OK] PDF attachment uploaded")

    def test_download_attachment(self, tokens, org_info):
        """Positive: upload then download attachment."""
        fr_id = self._make_fr(tokens, org_info)
        content = b"Test file for download verification."
        req_lib.post(
            f"{BASE}/direct-submissions/{fr_id}/attach",
            headers=h(tokens["admin"]),
            files={"file": ("evidence.txt", io.BytesIO(content), "text/plain")},
        )
        r = api("get", f"/direct-submissions/{fr_id}/attachment", tokens["admin"])
        assert r.status_code == 200, f"Download failed {r.status_code}: {r.text[:200]}"
        assert len(r.content) > 0
        print(f"\n   [OK] Attachment downloaded ({len(r.content)} bytes)")

    def test_download_nonexistent_attachment(self, tokens, org_info):
        """Negative: download from FR with no attachment -> 404."""
        fr_id = self._make_fr(tokens, org_info)
        r = api("get", f"/direct-submissions/{fr_id}/attachment", tokens["admin"])
        assert r.status_code == 404, (
            f"Expected 404 no-attachment got {r.status_code}"
        )
        print(f"\n   [OK] 404 on missing attachment")

    def test_attach_nonexistent_fr(self, tokens):
        """Negative: attach to a non-existent FR -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000001"
        r = req_lib.post(
            f"{BASE}/direct-submissions/{fake_id}/attach",
            headers=h(tokens["admin"]),
            files={"file": ("x.txt", io.BytesIO(b"data"), "text/plain")},
        )
        assert r.status_code in (404, 422), (
            f"Expected 404/422 got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] {r.status_code} on attach to fake FR")


# ===========================================================================
# C. Pass-1 Initial Approval Tests
# ===========================================================================

class TestFRPass1:
    """POST /testing-requests/approvals/{id}/initial-approve"""

    def test_initial_approve_success(self, tokens, org_info):
        """Positive: initial-approve a valid submitted FR -> child TR created."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        assert r_fr.status_code == 201
        fr_id = r_fr.json()["request_id"]
        fr_num = r_fr.json()["request_number"]

        r = _initial_approve(fr_id, tokens["admin"])
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body["success"] is True
        assert "TR-" in body["message"]
        print(f"\n   [OK] FR {fr_num} initial-approved. {body['message'][:80]}")

    def test_initial_approve_creates_child_tr(self, tokens, org_info):
        """Positive: initial-approve returns child_tr_id and child TR has category=test."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        r_ia = _initial_approve(fr_id, tokens["admin"])
        assert r_ia.status_code == 200
        ia = r_ia.json()

        # child_tr_id and child_tr_number are returned directly in the initial-approve response
        child_tr_id = ia.get("child_tr_id")
        child_tr_num = ia.get("child_tr_number", "")
        assert child_tr_id, "child_tr_id missing from initial-approve response"
        assert child_tr_num.startswith("TR-"), (
            f"Expected TR- prefix got '{child_tr_num}'"
        )

        # Verify the child TR exists and has the correct category
        r = api("get", f"/testing_requests/{child_tr_id}", tokens["admin"])
        assert r.status_code == 200
        child = r.json()
        assert child["request_category"] == "test", (
            f"Expected child TR category=test got '{child['request_category']}'"
        )
        # FR is now in 'approved' state — verify the linkage via FR status
        r_fr_detail = api("get", f"/direct-submissions/{fr_id}", tokens["admin"])
        assert r_fr_detail.status_code == 200
        assert r_fr_detail.json()["status"] == "approved"
        print(f"\n   [OK] Child TR {child_tr_num} created with category=test; FR status=approved")

    def test_initial_approve_fr_status_becomes_approved(self, tokens, org_info):
        """Positive: FR status changes to 'approved' after Pass-1."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        _initial_approve(fr_id, tokens["admin"])

        r = api("get", f"/direct-submissions/{fr_id}", tokens["admin"])
        assert r.status_code == 200
        assert r.json()["status"] == "approved", (
            f"Expected approved got {r.json()['status']}"
        )
        print(f"\n   [OK] FR status=approved after Pass-1")

    def test_initial_approve_already_approved_fails(self, tokens, org_info):
        """Negative: double initial-approve -> 400."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        _initial_approve(fr_id, tokens["admin"])  # first approve succeeds
        r = _initial_approve(fr_id, tokens["admin"])  # second should fail
        assert r.status_code == 400, (
            f"Expected 400 on double-approve got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 400 on double initial-approve")

    def test_initial_approve_nonexistent_request(self, tokens):
        """Negative: non-existent request_id -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000002"
        r = _initial_approve(fake_id, tokens["admin"])
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on fake FR initial-approve")

    def test_initial_approve_wrong_category_fails(self, tokens, org_info):
        """Negative: initial-approve on a non-FR request -> 400."""
        org_id, dept_id = org_info
        # Create a standard test request (not FR)
        r_tr = api(
            "post",
            "/testing_requests/",
            tokens["originator"],
            json={
                "title":            f"[REG] Non-FR {_ts()}",
                "request_category": "test",
                "organization_id":  org_id,
                "department_id":    dept_id,
            },
        )
        if r_tr.status_code not in (200, 201):
            pytest.skip("Cannot create standard TR for this test")
        tr_id = r_tr.json()["id"]

        r = _initial_approve(tr_id, tokens["admin"])
        assert r.status_code == 400, (
            f"Expected 400 for non-FR initial-approve got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 400 on initial-approve of non-FR request")

    def test_initial_approve_no_auth(self, tokens, org_info):
        """Negative: no auth token -> 401."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        r = req_lib.post(f"{BASE}/testing-requests/approvals/{fr_id}/initial-approve")
        assert r.status_code == 401, f"Expected 401 got {r.status_code}"
        print(f"\n   [OK] 401 without auth token")


# ===========================================================================
# D. Pass-2 Approve-and-Assign Tests
# ===========================================================================

class TestFRPass2:
    """POST /testing-requests/approvals/{id}/approve-and-assign"""

    def _create_and_pass1(self, tokens, org_info) -> Tuple[str, str]:
        """Create FR, run Pass-1, return (fr_id, child_tr_id)."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        assert r_fr.status_code == 201
        fr_id = r_fr.json()["request_id"]
        r_ia = _initial_approve(fr_id, tokens["admin"])
        assert r_ia.status_code == 200, f"initial-approve failed: {r_ia.text[:200]}"
        ia = r_ia.json()
        child_tr_id = ia.get("child_tr_id")
        if not child_tr_id:
            pytest.fail("child_tr_id missing from initial-approve response")
        return fr_id, child_tr_id

    def test_approve_and_assign_success(self, tokens, org_info):
        """Positive: assign child TR to tester -> status=assigned."""
        _, tr_id = self._create_and_pass1(tokens, org_info)
        role_id, tester_user, _ = resolve_tester(tr_id, tokens["admin"], tokens)
        assert tester_user and tester_user.get("user_id"), "No tester found"

        body: dict = {
            "tester_id": str(tester_user["user_id"]),
            "comment":   "FR regression Pass-2",
        }
        if role_id:
            body["tester_role_id"] = str(role_id)

        r = api(
            "post",
            f"/testing-requests/approvals/{tr_id}/approve-and-assign",
            tokens["admin"],
            json=body,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        resp = r.json()
        assert resp["success"] is True
        assert resp["assigned_tester_id"] is not None
        print(f"\n   [OK] Pass-2 assigned to {resp['assigned_tester_email']}")

    def test_assign_nonexistent_request(self, tokens):
        """Negative: assign to non-existent TR -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000003"
        r = api(
            "post",
            f"/testing-requests/approvals/{fake_id}/approve-and-assign",
            tokens["admin"],
            json={
                "tester_id":      "00000000-0000-0000-0000-000000000099",
                "tester_role_id": "00000000-0000-0000-0000-000000000099",
            },
        )
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on assign to fake TR")

    def test_assign_invalid_tester_id(self, tokens, org_info):
        """Negative: non-existent tester_id -> 404."""
        _, tr_id = self._create_and_pass1(tokens, org_info)
        r = api(
            "post",
            f"/testing-requests/approvals/{tr_id}/approve-and-assign",
            tokens["admin"],
            json={
                "tester_id":      "00000000-0000-0000-0000-000000000099",
                "tester_role_id": "00000000-0000-0000-0000-000000000099",
            },
        )
        assert r.status_code in (404, 400), (
            f"Expected 404/400 got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] {r.status_code} on invalid tester_id")

    def test_assign_no_auth(self, tokens, org_info):
        """Negative: no auth -> 401."""
        _, tr_id = self._create_and_pass1(tokens, org_info)
        r = req_lib.post(
            f"{BASE}/testing-requests/approvals/{tr_id}/approve-and-assign",
            json={"tester_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert r.status_code == 401, f"Expected 401 got {r.status_code}"
        print(f"\n   [OK] 401 on assign without auth")

    def test_get_tester_roles(self, tokens, org_info):
        """Positive: tester-roles endpoint returns list."""
        _, tr_id = self._create_and_pass1(tokens, org_info)
        r = api(
            "get",
            f"/testing-requests/approvals/{tr_id}/tester-roles",
            tokens["admin"],
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        roles = r.json()
        assert isinstance(roles, list)
        print(f"\n   [OK] {len(roles)} tester roles returned")

    def test_get_users_by_role(self, tokens, org_info):
        """Positive: users-by-role returns testers with workload."""
        _, tr_id = self._create_and_pass1(tokens, org_info)
        roles_r = api(
            "get",
            f"/testing-requests/approvals/{tr_id}/tester-roles",
            tokens["admin"],
        )
        roles = roles_r.json() if roles_r.status_code == 200 else []
        if not roles:
            pytest.skip("No tester roles configured")
        role_id = roles[0]["role_id"]
        r = api(
            "get",
            f"/testing-requests/approvals/{tr_id}/tester-roles/{role_id}/users",
            tokens["admin"],
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        users = r.json()
        assert isinstance(users, list)
        for u in users[:3]:
            assert "user_id" in u
            assert "email" in u
            assert "active_requests" in u
        print(f"\n   [OK] {len(users)} users in role")


# ===========================================================================
# E. FR Rejection Tests
# ===========================================================================

class TestFRRejection:
    """POST /testing-requests/approvals/{id}/reject"""

    def test_reject_submitted_fr(self, tokens, org_info):
        """Positive: reject a submitted FR with a comment."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]

        r = _reject(fr_id, tokens["admin"], "Insufficient failure details provided")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body["success"] is True
        print(f"\n   [OK] FR rejected: {body['message'][:80]}")

    def test_reject_fr_status_becomes_rejected(self, tokens, org_info):
        """Positive: FR status is 'rejected' after rejection."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        _reject(fr_id, tokens["admin"], "Missing equipment details")

        r = api("get", f"/direct-submissions/{fr_id}", tokens["admin"])
        assert r.status_code == 200
        assert r.json()["status"] == "rejected", (
            f"Expected rejected got {r.json()['status']}"
        )
        print(f"\n   [OK] FR status=rejected after rejection")

    def test_reject_without_comment_fails(self, tokens, org_info):
        """Negative: empty rejection_comment -> 400."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        r = api(
            "post",
            f"/testing-requests/approvals/{fr_id}/reject",
            tokens["admin"],
            json={"rejection_comment": ""},
        )
        assert r.status_code == 400, (
            f"Expected 400 on empty comment got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 400 on empty rejection comment")

    def test_reject_approved_fr_fails(self, tokens, org_info):
        """Negative: reject an already-approved FR -> 400."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        _initial_approve(fr_id, tokens["admin"])

        r = _reject(fr_id, tokens["admin"], "Trying to reject approved FR")
        assert r.status_code == 400, (
            f"Expected 400 on reject-after-approve got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 400 on reject after approval")

    def test_reject_nonexistent_fr(self, tokens):
        """Negative: reject non-existent FR -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000004"
        r = _reject(fake_id, tokens["admin"], "No such FR")
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on reject of fake FR")

    def test_reject_missing_comment_field(self, tokens, org_info):
        """Negative: rejection_comment field missing entirely -> 422."""
        org_id, dept_id = org_info
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        r = api(
            "post",
            f"/testing-requests/approvals/{fr_id}/reject",
            tokens["admin"],
            json={},
        )
        assert r.status_code == 422, (
            f"Expected 422 on missing comment field got {r.status_code}"
        )
        print(f"\n   [OK] 422 on missing rejection_comment field")


# ===========================================================================
# F. FR Outcome Regression (all 6 next_action values)
# ===========================================================================

class TestFROutcomes:
    """Full FR lifecycle for each of the 6 next_action outcomes."""

    def test_outcome_test(self, tokens, org_info, sample_equipment):
        """Outcome: next_action=test -> follow-up TR- created (submitted)."""
        org_id, dept_id = org_info
        fr_id, rec_id, result = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="Outcome-Test",
            next_action_display="Test",
            next_action_direct="test",
            recommendation_type="fail",
            summary="Follow-up testing required after failure",
        )
        assert result.get("next_action") == "test", (
            f"Expected next_action=test got {result.get('next_action')}"
        )
        assert result.get("status") == "outcome_active", (
            f"Expected outcome_active got {result.get('status')}"
        )
        created = result.get("created") or ""
        assert created.startswith("TR-"), (
            f"Expected TR- reference got '{created}'"
        )
        print(f"\n   [OK] Outcome=Test  follow-up={created}")

    def test_outcome_procurement(self, tokens, org_info, sample_equipment):
        """Outcome: next_action=replacement -> PR- procurement ticket created."""
        org_id, dept_id = org_info
        products = [
            {
                "item_name":  "HV Bushing 33kV",
                "category":   "Transformer Components",
                "quantity":   2,
                "unit_price": 45000,
            }
        ]
        fr_id, rec_id, result = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="Outcome-Procurement",
            next_action_display="Procurement",
            next_action_direct="replacement",
            recommendation_type="fail",
            summary="Replacement of failed HV bushing required",
            replacement_products=products,
        )
        assert result.get("next_action") == "replacement", (
            f"Expected replacement got {result.get('next_action')}"
        )
        assert result.get("status") == "finance_pending", (
            f"Expected finance_pending got {result.get('status')}"
        )
        created = result.get("created") or ""
        assert created.startswith("PR-"), (
            f"Expected PR- reference got '{created}'"
        )
        print(f"\n   [OK] Outcome=Procurement  ticket={created}")

    def test_outcome_repair(self, tokens, org_info, sample_equipment):
        """Outcome: next_action=repair_cycle -> repair workflow created."""
        org_id, dept_id = org_info
        fr_id, rec_id, result = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="Outcome-Repair",
            next_action_display="Repair",
            next_action_direct="repair_cycle",
            recommendation_type="fail",
            summary="Equipment requires repair lifecycle",
            schedule_frequency="monthly",
            outcome_start_date=_future(5),
            outcome_end_date=_future(180),
        )
        assert result.get("next_action") == "repair_cycle", (
            f"Expected repair_cycle got {result.get('next_action')}"
        )
        assert result.get("status") == "outcome_active", (
            f"Expected outcome_active got {result.get('status')}"
        )
        print(f"\n   [OK] Outcome=Repair  created={result.get('created')}")

    def test_outcome_inspection(self, tokens, org_info, sample_equipment):
        """Outcome: next_action=inspection -> IN- schedule created."""
        org_id, dept_id = org_info
        fr_id, rec_id, result = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="Outcome-Inspection",
            next_action_display="Inspection",
            next_action_direct="inspection",
            recommendation_type="conditional",
            summary="Regular inspection schedule required post-failure",
            schedule_frequency="quarterly",
            outcome_start_date=_future(10),
            outcome_end_date=_future(365),
        )
        assert result.get("next_action") == "inspection", (
            f"Expected inspection got {result.get('next_action')}"
        )
        assert result.get("status") == "outcome_active", (
            f"Expected outcome_active got {result.get('status')}"
        )
        created = result.get("created") or ""
        assert created.startswith("IN-"), (
            f"Expected IN- reference got '{created}'"
        )
        print(f"\n   [OK] Outcome=Inspection  schedule={created}")

    def test_outcome_maintenance(self, tokens, org_info, sample_equipment):
        """Outcome: next_action=maintenance -> MN- schedule created."""
        org_id, dept_id = org_info
        fr_id, rec_id, result = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="Outcome-Maintenance",
            next_action_display="Maintenance",
            next_action_direct="maintenance",
            recommendation_type="fail",
            summary="Preventive maintenance schedule initiated after failure",
            schedule_frequency="monthly",
            outcome_start_date=_future(7),
            outcome_end_date=_future(365),
        )
        assert result.get("next_action") == "maintenance", (
            f"Expected maintenance got {result.get('next_action')}"
        )
        assert result.get("status") == "outcome_active", (
            f"Expected outcome_active got {result.get('status')}"
        )
        created = result.get("created") or ""
        assert created.startswith("MN-"), (
            f"Expected MN- reference got '{created}'"
        )
        print(f"\n   [OK] Outcome=Maintenance  schedule={created}")

    def test_outcome_none(self, tokens, org_info, sample_equipment):
        """Outcome: next_action=none -> TR closed, no downstream artifact."""
        org_id, dept_id = org_info
        fr_id, rec_id, result = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="Outcome-None",
            next_action_display="None",
            next_action_direct="none",
            recommendation_type="pass",
            summary="No further action required. Failure was isolated incident.",
        )
        assert result.get("next_action") == "none", (
            f"Expected none got {result.get('next_action')}"
        )
        assert result.get("status") in ("closed", "outcome_active"), (
            f"Expected closed/outcome_active got {result.get('status')}"
        )
        print(f"\n   [OK] Outcome=None  status={result.get('status')}")


# ===========================================================================
# G. Negative / Validation Tests
# ===========================================================================

class TestFRNegative:
    """Cross-cutting negative tests: auth, validation, wrong-state errors."""

    # -- Auth failures -------------------------------------------------------

    def test_create_fr_no_auth(self, org_info):
        """Negative: create FR without token -> 401."""
        body = {
            "request_category": "failure_registry",
            "template_key":     "failure_registry",
            "title":            "Unauthenticated FR",
            "test_data":        {"failure_description": "test"},
            "organization_id":  org_info[0],
        }
        r = req_lib.post(f"{BASE}/direct-submissions/", json=body)
        assert r.status_code == 401, f"Expected 401 got {r.status_code}"
        print(f"\n   [OK] 401 on create FR without auth")

    def test_list_fr_no_auth(self):
        """Negative: list FR without token -> 401."""
        r = req_lib.get(f"{BASE}/direct-submissions/?category=failure_registry")
        assert r.status_code == 401, f"Expected 401 got {r.status_code}"
        print(f"\n   [OK] 401 on list without auth")

    def test_get_fr_no_auth(self, tokens, org_info):
        """Negative: get FR detail without token -> 401."""
        r_fr = create_fr(tokens["admin"], org_info[0], org_info[1])
        fr_id = r_fr.json()["request_id"]
        r = req_lib.get(f"{BASE}/direct-submissions/{fr_id}")
        assert r.status_code == 401, f"Expected 401 got {r.status_code}"
        print(f"\n   [OK] 401 on get FR without auth")

    # -- Validation errors ---------------------------------------------------

    def test_create_fr_missing_title(self, tokens, org_info):
        """Negative: create FR without title -> 422."""
        r = api(
            "post",
            "/direct-submissions/",
            tokens["admin"],
            json={
                "request_category": "failure_registry",
                "template_key":     "failure_registry",
                "test_data":        {"failure_description": "no title"},
                "organization_id":  org_info[0],
            },
        )
        assert r.status_code == 422, (
            f"Expected 422 missing title got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 422 on missing title")

    def test_create_fr_missing_test_data(self, tokens, org_info):
        """Negative: create FR without test_data -> 422."""
        r = api(
            "post",
            "/direct-submissions/",
            tokens["admin"],
            json={
                "request_category": "failure_registry",
                "template_key":     "failure_registry",
                "title":            "No test data FR",
                "organization_id":  org_info[0],
            },
        )
        assert r.status_code == 422, (
            f"Expected 422 missing test_data got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 422 on missing test_data")

    def test_create_fr_invalid_category(self, tokens, org_info):
        """Negative: create with invalid request_category -> 422 or 400."""
        r = api(
            "post",
            "/direct-submissions/",
            tokens["admin"],
            json={
                "request_category": "invalid_category",
                "template_key":     "failure_registry",
                "title":            "Bad category FR",
                "test_data":        {"failure_description": "test"},
                "organization_id":  org_info[0],
            },
        )
        assert r.status_code in (400, 422), (
            f"Expected 400/422 got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] {r.status_code} on invalid category")

    def test_list_fr_without_category_param(self, tokens):
        """Negative: list without required category param -> 422."""
        r = api("get", "/direct-submissions/", tokens["admin"])
        assert r.status_code == 422, (
            f"Expected 422 missing category param got {r.status_code}"
        )
        print(f"\n   [OK] 422 on list without category param")

    def test_get_nonexistent_fr(self, tokens):
        """Negative: get FR with non-existent UUID -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000005"
        r = api("get", f"/direct-submissions/{fake_id}", tokens["admin"])
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on get fake FR")

    def test_get_fr_malformed_uuid(self, tokens):
        """Negative: malformed UUID in path -> 422."""
        r = api("get", "/direct-submissions/not-a-uuid", tokens["admin"])
        assert r.status_code == 422, f"Expected 422 got {r.status_code}"
        print(f"\n   [OK] 422 on malformed UUID")

    # -- Recommendation / approval errors ------------------------------------

    def test_approve_recommendation_no_products_for_procurement(
        self, tokens, org_info, sample_equipment
    ):
        """Negative: submit_results with next_action=replacement and no products -> 400."""
        org_id, dept_id = org_info
        # Create and run FR to the point of result submission
        r_fr = create_fr(tokens["admin"], org_id, dept_id)
        fr_id = r_fr.json()["request_id"]
        _initial_approve(fr_id, tokens["admin"])

        list_r = api("get", "/testing_requests/?limit=5&status=submitted", tokens["admin"])
        child_tr_id = None
        for tr in list_r.json():
            if str(tr.get("source_failure_id") or "") == str(fr_id):
                child_tr_id = tr["id"]
                break
        if not child_tr_id:
            pytest.skip("Child TR not found")

        role_id, tester_user, tester_token = resolve_tester(
            child_tr_id, tokens["admin"], tokens
        )
        if not tester_user.get("user_id"):
            pytest.skip("No tester available")

        assign_body = {"tester_id": str(tester_user["user_id"])}
        if role_id:
            assign_body["tester_role_id"] = str(role_id)
        api(
            "post",
            f"/testing-requests/approvals/{child_tr_id}/approve-and-assign",
            tokens["admin"],
            json=assign_body,
        )
        api("put", f"/testing/{child_tr_id}/accept", tester_token)
        api("put", f"/testing/{child_tr_id}/start", tester_token)
        api(
            "post",
            f"/testing/{child_tr_id}/results/structured",
            tester_token,
            json={
                "template_key":   "overall_assessment",
                "test_data":      {"overall_result": "Fail", "next_action": "Procurement"},
                "overall_result": "fail",
            },
        )

        # Submit with next_action=replacement but NO replacement_products
        r = api(
            "put",
            f"/testing/{child_tr_id}/submit_results",
            tester_token,
            json={
                "recommendation_type": "fail",
                "summary":             "Need procurement",
                "next_action":         "replacement",
                "replacement_products": [],   # empty -> should fail
            },
        )
        assert r.status_code == 400, (
            f"Expected 400 on empty products got {r.status_code}: {r.text[:300]}"
        )
        print(f"\n   [OK] 400 on replacement with empty products list")

    def test_approve_already_approved_recommendation(self, tokens, org_info, sample_equipment):
        """Negative: double-approve same recommendation -> 400."""
        org_id, dept_id = org_info
        # Run a full workflow to get an approved recommendation
        fr_id, rec_id, _ = run_fr_workflow(
            tokens=tokens,
            org_id=org_id,
            dept_id=dept_id,
            equip=sample_equipment,
            label="DoubleApprove",
            next_action_display="None",
            next_action_direct="none",
            recommendation_type="pass",
            summary="No action needed",
        )
        # Try to approve again
        r = api(
            "put",
            f"/approvals/{rec_id}/approve",
            tokens["admin"],
            json={"notes": "Second approve attempt"},
        )
        assert r.status_code == 400, (
            f"Expected 400 on double-approve got {r.status_code}: {r.text[:200]}"
        )
        print(f"\n   [OK] 400 on double recommendation approve")

    def test_approve_nonexistent_recommendation(self, tokens):
        """Negative: approve non-existent recommendation -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000006"
        r = api(
            "put",
            f"/approvals/{fake_id}/approve",
            tokens["admin"],
            json={"notes": "test"},
        )
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on approve fake recommendation")

    def test_reject_recommendation_nonexistent(self, tokens):
        """Negative: reject non-existent recommendation -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000007"
        r = api(
            "put",
            f"/approvals/{fake_id}/reject",
            tokens["admin"],
            json={"notes": "reject fake"},
        )
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on reject fake recommendation")

    # -- Tester role errors --------------------------------------------------

    def test_tester_roles_nonexistent_request(self, tokens):
        """Negative: tester-roles for fake request -> 404."""
        fake_id = "00000000-0000-0000-0000-000000000008"
        r = api(
            "get",
            f"/testing-requests/approvals/{fake_id}/tester-roles",
            tokens["admin"],
        )
        assert r.status_code == 404, f"Expected 404 got {r.status_code}"
        print(f"\n   [OK] 404 on tester-roles for fake request")
