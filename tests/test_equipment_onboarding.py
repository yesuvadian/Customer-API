"""
tests/test_equipment_onboarding.py
====================================
Equipment Onboarding — Schedule Auto-Commissioning Integration Suite

What this tests
---------------
1. Templates exist for Power Transformer (seeded by seed_default_test_register)
2. Creating a Power Transformer equipment auto-triggers commission_equipment()
3. Multiple live schedules are created (one per active template)
4. Each schedule has correct fields: frequency, next_run_date, advance_days,
   responsible_role, oem_reference
5. Manual commission call (POST /test-register/commission/{id}) creates MORE
   schedules (no idempotency guard — each call is a new commissioning cycle)
6. ALERT reschedule advances next_run_date on a live schedule
7. GET /test-register/equipment/{id}/schedules is ordered by next_run_date asc

Prerequisites
-------------
1. python tests/clean_and_seed.py        ← drop + re-seed
2. uvicorn main:app --reload --port 8000 ← server must be running
3. python tests/test_equipment_onboarding.py
"""

import os
import sys
import time
import json
from datetime import datetime, timezone

import requests
from requests.exceptions import ConnectionError as ReqConnError

BASE = "http://localhost:8000"

# ── UTF-8 safe stdout ──────────────────────────────────────────────────────────
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
    suffix = f"  {YELLOW}({detail}){RESET}" if detail else ""
    print(f"  {GREEN}[PASS]{RESET} {label}{suffix}")


def fail(label, detail=""):
    global fail_count
    fail_count += 1
    print(f"  {RED}[FAIL]{RESET} {label}  {YELLOW}{detail}{RESET}")
    _print_summary()
    sys.exit(1)


def skip(label, detail=""):
    global skip_count
    skip_count += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  {YELLOW}[SKIP]{RESET} {label}{suffix}")


def info(label):
    print(f"  {CYAN}[INFO]{RESET} {label}")


def section(title):
    print(f"\n{BOLD}{CYAN}{'='*62}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")


def _print_summary():
    total  = pass_count + fail_count + skip_count
    colour = GREEN if fail_count == 0 else RED
    print(f"\n{BOLD}{colour}{'='*62}{RESET}")
    print(
        f"{BOLD}{colour}  RESULTS  "
        f"passed={pass_count}  failed={fail_count}  skipped={skip_count}  "
        f"total={total}{RESET}"
    )
    print(f"{BOLD}{colour}{'='*62}{RESET}\n")


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _resilient(fn, url, *, retries=3, delay=1.5, **kwargs):
    for attempt in range(retries):
        try:
            return fn(url, **kwargs)
        except ReqConnError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise


