# -*- coding: utf-8 -*-
"""
Endpoint validation script - FR / TR / TAQC / Finance flows
Run: python validate_flows.py
"""
import sys, io, requests

# Force UTF-8 output so arrows and dashes don't crash on Windows cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

def login(email, password):
    r = requests.post(f"{BASE}/token", data={"username": email, "password": password})
    assert r.status_code == 200, f"Login failed {email}: {r.text[:200]}"
    return r.json()["access_token"]

def auth(t):
    return {"Authorization": f"Bearer {t}"}

def p(r, label):
    status = "PASS" if r.status_code in [200, 201] else "FAIL"
    print(f"  [{r.status_code}] {status}  {label}")
    if r.status_code not in [200, 201]:
        print(f"         ERR: {r.text[:300]}")
    return r.status_code in [200, 201]

print("=" * 60)
print("  WORKFLOW ENDPOINT VALIDATION")
print("=" * 60)

# -- Login -------------------------------------------------------
print("\n[1] Logins")
orig  = login("originator@kptcl.com",   "admin123")
assig = login("testassigner@kptcl.com", "admin123")
tstr  = login("fieldtester1@kptcl.com", "Tester123!")
tech  = login("ee.rt@kptcl.com",        "admin123")
fin   = login("purchaser@kptcl.com",    "admin123")
print("  [OK] originator, test_assigner, tester, tech_approver, finance_approver")

# -- Equipment ---------------------------------------------------
equips = requests.get(f"{BASE}/equipment/", headers=auth(orig)).json()
eq_id = str(equips[0]["id"])
eq_type_id = equips[0].get("equipment_type_id")
print(f"\n  Using equipment: {equips[0].get('ueic')} (type_id={eq_type_id})")

# ================================================================
# FLOW A - FR -> TR -> Tester -> next_action=maintenance dispatch
# ================================================================
print("\n[2] FR Flow - maintenance dispatch")

# Create FR
fr_r = requests.post(f"{BASE}/testing_requests/", headers=auth(orig), json={
    "title": "FR Flow Test - Bushing Failure",
    "description": "Oil leak on bushing A",
    "request_category": "failure_registry",
    "equipment_id": eq_id,
    "equipment_type_id": eq_type_id,
    "priority": "high",
})
p(fr_r, "Originator: Create FR")
fr_id = fr_r.json()["id"]
print(f"    FR: {fr_r.json()['request_number']}  status={fr_r.json()['status']}")

# Submit FR
sub_r = requests.put(f"{BASE}/testing_requests/{fr_id}/submit", headers=auth(orig))
p(sub_r, "Originator: Submit FR")
print(f"    status={sub_r.json().get('status')}")

# FR Pass 1 - initial approve
ia_r = requests.post(f"{BASE}/testing-requests/approvals/{fr_id}/initial-approve", headers=auth(assig))
p(ia_r, "Test Assigner: initial-approve FR (Pass 1)")
if ia_r.status_code == 200:
    print(f"    {ia_r.json()['message']}")

# TR queue check
items = requests.get(f"{BASE}/testing-requests/approvals/pending", headers=auth(assig)).json()
trs = [x for x in items if x.get("request_category") == "test"]
print(f"    TR queue: {len(trs)} test TRs")
tr_id = trs[0]["id"] if trs else None
if tr_id:
    print(f"    TR: {trs[0]['request_number']}  status={trs[0]['status']}")

# Get tester roles + users — prefer "Field Tester" role so fieldtester1 can accept
roles = requests.get(f"{BASE}/testing-requests/approvals/{tr_id}/tester-roles", headers=auth(assig)).json()
# Pick "Field Tester" role if available, otherwise fall back to first role
field_role = next((r for r in roles if r["role_name"] == "Field Tester"), None) or (roles[0] if roles else None)
role_id = field_role["role_id"] if field_role else None
users = requests.get(f"{BASE}/testing-requests/approvals/{tr_id}/tester-roles/{role_id}/users", headers=auth(assig)).json() if role_id else []
# fieldtester1@kptcl.com is "KPTCL Field Tester One" — pick that user
tester_uid = users[0]["user_id"] if users else None
print(f"    Tester roles: {[r['role_name'] for r in roles]}  Testers: {[u['name'] for u in users]}")
print(f"    Assigning role={field_role['role_name'] if field_role else None}  user_id={tester_uid}")

# TR Pass 2 - approve-and-assign
aa_r = requests.post(f"{BASE}/testing-requests/approvals/{tr_id}/approve-and-assign", headers=auth(assig),
    json={"tester_id": tester_uid, "tester_role_id": role_id, "comment": "Assigned for testing"})
p(aa_r, "Test Assigner: approve-and-assign (Pass 2)")
print(f"    status={aa_r.json().get('new_status')}")

