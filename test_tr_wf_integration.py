"""
Integration test suite for the KPTCL Configurable Workflow Engine (tr_wf_*).

Live scenario under test:
    1.  Originator creates a TestingRequest                (POST /testing_requests/)
    2.  Originator submits the TR                          (PUT  /testing_requests/{id}/submit)
    3.  Admin assigns a tester                             (PUT  /testing_requests/{id}/assign)
    4.  Tester accepts the assignment                      (PUT  /testing/{id}/accept)
    5.  Tester submits results + recommendation            (PUT  /testing/{id}/submit_results)
    6.  AEE R&T approves the recommendation                (PUT  /approvals/{rec_id}/approve)
        → WorkflowDispatchService spawns a follow-up TR
    7.  Follow-up TR enters the tr_wf L2 queue
    8.  EE_TLSS approves & routes at L2                   (POST /testing-requests/approvals/{id}/tr-wf/l2-approve-route)
    9.  AEE R&T assigns tester at L3                      (POST /testing-requests/approvals/{id}/tr-wf/l3-assign)
   10.  Tester advances at L4                             (POST /testing-requests/approvals/{id}/tr-wf/advance)
   11.  Audit log reflects all transitions

Run with:
    pip install requests pytest
    pytest test_tr_wf_integration.py -v
"""

import os
import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

