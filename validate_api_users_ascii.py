"""
validate_api_users.py
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Logs in as different KPTCL users and validates:
  - Auth (login / me)
  - Role-based access to Test Register (create/list/get)
  - Direct Submissions (Failure Registry, TA&QC)
  - Equipment list
  - Test Request list
  - Dashboard KPI

Run:  python validate_api_users.py
"""

import json
import sys
import requests

BASE = "http://localhost:8000"
results = []


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def log(label, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((status, label, detail))
    icon = "âœ“" if ok else "âœ—"
    print(f"  {icon}  {label}" + (f"  [{detail}]" if detail else ""))


def login(email, password):
    r = requests.post(f"{BASE}/token", data={"username": email, "password": password})
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def get(token, path, params=None):
    h = {"Authorization": f"Bearer {token}"}
    return requests.get(f"{BASE}{path}", headers=h, params=params)


def post(token, path, body):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return requests.post(f"{BASE}{path}", headers=h, json=body)


def put(token, path, body):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return requests.put(f"{BASE}{path}", headers=h, json=body)


def delete(token, path):
    h = {"Authorization": f"Bearer {token}"}
    return requests.delete(f"{BASE}{path}", headers=h)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Shared state
state = {}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=" * 65)
print("  USER LOGIN & API VALIDATION")
print("=" * 65)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 1. SUPER ADMIN (superadmin@system.com) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
tok = login("superadmin@system.com", "Admin123!")
log("SuperAdmin login", tok is not None, "token obtained" if tok else "FAILED")

if tok:
    r = get(tok, "/me")
    log("GET /me", r.status_code == 200, r.json().get("email", ""))

    r = get(tok, "/test-register/")
    log("GET /test-register/ (list templates)", r.status_code == 200,
        f"{len(r.json())} templates" if r.status_code == 200 else r.text[:80])

    r = get(tok, "/equipment/")
    log("GET /equipment/", r.status_code in (200, 403),
        f"{len(r.json())} items" if r.status_code == 200 else f"HTTP {r.status_code}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 2. KPTCL ORG ADMIN (orgadmin@kptcl.com) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
tok_admin = login("orgadmin@kptcl.com", "admin123")
log("Org Admin login", tok_admin is not None)

if tok_admin:
    r = get(tok_admin, "/me")
    me = r.json()
    log("GET /me", r.status_code == 200, me.get("email", ""))
    state["org_id"] = me.get("organization_id")

    r = get(tok_admin, "/test-register/", params={"organization_id": state.get("org_id")})
    log("GET /test-register/ with org filter", r.status_code == 200,
        f"{len(r.json())} templates" if r.status_code == 200 else r.text[:80])
    if r.status_code == 200 and r.json():
        state["template_id"] = r.json()[0]["id"]
        state["template_eq_type_id"] = r.json()[0].get("equipment_type_id")

    r = get(tok_admin, "/equipment/")
    eq_list = r.json() if r.status_code == 200 else []
    log("GET /equipment/", r.status_code == 200, f"{len(eq_list)} units")
    if eq_list:
        state["equipment_id"] = eq_list[0]["id"]
        state["equipment_ueic"] = eq_list[0].get("ueic", "")

    # Create a direct submission (Failure Registry) as admin
    r = get(tok_admin, "/equipment/")
    eq = r.json()[0] if r.status_code == 200 and r.json() else None
    if eq:
        body = {
            "request_category": "failure_registry",
            "template_key": "failure_registry_generic",
            "title": "Validation â€” Bushing Flashover Detected",
            "test_data": {"fault_type": "flashover", "phase": "R"},
            "equipment_id": eq["id"],
            "organization_id": state.get("org_id"),
            "overall_result": "fail",
            "remarks": "API validation test entry",
        }
        r2 = post(tok_admin, "/direct-submissions/", body)
        log("POST /direct-submissions/ (Failure Registry as Admin)",
            r2.status_code == 201,
            f"request_number={r2.json().get('request_number','')}" if r2.status_code == 201 else r2.text[:100])
        if r2.status_code == 201:
            state["fr_submission_id"] = r2.json().get("request_id")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 3. EE TLSS (ee.tlss@kptcl.com) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
tok_ee = login("ee.tlss@kptcl.com", "admin123")
log("EE TLSS login", tok_ee is not None)

if tok_ee:
    r = get(tok_ee, "/me")
    log("GET /me", r.status_code == 200, r.json().get("email", ""))

    # Should be able to list templates
    r = get(tok_ee, "/test-register/")
    log("GET /test-register/ (read)", r.status_code == 200,
        f"{len(r.json())} templates" if r.status_code == 200 else r.text[:80])

    # Should be able to GET single template
    if state.get("template_id"):
        r = get(tok_ee, f"/test-register/{state['template_id']}")
        log(f"GET /test-register/{{id}}", r.status_code == 200,
            r.json().get("title", "")[:40] if r.status_code == 200 else r.text[:80])

    # EE TLSS has write access â€” create a new template
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title": "VALIDATION â€” CT Excitation Test",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id": state["org_id"],
            "frequency": "yearly",
            "advance_days": 14,
            "oem_reference": "IS 2705 Cl.9 â€” validation entry",
            "priority": "normal",
        }
        r = post(tok_ee, "/test-register/", body)
        log("POST /test-register/ (create template as EE TLSS)",
            r.status_code == 201,
            r.json().get("request_number", "") if r.status_code == 201 else r.text[:100])
        if r.status_code == 201:
            state["new_template_id"] = r.json()["id"]

    # Update the newly created template
    if state.get("new_template_id"):
        r = put(tok_ee, f"/test-register/{state['new_template_id']}",
                {"advance_days": 20, "notes": "Updated by EE TLSS during validation"})
        log("PUT /test-register/{id} (update as EE TLSS)",
            r.status_code == 200,
            f"advance_days={r.json().get('schedule', {}).get('advance_days')}"
            if r.status_code == 200 else r.text[:100])

    # Commission equipment manually
    if state.get("equipment_id"):
        r = post(tok_ee, f"/test-register/commission/{state['equipment_id']}", {})
        log("POST /test-register/commission/{equipment_id}",
            r.status_code == 201,
            f"created={r.json().get('requests_created','?')}" if r.status_code == 201 else r.text[:100])

    # Equipment schedules for that unit
    if state.get("equipment_id"):
        r = get(tok_ee, f"/test-register/equipment/{state['equipment_id']}/schedules")
        log("GET /test-register/equipment/{id}/schedules",
            r.status_code == 200,
            f"{len(r.json())} schedules" if r.status_code == 200 else r.text[:80])

    # Deactivate the validation template
    if state.get("new_template_id"):
        r = delete(tok_ee, f"/test-register/{state['new_template_id']}")
        log("DELETE /test-register/{id} (deactivate as EE TLSS)",
            r.status_code == 200,
            f"is_active={r.json().get('schedule',{}).get('is_active')}" if r.status_code == 200 else r.text[:80])

    # TA&QC submission by EE TLSS
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "taqc_inspection",
            "template_key": "taqc_generic",
            "title": "Validation â€” Annual TA&QC Inspection",
            "test_data": {"compliance_score": 88, "observations": ["Minor oil seepage noted"]},
            "equipment_id": state["equipment_id"],
            "organization_id": state["org_id"],
            "overall_result": "advisory",
            "remarks": "Corrective action required within 30 days",
        }
        r = post(tok_ee, "/direct-submissions/", body)
        log("POST /direct-submissions/ (TA&QC as EE TLSS)",
            r.status_code == 201,
            r.json().get("request_number", "") if r.status_code == 201 else r.text[:100])

    # List direct submissions
    r = get(tok_ee, "/direct-submissions/", params={"category": "failure_registry"})
    log("GET /direct-submissions/?category=failure_registry",
        r.status_code == 200,
        f"{len(r.json())} records" if r.status_code == 200 else r.text[:80])

    r = get(tok_ee, "/direct-submissions/", params={"category": "taqc_inspection"})
    log("GET /direct-submissions/?category=taqc_inspection",
        r.status_code == 200,
        f"{len(r.json())} records" if r.status_code == 200 else r.text[:80])

    # Get detail of FR submission
    if state.get("fr_submission_id"):
        r = get(tok_ee, f"/direct-submissions/{state['fr_submission_id']}")
        log("GET /direct-submissions/{id}",
            r.status_code == 200,
            r.json().get("title", "")[:40] if r.status_code == 200 else r.text[:80])


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 4. AEE MAINTENANCE (aee.maintenance@kptcl.com) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
tok_aee = login("aee.maintenance@kptcl.com", "admin123")
log("AEE Maintenance login", tok_aee is not None)

