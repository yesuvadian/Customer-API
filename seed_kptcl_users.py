"""
Seed KPTCL Organization with Sample Users
This script adds KPTCL organization and 5 sample users to the database
"""

import uuid
from datetime import datetime
from database import VendorSessionLocal
from models import Organization, OrgRole, OrgDepartment, User, OrgUserRole
from security_utils import get_password_hash


def get_or_create_kptcl_org(session):
    """Get existing KPTCL org or create new one"""
    org = session.query(Organization).filter_by(code='KPTCL').first()

    if org:
        print(f"[INFO] KPTCL organization already exists: {org.id}")
        return org

    # Create KPTCL organization
    org = Organization(
        id=uuid.uuid4(),
        name="Karnataka Power Transmission Corporation Limited",
        code="KPTCL",
        display_name="KPTCL",
        organization_type="utility",
        industry="Power Transmission",
        primary_email="info@kptcl.com",
        primary_phone="+91-XXXX-XXXXX",
        is_active=True,
        is_verified=True,
        settings={},
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(org)
    session.flush()
    print(f"[OK] Created KPTCL organization: {org.id}")
    return org


def create_departments(session, org_id):
    """Create 6-level department hierarchy"""
    departments = {}

    # Zone
    zone = OrgDepartment(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Bangalore Zone",
        code="BLR_ZONE",
        parent_department_id=None,
        is_active=True,
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(zone)
    session.flush()
    departments['zone'] = zone.id

    # Circle
    circle = OrgDepartment(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Bangalore Transmission Circle",
        code="BLR_TRANS_CIRCLE",
        parent_department_id=zone.id,
        is_active=True,
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(circle)
    session.flush()
    departments['circle'] = circle.id

    # Division
    division = OrgDepartment(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="RT North Division",
        code="RT_NORTH_DIV",
        parent_department_id=circle.id,
        is_active=True,
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(division)
    session.flush()
    departments['division'] = division.id

    # Subdivision
    subdivision = OrgDepartment(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="RT North SD1 Yelahanka",
        code="RT_NORTH_SD1",
        parent_department_id=division.id,
        is_active=True,
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(subdivision)
    session.flush()
    departments['subdivision'] = subdivision.id

    # Section
    section = OrgDepartment(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Yelahanka Section",
        code="YLK_SECTION",
        parent_department_id=subdivision.id,
        is_active=True,
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(section)
    session.flush()
    departments['section'] = section.id

    # Substation
    substation = OrgDepartment(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="220kV Yelahanka Substation",
        code="220KV_YLK",
        parent_department_id=section.id,
        is_active=True,
        cts=datetime.now(),
        mts=datetime.now()
    )
    session.add(substation)
    session.flush()
    departments['substation'] = substation.id

    print(f"[OK] Created 6-level department hierarchy")
    return departments


def create_roles(session, org_id):
    """Create 5 organization roles"""
    roles_data = [
        ("Organization Admin", "Full administrative access to organization", True, False),
        ("Department Head", "Head of department with management privileges", False, True),
        ("Tester", "Testing personnel who conduct equipment tests", False, False),
        ("Engineer", "Engineering staff who request testing", False, False),
        ("Section Head", "Section level supervisor", False, True)
    ]

    roles = {}
    for name, description, is_org_admin, is_dept_admin in roles_data:
        # Check if exists
        existing = session.query(OrgRole).filter_by(
            organization_id=org_id,
            name=name
        ).first()

        if existing:
            roles[name] = existing.id
            continue

        role = OrgRole(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            description=description,
            is_org_admin=is_org_admin,
            is_dept_admin=is_dept_admin,
            is_active=True,
            cts=datetime.now(),
            mts=datetime.now()
        )
        session.add(role)
        session.flush()
        roles[name] = role.id

    print(f"[OK] Created/verified {len(roles_data)} roles")
    return roles


def create_sample_users(session, org_id, departments, roles):
    """Create 5 sample users with role assignments"""
    users_data = [
        ("orgadmin@kptcl.com", "Organization", "Admin", "9876543210", None, "Organization Admin"),
        ("depthead@kptcl.com", "Ramesh", "Kumar", "9876543211", departments['division'], "Department Head"),
        ("tester1@kptcl.com", "Suresh", "Reddy", "9876543212", departments['section'], "Tester"),
        ("tester2@kptcl.com", "Lakshmi", "Narayanan", "9876543213", departments['subdivision'], "Tester"),
        ("engineer@kptcl.com", "Priya", "Sharma", "9876543214", departments['substation'], "Engineer")
    ]

    password_hash = get_password_hash("admin123")
    created_users = []

    for email, firstname, lastname, phone, dept_id, role_name in users_data:
        # Check if user exists
        existing = session.query(User).filter_by(email=email).first()

        if existing:
            # Update organization and department
            existing.organization_id = org_id
            existing.department_id = dept_id
            print(f"[INFO] Updated existing user: {email}")
            user_id = existing.id
        else:
            # Create new user
            user = User(
                id=uuid.uuid4(),
                email=email,
                password_hash=password_hash,
                firstname=firstname,
                lastname=lastname,
                phone_number=phone,
                organization_id=org_id,
                department_id=dept_id,
                isactive=True,
                email_confirmed=True,
                phone_confirmed=True,
                cts=datetime.now(),
                mts=datetime.now()
            )
            session.add(user)
            session.flush()
            user_id = user.id
            print(f"[OK] Created user: {email}")

        # Assign role
        existing_role = session.query(OrgUserRole).filter_by(
            user_id=user_id,
            org_role_id=roles[role_name]
        ).first()

        if not existing_role:
            user_role = OrgUserRole(
                id=uuid.uuid4(),
                user_id=user_id,
                org_role_id=roles[role_name],
                department_id=dept_id,
                is_active=True,
                assigned_at=datetime.now()
            )
            session.add(user_role)

        created_users.append((email, role_name))

    session.flush()
    print(f"[OK] Created/updated {len(users_data)} users with role assignments")
    return created_users


def seed_kptcl_organization():
    """Main function to seed KPTCL organization and sample users"""
    session = VendorSessionLocal()

    try:
        print("\n" + "=" * 80)
        print("  KPTCL ORGANIZATION SEEDING")
        print("=" * 80 + "\n")

        # Step 1: Create/Get Organization
        org = get_or_create_kptcl_org(session)

        # Step 2: Create Departments
        departments = create_departments(session, org.id)

        # Step 3: Create Roles
        roles = create_roles(session, org.id)

        # Step 4: Create Sample Users
        users = create_sample_users(session, org.id, departments, roles)

        # Commit all changes
        session.commit()

        print("\n" + "=" * 80)
        print("  [OK] KPTCL ORGANIZATION SEEDED SUCCESSFULLY")
        print("=" * 80 + "\n")

        print("Sample Users Created (password: admin123 for all):")
        for email, role in users:
            print(f"  {email:30} → {role}")

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