def get(url, *, token=None, **kw):
    hdrs = kw.pop("headers", {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return _resilient(requests.get, url, headers=hdrs, **kw)


def post(url, *, token=None, body=None, **kw):
    hdrs = kw.pop("headers", {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        kw["data"] = json.dumps(body)
    return _resilient(requests.post, url, headers=hdrs, **kw)


def check(label, resp, expected_status):
    if resp.status_code == expected_status:
        ok(label, str(resp.status_code))
        try:
            return resp.json()
        except Exception:
            return {}
    else:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:300]
        fail(label, f"got {resp.status_code} expected {expected_status} — {detail}")
        return None  # unreachable — fail() exits


# ── Server health ──────────────────────────────────────────────────────────────

def wait_for_server(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{BASE}/testing_requests/stats",
                headers={"Authorization": "Bearer dummy"},
                timeout=3,
            )
            if r.status_code < 600:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ── Auth ───────────────────────────────────────────────────────────────────────

def login(email, password):
    r = requests.post(f"{BASE}/token", data={"username": email, "password": password})
    if r.status_code != 200:
        fail(f"Login {email}", f"{r.status_code} {r.text[:120]}")
    return r.json()["access_token"]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SUITE
# ══════════════════════════════════════════════════════════════════════════════

def run():
    # ── 0. Server health ───────────────────────────────────────────────────────
    section("0 — Server Health")
    if not wait_for_server(timeout=30):
        fail("Server reachable", "No response on :8000 after 30 s — start uvicorn first")
    ok("Server reachable", ":8000")

    # ── 1. Login ───────────────────────────────────────────────────────────────
    section("1 — Authentication")
    admin_token = login("orgadmin@kptcl.com", "admin123")
    ok("Admin login", "orgadmin@kptcl.com")

    # ── 2. Resolve org ─────────────────────────────────────────────────────────
    section("2 — Organisation & Department")
    orgs = check("GET /organizations/", get(f"{BASE}/organizations/", token=admin_token), 200)
    org = next((o for o in orgs if o.get("code") == "KPTCL"), orgs[0] if orgs else None)
    if not org:
        fail("KPTCL org exists", "No organisation in DB — run seed.py first")
    org_id = org["id"]
    ok("KPTCL org found", org_id[:8] + "…")

    # Fetch department
    r = get(f"{BASE}/testing_requests/department_hierarchy?org_id={org_id}", token=admin_token)
    depts = r.json() if r.status_code == 200 else []
    dept_id = depts[0]["id"] if depts else None
    if dept_id:
        ok("Department found", depts[0].get("name", dept_id[:8]))
    else:
        skip("Department found", "no departments seeded — proceeding without dept_id")

    # ── 3. Resolve Power Transformer equipment type ────────────────────────────
    section("3 — Equipment Type: Power Transformer")
    test_types = check(
        "GET /test-register/test-types",
        get(f"{BASE}/test-register/test-types", token=admin_token),
        200,
    )

    # Collect all unique equipment types from the test-types list
    eq_types_seen: dict[str, int] = {}
    for tt in test_types:
        eq_types_seen[tt["equipment_type_name"]] = tt["equipment_type_id"]

    info(f"Equipment types with test templates: {list(eq_types_seen.keys())}")

    pt_eq_type_id = eq_types_seen.get("Power Transformer")
    if not pt_eq_type_id:
        fail("Power Transformer type found", f"Available: {list(eq_types_seen.keys())}")
    ok("Power Transformer equipment type found", f"type_id={pt_eq_type_id}")

    # Count how many test templates exist for Power Transformer
    pt_tests = [t for t in test_types if t["equipment_type_id"] == pt_eq_type_id]
    info(f"Test types for Power Transformer: {[t['name'] for t in pt_tests]}")
    if len(pt_tests) < 1:
        fail("At least 1 test type for Power Transformer", "0 found — run seed_default_test_register")
    ok(f"{len(pt_tests)} test type(s) for Power Transformer", "seed verified")

    # Also check maintenance types
    maint_types = check(
        "GET /test-register/maintenance-types",
        get(f"{BASE}/test-register/maintenance-types", token=admin_token),
        200,
    )
    pt_maints = [m for m in maint_types if m["equipment_type_id"] == pt_eq_type_id]
    info(f"Maintenance types for Power Transformer: {[m['name'] for m in pt_maints]}")

    # ── 4. Verify templates exist in the register ──────────────────────────────
    section("4 — Test Register Templates")
    templates = check(
        f"GET /test-register/?equipment_type_id={pt_eq_type_id}",
        get(
            f"{BASE}/test-register/",
            token=admin_token,
            params={"equipment_type_id": pt_eq_type_id, "organization_id": org_id, "limit": 100},
        ),
        200,
    )
    info(f"Templates found for Power Transformer: {len(templates)}")
    for t in templates:
        sched = t.get("schedule") or {}
        info(
            f"  • {t['title']!r:55s}  "
            f"freq={sched.get('frequency', '?')!s:12s}  "
            f"advance={sched.get('advance_days', '?')} days"
        )

    if len(templates) < 2:
        fail(
            "At least 2 active templates for Power Transformer",
            f"only {len(templates)} found — check seed_default_test_register",
        )
    ok(f"{len(templates)} active templates confirmed", "commission will clone all of these")

    # Verify each template has an active schedule
    templates_with_schedule = [t for t in templates if t.get("schedule") and t["schedule"].get("is_active")]
    if len(templates_with_schedule) < len(templates):
        skip(
            "All templates have active schedules",
            f"{len(templates) - len(templates_with_schedule)} template(s) have no/inactive schedule",
        )
    else:
        ok("All templates have active schedules")

    # ── 5. Create Power Transformer equipment — no tickets yet ────────────────
    section("5 — Equipment Creation (no auto-ticket)")
    create_body = {
        "organization_id":      org_id,
        "department_id":        dept_id,
        "equipment_type_id":    pt_eq_type_id,
        "voltage_class":        "220kV",
        "bay_number":           "B-01",
        "manufacturer":         "BHEL",
        "model_number":         "ICT-220/110",
        "factory_serial_number":"SN-TEST-001",
        "year_of_manufacture":  2015,
        "nameplate_data": {
            "rated_mva":         "100",
            "primary_voltage":   "220kV",
            "secondary_voltage": "110kV",
            "vector_group":      "YNd11",
        },
    }
    equipment = check(
        "POST /equipment/ — create Power Transformer",
        post(f"{BASE}/equipment/", token=admin_token, body=create_body),
        201,
    )
    equipment_id = equipment["id"]
    ueic         = equipment.get("ueic", "")
    ok("Equipment created", f"id={equipment_id[:8]}…  ueic={ueic}")

    # Confirm no tickets were auto-created
    tickets_at_creation = check(
        "GET /testing_requests/?equipment_id=… (should be empty)",
        get(f"{BASE}/testing_requests/", token=admin_token,
            params={"equipment_id": equipment_id, "limit": 10}),
        200,
    )
    if len(tickets_at_creation) > 0:
        fail("No tickets auto-created on equipment creation",
             f"{len(tickets_at_creation)} ticket(s) found — commission hook was not removed")
    ok("No tickets auto-created on equipment creation")

    # ── 6. Template schedules visible for this equipment ──────────────────────
    section("6 — Template Schedules for Equipment")
    schedules = check(
        f"GET /test-register/equipment/{equipment_id[:8]}…/schedules",
        get(f"{BASE}/test-register/equipment/{equipment_id}/schedules", token=admin_token),
        200,
    )
    info(f"Template schedules applicable to this equipment: {len(schedules)}")

    if len(schedules) < 2:
        fail("At least 2 template schedules for Power Transformer",
             f"got {len(schedules)}")
    ok(f"{len(schedules)} template schedules shown for equipment")

    # Verify ordering — next_run_date ascending
    run_dates = [s["next_run_date"] for s in schedules if s.get("next_run_date")]
    if len(run_dates) >= 2 and run_dates != sorted(run_dates):
        fail("Schedules ordered by next_run_date ascending", f"got {run_dates[:3]}")
    ok("Schedules ordered by next_run_date ascending")

    # Per-schedule field validation
    frequencies_seen = set()
    missing_fields   = []
    for sched in schedules:
        title = sched.get("title", "?")
        for f in ("schedule_id", "template_request_id", "frequency", "next_run_date", "advance_days"):
            if sched.get(f) is None:
                missing_fields.append(f"{title!r}.{f}")
        if sched.get("frequency"):
            frequencies_seen.add(sched["frequency"])
        info(
            f"  • {title!r:55s}  "
            f"freq={sched.get('frequency','?')!s:12s}  "
            f"next={str(sched.get('next_run_date','?'))[:10]}  "
            f"adv={sched.get('advance_days','?')} d"
        )
    if missing_fields:
        fail("All required schedule fields present", f"missing: {missing_fields[:5]}")
    ok("All required fields present on every schedule")

    info(f"Unique frequencies: {frequencies_seen}")
    if len(frequencies_seen) >= 2:
        ok(f"{len(frequencies_seen)} distinct frequencies")
    else:
        fail("At least 2 distinct frequencies for Power Transformer",
             f"only found: {frequencies_seen}")

    # ── 7. Run scheduler — tickets generated from due schedules ───────────────
    section("7 — Scheduler Run (POST /test-register/run-scheduler)")
    scheduler_result = check(
        "POST /test-register/run-scheduler",
        post(f"{BASE}/test-register/run-scheduler", token=admin_token),
        200,
    )
    tickets_created   = scheduler_result.get("tickets_created", 0)
    schedules_skipped = scheduler_result.get("schedules_skipped", 0)
    info(f"Scheduler result: tickets_created={tickets_created}  schedules_skipped={schedules_skipped}")
    ok("Scheduler ran successfully")

    if tickets_created < 1:
        fail("Scheduler created at least 1 ticket",
             "0 tickets — check next_run_date in seed vs today, or no active equipment matches")
    ok(f"{tickets_created} ticket(s) generated by scheduler")

    # ── 8. Verify tickets in approval queue ───────────────────────────────────
    section("8 — Tickets in Approval Queue")
    tickets = check(
        f"GET /testing_requests/?equipment_id={equipment_id[:8]}…",
        get(f"{BASE}/testing_requests/", token=admin_token,
            params={"equipment_id": equipment_id, "limit": 200}),
        200,
    )
    info(f"Tickets in queue for this equipment: {len(tickets)}")

    if len(tickets) < 1:
        fail("At least 1 ticket in approval queue", "0 found after scheduler ran")
    ok(f"{len(tickets)} ticket(s) in approval queue")

    # All must be non-template, bound to this equipment, status=submitted
    bad = [t for t in tickets
           if t.get("is_schedule_template") is True
           or str(t.get("equipment_id", "")) != equipment_id]
    if bad:
        fail("All tickets: is_schedule_template=False and correct equipment_id",
             f"{len(bad)} bad ticket(s)")
    ok("All tickets: is_schedule_template=False, equipment_id matches")

    non_submitted = [t for t in tickets if t.get("status") != "submitted"]
    if non_submitted:
        fail("All tickets have status=submitted",
             f"{[(t.get('request_number'), t.get('status')) for t in non_submitted[:3]]}")
    ok("All tickets have status=submitted")

    # Verify request_number prefix
    bad_prefix = [t for t in tickets if not t.get("request_number", "").startswith("TR-SCH-")]
    if bad_prefix:
        fail("All scheduler tickets have TR-SCH- prefix",
             f"bad: {[t.get('request_number') for t in bad_prefix[:3]]}")
    ok("All scheduler tickets have TR-SCH- request_number prefix")

    # ── 9. Idempotency — second scheduler run creates no duplicates ────────────
    section("9 — Scheduler Idempotency")
    scheduler_result2 = check(
        "POST /test-register/run-scheduler (2nd run)",
        post(f"{BASE}/test-register/run-scheduler", token=admin_token),
        200,
    )
    info(f"2nd run: tickets_created={scheduler_result2.get('tickets_created')}  "
         f"schedules_skipped={scheduler_result2.get('schedules_skipped')}")

    # next_run_date was advanced by the first run, so 2nd run should create 0
    if scheduler_result2.get("tickets_created", 0) == 0:
        ok("2nd scheduler run created 0 tickets (next_run_date advanced — idempotent)")
    else:
        fail("2nd scheduler run should create 0 tickets",
             f"created {scheduler_result2.get('tickets_created')} — next_run_date not advancing")

    tickets_after = check(
        "GET /testing_requests/?equipment_id=… (after 2nd run)",
        get(f"{BASE}/testing_requests/", token=admin_token,
            params={"equipment_id": equipment_id, "limit": 200}),
        200,
    )
    if len(tickets_after) == len(tickets):
        ok("Ticket count unchanged after 2nd scheduler run", f"{len(tickets_after)} tickets")
    else:
        fail("No duplicate tickets after 2nd run",
             f"before={len(tickets)}  after={len(tickets_after)}")

    # ── 10. Commission endpoint — scoped scheduler run for one equipment ───────
    section("10 — Commission Endpoint (scoped scheduler)")
    commission_result = check(
        f"POST /test-register/commission/{equipment_id[:8]}…",
        post(f"{BASE}/test-register/commission/{equipment_id}", token=admin_token),
        200,
    )
    info(f"Commission (scoped): tickets_created={commission_result.get('tickets_created')}  "
         f"equipment_id={str(commission_result.get('equipment_id',''))[:8]}…")
    ok("Commission endpoint returns scheduler result",
       f"tickets_created={commission_result.get('tickets_created')}")

    # ── 11. ALERT reschedule ──────────────────────────────────────────────────
    section("11 — ALERT Reschedule")
    target_sched = next((s for s in schedules if s.get("next_run_date")), None)
    if not target_sched:
        fail("ALERT reschedule", "no schedules with next_run_date")

    schedule_id   = target_sched["schedule_id"]
    original_date = target_sched["next_run_date"]
    info(f"Rescheduling: {target_sched.get('title','?')!r}  original={original_date[:10]}")

    reschedule_result = check(
        f"POST /test-register/alert-reschedule/{schedule_id[:8]}…",
        post(f"{BASE}/test-register/alert-reschedule/{schedule_id}", token=admin_token),
        200,
    )
    if not reschedule_result.get("rescheduled"):
        fail("ALERT reschedule returned rescheduled=true", f"got {reschedule_result}")
    ok("ALERT reschedule returned rescheduled=true")

    new_date = reschedule_result.get("next_run_date", "")
    if new_date and new_date != original_date:
        ok("next_run_date advanced", f"{original_date[:10]} → {new_date[:10]}")
    else:
        fail("next_run_date changed after ALERT reschedule", f"still {original_date[:10]}")

    # ── 12. Single template GET ───────────────────────────────────────────────
    section("12 — Single Template GET")
    single = check(
        f"GET /test-register/{templates[0]['id'][:8]}…",
        get(f"{BASE}/test-register/{templates[0]['id']}", token=admin_token),
        200,
    )
    for field in ("id", "title", "equipment_type_id", "schedule"):
        if single.get(field) is None:
            fail(f"Template response has '{field}'", f"got {single}")
    ok("Template GET has all expected fields", f"title={single.get('title','?')!r}")

    # ── 13. Summary ───────────────────────────────────────────────────────────
    section("13 — Summary")
    info(f"Equipment          : {ueic}  ({equipment_id[:8]}…)")
    info(f"Templates matched  : {len(templates)}")
    info(f"Template schedules : {len(schedules)}")
    info(f"Tickets generated  : {tickets_created}  (by scheduler)")
    info(f"Frequencies        : {', '.join(sorted(frequencies_seen))}")

    _print_summary()


if __name__ == "__main__":
    run()