if tok_aee:
    r = get(tok_aee, "/me")
    log("GET /me", r.status_code == 200, r.json().get("email", ""))

    # Can read register
    r = get(tok_aee, "/test-register/")
    log("GET /test-register/ (read as AEE Maintenance)", r.status_code == 200,
        f"{len(r.json())} templates" if r.status_code == 200 else r.text[:80])

    # Cannot create template (should get 403)
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title": "Unauthorized Template Attempt",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id": state["org_id"],
            "frequency": "yearly",
        }
        r = post(tok_aee, "/test-register/", body)
        log("POST /test-register/ blocked for AEE Maintenance (expect 403)",
            r.status_code == 403,
            f"HTTP {r.status_code}: {r.json().get('detail','')[:60]}" if r.status_code != 200 else "WRONGLY ALLOWED")

    # Can post Failure Registry
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "failure_registry",
            "template_key": "failure_registry_generic",
            "title": "Validation â€” Transformer Oil Leakage",
            "test_data": {"location": "Main tank drain valve", "severity": "medium"},
            "equipment_id": state["equipment_id"],
            "organization_id": state["org_id"],
            "overall_result": "fail",
            "remarks": "Oil pooling observed at base",
        }
        r = post(tok_aee, "/direct-submissions/", body)
        log("POST /direct-submissions/ (Failure Registry as AEE Maintenance)",
            r.status_code == 201,
            r.json().get("request_number", "") if r.status_code == 201 else r.text[:100])

    # List testing requests
    r = get(tok_aee, "/testing-requests/")
    log("GET /testing-requests/",
        r.status_code in (200, 403),
        f"HTTP {r.status_code}" + (f" â€” {len(r.json())} items" if r.status_code == 200 and isinstance(r.json(), list) else ""))


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 5. FIELD TESTER (fieldtester1@kptcl.com / fieldtester@kptcl.com) â”€â”€")
tok_ft = login("fieldtester1@kptcl.com", "admin123")
if not tok_ft:
    tok_ft = login("fieldtester@kptcl.com", "admin123")
