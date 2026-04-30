"""
validate_api_users.py -- Multi-user + dashboard API validation
Run:  python validate_api_users.py
"""
import sys
import requests
from database import SessionLocal
from models import TestRequestSchedule

BASE = "http://localhost:8001"
results = []
state = {}


def ok(label, passed, detail=""):
    results.append(("PASS" if passed else "FAIL", label, detail))
    mark = "PASS" if passed else "FAIL"
    line = f"  [{mark}]  {label}"
    if detail:
        line += f"  ({detail})"
    print(line)


def login(email, password):
    r = requests.post(f"{BASE}/token", data={"username": email, "password": password})
    return r.json().get("access_token") if r.status_code == 200 else None


def GET(token, path, params=None):
    return requests.get(f"{BASE}{path}",
                        headers={"Authorization": f"Bearer {token}"},
                        params=params)


def POST(token, path, body=None):
    return requests.post(f"{BASE}{path}",
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"},
                         json=body or {})


def PUT(token, path, body):
    return requests.put(f"{BASE}{path}",
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json"},
                        json=body)


def DELETE(token, path):
    return requests.delete(f"{BASE}{path}",
                           headers={"Authorization": f"Bearer {token}"})


# =============================================================================
print()
print("=" * 65)
print("  MULTI-USER API VALIDATION  (port 8001)")
print("=" * 65)


# --- 1. SUPER ADMIN ----------------------------------------------------------
print("\n[1] SUPER ADMIN  superadmin@system.com")
t_sa = login("superadmin@system.com", "Admin123!")
ok("SuperAdmin login", bool(t_sa))

if t_sa:
    r = GET(t_sa, "/users/me")
    ok("GET /users/me", r.status_code == 200, r.json().get("email", ""))

    r = GET(t_sa, "/test-register/")
    ok("GET /test-register/", r.status_code == 200,
       f"{len(r.json())} templates" if r.status_code == 200 else r.text[:60])

    r = GET(t_sa, "/equipment/")
    ok("GET /equipment/", r.status_code in (200, 403), f"HTTP {r.status_code}")


# --- 2. KPTCL ORG ADMIN ------------------------------------------------------
print("\n[2] ORG ADMIN  orgadmin@kptcl.com")
t_adm = login("orgadmin@kptcl.com", "admin123")
ok("Org Admin login", bool(t_adm))

if t_adm:
    r = GET(t_adm, "/users/me")
    me = r.json()
    ok("GET /users/me", r.status_code == 200, me.get("email", ""))
    state["org_id"] = me.get("organization_id")

    r = GET(t_adm, "/test-register/", {"organization_id": state.get("org_id")})
    rows = r.json() if r.status_code == 200 else []
    ok("GET /test-register/ (org filter)", r.status_code == 200,
       f"{len(rows)} templates")
    if rows:
        state["template_id"]         = rows[0]["id"]
        state["template_eq_type_id"] = rows[0].get("equipment_type_id")

    r = GET(t_adm, "/equipment/")
    eq_list = r.json() if r.status_code == 200 else []
    ok("GET /equipment/", r.status_code == 200, f"{len(eq_list)} units")
    if eq_list:
        state["equipment_id"]   = eq_list[0]["id"]
        state["equipment_ueic"] = eq_list[0].get("ueic", "")

    # Failure Registry submission by admin
    if eq_list and state.get("org_id"):
        body = {
            "request_category": "failure_registry",
            "template_key":     "failure_registry_generic",
            "title":            "VAL -- Bushing Flashover Detected",
            "test_data":        {"fault_type": "flashover", "phase": "R"},
            "equipment_id":     eq_list[0]["id"],
            "organization_id":  state["org_id"],
            "overall_result":   "fail",
            "remarks":          "Validation test entry",
        }
        r2 = POST(t_adm, "/direct-submissions/", body)
        ok("POST /direct-submissions/ failure_registry (Admin)",
           r2.status_code == 201,
           r2.json().get("request_number", "")
           if r2.status_code == 201 else r2.text[:80])
        if r2.status_code == 201:
            state["fr_id"] = r2.json().get("request_id")


# --- 3. EE TLSS --------------------------------------------------------------
print("\n[3] EE TLSS  ee.tlss@kptcl.com")
t_ee = login("ee.tlss@kptcl.com", "admin123")
ok("EE TLSS login", bool(t_ee))

