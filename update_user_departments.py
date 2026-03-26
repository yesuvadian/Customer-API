#!/usr/bin/env python3
"""
Update KPTCL User Department Assignments to Real Departments
"""

from datetime import datetime
from sqlalchemy import text
from database import VendorSessionLocal


def update_user_departments():
    """Update user department assignments"""
    session = VendorSessionLocal()

    try:
        print("\n" + "=" * 80)
        print("  UPDATE USER DEPARTMENT ASSIGNMENTS")
        print("=" * 80 + "\n")

        # Get KPTCL org
        org = session.execute(
            text("SELECT id FROM organizations WHERE code = 'KPTCL'")
        ).fetchone()

        if not org:
            print("[ERROR] KPTCL organization not found!")
            exit(1)

        org_id = str(org[0])

        # Get sample departments from hierarchy
        print("Fetching real departments from hierarchy...\n")

        # Get Bengaluru Zone
        bengaluru_zone = session.execute(
            text("""
                SELECT id, name FROM org_departments
                WHERE organization_id = :org_id
                AND name = 'Bengaluru Zone'
                AND parent_department_id IS NULL
            """),
            {'org_id': org_id}
        ).fetchone()

        # Get RT North Division
        rt_north_div = session.execute(
            text("""
                SELECT id, name FROM org_departments
                WHERE organization_id = :org_id
                AND name = 'RT North Division'
            """),
            {'org_id': org_id}
        ).fetchone()

        # Get a subdivision under RT North
        rt_north_sd1 = session.execute(
            text("""
                SELECT id, name FROM org_departments
                WHERE organization_id = :org_id
                AND name LIKE 'RT North SD%'
                LIMIT 1
            """),
            {'org_id': org_id}
        ).fetchone()

        # Get Yelahanka Section
        yelahanka_section = session.execute(
            text("""
                SELECT d.id, d.name
                FROM org_departments d
                WHERE d.organization_id = :org_id
                AND d.name LIKE '%Yelahanka%Section%'
                LIMIT 1
            """),
            {'org_id': org_id}
        ).fetchone()

        # Get 220kV Yelahanka Substation
        yelahanka_substation = session.execute(
            text("""
                SELECT d.id, d.name
                FROM org_departments d
                WHERE d.organization_id = :org_id
                AND d.name LIKE '%220%Yelahanka%'
                AND d.parent_department_id IS NOT NULL
                LIMIT 1
            """),
            {'org_id': org_id}
        ).fetchone()

        # User assignments
        user_assignments = [
            ('orgadmin@kptcl.com', None, 'Organization Admin', 'Organization level (no specific department)'),
            ('depthead@kptcl.com', rt_north_div[0] if rt_north_div else None, 'Department Head', rt_north_div[1] if rt_north_div else 'N/A'),
            ('tester1@kptcl.com', yelahanka_section[0] if yelahanka_section else None, 'Tester', yelahanka_section[1] if yelahanka_section else 'N/A'),
            ('tester2@kptcl.com', rt_north_sd1[0] if rt_north_sd1 else None, 'Tester', rt_north_sd1[1] if rt_north_sd1 else 'N/A'),
            ('engineer@kptcl.com', yelahanka_substation[0] if yelahanka_substation else None, 'Engineer', yelahanka_substation[1] if yelahanka_substation else 'N/A')
        ]

        print("Updating user department assignments:\n")

        for email, dept_id, role, dept_name in user_assignments:
            # Update user
            session.execute(
                text("""
                    UPDATE users
                    SET department_id = :dept_id, mts = :mts
                    WHERE email = :email
                """),
                {
                    'dept_id': dept_id,
                    'email': email,
                    'mts': datetime.now()
                }
            )

            # Update role assignment department
            if dept_id:
                session.execute(
                    text("""
                        UPDATE org_user_roles
                        SET department_id = :dept_id
                        WHERE user_id = (SELECT id FROM users WHERE email = :email)
                    """),
                    {
                        'dept_id': dept_id,
                        'email': email
                    }
                )

            dept_display = dept_name if dept_id else "None (Organization level)"
            print(f"[OK] {email:30} - {dept_display}")

        session.commit()

        print("\n" + "=" * 80)
        print("  [SUCCESS] Updated all user department assignments")
        print("=" * 80 + "\n")

        print("Updated User Assignments:\n")
        print(f"{'Email':<30} {'Role':<20} {'Department'}")
        print("-" * 100)
        for email, dept_id, role, dept_name in user_assignments:
            dept_display = dept_name if dept_id else "None (Org level)"
            print(f"{email:<30} {role:<20} {dept_display}")

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    update_user_departments()
