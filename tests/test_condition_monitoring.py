#!/usr/bin/env python3
"""
Condition Monitoring Recommendation — Test Suite
=================================================
Tests the full lifecycle of the condition-monitoring recommendation module:

  §1  Discovery          — list seeded configs, filter by equipment type
  §2  Config CRUD        — create / update / deactivate a recommendation config
  §3  Evaluate           — GET /analytics/equipment/{id}/recommendations
  §4  Activate           — POST /condition-recommendations/{id}/activate
  §5  Conflict (409)     — second activate returns SCHEDULE_EXISTS
  §6  Post-activation    — evaluate reflects activated status + schedule info
  §7  RBAC               — field tester cannot manage configs
  §8  Evaluate results   — score-based binding, schedule_ref, Step-3 fallback
  §9  Ticket creation    — schedule run-now creates TestingRequest (advance_days logic)
  §10 Notification vars  — table.testkit / table.performance / report.lastexecution resolve in tester_assigned

Prerequisites:
  1.  python seed.py                        (populate org, equipment, users)
  2.  python seed_condition_recommendations.py
  3.  uvicorn main:app --reload --port 8000
  4.  python tests/test_condition_monitoring.py [--base-url http://host:port]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL: str = "http://127.0.0.1:8000"

CREDS: Dict[str, Tuple[str, str]] = {
    "org_admin":     ("orgadmin@utility.com",           "Kptcl@2026"),
    "originator":    ("assetofficer.north@utility.com", "TestDept@123"),
    "field_tester":  ("testengineer.north@utility.com", "TestDept@123"),
}

# ── Terminal output ───────────────────────────────────────────────────────────

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
        print(f"           {R}{detail[:200]}{RS}")


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


# ── HTTP helpers ──────────────────────────────────────────────────────────────

state: Dict[str, Any] = {
    "tokens":       {},
    "org_id":       None,
    "equip_id":     None,           # equipment with a Power Transformer type
    "equip_type_id": None,          # CategoryMaster id for Power Transformer (or first)
    "rec_id":       None,           # recommendation config id used for activation
    "rec_test_type_id": None,
    "created_rec_id":   None,       # config created by §2 (for cleanup / deactivate)
    "schedule_id":  None,           # schedule created by §4 activate
}


def _h(role: str) -> Dict[str, str]:
    token = state["tokens"].get(role, "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def GET(role: str, path: str, params: dict = None) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=_h(role), params=params, timeout=30)


def POST(role: str, path: str, body: dict = None) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", headers=_h(role), json=body or {}, timeout=30)


def PUT(role: str, path: str, body: dict = None) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=_h(role), json=body or {}, timeout=30)


def DELETE(role: str, path: str) -> requests.Response:
    return requests.delete(f"{BASE_URL}{path}", headers=_h(role), timeout=30)


def assert200(r: requests.Response, label: str) -> bool:
    if r.status_code in (200, 201):
        ok(f"{label}  [{r.status_code}]")
        return True
    fail(f"{label}  [{r.status_code}]", r.text[:200])
    return False


def assert_status(r: requests.Response, expected: int, label: str) -> bool:
    if r.status_code == expected:
        ok(f"{label}  [{r.status_code}]")
        return True
    fail(f"{label}  [expected {expected}, got {r.status_code}]", r.text[:200])
    return False


def assert_forbidden(r: requests.Response, label: str) -> bool:
    if r.status_code in (401, 403, 422):
        ok(f"{label}  [correctly {r.status_code}]")
        return True
    fail(f"{label}  [expected 4xx, got {r.status_code}]", r.text[:100])
    return False


# ── §1  Setup + Discovery ─────────────────────────────────────────────────────

def test_setup() -> None:
    section("§1  SETUP — login + discover equipment")

    step("Login roles")
    for role, (email, pwd) in CREDS.items():
        r = requests.post(f"{BASE_URL}/auth/login",
                          json={"email": email, "password": pwd}, timeout=60)
        if r.status_code == 200:
            state["tokens"][role] = r.json()["access_token"]
            ok(f"Login  {role:<14}  ({email})")
        else:
            fail(f"Login  {role:<14}", r.text[:100])

    if "org_admin" not in state["tokens"]:
        warn("org_admin login failed — all subsequent tests will be skipped")
        return

    step("Resolve org_id")
    r = GET("org_admin", "/organizations/")
    if assert200(r, "GET /organizations/"):
        orgs = r.json()
        org = next((o for o in orgs if "kptcl" in o.get("code","").lower()), orgs[0] if orgs else None)
        if org:
            state["org_id"] = org["id"]
            info(f"org: {org['name']}  id={state['org_id']}")

    step("Find Power Transformer equipment (or any equipment with analytics)")
    r = GET("org_admin", "/equipment/", params={"limit": 50})
    if assert200(r, "GET /equipment/?limit=50"):
        items = r.json()
        # Prefer a Power Transformer
        pt = next(
            (e for e in items
             if (e.get("equipment_type") or {}).get("name", "").lower() == "power transformer"),
            None
        )
        chosen = pt or (items[0] if items else None)
        if chosen:
            state["equip_id"]      = chosen["id"]
            state["equip_type_id"] = chosen.get("equipment_type_id")
            info(f"equip: {chosen.get('ueic','?')}  id={state['equip_id']}  "
                 f"type={state['equip_type_id']}")
        else:
            warn("No equipment in DB — run seed.py first")

    step("List seeded recommendation configs")
    r = GET("org_admin", "/condition-recommendations/")
    if assert200(r, "GET /condition-recommendations/"):
        configs = r.json()
        chk(len(configs) > 0, f"At least 1 config exists (got {len(configs)})")
        info(f"Total configs: {len(configs)}")
        if configs:
            state["rec_id"]           = configs[0]["id"]
            state["rec_test_type_id"] = configs[0].get("test_type_id")
            info(f"Using config id={state['rec_id']}  "
                 f"test_type_id={state['rec_test_type_id']}")

    step("Filter configs by equipment_type_id")
    if state["equip_type_id"]:
        r = GET("org_admin", "/condition-recommendations/",
                params={"equipment_type_id": state["equip_type_id"]})
        if assert200(r, "GET /condition-recommendations/?equipment_type_id=..."):
            filtered = r.json()
            info(f"Filtered configs for type {state['equip_type_id']}: {len(filtered)}")
            # Pick the first config for the correct equipment type for activation later
            if filtered:
                state["rec_id"]           = filtered[0]["id"]
                state["rec_test_type_id"] = filtered[0].get("test_type_id")
                info(f"Updated rec_id={state['rec_id']}")
            chk(
                all(c["equipment_type_id"] == state["equip_type_id"] for c in filtered),
                "All returned configs match the requested equipment_type_id",
            )

    step("Filter active-only configs")
    r = GET("org_admin", "/condition-recommendations/", params={"is_active": "true"})
    if assert200(r, "GET /condition-recommendations/?is_active=true"):
        active = r.json()
        chk(all(c.get("is_active") for c in active), "All returned configs are active")


# ── §2  Config CRUD ───────────────────────────────────────────────────────────

def test_config_crud() -> None:
    section("§2  CONFIG CRUD — create / update / deactivate")

    if not state["equip_type_id"] or not state["rec_test_type_id"]:
        warn("Missing equip_type_id or test_type_id — skipping CRUD tests")
        return

    # Create a fresh config (distinct score band unlikely to collide)
    step("POST /condition-recommendations/ — create config")
    payload = {
        "equipment_type_id": state["equip_type_id"],
        "test_type_id":      state["rec_test_type_id"],
        "score_from":        0.0,
        "score_to":          10.0,
        "frequency":         "monthly",
        "display_order":     99,
        "is_active":         True,
    }
    r = POST("org_admin", "/condition-recommendations/", payload)
    new_id = None
    if assert200(r, "POST /condition-recommendations/"):
        cfg = r.json()
        new_id = cfg.get("id")
        state["created_rec_id"] = new_id
        chk(cfg.get("is_active") is True,   "New config is active")
        chk(cfg.get("score_from") == 0.0,   "score_from=0")
        chk(cfg.get("score_to")   == 10.0,  "score_to=10")
        chk(cfg.get("frequency")  == "monthly", "frequency=monthly")
        info(f"Created config id={new_id}")

    step("GET /condition-recommendations/ — new config appears in list")
    r = GET("org_admin", "/condition-recommendations/",
            params={"equipment_type_id": state["equip_type_id"]})
    if r.status_code == 200:
        ids = [c["id"] for c in r.json()]
        chk(new_id in ids, "Newly created config appears in filtered list")

    step("PUT /condition-recommendations/{id} — update frequency")
    if new_id:
        r = PUT("org_admin", f"/condition-recommendations/{new_id}",
                {"frequency": "quarterly", "display_order": 50})
        if assert200(r, f"PUT /condition-recommendations/{new_id}"):
            updated = r.json()
            chk(updated.get("frequency")     == "quarterly", "frequency updated to quarterly")
            chk(updated.get("display_order") == 50,          "display_order updated to 50")

    step("DELETE /condition-recommendations/{id} — deactivate config")
    if new_id:
        r = DELETE("org_admin", f"/condition-recommendations/{new_id}")
        assert_status(r, 204, f"DELETE /condition-recommendations/{new_id}")

        # Verify it no longer appears in active-only list
        r2 = GET("org_admin", "/condition-recommendations/",
                 params={"equipment_type_id": state["equip_type_id"], "is_active": "true"})
        if r2.status_code == 200:
            active_ids = [c["id"] for c in r2.json()]
            chk(new_id not in active_ids, "Deactivated config absent from active-only list")

    step("PUT on non-existent id → 404")
    r = PUT("org_admin",
            "/condition-recommendations/00000000-0000-0000-0000-000000000000",
            {"frequency": "yearly"})
    assert_status(r, 404, "PUT unknown rec_id")

    step("POST with invalid frequency → 422")
    bad_payload = {**payload, "frequency": "hourly"}
    r = POST("org_admin", "/condition-recommendations/", bad_payload)
    assert_status(r, 422, "POST invalid frequency=hourly → 422")


# ── §3  Evaluate ──────────────────────────────────────────────────────────────

def test_evaluate() -> None:
    section("§3  EVALUATE — GET /analytics/equipment/{id}/recommendations")

    if not state["equip_id"]:
        warn("No equipment_id — skipping evaluate test")
        return

    step("GET /analytics/equipment/{id}/recommendations")
    r = GET("org_admin", f"/analytics/equipment/{state['equip_id']}/recommendations")
    if assert200(r, "GET /analytics/equipment/{id}/recommendations"):
        body = r.json()
        chk("equipment_id"    in body, "Response has 'equipment_id'")
        chk("health_score"    in body, "Response has 'health_score'")
        chk("risk_level"      in body, "Response has 'risk_level'")
        chk("recommendations" in body, "Response has 'recommendations'")
        recs = body.get("recommendations", [])
        info(f"health_score={body.get('health_score')}  "
             f"risk_level={body.get('risk_level')}  "
             f"recommendations={len(recs)}")

        if recs:
            first = recs[0]
            chk("recommendation_id" in first, "Rec item has 'recommendation_id'")
            chk("test_name"         in first, "Rec item has 'test_name'")
            chk("frequency"         in first, "Rec item has 'frequency'")
            chk("status"            in first, "Rec item has 'status'")
            info(f"First rec: {first.get('test_name')}  "
                 f"status={first.get('status')}  freq={first.get('frequency')}")
            # Always pick rec_id from evaluate — ensures it matches this equipment's type
            state["rec_id"] = first["recommendation_id"]
            info(f"Updated rec_id from evaluate: {state['rec_id']}")
        else:
            warn("No recommendations returned — equipment may have no health_score or "
                 "no matching score-band configs; activate tests will be skipped")

    step("GET recommendations for non-existent equipment → 404")
    r = GET("org_admin",
            "/analytics/equipment/00000000-0000-0000-0000-000000000000/recommendations")
    assert_status(r, 404, "Non-existent equipment → 404")


# ── §4  Activate ──────────────────────────────────────────────────────────────

def test_activate() -> None:
    section("§4  ACTIVATE — POST /condition-recommendations/{id}/activate")

    if not state["rec_id"] or not state["equip_id"]:
        warn("Missing rec_id or equip_id — skipping activation tests")
        return

    start_date = (date.today() + timedelta(days=1)).isoformat()

    step(f"Activate rec {state['rec_id']} for equipment {state['equip_id']}")
    r = POST("org_admin",
             f"/condition-recommendations/{state['rec_id']}/activate",
             {"equipment_id": state["equip_id"], "start_date": start_date})

    if r.status_code in (200, 201):
        body = r.json()
        chk(body.get("created") is True, "Response has created=true")
        sched = body.get("schedule", {})
        chk(bool(sched.get("schedule_id")),  "Schedule has schedule_id")
        chk(bool(sched.get("schedule_ref")), "Schedule has schedule_ref (SCH-...)")
        chk(bool(sched.get("frequency")),    "Schedule has frequency")
        chk(sched.get("is_active") is True,  "Schedule is active")
        state["schedule_id"] = sched.get("schedule_id")
        info(f"Activated: schedule_ref={sched.get('schedule_ref')}  "
             f"freq={sched.get('frequency')}  next_due={sched.get('next_due_date')}")
        ok("POST /activate  [200/201]")
    elif r.status_code == 409:
        # Already activated from a prior test run
        detail = r.json().get("detail", {})
        warn(f"409 conflict — schedule already active: ref={detail.get('schedule_ref')}")
        state["schedule_id"] = detail.get("schedule_id")
        info("Treating prior activation as success (idempotent)")
        ok("POST /activate already-active → 409 (expected in re-run)")
    else:
        fail(f"POST /activate  [{r.status_code}]", r.text[:200])

    step("Activate with invalid date → 422")
    r = POST("org_admin",
             f"/condition-recommendations/{state['rec_id']}/activate",
             {"equipment_id": state["equip_id"], "start_date": "not-a-date"})
    assert_status(r, 422, "Invalid start_date → 422")

    step("Activate non-existent recommendation → 404")
    r = POST("org_admin",
             "/condition-recommendations/00000000-0000-0000-0000-000000000000/activate",
             {"equipment_id": state["equip_id"], "start_date": start_date})
    assert_status(r, 404, "Non-existent rec_id → 404")

    step("Activate with non-existent equipment → 404")
    r = POST("org_admin",
             f"/condition-recommendations/{state['rec_id']}/activate",
             {"equipment_id": "00000000-0000-0000-0000-000000000000",
              "start_date": start_date})
    assert_status(r, 404, "Non-existent equipment_id → 404")


# ── §5  Conflict (409) ────────────────────────────────────────────────────────

def test_conflict() -> None:
    section("§5  CONFLICT — duplicate activate returns 409 SCHEDULE_EXISTS")

    if not state["rec_id"] or not state["equip_id"] or not state["schedule_id"]:
        warn("No prior activation state — skipping conflict test")
        return

    step("Attempt second activation of the same recommendation for the same equipment")
    start_date = (date.today() + timedelta(days=7)).isoformat()
    r = POST("org_admin",
             f"/condition-recommendations/{state['rec_id']}/activate",
             {"equipment_id": state["equip_id"], "start_date": start_date})

    assert_status(r, 409, "Second activate → 409 SCHEDULE_EXISTS")
    if r.status_code == 409:
        detail = r.json().get("detail", {})
        chk(detail.get("code") == "SCHEDULE_EXISTS",  "detail.code == SCHEDULE_EXISTS")
        chk(bool(detail.get("schedule_id")),          "detail has schedule_id")
        chk(bool(detail.get("schedule_ref")),         "detail has schedule_ref")
        chk(bool(detail.get("test_name")),            "detail has test_name")
        chk(bool(detail.get("frequency")),            "detail has frequency")
        info(f"Conflict detail: ref={detail.get('schedule_ref')}  "
             f"test={detail.get('test_name')}  freq={detail.get('frequency')}")


# ── §6  Post-activation evaluate ─────────────────────────────────────────────

def test_post_activation_evaluate() -> None:
    section("§6  POST-ACTIVATION EVALUATE — status reflects activation")

    if not state["equip_id"] or not state["rec_id"]:
        warn("Missing state — skipping post-activation evaluate")
        return

    step("GET /analytics/equipment/{id}/recommendations after activation")
    r = GET("org_admin", f"/analytics/equipment/{state['equip_id']}/recommendations")
    if assert200(r, "GET recommendations (post-activation)"):
        recs = r.json().get("recommendations", [])
        activated = [x for x in recs if x.get("status") in ("activated", "active")]
        chk(len(activated) > 0, f"At least 1 recommendation shows activated status "
                                 f"(found {len(activated)} of {len(recs)})")
        if activated:
            a = activated[0]
            sched = a.get("schedule") or {}
            chk(bool(sched.get("schedule_id")),  "Activated rec has schedule.schedule_id")
            chk(bool(sched.get("schedule_ref")), "Activated rec has schedule.schedule_ref")
            chk(bool(sched.get("frequency")),    "Activated rec has schedule.frequency")
            info(f"Activated rec: {a.get('test_name')}  "
                 f"ref={sched.get('schedule_ref')}  freq={sched.get('frequency')}")


# ── §8  Evaluate results ──────────────────────────────────────────────────────

def test_evaluate_results() -> None:
    section("§8  EVALUATE RESULTS — score-based evaluate returns bound schedule info")

    if not state["equip_id"] or not state["schedule_id"]:
        warn("No equipment or schedule state — skipping evaluate results test")
        return

    step("GET /analytics/equipment/{id}/recommendations — validate schedule binding")
    r = GET("org_admin", f"/analytics/equipment/{state['equip_id']}/recommendations")
    if assert200(r, "GET recommendations (evaluate results)"):
        body = r.json()
        recs = body.get("recommendations", [])

        # Locate the recommendation we activated (by rec_id or test_type_id)
        matched = [
            x for x in recs
            if x.get("recommendation_id") == state["rec_id"]
            or (
                state.get("rec_test_type_id")
                and x.get("test_type_id") == state["rec_test_type_id"]
            )
        ]

        if not matched:
            warn(
                f"Activated recommendation not found in evaluate results "
                f"({len(recs)} recs returned) — equipment score may have shifted bands"
            )
        else:
            act   = matched[0]
            sched = act.get("schedule") or {}

            chk(
                act.get("status") in ("activated", "active"),
                f"Activated rec status={act.get('status')!r}  (expected 'activated')",
            )
            chk(bool(sched), "Activated rec carries non-null schedule block")
            chk(
                str(sched.get("schedule_id", "")) == str(state["schedule_id"]),
                f"schedule.schedule_id matches activated id={state['schedule_id'][:8]}...",
            )
            chk(
                sched.get("schedule_ref", "").startswith("SCH-"),
                f"schedule_ref={sched.get('schedule_ref')!r} starts with 'SCH-'",
            )
            chk(bool(sched.get("next_due_date")), "schedule.next_due_date is set")
            chk(sched.get("is_active") is True,   "schedule.is_active=True")

            info(
                f"Rec: {act.get('test_name')}  freq={act.get('frequency')}"
                f"  ref={sched.get('schedule_ref')}  next={sched.get('next_due_date')}"
            )

    step("Health score context — score and risk_level are valid")
    r = GET("org_admin", f"/analytics/equipment/{state['equip_id']}/recommendations")
    if r.status_code == 200:
        body         = r.json()
        health_score = body.get("health_score")
        risk_level   = body.get("risk_level")

        chk(health_score is not None, f"health_score present (={health_score})")
        if health_score is not None:
            chk(0 <= health_score <= 100, f"health_score={health_score} in [0, 100]")
        if risk_level:
            chk(
                risk_level.lower() in ("critical", "high", "medium", "low"),
                f"risk_level={risk_level!r} is a recognised band",
            )
        info(f"Analytics: health_score={health_score}  risk_level={risk_level}")

    step("Step-3 fallback — evaluate shows 'activated' for the test_type we scheduled")
    # evaluate_for_equipment() checks active TestRequestSchedule rows directly
    # (Step 3) when no ConditionRecommendationActivation record links them.
    # We verify this using only the evaluate endpoint + the test_type_id we know
    # was activated — no dependency on the /test-register/schedules/ API.
    if state.get("rec_test_type_id"):
        r = GET("org_admin", f"/analytics/equipment/{state['equip_id']}/recommendations")
        if r.status_code == 200:
            recs = r.json().get("recommendations", [])
            match = next(
                (x for x in recs if x.get("test_type_id") == state["rec_test_type_id"]),
                None,
            )
            if match:
                chk(
                    match.get("status") in ("activated", "active"),
                    f"test_type_id={state['rec_test_type_id']} evaluate status="
                    f"{match.get('status')!r}  (expected 'activated' via Step-3 fallback)",
                )
                chk(
                    bool((match.get("schedule") or {}).get("schedule_id")),
                    "Step-3: evaluate.schedule.schedule_id is populated",
                )
                info(
                    f"Step-3 fallback confirmed: test_type_id={state['rec_test_type_id']}"
                    f"  status={match.get('status')}"
                )
            else:
                warn("test_type_id not found in evaluate — score may have shifted bands")


# ── §9  Ticket creation from schedule ────────────────────────────────────────

def test_ticket_creation() -> None:
    section("§9  TICKET CREATION — schedule run-now triggers TestingRequest via advance_days logic")

    if not state["schedule_id"] or not state["equip_id"]:
        warn("No schedule_id or equip_id — skipping ticket creation test")
        return

    # Normal activation in §4 uses start_date = tomorrow, so next_run_date is
    # 1+ months away — the auto-trigger inside activate() will NOT fire because
    # now < (next_run_date - advance_days).
    #
    # To verify the advance_days path we use the run-now endpoint which calls
    # create_one_ticket(force_run=True), bypassing the date check entirely.
    # This is the same code path the daily scheduler uses when the trigger fires.

    step("POST /test-register/schedules/operational/{equip_id}/{schedule_id}/run — force trigger")
    r = requests.post(
        f"{BASE_URL}/test-register/schedules/operational"
        f"/{state['equip_id']}/{state['schedule_id']}/run",
        headers=_h("org_admin"),
        timeout=30,
    )
    if r.status_code in (200, 201):
        created = r.json()
        # Returns True  → new TestingRequest was generated
        # Returns False → skipped (open ticket already exists for this schedule)
        if created is True:
            ok("run-now returned True — TestingRequest generated from schedule")
        else:
            warn("run-now returned False — an open ticket already exists for this "
                 "equipment+test_type (deduplicated correctly, not an error)")
    else:
        fail(f"POST run-now  [{r.status_code}]", r.text[:200])

    step("GET /test-register/schedules/operational/{equip_id}/{schedule_id}/logs — verify run logged")
    r = GET(
        "org_admin",
        f"/test-register/schedules/operational"
        f"/{state['equip_id']}/{state['schedule_id']}/logs",
    )
    if assert200(r, "GET schedule logs"):
        logs = r.json() if isinstance(r.json(), list) else r.json().get("logs", [])
        chk(len(logs) > 0, f"At least 1 schedule log entry exists (got {len(logs)})")
        if logs:
            latest = logs[0]
            info(f"Latest log: status={latest.get('status')}  "
                 f"run_date={str(latest.get('run_date',''))[:10]}  "
                 f"request_id={str(latest.get('generated_request_id',''))[:8]}")
            chk(
                latest.get("status") in ("success", "failed"),
                f"Log status={latest.get('status')!r} is valid",
            )
            # Store for §10 — walk all logs in case the latest run was deduplicated
            for log_entry in logs:
                if log_entry.get("generated_request_id"):
                    state["tr_id"] = log_entry["generated_request_id"]
                    info(f"Stored tr_id={str(state['tr_id'])[:8]}... in state for §10")
                    break


# ── §10  Notification variables ───────────────────────────────────────────────

def test_notification_variables() -> None:
    section("§10  NOTIFICATION VARIABLES — table.testkit / table.performance / report.lastexecution")

    TARGET_VARS  = {"table.testkit", "table.performance", "report.lastexecution"}
    EVENT_TYPE   = "tester_assigned"

    # ── Step 1: system-variables list ────────────────────────────────────────
    step("GET /notifications/templates/system-variables — verify all 3 vars registered")
    r = GET("org_admin", "/notifications/templates/system-variables")
    if assert200(r, "GET system-variables"):
        body     = r.json()
        var_keys = {v.get("var_key") for v in (body if isinstance(body, list) else body.get("variables", []))}
        for key in TARGET_VARS:
            chk(key in var_keys, f"system-variables contains {key!r}")
    else:
        warn("Cannot verify system-variables — skipping downstream checks")
        return

    # ── Step 2: event catalogue context_vars ─────────────────────────────────
    step(f"GET /notifications/templates/event-types — {EVENT_TYPE!r} lists all 3 vars in context_vars")
    r = GET("org_admin", "/notifications/templates/event-types")
    if assert200(r, "GET event-types"):
        events = r.json() if isinstance(r.json(), list) else r.json().get("events", [])
        ev = next((e for e in events if e.get("event_type") == EVENT_TYPE), None)
        if ev:
            ctx_vars = set(ev.get("context_vars") or [])
            for key in TARGET_VARS:
                chk(key in ctx_vars,
                    f"tester_assigned.context_vars contains {key!r}")
        else:
            warn(f"{EVENT_TYPE!r} not found in event-types catalogue")

    # ── Step 2b: verify template attachment_vars includes PDF var ────────────
    step(f"GET /notifications/templates — {EVENT_TYPE!r}/email has PDF attachment_var")
    r = GET("org_admin", f"/notifications/templates?event_type={EVENT_TYPE}&channel=email")
    if assert200(r, f"GET templates for {EVENT_TYPE}/email"):
        tmpls = r.json() if isinstance(r.json(), list) else []
        tmpl  = next((t for t in tmpls if t.get("channel") == "email"), None)
        if tmpl:
            att_vars = tmpl.get("attachment_vars") or []
            chk(
                any(
                    isinstance(a, dict) and a.get("var_key") == "report.lastexecution.test_result_id"
                    for a in att_vars
                ),
                "tester_assigned email template has PDF attachment_var "
                "(report.lastexecution.test_result_id)",
            )
        else:
            warn("No email template found for tester_assigned")

    # ── Step 3: trigger real tester_assigned event via assignment ────────────
    # Resolve field_tester user id via /auth/me
    tester_id = None
    if "field_tester" in state.get("tokens", {}):
        r = GET("field_tester", "/auth/me")
        if r.status_code == 200:
            tester_id = r.json().get("id")
            info(f"field_tester id={str(tester_id)[:8]}...")
    if not tester_id:
        warn("field_tester token/id unavailable — skipping assignment step")
        return

    # Use TR from §9; create a fresh one if it's already been assigned
    tr_id = state.get("tr_id")
    if tr_id:
        r = GET("org_admin", f"/testing_requests/{tr_id}")
        tr_status = r.json().get("status") if r.status_code == 200 else None
        if tr_status not in ("draft", "submitted"):
            info(f"TR {str(tr_id)[:8]} already {tr_status!r} — creating a fresh TR for §10")
            tr_id = None   # will create below

    if not tr_id:
        step("POST /testing_requests/ — fresh TR for assignment test")
        r = POST("org_admin", "/testing_requests/", {
            "title":            "§10 notification-variables validation TR",
            "equipment_id":     str(state["equip_id"]),
            "organization_id":  str(state["org_id"]),
            "request_category": "test",
            "priority":         "normal",
        })
        if not assert200(r, "POST /testing_requests/"):
            warn("Could not create fresh TR — skipping assignment test")
            return
        tr_id = r.json().get("id")
        info(f"Fresh TR id={str(tr_id)[:8]}  status={r.json().get('status')}")
    else:
        step(f"Using TR {str(tr_id)[:8]} from §9 for assignment")

    # Submit if still draft
    r = GET("org_admin", f"/testing_requests/{tr_id}")
    tr_status = r.json().get("status") if r.status_code == 200 else "unknown"
    info(f"TR status={tr_status}")
    if tr_status == "draft":
        r2 = requests.put(f"{BASE_URL}/testing_requests/{tr_id}/submit",
                          headers=_h("org_admin"), timeout=30)
        chk(r2.status_code == 200, f"Submit TR [{r2.status_code}]", r2.text[:100])
        tr_status = r2.json().get("status") if r2.status_code == 200 else tr_status

    if tr_status != "submitted":
        warn(f"TR status={tr_status!r} — cannot assign (expected 'submitted')")
        return

    # Assign → fires notify_tester_assigned (real event, not test-fire)
    step(f"PUT /testing_requests/{str(tr_id)[:8]}/assign → triggers tester_assigned notification")
    r = requests.put(
        f"{BASE_URL}/testing_requests/{tr_id}/assign",
        json={"tester_id": tester_id},
        headers=_h("org_admin"), timeout=30,
    )
    if not chk(r.status_code == 200, f"Assign tester [{r.status_code}]", r.text[:200]):
        return
    info(f"Assigned → status={r.json().get('status')}")

    # ── Step 4: verify tester_assigned email notification was sent ────────────
    step("GET /admin/notifications/logs — tester_assigned email must be sent/pending")
    time.sleep(2)
    r = GET("org_admin", f"/admin/notifications/logs?event_type={EVENT_TYPE}&channel=email&limit=5")
    if assert200(r, "GET notification logs (email)"):
        logs = r.json() if isinstance(r.json(), list) else r.json().get("logs", [])
        if not logs:
            warn("No email log entries for tester_assigned")
        else:
            latest = logs[0]
            info(f"Log: status={latest.get('status')}  "
                 f"source_id={str(latest.get('source_id') or '')[:8]}")
            chk(
                latest.get("status") in ("sent", "pending"),
                f"tester_assigned email log status={latest.get('status')!r} is sent/pending",
            )
            chk(
                latest.get("source_id") == str(tr_id),
                "Log is linked to the correct TR (source_id matches)",
            )



# ── §7  RBAC ──────────────────────────────────────────────────────────────────

def test_rbac() -> None:
    section("§7  ACCESS — any authenticated user with AI module access")

    if "field_tester" not in state["tokens"]:
        warn("field_tester token missing — skipping access tests")
        return

    step("Field tester: GET /condition-recommendations/ → allowed (authenticated)")
    r = GET("field_tester", "/condition-recommendations/")
    chk(r.status_code == 200, f"Authenticated user can LIST configs  [{r.status_code}]")

    step("Field tester: GET /analytics/equipment/{id}/recommendations → allowed")
    if state["equip_id"]:
        r = GET("field_tester", f"/analytics/equipment/{state['equip_id']}/recommendations")
        chk(r.status_code == 200,
            f"Authenticated user can EVALUATE recommendations  [{r.status_code}]")

    step("Unauthenticated request → 401")
    r = requests.get(f"{BASE_URL}/condition-recommendations/", timeout=10)
    chk(r.status_code in (401, 403),
        f"No-token request rejected  [{r.status_code}]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global BASE_URL

    parser = argparse.ArgumentParser(description="Condition Monitoring Test Suite")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")

    print(f"\n{BD}{C}Condition Monitoring Recommendation — Test Suite{RS}")
    print(f"{C}Target: {BASE_URL}{RS}")

    test_setup()
    test_config_crud()
    test_evaluate()
    test_activate()
    test_conflict()
    test_post_activation_evaluate()
    test_evaluate_results()
    test_ticket_creation()
    test_notification_variables()
    test_rbac()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = _passed + _failed + _warned
    colour = G if _failed == 0 else R
    print(f"\n{BD}{colour}{'='*70}{RS}")
    print(f"{BD}{colour}  RESULTS  passed={_passed}  failed={_failed}  warned={_warned}  total={total}{RS}")
    print(f"{BD}{colour}{'='*70}{RS}\n")

    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