if not tok_ft:
    # try generic field tester from seed
    tok_ft = login("tester1@kptcl.com", "admin123")

log("Field Tester login", tok_ft is not None,
    "found" if tok_ft else "no field tester account â€” trying originator")

if not tok_ft:
    tok_ft = login("originator@kptcl.com", "admin123")
    log("Originator login (fallback)", tok_ft is not None)

if tok_ft:
    r = get(tok_ft, "/me")
    log("GET /me", r.status_code == 200, r.json().get("email", ""))

    # Can read register (view only)
    r = get(tok_ft, "/test-register/")
    log("GET /test-register/ (read as Field-level user)", r.status_code == 200,
        f"{len(r.json())} templates" if r.status_code == 200 else r.text[:80])

    # Cannot create template
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title": "Unauthorized Template by Field Tester",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id": state["org_id"],
            "frequency": "monthly",
        }
        r = post(tok_ft, "/test-register/", body)
        log("POST /test-register/ blocked for Field Tester (expect 403)",
            r.status_code == 403,
            f"HTTP {r.status_code}")

    # Cannot post TA&QC (role not in allowed list)
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "taqc_inspection",
            "template_key": "taqc_generic",
            "title": "Unauthorized TA&QC by Field Tester",
            "test_data": {},
            "equipment_id": state["equipment_id"],
            "organization_id": state["org_id"],
        }
        r = post(tok_ft, "/direct-submissions/", body)
        log("POST /direct-submissions/ TA&QC blocked for Field Tester (expect 403)",
            r.status_code == 403,
            f"HTTP {r.status_code}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 6. ORIGINATOR (originator@kptcl.com) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
tok_orig = login("originator@kptcl.com", "admin123")
log("Originator login", tok_orig is not None)

if tok_orig:
    r = get(tok_orig, "/me")
    log("GET /me", r.status_code == 200, r.json().get("email", ""))

    # Can post Failure Registry
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "failure_registry",
            "template_key": "failure_registry_generic",
            "title": "Validation â€” Buchholz Relay Trip",
            "test_data": {"relay": "Buchholz", "trip_type": "alarm"},
            "equipment_id": state["equipment_id"],
            "organization_id": state["org_id"],
            "overall_result": "fail",
        }
        r = post(tok_orig, "/direct-submissions/", body)
        log("POST /direct-submissions/ (Failure Registry as Originator)",
            r.status_code == 201,
            r.json().get("request_number", "") if r.status_code == 201 else r.text[:100])

    # Cannot post TA&QC
    if state.get("equipment_id") and state.get("org_id"):
        body = {
            "request_category": "taqc_inspection",
            "template_key": "taqc_generic",
            "title": "Unauthorized TA&QC by Originator",
            "test_data": {},
            "equipment_id": state["equipment_id"],
            "organization_id": state["org_id"],
        }
        r = post(tok_orig, "/direct-submissions/", body)
        log("POST /direct-submissions/ TA&QC blocked for Originator (expect 403)",
            r.status_code == 403,
            f"HTTP {r.status_code}")

    # Register template â€” should be blocked
    if state.get("template_eq_type_id") and state.get("org_id"):
        body = {
            "title": "Unauthorized Register Entry by Originator",
            "equipment_type_id": state["template_eq_type_id"],
            "organization_id": state["org_id"],
            "frequency": "monthly",
        }
        r = post(tok_orig, "/test-register/", body)
        log("POST /test-register/ blocked for Originator (expect 403)",
            r.status_code == 403,
            f"HTTP {r.status_code}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 7. CROSS-CHECK: own_only filter & submission detail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
if tok_admin and state.get("org_id"):
    r = get(tok_admin, "/direct-submissions/",
            params={"category": "failure_registry", "own_only": "true"})
    log("GET /direct-submissions/?own_only=true (admin sees own)",
        r.status_code == 200,
        f"{len(r.json())} records" if r.status_code == 200 else r.text[:80])

if tok_ee and state.get("fr_submission_id"):
    r = get(tok_ee, f"/direct-submissions/{state['fr_submission_id']}")
    data = r.json() if r.status_code == 200 else {}
    has_test_data = bool(data.get("test_data"))
    has_result    = data.get("overall_result") is not None
    log("GET /direct-submissions/{id} has test_data + overall_result",
        r.status_code == 200 and has_test_data and has_result,
        f"test_data={has_test_data} result={data.get('overall_result', 'missing')}")

# Alert reschedule via API
if tok_ee:
    from database import SessionLocal
    from models import TestRequestSchedule
    db = SessionLocal()
    sched = db.query(TestRequestSchedule).filter(
        TestRequestSchedule.revised_periodicity_days.isnot(None)
    ).first()
    db.close()
    if sched:
        r = post(tok_ee, f"/test-register/alert-reschedule/{sched.id}", {})
        log("POST /test-register/alert-reschedule/{id}",
            r.status_code == 200,
            f"next_run_date={r.json().get('next_run_date','')[:10]}" if r.status_code == 200 else r.text[:80])


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ 8. INVALID / UNAUTHENTICATED REQUESTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
r = requests.get(f"{BASE}/test-register/")
log("GET /test-register/ without token (expect 401/403)",
    r.status_code in (401, 403), f"HTTP {r.status_code}")

r = requests.get(f"{BASE}/direct-submissions/?category=failure_registry")
log("GET /direct-submissions/ without token (expect 401/403)",
    r.status_code in (401, 403), f"HTTP {r.status_code}")

if tok_ee:
    r = post(tok_ee, "/direct-submissions/", {
        "request_category": "invalid_category",
        "template_key": "x",
        "title": "Bad request",
        "test_data": {},
    })
    log("POST /direct-submissions/ invalid category (expect 400/422)",
        r.status_code in (400, 422), f"HTTP {r.status_code}")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=" * 65)
print("  FINAL REPORT")
print("=" * 65)
passed = failed = 0
for r in results:
    if r[0] == "PASS":
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {r[1]}")
        if r[2]:
            print(f"          {r[2]}")

print("=" * 65)
print(f"  PASSED: {passed}   FAILED: {failed}   TOTAL: {passed + failed}")
print("=" * 65)
sys.exit(0 if failed == 0 else 1)