# Tester accept  (PUT, not POST)
acc_r = requests.put(f"{BASE}/testing/{tr_id}/accept", headers=auth(tstr))
p(acc_r, "Tester: accept assignment")

# Tester submit_results with next_action=maintenance  (PUT, not POST)
sub2 = requests.put(f"{BASE}/testing/{tr_id}/submit_results", headers=auth(tstr), json={
    "recommendation_type": "pass",
    "summary": "Transformer passed. Yearly maintenance needed.",
    "next_action": "maintenance",
    "schedule_frequency": "yearly",
    "detailed_notes": "All parameters within limits",
})
p(sub2, "Tester: submit_results (next_action=maintenance, freq=yearly)")

# Tech Approver queue
pend = requests.get(f"{BASE}/approvals/pending", headers=auth(tech)).json()
print(f"    Tech queue: {len(pend)} recommendations")
rec_id = pend[0]["id"] if pend else None
if rec_id:
    det = requests.get(f"{BASE}/approvals/{rec_id}/detail", headers=auth(tech)).json()
    print(f"    Rec: next_action={det.get('next_action')}  schedule_frequency={det.get('schedule_frequency')}")

    # Tech Approve
    appr = requests.put(f"{BASE}/approvals/{rec_id}/approve", headers=auth(tech), json={"notes": "Approved"})
    p(appr, "Technical Approver: approve (dispatch=maintenance)")
    if appr.status_code == 200:
        resp = appr.json()
        print(f"    next_action={resp.get('next_action')}  created={resp.get('created')}  status={resp.get('status')}")

# ================================================================
# FLOW B - Adhoc TR -> reject from queue
# ================================================================
print("\n[3] Adhoc TR - reject from Test Assigner queue")
tr2_r = requests.post(f"{BASE}/testing_requests/", headers=auth(orig), json={
    "title": "Adhoc TR Test",
    "description": "Routine test",
    "request_category": "test",
    "equipment_id": eq_id,
    "equipment_type_id": eq_type_id,
    "priority": "normal",
})
p(tr2_r, "Originator: Create Adhoc TR")
tr2_id = tr2_r.json()["id"]
requests.put(f"{BASE}/testing_requests/{tr2_id}/submit", headers=auth(orig))

rej_r = requests.post(f"{BASE}/testing-requests/approvals/{tr2_id}/reject", headers=auth(assig),
    json={"rejection_comment": "Insufficient information provided"})
p(rej_r, "Test Assigner: reject from queue")
if rej_r.status_code == 200:
    print(f"    status={rej_r.json().get('new_status')}")

# ================================================================
# FLOW C - Adhoc TR -> next_action=replacement -> Finance
# ================================================================
print("\n[4] Adhoc TR - replacement dispatch -> Finance approve")
tr3_r = requests.post(f"{BASE}/testing_requests/", headers=auth(orig), json={
    "title": "Replacement needed TR",
    "description": "Equipment failed all tests",
    "request_category": "test",
    "equipment_id": eq_id,
    "equipment_type_id": eq_type_id,
    "priority": "high",
})
p(tr3_r, "Originator: Create TR (replacement)")
tr3_id = tr3_r.json()["id"]
requests.put(f"{BASE}/testing_requests/{tr3_id}/submit", headers=auth(orig))

requests.post(f"{BASE}/testing-requests/approvals/{tr3_id}/approve-and-assign", headers=auth(assig),
    json={"tester_id": tester_uid, "tester_role_id": role_id, "comment": "Assign"})
requests.put(f"{BASE}/testing/{tr3_id}/accept", headers=auth(tstr))

sub3 = requests.put(f"{BASE}/testing/{tr3_id}/submit_results", headers=auth(tstr), json={
    "recommendation_type": "fail",
    "summary": "Failed all tests - replacement required.",
    "next_action": "replacement",
    "detailed_notes": "Beyond repair - recommend full replacement",
})
p(sub3, "Tester: submit_results (next_action=replacement)")

