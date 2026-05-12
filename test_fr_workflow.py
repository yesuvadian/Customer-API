# -*- coding: utf-8 -*-
"""
test_fr_workflow.py
-------------------
End-to-end test of:
  - Failure Registry direct submission (Repair + Replacement outcomes)
  - Approval: auto-creates RL- work order for Repair; returns fr_outcome for Replacement
  - failure_resolution_report (all / Repair filter)
  - repair_progress_report (shows auto-created RL-)
  - source_failure_id linkage in DB
  - Role check (EE TLSS can submit failure_registry)

Run:  python test_fr_workflow.py
"""

import sys
import requests
from database import SessionLocal
from sqlalchemy import text

BASE = "http://localhost:8000"


def ok(label, r, expected=None):
    exp  = expected or [200, 201]
    code = r.status_code
    mark = "[PASS]" if code in exp else "[FAIL]"
    print(f"  {mark} {label}  ->  HTTP {code}")
    if code not in exp:
        print(f"         {r.text[:400]}")
        return None
    try:
        return r.json()
    except Exception:
        return r.content


def login(email, password):
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": email, "password": password})
    data = ok(f"Login {email}", r)
    if data is None:
        sys.exit(1)
    return data["access_token"]


def hdr(token):
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 1 -- Login")
print("="*65)

aee_token   = login("aee.maintenance@kptcl.com", "admin123")
admin_token = login("superadmin@system.com",      "Admin123!")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 2 -- Fetch a sample equipment_id from KPTCL")
print("="*65)

r = requests.get(f"{BASE}/equipment?limit=3", headers=hdr(aee_token))
equip_list = ok("GET /equipment", r)
equip_id = None
if equip_list:
    equip_id = equip_list[0]["id"]
    print(f"  Using: ueic={equip_list[0].get('ueic','?')}  id={equip_id}")
else:
    print("  No equipment found -- submitting without equipment_id")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 3a -- Submit FR record  (outcome = Repair)")
print("="*65)

fr_repair_body = {
    "request_category": "failure_registry",
    "template_key":     "failure_registry",
    "title":            "Power Transformer Winding Failure -- Repair",
    "test_data": {
        "failure_date":           "2026-04-20",
        "failure_category":       "Electrical",
        "failure_description":    "Primary winding insulation breakdown detected",
        "outage_duration_hours":  "6",
        "affected_feeder":        "Devanahalli 11kV Feeder-3",
        "outcome":                "Repair",
        "corrective_action":      "Rewinding of primary winding required",
    },
    "overall_result": "fail",
    "remarks":  "Urgent -- feeder restoration pending",
    "priority": "high",
}
if equip_id:
    fr_repair_body["equipment_id"] = equip_id

r = requests.post(f"{BASE}/direct-submissions/",
                  headers=hdr(aee_token), json=fr_repair_body)
fr_repair = ok("POST /direct-submissions/ (Repair)", r, [201])
repair_fr_id = None
if fr_repair:
    print(f"  FR number : {fr_repair['request_number']}")
    print(f"  request_id: {fr_repair['request_id']}")
    repair_fr_id = fr_repair["request_id"]
else:
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 3b -- Submit FR record  (outcome = Replacement)")
print("="*65)

fr_replace_body = {
    "request_category": "failure_registry",
    "template_key":     "failure_registry",
    "title":            "Distribution Transformer -- Total Failure Replacement",
    "test_data": {
        "failure_date":           "2026-04-22",
        "failure_category":       "Mechanical",
        "failure_description":    "Tank rupture, oil spillage -- beyond repair",
        "outage_duration_hours":  "24",
        "outcome":                "Replacement",
        "corrective_action":      "Full transformer replacement with 500 kVA unit",
    },
    "overall_result": "fail",
    "remarks":  "Transformer write-off -- procurement needed",
    "priority": "high",
}
if equip_id:
    fr_replace_body["equipment_id"] = equip_id

r = requests.post(f"{BASE}/direct-submissions/",
                  headers=hdr(aee_token), json=fr_replace_body)
fr_replace = ok("POST /direct-submissions/ (Replacement)", r, [201])
replace_fr_id = None
if fr_replace:
    print(f"  FR number : {fr_replace['request_number']}")
    replace_fr_id = fr_replace["request_id"]

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 4 -- List direct submissions (failure_registry)")
print("="*65)

