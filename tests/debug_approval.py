import requests

# Login as depthead
response = requests.post(
    "http://localhost:8000/token",
    data={"username": "depthead@kptcl.com", "password": "admin123"}
)
token = response.json()["access_token"]
print(f"Token: {token[:50]}...")

# Get pending approvals
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    "http://localhost:8000/testing-requests/approvals/pending",
    headers=headers
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
