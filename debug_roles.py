import requests

BASE = "http://localhost:8000"
orig_token = requests.post(f"{BASE}/token", data={"username":"originator@kptcl.com","password":"admin123"}).json()["access_token"]
assig_token = requests.post(f"{BASE}/token", data={"username":"testassigner@kptcl.com","password":"admin123"}).json()["access_token"]

hdrs_orig = {"Authorization": f"Bearer {orig_token}"}
hdrs_assig = {"Authorization": f"Bearer {assig_token}"}

eq = requests.get(f"{BASE}/equipment/", headers=hdrs_orig).json()[0]
tr_r = requests.post(f"{BASE}/testing_requests/", headers=hdrs_orig, json={
    "title": "Debug TR", "request_category": "test",
    "equipment_id": eq["id"], "priority": "normal",
})
tr_id = tr_r.json()["id"]
requests.put(f"{BASE}/testing_requests/{tr_id}/submit", headers=hdrs_orig)

roles = requests.get(f"{BASE}/testing-requests/approvals/{tr_id}/tester-roles", headers=hdrs_assig).json()
print("Roles and users:")
for r in roles:
    print(f"  Role: {r['role_name']} (role_id={r['role_id']})")
    users = requests.get(f"{BASE}/testing-requests/approvals/{tr_id}/tester-roles/{r['role_id']}/users", headers=hdrs_assig).json()
    for u in users:
        print(f"    User: {u['name']} (user_id={u['user_id']})")