r = requests.get(f"{BASE}/direct-submissions/?category=failure_registry&limit=10",
                 headers=hdr(aee_token))
fr_list = ok("GET /direct-submissions/?category=failure_registry", r)
if fr_list:
    print(f"  Found {len(fr_list)} record(s)")
    for s in fr_list:
        print(f"    {s['request_number']}  "
              f"outcome={s.get('test_data',{}).get('outcome','?')}  "
              f"status={s['status']}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 5 -- Fetch pending approvals")
print("="*65)

r = requests.get(f"{BASE}/approvals/pending", headers=hdr(admin_token))
approvals = ok("GET /approvals/pending", r)
repair_rec_id  = None
replace_rec_id = None
if approvals:
    print(f"  {len(approvals)} pending approval(s)")
    for a in approvals:
        sid = a.get("testing_request_id", "")
        print(f"    id={a['id']}  req_id={sid}  summary={a['summary'][:55]}")
        if sid == repair_fr_id:
            repair_rec_id = a["id"]
        if replace_fr_id and sid == replace_fr_id:
            replace_rec_id = a["id"]

print(f"\n  repair_rec_id  = {repair_rec_id}")
print(f"  replace_rec_id = {replace_rec_id}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 6 -- Approve FR (Repair) -> expect auto RL- work order")
print("="*65)

if repair_rec_id:
    r = requests.put(f"{BASE}/approvals/{repair_rec_id}/approve",
                     headers=hdr(admin_token),
                     json={"notes": "Approved -- initiate repair"})
    result = ok("PUT /approvals/{id}/approve (Repair)", r)
    if result:
        print(f"  approval_status       : {result.get('approval_status')}")
        print(f"  fr_outcome            : {result.get('fr_outcome')}")
        print(f"  fr_number             : {result.get('fr_number')}")
        print(f"  fr_failure_category   : {result.get('fr_failure_category')}")
        print(f"  fr_failure_date       : {result.get('fr_failure_date')}")
        print(f"  auto_created_repair_tr: {result.get('auto_created_repair_tr')}")
        if result.get("auto_created_repair_tr"):
            print("  >> Repair work order auto-created successfully")
        else:
            print("  >> WARNING: expected auto_created_repair_tr -- not present")
else:
    print("  SKIP -- repair recommendation id not found")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 7 -- Approve FR (Replacement) -> expect fr_outcome=Replacement")
print("="*65)

if replace_rec_id:
    r = requests.put(f"{BASE}/approvals/{replace_rec_id}/approve",
                     headers=hdr(admin_token),
                     json={"notes": "Approved -- initiate procurement"})
    result = ok("PUT /approvals/{id}/approve (Replacement)", r)
    if result:
        print(f"  approval_status       : {result.get('approval_status')}")
        print(f"  fr_outcome            : {result.get('fr_outcome')}")
        print(f"  fr_number             : {result.get('fr_number')}")
        print(f"  fr_equipment_ueic     : {result.get('fr_equipment_ueic')}")
        print(f"  auto_created_repair_tr: {result.get('auto_created_repair_tr')}")
        if result.get("fr_outcome") == "Replacement":
            print("  >> Replacement outcome returned -- Flutter shows procurement prompt")
        else:
            print("  >> WARNING: expected fr_outcome=Replacement")
else:
    print("  SKIP -- replacement recommendation id not found")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 8 -- Find report definition IDs")
print("="*65)

r = requests.get(f"{BASE}/reports/definitions", headers=hdr(admin_token))
defs = ok("GET /reports/definitions", r)
fr_def_id = rl_def_id = None
if defs:
    for d in defs:
        if d["query_key"] == "failure_resolution_report":
            fr_def_id = d["id"]
        if d["query_key"] == "repair_progress_report":
            rl_def_id = d["id"]
    print(f"  failure_resolution_report id : {fr_def_id}")
    print(f"  repair_progress_report id    : {rl_def_id}")
    print(f"  Total definitions            : {len(defs)}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 9 -- Run failure_resolution_report (outcome=all)")
print("="*65)

if fr_def_id:
    r = requests.post(f"{BASE}/reports/definitions/{fr_def_id}/run",
                      headers=hdr(admin_token),
                      json={"parameters": {"outcome": "all"}, "output_format": "excel"})
    if r.status_code == 200:
        print(f"  [PASS] Report generated  {len(r.content)} bytes  "
              f"file={r.headers.get('Content-Disposition','')}")
    else:
        print(f"  [FAIL] HTTP {r.status_code}  {r.text[:300]}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 10 -- Run failure_resolution_report (outcome=Repair only)")