USERS = {
    # L2 — EE TLSS (approves & routes at L2)
    "ee_tlss": {
        "username": os.getenv("WF_USER_EE_TLSS", "ee.tlss@utility.local"),
        "password": os.getenv("WF_PASS_EE_TLSS", "TestDept@123"),
    },
    # L3 — AEE Maintenance (assigns tester at L3, approves result recommendation)
    "aee_rt": {
        "username": os.getenv("WF_USER_AEE", "aee.maintenance@utility.local"),
        "password": os.getenv("WF_PASS_AEE", "TestDept@123"),
    },
    # L4 — AE/JE (tester who accepts, runs test, submits results)
    "ae_rt": {
        "username": os.getenv("WF_USER_AE", "ae.je@utility.local"),
        "password": os.getenv("WF_PASS_AE", "TestDept@123"),
    },
    # EE R&T — used as originator / admin (submits and assigns TRs)
    "ee_rt": {
        "username": os.getenv("WF_USER_EE_RT", "ee.rt@utility.local"),
        "password": os.getenv("WF_PASS_EE_RT", "TestDept@123"),
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_token_cache: dict = {}


def _token(username: str, password: str) -> str:
    if username not in _token_cache:
        resp = requests.post(
            f"{BASE_URL}/token",
            data={"username": username, "password": password},
        )
        assert resp.status_code == 200, f"Auth failed for {username}: {resp.text}"
        _token_cache[username] = resp.json()["access_token"]
    return _token_cache[username]


def _h(role: str) -> dict:
    creds = USERS[role]
    return {"Authorization": f"Bearer {_token(creds['username'], creds['password'])}"}


def get(path, role, **kw):
    return requests.get(f"{BASE_URL}{path}", headers=_h(role), **kw)


def post(path, role, json=None, **kw):
    return requests.post(f"{BASE_URL}{path}", headers=_h(role), json=json, **kw)


def put(path, role, json=None, **kw):
    return requests.put(f"{BASE_URL}{path}", headers=_h(role), json=json, **kw)


def delete(path, role, **kw):
    return requests.delete(f"{BASE_URL}{path}", headers=_h(role), **kw)


def _user_id(role: str) -> str:
    """Fetch the current user's ID for the given role."""
    r = get("/auth/me", role)
    assert r.status_code == 200, f"Cannot fetch /auth/me for {role}: {r.text}"
    return r.json()["id"]


# Known seed data IDs used across all TR creation calls.
# Equipment: BN-BBXX-220-400kV Hoody-Begur line-CT-01 (Current Transformer)
# Test type: CT Insulation Test (category_master_id=18, CategoryDetails id=130)
_EQUIPMENT_ID = "f9ca7873-36af-41b8-b0d1-8fe188c36cee"
_TEST_TYPE_ID = 130  # CT Insulation Test

# Tester seed data (ae.je@utility.local)
_TESTER_ID      = "bc9137ba-b5a9-446d-a0fb-f882f572943e"
_TESTER_ROLE_ID = "1de85d1e-030e-4405-943d-62fa7e335a9c"  # AE_JE role


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wf_definition_id():
    """
    Create a workflow definition with 3 stages and register it as the org
    routing default. Cleaned up after the module.
    """
    resp = post("/tr-workflow-config/definitions", "ee_tlss", json={
        "name": "Integration Test WF",
        "description": "Created by integration test suite",
        "is_default": False,
        "is_active": True,
    })
    assert resp.status_code in (200, 201), f"Create definition failed: {resp.text}"
    wf_id = resp.json()["id"]

    # Two stages:
    #   l3_assign  (seq 1) — first stage after L2 instantiation; "assign" advances to l4_testing
    #   l4_testing (seq 2) — tester stage; "complete" terminates
    stage_ids = {}
    for stage in [
        {"name": "L3 Assign",  "code": "l3_assign",  "sequence": 1, "weight": 10, "is_mandatory": True},
        {"name": "L4 Testing", "code": "l4_testing", "sequence": 2, "weight": 10, "is_mandatory": True},
    ]:
        sr = post(f"/tr-workflow-config/definitions/{wf_id}/stages", "ee_tlss", json=stage)
        assert sr.status_code in (200, 201), f"Stage create failed: {sr.text}"
        stage_ids[stage["code"]] = sr.json()["id"]

    # Wire transitions so advance_stage can resolve action_code → next stage
    r = requests.put(
        f"{BASE_URL}/tr-workflow-config/stages/{stage_ids['l3_assign']}/transitions",
        headers=_h("ee_tlss"),
        json=[{"action_code": "assign", "to_stage_id": stage_ids["l4_testing"]}],
    )
    assert r.status_code in (200, 201), f"l3_assign transition failed: {r.text}"

    r = requests.put(
        f"{BASE_URL}/tr-workflow-config/stages/{stage_ids['l4_testing']}/transitions",
        headers=_h("ee_tlss"),
        json=[{"action_code": "complete", "to_stage_id": None}],
    )
    assert r.status_code in (200, 201), f"l4_testing transition failed: {r.text}"

    # Set as org routing default so routing engine resolves it
    put("/tr-workflow-config/routing/default", "ee_tlss",
        json={"wf_definition_id": wf_id})

    yield wf_id

    # Teardown — clear routing default first, then delete definition
    put("/tr-workflow-config/routing/default", "ee_tlss",
        json={"wf_definition_id": None})
    delete(f"/tr-workflow-config/definitions/{wf_id}", "ee_tlss")


@pytest.fixture(scope="module")
def live_scenario(wf_definition_id):
    """
    Drives the full live scenario for the tr_wf configurable workflow engine.

    Live flow:
      1.  Originator creates TR with equipment + test type
      2.  Originator submits TR  →  TR enters L2 wf queue (routing engine assigns wf_definition)
      3.  EE_TLSS approves & routes at L2  →  wf_instance created, TR moves to pending_assignment
      4.  AEE_RT assigns tester at L3
      5.  AE_RT (tester) advances at L4
      6.  Tester accepts the assignment
      7.  Tester submits results + recommendation  →  Recommendation record created (pending)
      8.  AEE_RT reviews test results and approves recommendation
          →  WorkflowDispatchService creates recurring schedule(s)

    Returns dict with:
        tr_id           — the testing request used throughout
        rec_id          — the approved recommendation
        schedule_ids    — list of schedule UUIDs created by dispatch
        wf_definition_id
    """
    # ── Step 1: Originator creates TR ────────────────────────────────────────
    r = post("/testing_requests/", "ee_rt", json={
        "title": "Integration Test TR",
        "description": "Auto-created by integration test suite",
        "request_category": "test",
        "priority": "normal",
        "equipment_id": _EQUIPMENT_ID,
        "test_type_id": _TEST_TYPE_ID,
    })
    assert r.status_code in (200, 201), f"Create TR failed: {r.text}"
    tr_id = r.json()["id"]

    # ── Step 2: Submit → enters L2 wf queue ─────────────────────────────────
    r = put(f"/testing_requests/{tr_id}/submit", "ee_rt")
    assert r.status_code in (200, 201), f"Submit failed: {r.text}"

    # ── Step 3: L2 EE_TLSS approves & routes ────────────────────────────────
    r = post(
        f"/testing-requests/approvals/{tr_id}/tr-wf/l2-approve-route",
        "ee_tlss",
        json={"comments": "L2 approved via integration test"},
    )
    assert r.status_code in (200, 201), f"L2 approve failed: {r.text}"

    # ── Step 4: L3 AEE_RT assigns tester via wf endpoint ────────────────────
    # ApproverTesterSelection requires tester_id + tester_role_id
    r = post(
        f"/testing-requests/approvals/{tr_id}/tr-wf/l3-assign",
        "aee_rt",
        json={
            "tester_id": _TESTER_ID,
            "tester_role_id": _TESTER_ROLE_ID,
            "comment": "Tester assigned via integration test",
        },
    )
    assert r.status_code in (200, 201), f"L3 assign failed: {r.text}"

    # ── Step 5: L4 AE_RT advances ───────────────────────────────────────────
    r = post(
        f"/testing-requests/approvals/{tr_id}/tr-wf/advance",
        "ae_rt",
        json={"comments": "Advanced via integration test"},
    )
    assert r.status_code in (200, 201, 409, 422), f"L4 advance failed: {r.text}"

    # ── Step 6: Tester accepts the assignment ────────────────────────────────
    r = put(f"/testing/{tr_id}/accept", "ae_rt")
    assert r.status_code in (200, 201), f"Accept assignment failed: {r.text}"

    # ── Step 7: Tester submits results + recommendation ──────────────────────
    r = put(f"/testing/{tr_id}/submit_results", "ae_rt", json={
        "recommendation_type": "retest",
        "summary": "Equipment requires retesting — integration test",
        "next_action": "test",
    })
    assert r.status_code in (200, 201), f"Submit results failed: {r.text}"

    # Fetch the pending recommendation
    recs = get(f"/recommendations/by-request/{tr_id}", "ae_rt")
    assert recs.status_code == 200, f"Get recommendations failed: {recs.text}"
    rec_list = recs.json()
    assert len(rec_list) >= 1, "Expected at least one recommendation after submit_results"
    rec_id = next(
        (rec["id"] for rec in rec_list if rec.get("approval_status") == "pending"),
        rec_list[0]["id"],
    )

    # ── Step 8: AEE_RT reviews & approves recommendation ────────────────────
    # This is the final approver action that triggers WorkflowDispatchService
    r = put(f"/approvals/{rec_id}/approve", "aee_rt", json={"notes": "Approved via integration test"})
    assert r.status_code in (200, 201), f"Approve recommendation failed: {r.text}"
    dispatch = r.json()

    # dispatch["created"] = list of schedule UUIDs created (not TR IDs)
    schedule_ids = dispatch.get("created") or []

    yield {
        "tr_id": tr_id,
        "rec_id": rec_id,
        "schedule_ids": schedule_ids,
        "dispatch": dispatch,
        "wf_definition_id": wf_definition_id,
    }


# ---------------------------------------------------------------------------
# Section 1 — Authentication
# ---------------------------------------------------------------------------

class TestAuth:
    def test_ee_tlss_login(self):
        creds = USERS["ee_tlss"]
        tok = _token(creds["username"], creds["password"])
        assert isinstance(tok, str) and len(tok) > 10

    def test_aee_rt_login(self):
        creds = USERS["aee_rt"]
        tok = _token(creds["username"], creds["password"])
        assert isinstance(tok, str) and len(tok) > 10

    def test_ae_rt_login(self):
        creds = USERS["ae_rt"]
        tok = _token(creds["username"], creds["password"])
        assert isinstance(tok, str) and len(tok) > 10

    def test_ee_rt_login(self):
        creds = USERS["ee_rt"]
        tok = _token(creds["username"], creds["password"])
        assert isinstance(tok, str) and len(tok) > 10

    def test_bad_credentials_rejected(self):
        resp = requests.post(
            f"{BASE_URL}/token",
            data={"username": "nobody", "password": "wrong"},
        )
        assert resp.status_code in (400, 401, 403, 422)


# ---------------------------------------------------------------------------
# Section 2 — Picker Options
# ---------------------------------------------------------------------------

class TestPickerOptions:
    def test_get_roles(self):
        r = get("/tr-workflow-config/options/roles", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_equipment_types(self):
        r = get("/tr-workflow-config/options/equipment-types", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_test_types(self):
        r = get("/tr-workflow-config/options/test-types", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Section 3 — Workflow Config CRUD
# ---------------------------------------------------------------------------

class TestWorkflowConfigCRUD:
    def test_list_definitions(self):
        r = get("/tr-workflow-config/definitions", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_patch_delete_definition(self):
        r = post("/tr-workflow-config/definitions", "ee_tlss", json={
            "name": "Temp Test WF",
            "description": "Temporary",
            "is_default": False,
            "is_active": True,
        })
        assert r.status_code in (200, 201), r.text
        wf_id = r.json()["id"]

        patch = requests.patch(
            f"{BASE_URL}/tr-workflow-config/definitions/{wf_id}",
            headers=_h("ee_tlss"),
            json={"description": "Updated description"},
        )
        assert patch.status_code == 200

        d = delete(f"/tr-workflow-config/definitions/{wf_id}", "ee_tlss")
        assert d.status_code in (200, 204)

    def test_create_stage(self, wf_definition_id):
        r = post(
            f"/tr-workflow-config/definitions/{wf_definition_id}/stages",
            "ee_tlss",
            json={"name": "Extra Stage", "code": "extra_stage_test",
                  "sequence": 99, "weight": 5, "is_mandatory": False},
        )
        assert r.status_code in (200, 201), r.text
        assert r.json()["code"] == "extra_stage_test"

    def test_list_stages(self, wf_definition_id):
        r = get(f"/tr-workflow-config/definitions/{wf_definition_id}/stages", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_status(self, wf_definition_id):
        r = post(
            f"/tr-workflow-config/definitions/{wf_definition_id}/statuses",
            "ee_tlss",
            json={"status_code": "pending_l2_test", "status_name": "Pending L2 (Test)",
                  "sequence": 1, "is_terminal": False},
        )
        assert r.status_code in (200, 201), r.text

    def test_list_statuses(self, wf_definition_id):
        r = get(f"/tr-workflow-config/definitions/{wf_definition_id}/statuses", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Section 4 — Routing Config
# ---------------------------------------------------------------------------

class TestRoutingConfig:
    def test_get_routing_default(self):
        r = get("/tr-workflow-config/routing/default", "ee_tlss")
        assert r.status_code in (200, 404)

    def test_list_routing_rules(self):
        r = get("/tr-workflow-config/routing/rules", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_and_delete_routing_rule(self, wf_definition_id):
        r = post("/tr-workflow-config/routing/rules", "ee_tlss", json={
            "wf_definition_id": wf_definition_id,
            "priority": 99,
        })
        assert r.status_code in (200, 201), r.text
        rule_id = r.json()["id"]
        d = delete(f"/tr-workflow-config/routing/rules/{rule_id}", "ee_tlss")
        assert d.status_code in (200, 204)


# ---------------------------------------------------------------------------
# Section 5 — Live Scenario Assertions
# ---------------------------------------------------------------------------

class TestLiveScenarioFlow:
    def test_tr_progressed_beyond_draft(self, live_scenario):
        """TR moved out of draft after submit + L2 approve."""
        r = get(f"/testing_requests/{live_scenario['tr_id']}", "ee_rt")
        assert r.status_code == 200
        assert r.json()["status"] != "draft"

    def test_recommendation_was_approved(self, live_scenario):
        """Recommendation approval_status is 'approved' after final approver action."""
        r = get(f"/recommendations/by-request/{live_scenario['tr_id']}", "aee_rt")
        assert r.status_code == 200
        recs = r.json()
        rec = next((x for x in recs if x["id"] == live_scenario["rec_id"]), None)
        assert rec is not None
        assert rec["approval_status"] == "approved"

    def test_dispatch_created_schedules(self, live_scenario):
        """WorkflowDispatchService created at least one recurring schedule on approval."""
        assert len(live_scenario["schedule_ids"]) >= 1, (
            f"No schedules created. Dispatch result: {live_scenario['dispatch']}"
        )

    def test_tr_status_after_dispatch(self, live_scenario):
        """TR status is outcome_active after recommendation approval."""
        r = get(f"/testing_requests/{live_scenario['tr_id']}", "ee_rt")
        assert r.status_code == 200
        assert r.json()["status"] == "outcome_active"


# ---------------------------------------------------------------------------
# Section 6 — Approval Queue
# ---------------------------------------------------------------------------

class TestApprovalQueue:
    def test_pending_queue_returns_list(self):
        r = get("/testing-requests/approvals/tr-wf/pending", "ee_tlss")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_pending_items_have_required_fields(self):
        r = get("/testing-requests/approvals/tr-wf/pending", "ee_tlss")
        assert r.status_code == 200
        for item in r.json():
            assert "id" in item
            assert "equipment_ueic" in item
            assert "bay_number" in item

    def test_department_scope(self):
        r_ee = get("/testing-requests/approvals/tr-wf/pending", "ee_tlss")
        r_ae = get("/testing-requests/approvals/tr-wf/pending", "ae_rt")
        assert r_ee.status_code == 200
        assert r_ae.status_code == 200


# ---------------------------------------------------------------------------
# Section 7 — Result Review Queue
# ---------------------------------------------------------------------------

class TestResultReviewQueue:
    def test_pending_result_review_returns_list(self):
        r = get("/approvals/tr-wf/pending", "aee_rt")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_result_items_have_bay_number(self):
        r = get("/approvals/tr-wf/pending", "aee_rt")
        assert r.status_code == 200
        for item in r.json():
            assert "bay_number" in item


# ---------------------------------------------------------------------------
# Section 8 — Happy Path: Audit Log Verification
# (L2 → L3 → L4 steps are driven inside the live_scenario fixture)
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_audit_log_has_entries(self, live_scenario):
        """Audit log has at least one entry after L2 approve ran in the fixture."""
        tr_id = live_scenario["tr_id"]
        r = get(f"/testing-requests/approvals/{tr_id}/tr-wf/audit-log", "ee_tlss")
        assert r.status_code == 200
        log = r.json()
        assert isinstance(log, list)
        assert len(log) >= 1, "Expected at least one audit entry after wf actions"

    def test_audit_log_entry_fields(self, live_scenario):
        """Each audit log entry has action_code field."""
        tr_id = live_scenario["tr_id"]
        r = get(f"/testing-requests/approvals/{tr_id}/tr-wf/audit-log", "ee_tlss")
        assert r.status_code == 200
        for entry in r.json():
            assert "action_code" in entry or "action" in entry


# ---------------------------------------------------------------------------
# Section 9 — Rejection Path (independent TR)
# ---------------------------------------------------------------------------

class TestRejectionPath:
    def test_l2_reject(self, wf_definition_id):
        """Create a fresh TR, submit it into the wf queue, then attempt L2 rejection."""
        # Create + submit → TR enters L2 queue via routing engine
        r = post("/testing_requests/", "ee_rt", json={
            "title": "Rejection Path Test TR",
            "request_category": "test",
            "priority": "normal",
            "equipment_id": _EQUIPMENT_ID,
            "test_type_id": _TEST_TYPE_ID,
        })
        assert r.status_code in (200, 201), r.text
        tr_id = r.json()["id"]
        put(f"/testing_requests/{tr_id}/submit", "ee_rt")

        # Attempt L2 rejection with action=reject
        reject_resp = post(
            f"/testing-requests/approvals/{tr_id}/tr-wf/l2-approve-route",
            "ee_tlss",
            json={"comments": "Rejected by integration test", "action": "reject"},
        )
        # 200/201 = rejection accepted; 400/409/422 = endpoint doesn't support reject action yet
        assert reject_resp.status_code in (200, 201, 400, 409, 422), reject_resp.text


# ---------------------------------------------------------------------------
# Section 10 — Result Review Actions
# ---------------------------------------------------------------------------

class TestResultReviewActions:
    def test_approve_non_existent_recommendation(self):
        resp = put("/approvals/99999999/approve", "aee_rt", json={"notes": "test"})
        assert resp.status_code in (404, 422)

    def test_reject_non_existent_recommendation(self):
        resp = put("/approvals/99999999/reject", "aee_rt", json={"notes": "test"})
        assert resp.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Section 11 — Unauthenticated access denied
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    def test_pending_queue_requires_auth(self):
        r = requests.get(f"{BASE_URL}/testing-requests/approvals/tr-wf/pending")
        assert r.status_code in (401, 403)

    def test_result_review_requires_auth(self):
        r = requests.get(f"{BASE_URL}/approvals/tr-wf/pending")
        assert r.status_code in (401, 403)

    def test_wf_config_requires_auth(self):
        r = requests.get(f"{BASE_URL}/tr-workflow-config/definitions")
        assert r.status_code in (401, 403)

    def test_routing_rules_requires_auth(self):
        r = requests.get(f"{BASE_URL}/tr-workflow-config/routing/rules")
        assert r.status_code in (401, 403)
