"""
Test login for depthead@kptcl.com
"""
import requests
import json

# API endpoint
url = "http://localhost:8000/login"

# Login credentials
payload = {
    "email": "depthead@kptcl.com",
    "password": "admin123"
}

print("=" * 60)
print("Testing Login: depthead@kptcl.com")
print("=" * 60)
print()

try:
    response = requests.post(url, json=payload, timeout=10)

    print(f"Status Code: {response.status_code}")
    print()

    if response.status_code == 200:
        data = response.json()
        print("SUCCESS! Login response:")
        print(json.dumps(data, indent=2))

        # Check roles
        if "user" in data and "roles" in data["user"]:
            roles = data["user"]["roles"]
            print()
            print(f"Roles assigned: {roles}")
    else:
        print("ERROR Response:")
        print(response.text)

except requests.exceptions.ConnectionError:
    print("ERROR: Could not connect to API")
    print("Make sure the API is running: python main.py")
except Exception as e:
    print(f"ERROR: {e}")