pend3 = requests.get(f"{BASE}/approvals/pending", headers=auth(tech)).json()
if pend3:
    rec3_id = pend3[0]["id"]
    appr3 = requests.put(f"{BASE}/approvals/{rec3_id}/approve", headers=auth(tech),
        json={"notes": "Confirmed - replacement needed"})
    p(appr3, "Technical Approver: approve (dispatch=replacement)")
    if appr3.status_code == 200:
        resp3 = appr3.json()
        print(f"    next_action={resp3.get('next_action')}  created={resp3.get('created')}  status={resp3.get('status')}")

    # Finance queue
    prs = requests.get(f"{BASE}/validation_requests/", headers=auth(fin)).json()
    prs_pending = [x for x in prs if x.get("status") == "pending_finance"]
    print(f"    Finance queue: {len(prs_pending)} pending procurement(s)")
    if prs_pending:
        pr_id = prs_pending[0]["id"]
        print(f"    PR: {prs_pending[0]['procurement_number']}  status={prs_pending[0]['status']}")

        # Finance approve
        fa_r = requests.put(f"{BASE}/validation_requests/{pr_id}/finance-approve", headers=auth(fin),
            json={"description": "Budget sanctioned"})
        p(fa_r, "Finance Approver: finance-approve")
        if fa_r.status_code == 200:
            print(f"    {fa_r.json()['message']}")

        # Finance reject (create another PR to test)
        sub3b = requests.post(f"{BASE}/testing_requests/", headers=auth(orig), json={
            "title": "Another Replacement TR",
            "request_category": "test",
            "equipment_id": eq_id, "equipment_type_id": eq_type_id, "priority": "high",
        })
        tr3b_id = sub3b.json()["id"]
        requests.put(f"{BASE}/testing_requests/{tr3b_id}/submit", headers=auth(orig))
        requests.post(f"{BASE}/testing-requests/approvals/{tr3b_id}/approve-and-assign", headers=auth(assig),
            json={"tester_id": tester_uid, "tester_role_id": role_id})
        requests.put(f"{BASE}/testing/{tr3b_id}/accept", headers=auth(tstr))
        requests.put(f"{BASE}/testing/{tr3b_id}/submit_results", headers=auth(tstr), json={
            "recommendation_type": "fail", "summary": "Failed - replace",
            "next_action": "replacement", "detailed_notes": "Bad"})
        pend3b = requests.get(f"{BASE}/approvals/pending", headers=auth(tech)).json()
        if pend3b:
            requests.put(f"{BASE}/approvals/{pend3b[0]['id']}/approve", headers=auth(tech),
                json={"notes": "Approved"})
        prs2 = requests.get(f"{BASE}/validation_requests/", headers=auth(fin)).json()
        prs2_p = [x for x in prs2 if x.get("status") == "pending_finance"]
        if prs2_p:
            fr2_r = requests.put(f"{BASE}/validation_requests/{prs2_p[0]['id']}/finance-reject", headers=auth(fin),
                json={"description": "Budget not available - revise"})
            p(fr2_r, "Finance Approver: finance-reject (back to tester)")
            if fr2_r.status_code == 200:
                print(f"    {fr2_r.json()['message']}")

# ================================================================
# FLOW D - Technical Approver rejects -> under_review -> tester resubmit
# ================================================================
print("\n[5] Tech Approver reject -> under_review -> tester resubmit")
tr4_r = requests.post(f"{BASE}/testing_requests/", headers=auth(orig), json={
    "title": "TR for tech reject test",
    "request_category": "test",
    "equipment_id": eq_id, "equipment_type_id": eq_type_id, "priority": "normal",
})
tr4_id = tr4_r.json()["id"]
requests.put(f"{BASE}/testing_requests/{tr4_id}/submit", headers=auth(orig))
requests.post(f"{BASE}/testing-requests/approvals/{tr4_id}/approve-and-assign", headers=auth(assig),
    json={"tester_id": tester_uid, "tester_role_id": role_id})
requests.put(f"{BASE}/testing/{tr4_id}/accept", headers=auth(tstr))
requests.put(f"{BASE}/testing/{tr4_id}/submit_results", headers=auth(tstr), json={
    "recommendation_type": "conditional", "summary": "Needs more data",
    "next_action": "none", "detailed_notes": "Inconclusive"})

pend4 = requests.get(f"{BASE}/approvals/pending", headers=auth(tech)).json()
if pend4:
    rec4_id = pend4[0]["id"]
    rej4 = requests.put(f"{BASE}/approvals/{rec4_id}/reject", headers=auth(tech),
        json={"notes": "Need additional test data"})
    p(rej4, "Technical Approver: reject recommendation -> under_review")
    if rej4.status_code == 200:
        print(f"    approval_status={rej4.json().get('approval_status')}")
        # Check TR status is now under_review
        tr4_det = requests.get(f"{BASE}/testing_requests/{tr4_id}", headers=auth(tstr)).json()
        print(f"    TR status={tr4_det.get('status')}  (expected: under_review)")

    # Tester resubmits after under_review
    resub = requests.put(f"{BASE}/testing/{tr4_id}/submit_results", headers=auth(tstr), json={
        "recommendation_type": "pass", "summary": "Additional data collected - now passing",
        "next_action": "none", "detailed_notes": "All checks clear"})
    p(resub, "Tester: resubmit results after under_review")
    if resub.status_code == 200:
        print(f"    TR status={resub.json().get('status')}")

print("\n" + "=" * 60)
print("  VALIDATION COMPLETE")
print("=" * 60)