print("="*65)

if fr_def_id:
    r = requests.post(f"{BASE}/reports/definitions/{fr_def_id}/run",
                      headers=hdr(admin_token),
                      json={"parameters": {"outcome": "Repair"}, "output_format": "excel"})
    if r.status_code == 200:
        print(f"  [PASS] Repair-only report  {len(r.content)} bytes")
    else:
        print(f"  [FAIL] HTTP {r.status_code}  {r.text[:200]}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 11 -- Run repair_progress_report (should include auto RL-)")
print("="*65)

if rl_def_id:
    r = requests.post(f"{BASE}/reports/definitions/{rl_def_id}/run",
                      headers=hdr(admin_token),
                      json={"parameters": {}, "output_format": "excel"})
    if r.status_code == 200:
        print(f"  [PASS] Repair progress report  {len(r.content)} bytes")
    else:
        print(f"  [FAIL] HTTP {r.status_code}  {r.text[:200]}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 12 -- Verify source_failure_id linkage in DB")
print("="*65)

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT rl.request_number AS repair_tr,
               fr.request_number AS source_fr,
               rl.status,
               rl.source_failure_id IS NOT NULL AS linked
        FROM   public.testing_requests rl
        JOIN   public.testing_requests fr ON fr.id = rl.source_failure_id
        WHERE  rl.request_category = 'repair_lifecycle'
          AND  rl.source_failure_id IS NOT NULL
    """)).fetchall()
finally:
    db.close()

if rows:
    for row in rows:
        print(f"  [PASS] RL: {row[0]}  <-- source FR: {row[1]}  status={row[2]}")
else:
    print("  [FAIL] No linked repair_lifecycle records found (expected >= 1)")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 13 -- Role check: EE TLSS can submit failure_registry")
print("="*65)

ee_token = login("ee.tlss@kptcl.com", "admin123")
ee_body = dict(fr_repair_body)
ee_body["title"] = "Busbar Fault -- EE TLSS submission"
ee_body["test_data"] = dict(fr_repair_body["test_data"])
ee_body["test_data"]["outcome"] = "Under Investigation"

r = requests.post(f"{BASE}/direct-submissions/",
                  headers=hdr(ee_token), json=ee_body)
result = ok("POST /direct-submissions/ as EE TLSS", r, [201])
if result:
    print(f"  [PASS] EE TLSS can submit FR: {result['request_number']}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 14 -- Role check: Originator CAN submit (allowed); Purchaser CANNOT (403)")
print("="*65)

# Originator is in the allowed list -- expect 201
orig_token = login("originator@kptcl.com", "admin123")
r = requests.post(f"{BASE}/direct-submissions/",
                  headers=hdr(orig_token), json=dict(fr_repair_body, title="Originator-filed FR"))
result = ok("POST /direct-submissions/ as Originator (expect 201 -- allowed)", r, [201])
if result:
    print(f"  [PASS] Originator allowed: FR={result['request_number']}")

# Purchaser is NOT in the allowed list -- expect 403
purch_token = login("purchaser@kptcl.com", "admin123")
r = requests.post(f"{BASE}/direct-submissions/",
                  headers=hdr(purch_token), json=fr_repair_body)
if r.status_code == 403:
    print("  [PASS] Purchaser correctly blocked with 403")
    print(f"         {r.json().get('detail','')[:80]}")
else:
    ok("POST /direct-submissions/ as Purchaser (expected 403)", r, [403])

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  STEP 15 -- Get single FR submission detail (includes test_data)")
print("="*65)

r = requests.get(f"{BASE}/direct-submissions/{repair_fr_id}",
                 headers=hdr(aee_token))
detail = ok("GET /direct-submissions/{repair_fr_id}", r)
if detail:
    print(f"  request_number : {detail.get('request_number')}")
    print(f"  status         : {detail.get('status')}")
    print(f"  overall_result : {detail.get('overall_result')}")
    td = detail.get("test_data", {})
    print(f"  outcome        : {td.get('outcome')}")
    print(f"  failure_date   : {td.get('failure_date')}")
    print(f"  failure_cat    : {td.get('failure_category')}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  ALL STEPS COMPLETE")
print("="*65 + "\n")
