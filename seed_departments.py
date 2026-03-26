#!/usr/bin/env python3
"""
Seed script to populate department hierarchy from KPTCL Excel file.
This script will:
1. Delete all existing departments for the organization
2. Create new departments from the Excel file in hierarchical order
"""

import requests
import pandas as pd
import json
from typing import Dict, List, Optional
import sys


class DepartmentSeeder:
    def __init__(self, base_url: str, org_id: str, auth_token: str):
        self.base_url = base_url.rstrip('/')
        self.org_id = org_id
        self.headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json'
        }
        # Track created department IDs by full path
        self.department_map: Dict[str, str] = {}

    def delete_all_departments(self):
        """Delete all departments for the organization."""
        print(f"\n🗑️  Fetching existing departments...")
        url = f"{self.base_url}/organizations/{self.org_id}/departments/"
        response = requests.get(url, headers=self.headers)

        if response.status_code != 200:
            print(f"❌ Failed to fetch departments: {response.status_code}")
            print(response.text)
            return False

        departments = response.json()
        print(f"Found {len(departments)} existing departments")

        if not departments:
            print("✅ No existing departments to delete")
            return True

        # Delete in reverse order to handle dependencies
        for dept in reversed(departments):
            dept_id = dept['id']
            dept_name = dept['name']
            delete_url = f"{self.base_url}/organizations/{self.org_id}/departments/{dept_id}"
            response = requests.delete(delete_url, headers=self.headers)

            if response.status_code == 204:
                print(f"  ✓ Deleted: {dept_name}")
            else:
                print(f"  ✗ Failed to delete {dept_name}: {response.status_code}")

        print("✅ All departments deleted\n")
        return True

    def create_department(self, name: str, code: str, parent_id: Optional[str] = None) -> Optional[str]:
        """Create a single department and return its ID."""
        url = f"{self.base_url}/organizations/{self.org_id}/departments/"

        payload = {
            "organization_id": self.org_id,
            "name": name,
            "code": code,
            "description": None,
            "parent_department_id": parent_id,
            "manager_id": None,
            "is_active": True
        }

        response = requests.post(url, headers=self.headers, json=payload)

        if response.status_code in [200, 201]:
            dept_data = response.json()
            dept_id = dept_data.get('id')
            print(f"  ✓ Created: {name} (ID: {dept_id[:8]}...)")
            return dept_id
        else:
            print(f"  ✗ Failed to create {name}: {response.status_code}")
            print(f"    Response: {response.text}")
            return None

    def generate_code(self, name: str) -> str:
        """Generate a department code from the name."""
        # Remove common suffixes and get first letters
        clean_name = name.replace(' Zone', '').replace(' Circle', '').replace(' Division', '')
        clean_name = clean_name.replace(' Section', '').replace('kV', '').strip()

        # Get first letters of each word
        words = clean_name.split()
        if len(words) > 1:
            code = ''.join([w[0].upper() for w in words[:3]])
        else:
            code = clean_name[:3].upper()

        return code

    def seed_from_excel(self, excel_path: str):
        """Read Excel file and create departments in hierarchical order."""
        print(f"\n📂 Reading Excel file: {excel_path}")
        df = pd.read_excel(excel_path)

        print(f"✅ Loaded {len(df)} rows")
        print(f"Columns: {df.columns.tolist()}\n")

        # Hierarchy levels in order
        levels = ['Zone', 'Circle', 'Division', 'Sub Division', 'Section', 'Substation']

        # Process each level
        for level_idx, level in enumerate(levels):
            print(f"\n{'='*60}")
            print(f"Creating {level} departments...")
            print(f"{'='*60}")

            # Get parent level
            parent_level = levels[level_idx - 1] if level_idx > 0 else None

            # Get unique combinations at this level
            if parent_level:
                # Group by all parent levels + current level
                parent_cols = levels[:level_idx]
                current_cols = parent_cols + [level]
                unique_combos = df[current_cols].drop_duplicates()
            else:
                # Root level (Zone)
                unique_combos = df[[level]].drop_duplicates()

            print(f"Found {len(unique_combos)} unique {level} departments\n")

            # Create each department at this level
            for _, row in unique_combos.iterrows():
                dept_name = str(row[level]).strip()

                # Build full path for tracking
                if parent_level:
                    parent_path = '|'.join([str(row[pl]).strip() for pl in parent_cols])
                    full_path = f"{parent_path}|{dept_name}"

                    # Get parent ID
                    parent_id = self.department_map.get(parent_path)
                    if not parent_id:
                        print(f"  ⚠️  Warning: Parent not found for {dept_name}")
                        continue
                else:
                    full_path = dept_name
                    parent_id = None

                # Generate code
                code = self.generate_code(dept_name)

                # Create department
                dept_id = self.create_department(dept_name, code, parent_id)

                if dept_id:
                    self.department_map[full_path] = dept_id

        print(f"\n{'='*60}")
        print(f"✅ COMPLETED: Created {len(self.department_map)} departments")
        print(f"{'='*60}\n")


def get_auth_token(base_url: str, email: str, password: str) -> Optional[str]:
    """Authenticate and get access token."""
    print(f"\n🔐 Authenticating as {email}...")
    url = f"{base_url}/token"

    payload = {
        "username": email,
        "password": password
    }

    response = requests.post(url, data=payload)

    if response.status_code == 200:
        token_data = response.json()
        print("✅ Authentication successful")
        return token_data.get('access_token')
    else:
        print(f"❌ Authentication failed: {response.status_code}")
        print(response.text)
        return None


def main():
    # Configuration
    BASE_URL = "http://localhost:8000"

    # Excel file path - default to project root
    import os
    project_root = os.path.dirname(os.path.abspath(__file__))
    EXCEL_PATH = os.path.join(project_root, "KPTCL_Substation_Mapping.xlsx")

    # Get credentials from command line or prompt
    if len(sys.argv) >= 4:
        email = sys.argv[1]
        password = sys.argv[2]
        org_id = sys.argv[3]
    else:
        print("=" * 60)
        print("Department Seeder - KPTCL Hierarchy")
        print("=" * 60)
        email = input("Enter email: ").strip()
        password = input("Enter password: ").strip()
        org_id = input("Enter organization ID: ").strip()

    # Authenticate
    auth_token = get_auth_token(BASE_URL, email, password)
    if not auth_token:
        print("\n❌ Failed to authenticate. Exiting.")
        sys.exit(1)

    # Initialize seeder
    seeder = DepartmentSeeder(BASE_URL, org_id, auth_token)

    # Confirm deletion
    print("\n" + "=" * 60)
    print("⚠️  WARNING: This will DELETE all existing departments")
    print("=" * 60)
    confirm = input("Type 'yes' to continue: ").strip().lower()

    if confirm != 'yes':
        print("❌ Operation cancelled")
        sys.exit(0)

    # Delete existing departments
    if not seeder.delete_all_departments():
        print("\n❌ Failed to delete existing departments. Exiting.")
        sys.exit(1)

    # Seed new departments
    try:
        seeder.seed_from_excel(EXCEL_PATH)
        print("\n✅ Department seeding completed successfully!")
    except Exception as e:
        print(f"\n❌ Error during seeding: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