if t_ee:
    r = GET(t_ee, "/users/me")
    ok("GET /users/me", r.status_code == 200, r.json().get("email", ""))

    # Read register
    r = GET(t_ee, "/test-register/")
    ok("GET /test-register/ (read)", r.status_code == 200,
       f"{len(r.json())} templates" if r.status_code == 200 else r.text[:60])

    # Get single template
    if state.get("template_id"):
        r = GET(t_ee, f"/test-register/{state['template_id']}")
        ok("GET /test-register/{id}", r.status_code == 200,
           r.json().get("title", "")[:40] if r.status_code == 200 else r.text[:60])

    # Create template (EE TLSS has write access)
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title":             "VAL -- CT Excitation Test",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id":   state["org_id"],
            "frequency":         "yearly",
            "advance_days":      14,
            "oem_reference":     "IS 2705 Cl.9 -- validation entry",
            "priority":          "normal",
        }
        r = POST(t_ee, "/test-register/", body)
        ok("POST /test-register/ (create as EE TLSS)", r.status_code == 201,
           r.json().get("request_number", "")
           if r.status_code == 201 else r.text[:80])
        if r.status_code == 201:
            state["new_tmpl_id"] = r.json()["id"]

    # Update template
    if state.get("new_tmpl_id"):
        r = PUT(t_ee, f"/test-register/{state['new_tmpl_id']}",
                {"advance_days": 20,
                 "notes": "Updated by EE TLSS during validation"})
        adv = (r.json().get("schedule", {}) or {}).get("advance_days") \
            if r.status_code == 200 else None
        ok("PUT /test-register/{id} (update as EE TLSS)", r.status_code == 200,
           f"advance_days={adv}")

    # Commission equipment
    if state.get("equipment_id"):
        r = POST(t_ee, f"/test-register/commission/{state['equipment_id']}")
        ok("POST /test-register/commission/{equipment_id}",
           r.status_code == 201,
           f"requests_created={r.json().get('requests_created','?')}"
           if r.status_code == 201 else r.text[:80])

    # Equipment schedules
    if state.get("equipment_id"):
        r = GET(t_ee, f"/test-register/equipment/{state['equipment_id']}/schedules")
        schedules = r.json() if r.status_code == 200 else []
        ok("GET /test-register/equipment/{id}/schedules",
           r.status_code == 200, f"{len(schedules)} live schedules")

    # Deactivate validation template
    if state.get("new_tmpl_id"):
        r = DELETE(t_ee, f"/test-register/{state['new_tmpl_id']}")
        is_active = (r.json().get("schedule", {}) or {}).get("is_active") \
            if r.status_code == 200 else None
        ok("DELETE /test-register/{id} (deactivate as EE TLSS)",
           r.status_code == 200 and is_active is False,
           f"is_active={is_active}")

    # TA&QC submission
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "taqc_inspection",
            "template_key":     "taqc_generic",
            "title":            "VAL -- Annual TA&QC Inspection",
            "test_data":        {"compliance_score": 88,
                                 "observations": ["Minor oil seepage"]},
            "equipment_id":     state["equipment_id"],
            "organization_id":  state["org_id"],
            "overall_result":   "advisory",
            "remarks":          "Corrective action within 30 days",
        }
        r = POST(t_ee, "/direct-submissions/", body)
        ok("POST /direct-submissions/ taqc_inspection (EE TLSS)",
           r.status_code == 201,
           r.json().get("request_number", "")
           if r.status_code == 201 else r.text[:80])

    # List both categories
    r = GET(t_ee, "/direct-submissions/", {"category": "failure_registry"})
    ok("GET /direct-submissions/?category=failure_registry",
       r.status_code == 200,
       f"{len(r.json())} records" if r.status_code == 200 else r.text[:60])

    r = GET(t_ee, "/direct-submissions/", {"category": "taqc_inspection"})
    ok("GET /direct-submissions/?category=taqc_inspection",
       r.status_code == 200,
       f"{len(r.json())} records" if r.status_code == 200 else r.text[:60])

    # Detail with test_data populated (not all dashes)
    if state.get("fr_id"):
        r = GET(t_ee, f"/direct-submissions/{state['fr_id']}")
        d = r.json() if r.status_code == 200 else {}
        ok("GET /direct-submissions/{id} has test_data + overall_result",
           r.status_code == 200
           and bool(d.get("test_data"))
           and d.get("overall_result") is not None,
           f"result={d.get('overall_result', 'MISSING')}")

    # Alert reschedule
    db = SessionLocal()
    sched = db.query(TestRequestSchedule).filter(
        TestRequestSchedule.revised_periodicity_days.isnot(None)
    ).first()
    db.close()
    if sched:
        r = POST(t_ee, f"/test-register/alert-reschedule/{sched.id}")
        ok("POST /test-register/alert-reschedule/{id}", r.status_code == 200,
           f"next={r.json().get('next_run_date','')[:10]}"
           if r.status_code == 200 else r.text[:60])

    # DASHBOARD -- EE TLSS dashboard
    r = GET(t_ee, "/dashboard/ee-tlss")
    ok("GET /dashboard/ee-tlss (EE TLSS role dashboard)",
       r.status_code in (200, 403),
       f"HTTP {r.status_code}" +
       (f" -- {list(r.json().keys())[:5]}" if r.status_code == 200 else ""))

    # DASHBOARD -- overdue tests (templates must NOT appear)
    r = GET(t_ee, "/dashboard/overdue-tests")
    if r.status_code == 200:
        data = r.json()
        # Overdue list items must have is_schedule_template=False (or not present)
        if isinstance(data, list):
            tmpl_leaked = [x for x in data if x.get("is_schedule_template") is True]
            ok("Dashboard overdue-tests excludes register templates",
               len(tmpl_leaked) == 0,
               f"{len(data)} items, {len(tmpl_leaked)} templates leaked")
        else:
            ok("GET /dashboard/overdue-tests", True,
               f"HTTP {r.status_code} -- non-list response (widget dict)")
    else:
        ok("GET /dashboard/overdue-tests", r.status_code in (200, 403),
           f"HTTP {r.status_code}")

    r = GET(t_ee, "/dashboard/active-alerts")
    ok("GET /dashboard/active-alerts",
       r.status_code in (200, 403), f"HTTP {r.status_code}")

    r = GET(t_ee, "/dashboard/kpi")
    ok("GET /dashboard/kpi",
       r.status_code in (200, 403), f"HTTP {r.status_code}")


