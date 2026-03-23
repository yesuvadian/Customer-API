#!/usr/bin/env python3
"""
Simple KPTCL Seeding Script Using Raw SQL
Bypasses SQLAlchemy ORM relationship issues
"""

import uuid
from datetime import datetime
from sqlalchemy import text
from database import VendorSessionLocal
from security_utils import get_password_hash


def seed_kptcl_organization():
    """Seed KPTCL organization using raw SQL"""
    session = VendorSessionLocal()

    try:
        print("\n" + "=" * 80)
        print("  KPTCL ORGANIZATION SEEDING (RAW SQL)")
        print("=" * 80 + "\n")

        # Generate UUIDs
        org_id = str(uuid.uuid4())

        dept_ids = {
            'zone': str(uuid.uuid4()),
            'circle': str(uuid.uuid4()),
            'division': str(uuid.uuid4()),
            'subdivision': str(uuid.uuid4()),
            'section': str(uuid.uuid4()),
            'substation': str(uuid.uuid4())
        }

        role_ids = {
            'Organization Admin': str(uuid.uuid4()),
            'Department Head': str(uuid.uuid4()),
            'Tester': str(uuid.uuid4()),
            'Engineer': str(uuid.uuid4()),
            'Section Head': str(uuid.uuid4())
        }

        user_ids = {
            'orgadmin': str(uuid.uuid4()),
            'depthead': str(uuid.uuid4()),
            'tester1': str(uuid.uuid4()),
            'tester2': str(uuid.uuid4()),
            'engineer': str(uuid.uuid4())
        }

        password_hash = get_password_hash("admin123")

        # Step 1: Check/Create Organization
        result = session.execute(
            text("SELECT id FROM organizations WHERE code = 'KPTCL'")
        ).fetchone()

        if result:
            org_id = str(result[0])
            print(f"[INFO] KPTCL organization already exists: {org_id}")
        else:
            session.execute(
                text("""
                INSERT INTO organizations (id, name, code, display_name, organization_type,
                    industry, primary_email, primary_phone, is_active, is_verified, settings, cts, mts)
                VALUES (:id, :name, :code, :display_name, :org_type, :industry, :email, :phone,
                    :is_active, :is_verified, :settings, :cts, :mts)
                """),
                {
                    'id': org_id,
                    'name': 'Karnataka Power Transmission Corporation Limited',
                    'code': 'KPTCL',
                    'display_name': 'KPTCL',
                    'org_type': 'utility',
                    'industry': 'Power Transmission',
                    'email': 'info@kptcl.com',
                    'phone': '+91-XXXX-XXXXX',
                    'is_active': True,
                    'is_verified': True,
                    'settings': '{}',
                    'cts': datetime.now(),
                    'mts': datetime.now()
                }
            )
            print(f"[OK] Created KPTCL organization: {org_id}")

        # Step 2: Create Departments (6-level hierarchy)
        departments = [
            (dept_ids['zone'], org_id, 'Bangalore Zone', 'BLR_ZONE', None),
            (dept_ids['circle'], org_id, 'Bangalore Transmission Circle', 'BLR_TRANS_CIRCLE', dept_ids['zone']),
            (dept_ids['division'], org_id, 'RT North Division', 'RT_NORTH_DIV', dept_ids['circle']),
            (dept_ids['subdivision'], org_id, 'RT North SD1 Yelahanka', 'RT_NORTH_SD1', dept_ids['division']),
            (dept_ids['section'], org_id, 'Yelahanka Section', 'YLK_SECTION', dept_ids['subdivision']),
            (dept_ids['substation'], org_id, '220kV Yelahanka Substation', '220KV_YLK', dept_ids['section'])
        ]

        for dept_id, org_id_val, name, code, parent_id in departments:
            # Check if exists by organization and name
            result = session.execute(
                text("SELECT id FROM org_departments WHERE organization_id = :org_id AND name = :name"),
                {'org_id': org_id_val, 'name': name}
            ).fetchone()

            if result:
                # Update dept_ids dict with existing ID
                for key, val in dept_ids.items():
                    if val == dept_id:
                        dept_ids[key] = str(result[0])
                        break
            else:
                session.execute(
                    text("""
                    INSERT INTO org_departments (id, organization_id, name, code,
                        parent_department_id, is_active, cts, mts)
                    VALUES (:id, :org_id, :name, :code, :parent_id, :is_active, :cts, :mts)
                    """),
                    {
                        'id': dept_id,
                        'org_id': org_id_val,
                        'name': name,
                        'code': code,
                        'parent_id': parent_id,
                        'is_active': True,
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )

        print(f"[OK] Created 6-level department hierarchy")

        # Step 3: Create Roles
        roles = [
            ('Organization Admin', 'Full administrative access to organization', True, False),
            ('Department Head', 'Head of department with management privileges', False, True),
            ('Tester', 'Testing personnel who conduct equipment tests', False, False),
            ('Engineer', 'Engineering staff who request testing', False, False),
            ('Section Head', 'Section level supervisor', False, True)
        ]

        for name, description, is_org_admin, is_dept_admin in roles:
            role_id = role_ids[name]

            # Check if exists
            result = session.execute(
                text("SELECT id FROM org_roles WHERE organization_id = :org_id AND name = :name"),
                {'org_id': org_id, 'name': name}
            ).fetchone()

            if not result:
                session.execute(
                    text("""
                    INSERT INTO org_roles (id, organization_id, name, description,
                        is_org_admin, is_dept_admin, is_active, cts, mts)
                    VALUES (:id, :org_id, :name, :description, :is_org_admin,
                        :is_dept_admin, :is_active, :cts, :mts)
                    """),
                    {
                        'id': role_id,
                        'org_id': org_id,
                        'name': name,
                        'description': description,
                        'is_org_admin': is_org_admin,
                        'is_dept_admin': is_dept_admin,
                        'is_active': True,
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )

        print(f"[OK] Created/verified {len(roles)} roles")

        # Step 4: Create Users
        users = [
            ('orgadmin', 'orgadmin@kptcl.com', 'Organization', 'Admin', '9876543210', None, 'Organization Admin'),
            ('depthead', 'depthead@kptcl.com', 'Ramesh', 'Kumar', '9876543211', dept_ids['division'], 'Department Head'),
            ('tester1', 'tester1@kptcl.com', 'Suresh', 'Reddy', '9876543212', dept_ids['section'], 'Tester'),
            ('tester2', 'tester2@kptcl.com', 'Lakshmi', 'Narayanan', '9876543213', dept_ids['subdivision'], 'Tester'),
            ('engineer', 'engineer@kptcl.com', 'Priya', 'Sharma', '9876543214', dept_ids['substation'], 'Engineer')
        ]

        created_users = []

        for user_key, email, firstname, lastname, phone, dept_id, role_name in users:
            user_id = user_ids[user_key]

            # Check if user exists
            result = session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {'email': email}
            ).fetchone()

            if result:
                # Update existing user
                session.execute(
                    text("""
                    UPDATE users
                    SET organization_id = :org_id, department_id = :dept_id, mts = :mts
                    WHERE email = :email
                    """),
                    {
                        'org_id': org_id,
                        'dept_id': dept_id,
                        'email': email,
                        'mts': datetime.now()
                    }
                )
                user_id = str(result[0])
                print(f"[INFO] Updated existing user: {email}")
            else:
                # Create new user
                session.execute(
                    text("""
                    INSERT INTO users (id, email, password_hash, firstname, lastname,
                        phone_number, organization_id, department_id, isactive,
                        email_confirmed, phone_confirmed, cts, mts)
                    VALUES (:id, :email, :password, :firstname, :lastname, :phone,
                        :org_id, :dept_id, :isactive, :email_confirmed, :phone_confirmed, :cts, :mts)
                    """),
                    {
                        'id': user_id,
                        'email': email,
                        'password': password_hash,
                        'firstname': firstname,
                        'lastname': lastname,
                        'phone': phone,
                        'org_id': org_id,
                        'dept_id': dept_id,
                        'isactive': True,
                        'email_confirmed': True,
                        'phone_confirmed': True,
                        'cts': datetime.now(),
                        'mts': datetime.now()
                    }
                )
                print(f"[OK] Created user: {email}")

            # Assign role
            role_id = role_ids[role_name]
            result = session.execute(
                text("SELECT id FROM org_user_roles WHERE user_id = :user_id AND org_role_id = :role_id"),
                {'user_id': user_id, 'role_id': role_id}
            ).fetchone()

            if not result:
                session.execute(
                    text("""
                    INSERT INTO org_user_roles (id, user_id, org_role_id, department_id,
                        is_active, assigned_at)
                    VALUES (:id, :user_id, :role_id, :dept_id, :is_active, :assigned_at)
                    """),
                    {
                        'id': str(uuid.uuid4()),
                        'user_id': user_id,
                        'role_id': role_id,
                        'dept_id': dept_id,
                        'is_active': True,
                        'assigned_at': datetime.now()
                    }
                )

            created_users.append((email, role_name))

        print(f"[OK] Created/updated {len(users)} users with role assignments")

        # Commit all changes
        session.commit()

        print("\n" + "=" * 80)
        print("  [OK] KPTCL ORGANIZATION SEEDED SUCCESSFULLY")
        print("=" * 80 + "\n")

        print("Sample Users Created (password: admin123 for all):")
        for email, role in created_users:
            print(f"  {email:30} - {role}")

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed to seed KPTCL organization: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    seed_kptcl_organization()
