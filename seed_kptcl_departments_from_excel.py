#!/usr/bin/env python3
"""
Seed KPTCL Departments from Excel File
Reads KPTCL_Substation_Mapping.xlsx from Downloads folder
Creates complete 6-level hierarchy
"""

import uuid
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from database import VendorSessionLocal


def generate_code(name):
    """Generate a code from department name"""
    # Remove special characters and convert to uppercase
    code = name.upper()
    code = code.replace('KV', 'KV')
    code = code.replace(' ', '_')
    code = code.replace('-', '_')
    # Limit length
    if len(code) > 50:
        code = code[:50]
    return code


def seed_kptcl_departments_from_excel():
    """Read Excel and create complete department hierarchy"""
    session = VendorSessionLocal()

    try:
        print("\n" + "=" * 80)
        print("  SEED KPTCL DEPARTMENTS FROM EXCEL")
        print("=" * 80 + "\n")

        # Step 1: Get KPTCL organization
        result = session.execute(
            text("SELECT id FROM organizations WHERE code = 'KPTCL'")
        ).fetchone()

        if not result:
            print("[ERROR] KPTCL organization not found!")
            exit(1)

        org_id = str(result[0])
        print(f"[OK] Found KPTCL organization: {org_id}\n")

        # Step 2: Delete existing KPTCL departments
        deleted = session.execute(
            text("DELETE FROM org_departments WHERE organization_id = :org_id"),
            {'org_id': org_id}
        ).rowcount

        print(f"[OK] Deleted {deleted} existing departments\n")
        session.commit()

        # Step 3: Read Excel file
        import os
        project_root = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(project_root, "KPTCL_Substation_Mapping.xlsx")
        print(f"[INFO] Reading Excel file: {excel_path}")

        df = pd.read_excel(excel_path)
        print(f"[OK] Loaded {len(df)} rows from Excel\n")

        # Step 4: Create department hierarchy
        # Track created departments to avoid duplicates
        created_depts = {}  # {name: id}

        total_created = 0

        # Process each row
        for idx, row in df.iterrows():
            zone_name = str(row['Zone']).strip()
            circle_name = str(row['Circle']).strip()
            division_name = str(row['Division']).strip()
            subdivision_name = str(row['Sub Division']).strip()
            section_name = str(row['Section']).strip()
            substation_name = str(row['Substation']).strip()

            # Create Zone (level 1)
            if zone_name not in created_depts:
                zone_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                        VALUES (:id, :org_id, :name, :code, NULL, true, :cts, :mts)
                    """),
                    {
                        'id': zone_id,
                        'org_id': org_id,
                        'name': zone_name,
                        'code': generate_code(zone_name),
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                created_depts[zone_name] = zone_id
                total_created += 1
                if total_created % 50 == 0:
                    print(f"[PROGRESS] Created {total_created} departments...")

            # Create Circle (level 2)
            circle_key = f"{zone_name}|{circle_name}"
            if circle_key not in created_depts:
                circle_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                        VALUES (:id, :org_id, :name, :code, :parent_id, true, :cts, :mts)
                    """),
                    {
                        'id': circle_id,
                        'org_id': org_id,
                        'name': circle_name,
                        'code': generate_code(circle_name),
                        'parent_id': created_depts[zone_name],
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                created_depts[circle_key] = circle_id
                total_created += 1
                if total_created % 50 == 0:
                    print(f"[PROGRESS] Created {total_created} departments...")

            # Create Division (level 3)
            division_key = f"{zone_name}|{circle_name}|{division_name}"
            if division_key not in created_depts:
                division_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                        VALUES (:id, :org_id, :name, :code, :parent_id, true, :cts, :mts)
                    """),
                    {
                        'id': division_id,
                        'org_id': org_id,
                        'name': division_name,
                        'code': generate_code(division_name),
                        'parent_id': created_depts[circle_key],
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                created_depts[division_key] = division_id
                total_created += 1
                if total_created % 50 == 0:
                    print(f"[PROGRESS] Created {total_created} departments...")

            # Create Sub Division (level 4)
            subdivision_key = f"{zone_name}|{circle_name}|{division_name}|{subdivision_name}"
            if subdivision_key not in created_depts:
                subdivision_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                        VALUES (:id, :org_id, :name, :code, :parent_id, true, :cts, :mts)
                    """),
                    {
                        'id': subdivision_id,
                        'org_id': org_id,
                        'name': subdivision_name,
                        'code': generate_code(subdivision_name),
                        'parent_id': created_depts[division_key],
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                created_depts[subdivision_key] = subdivision_id
                total_created += 1
                if total_created % 50 == 0:
                    print(f"[PROGRESS] Created {total_created} departments...")

            # Create Section (level 5)
            section_key = f"{zone_name}|{circle_name}|{division_name}|{subdivision_name}|{section_name}"
            if section_key not in created_depts:
                section_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                        VALUES (:id, :org_id, :name, :code, :parent_id, true, :cts, :mts)
                    """),
                    {
                        'id': section_id,
                        'org_id': org_id,
                        'name': section_name,
                        'code': generate_code(section_name),
                        'parent_id': created_depts[subdivision_key],
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                created_depts[section_key] = section_id
                total_created += 1
                if total_created % 50 == 0:
                    print(f"[PROGRESS] Created {total_created} departments...")

            # Create Substation (level 6)
            substation_key = f"{zone_name}|{circle_name}|{division_name}|{subdivision_name}|{section_name}|{substation_name}"
            if substation_key not in created_depts:
                substation_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                        VALUES (:id, :org_id, :name, :code, :parent_id, true, :cts, :mts)
                    """),
                    {
                        'id': substation_id,
                        'org_id': org_id,
                        'name': substation_name,
                        'code': generate_code(substation_name),
                        'parent_id': created_depts[section_key],
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                created_depts[substation_key] = substation_id
                total_created += 1
                if total_created % 50 == 0:
                    print(f"[PROGRESS] Created {total_created} departments...")

        # Commit all changes
        session.commit()

        print(f"\n[PROGRESS] Created {total_created} departments...")
        print("\n" + "=" * 80)
        print(f"  [SUCCESS] Created {total_created} departments")
        print("=" * 80 + "\n")

        # Print summary
        print("Hierarchy Summary:")
        print(f"  Zones: {len([k for k in created_depts.keys() if '|' not in k])}")
        print(f"  Circles: {len([k for k in created_depts.keys() if k.count('|') == 1])}")
        print(f"  Divisions: {len([k for k in created_depts.keys() if k.count('|') == 2])}")
        print(f"  Sub Divisions: {len([k for k in created_depts.keys() if k.count('|') == 3])}")
        print(f"  Sections: {len([k for k in created_depts.keys() if k.count('|') == 4])}")
        print(f"  Substations: {len([k for k in created_depts.keys() if k.count('|') == 5])}")

        print("\n" + "=" * 80 + "\n")

        # Step 5: Update user department assignments
        print("Updating user department assignments...\n")

        # Get sample departments for user assignments
        rt_north_div = session.execute(
            text("SELECT id, name FROM org_departments WHERE organization_id = :org_id AND name = 'RT North Division'"),
            {'org_id': org_id}
        ).fetchone()

        rt_north_sd1 = session.execute(
            text("SELECT id, name FROM org_departments WHERE organization_id = :org_id AND name LIKE 'RT North SD%' LIMIT 1"),
            {'org_id': org_id}
        ).fetchone()

        yelahanka_section = session.execute(
            text("SELECT id, name FROM org_departments WHERE organization_id = :org_id AND name LIKE '%Yelahanka%Section%' LIMIT 1"),
            {'org_id': org_id}
        ).fetchone()

        yelahanka_substation = session.execute(
            text("SELECT id, name FROM org_departments WHERE organization_id = :org_id AND name LIKE '%220%Yelahanka%' AND parent_department_id IS NOT NULL LIMIT 1"),
            {'org_id': org_id}
        ).fetchone()

        # Update users
        user_updates = [
            ('orgadmin@kptcl.com', None),
            ('depthead@kptcl.com', rt_north_div[0] if rt_north_div else None),
            ('tester1@kptcl.com', yelahanka_section[0] if yelahanka_section else None),
            ('tester2@kptcl.com', rt_north_sd1[0] if rt_north_sd1 else None),
            ('engineer@kptcl.com', yelahanka_substation[0] if yelahanka_substation else None)
        ]

        for email, dept_id in user_updates:
            session.execute(
                text("UPDATE users SET department_id = :dept_id, mts = :mts WHERE email = :email"),
                {'dept_id': dept_id, 'email': email, 'mts': datetime.now()}
            )
            if dept_id:
                session.execute(
                    text("UPDATE org_user_roles SET department_id = :dept_id WHERE user_id = (SELECT id FROM users WHERE email = :email)"),
                    {'dept_id': dept_id, 'email': email}
                )

        session.commit()
        print("[OK] Updated all user department assignments\n")

        print("=" * 80 + "\n")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    seed_kptcl_departments_from_excel()