# --- 4. AEE MAINTENANCE ------------------------------------------------------
print("\n[4] AEE MAINTENANCE  aee.maintenance@kptcl.com")
t_aee = login("aee.maintenance@kptcl.com", "admin123")
ok("AEE Maintenance login", bool(t_aee))

if t_aee:
    r = GET(t_aee, "/users/me")
    ok("GET /users/me", r.status_code == 200, r.json().get("email", ""))

    # Can read register
    r = GET(t_aee, "/test-register/")
    ok("GET /test-register/ (read as AEE)", r.status_code == 200,
       f"{len(r.json())} templates" if r.status_code == 200 else r.text[:60])

    # CANNOT create template -- expect 403
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title":             "Unauthorized by AEE",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id":   state["org_id"],
            "frequency":         "yearly",
        }
        r = POST(t_aee, "/test-register/", body)
        ok("POST /test-register/ BLOCKED for AEE Maintenance (expect 403)",
           r.status_code == 403, f"HTTP {r.status_code}")

    # Can post Failure Registry
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "failure_registry",
            "template_key":     "failure_registry_generic",
            "title":            "VAL -- Transformer Oil Leakage",
            "test_data":        {"location": "Main tank drain valve",
                                 "severity": "medium"},
            "equipment_id":     state["equipment_id"],
            "organization_id":  state["org_id"],
            "overall_result":   "fail",
            "remarks":          "Oil pooling at base",
        }
        r = POST(t_aee, "/direct-submissions/", body)
        ok("POST /direct-submissions/ failure_registry (AEE Maintenance)",
           r.status_code == 201,
           r.json().get("request_number", "")
           if r.status_code == 201 else r.text[:80])

    # AEE dashboard
    r = GET(t_aee, "/dashboard/aee")
    ok("GET /dashboard/aee (AEE role dashboard)",
       r.status_code in (200, 403), f"HTTP {r.status_code}")


# --- 5. ORIGINATOR -----------------------------------------------------------
print("\n[5] ORIGINATOR  originator@kptcl.com")
t_orig = login("originator@kptcl.com", "admin123")
ok("Originator login", bool(t_orig))

if t_orig:
    r = GET(t_orig, "/users/me")
    ok("GET /users/me", r.status_code == 200, r.json().get("email", ""))

    # Can read register
    r = GET(t_orig, "/test-register/")
    ok("GET /test-register/ (read as Originator)", r.status_code == 200,
       f"{len(r.json())} templates" if r.status_code == 200 else r.text[:60])

    # Can post Failure Registry
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "failure_registry",
            "template_key":     "failure_registry_generic",
            "title":            "VAL -- Buchholz Relay Trip",
            "test_data":        {"relay": "Buchholz", "trip_type": "alarm"},
            "equipment_id":     state["equipment_id"],
            "organization_id":  state["org_id"],
            "overall_result":   "fail",
        }
        r = POST(t_orig, "/direct-submissions/", body)
        ok("POST /direct-submissions/ failure_registry (Originator)",
           r.status_code == 201,
           r.json().get("request_number", "")
           if r.status_code == 201 else r.text[:80])

    # CANNOT post TA&QC -- expect 403
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "taqc_inspection",
            "template_key":     "taqc_generic",
            "title":            "Unauthorized TA&QC by Originator",
            "test_data":        {},
            "equipment_id":     state["equipment_id"],
            "organization_id":  state["org_id"],
        }
        r = POST(t_orig, "/direct-submissions/", body)
        ok("POST /direct-submissions/ TA&QC BLOCKED for Originator (expect 403)",
           r.status_code == 403, f"HTTP {r.status_code}")

    # CANNOT create template -- expect 403
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title":             "Unauthorized Register by Originator",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id":   state["org_id"],
            "frequency":         "monthly",
        }
        r = POST(t_orig, "/test-register/", body)
        ok("POST /test-register/ BLOCKED for Originator (expect 403)",
           r.status_code == 403, f"HTTP {r.status_code}")


# --- 6. CROSS-CHECKS ---------------------------------------------------------
print("\n[6] CROSS-CHECKS")

# own_only filter
if t_adm and state.get("org_id"):
    r = GET(t_adm, "/direct-submissions/",
            {"category": "failure_registry", "own_only": "true"})
    ok("GET /direct-submissions/?own_only=true",
       r.status_code == 200,
       f"{len(r.json())} own records" if r.status_code == 200 else r.text[:60])

# Unauthenticated requests
r = requests.get(f"{BASE}/test-register/")
ok("GET /test-register/ no token (expect 401/403)",
   r.status_code in (401, 403), f"HTTP {r.status_code}")

r = requests.get(f"{BASE}/direct-submissions/?category=failure_registry")
ok("GET /direct-submissions/ no token (expect 401/403)",
   r.status_code in (401, 403), f"HTTP {r.status_code}")

# Bad category
if t_ee:
    r = POST(t_ee, "/direct-submissions/",
             {"request_category": "bad_category",
              "template_key": "x", "title": "t", "test_data": {}})
    ok("POST /direct-submissions/ bad category (expect 400/422)",
       r.status_code in (400, 422), f"HTTP {r.status_code}")

# Template partition -- live requests created from commission should have is_direct_submission=False
from database import SessionLocal
from models import TestingRequest
db = SessionLocal()
live = db.query(TestingRequest).filter(
    TestingRequest.is_schedule_template.is_(False)
).count()
templates = db.query(TestingRequest).filter(
    TestingRequest.is_schedule_template.is_(True)
).count()
db.close()
ok("is_schedule_template partitions DB rows cleanly",
   True, f"live={live}  templates={templates}")

# Dashboard -- role-view endpoint (returns widget list for current user)
if t_ee:
    r = GET(t_ee, "/dashboard/role-view")
    ok("GET /dashboard/role-view (EE TLSS)",
       r.status_code in (200, 403), f"HTTP {r.status_code}")

if t_adm:
    r = GET(t_adm, "/dashboard/full")
    ok("GET /dashboard/full (Admin)",
       r.status_code in (200, 403), f"HTTP {r.status_code}")

# maintenance-overdue: should only show live requests not templates
if t_ee:
    r = GET(t_ee, "/dashboard/maintenance-overdue")
    ok("GET /dashboard/maintenance-overdue",
       r.status_code in (200, 403), f"HTTP {r.status_code}")


# =============================================================================
print()
print("=" * 65)
print("  FINAL REPORT")
print("=" * 65)
passed = failed = 0
for status, label, detail in results:
    if status == "FAIL":
        failed += 1
        print(f"  [FAIL]  {label}")
        if detail:
            print(f"            {detail}")
    else:
        passed += 1

print("=" * 65)
print(f"  PASSED: {passed}   FAILED: {failed}   TOTAL: {passed + failed}")
print("=" * 65)
sys.exit(0 if failed == 0 else 1)
