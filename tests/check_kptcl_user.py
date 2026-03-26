"""
Check if orgadmin@kptcl.com exists and has organization_id set
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# Get DB credentials from .env
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "cogniwatt_db")

# Create connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

try:
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        print("="*80)
        print("Checking orgadmin@kptcl.com user...")
        print("="*80)

        # Check user
        result = conn.execute(text("""
            SELECT
                id,
                email,
                firstname,
                lastname,
                organization_id,
                isactive,
                email_confirmed
            FROM users
            WHERE email = 'orgadmin@kptcl.com'
        """))

        user = result.fetchone()

        if user:
            print(f"\n[OK] User found:")
            print(f"   ID: {user[0]}")
            print(f"   Email: {user[1]}")
            print(f"   Name: {user[2]} {user[3]}")
            print(f"   Organization ID: {user[4]}")
            print(f"   Is Active: {user[5]}")
            print(f"   Email Confirmed: {user[6]}")

            if user[4]:  # organization_id exists
                # Check organization
                org_result = conn.execute(text("""
                    SELECT id, name, code, display_name, is_active, is_verified
                    FROM organizations
                    WHERE id = :org_id
                """), {"org_id": user[4]})

                org = org_result.fetchone()
                if org:
                    print(f"\n[OK] Organization found:")
                    print(f"   ID: {org[0]}")
                    print(f"   Name: {org[1]}")
                    print(f"   Code: {org[2]}")
                    print(f"   Display Name: {org[3]}")
                    print(f"   Is Active: {org[4]}")
                    print(f"   Is Verified: {org[5]}")

                    # Check department count
                    dept_result = conn.execute(text("""
                        SELECT COUNT(*) FROM org_departments
                        WHERE organization_id = :org_id
                    """), {"org_id": user[4]})
                    dept_count = dept_result.fetchone()[0]
                    print(f"   Departments: {dept_count}")
                else:
                    print(f"\n[ERROR] Organization {user[4]} not found in database!")

                # Check roles
                roles_result = conn.execute(text("""
                    SELECT
                        our.id,
                        our.is_active,
                        r.name,
                        r.is_org_admin
                    FROM org_user_roles our
                    JOIN org_roles r ON r.id = our.org_role_id
                    WHERE our.user_id = :user_id
                """), {"user_id": user[0]})

                roles = roles_result.fetchall()
                if roles:
                    print(f"\n[OK] User roles:")
                    for role in roles:
                        print(f"   - {role[2]} (Active: {role[1]}, Is Org Admin: {role[3]})")
                else:
                    print(f"\n[ERROR] No roles assigned to user!")

            else:
                print(f"\n[ERROR] User has no organization_id set!")
                print(f"\n[FIX] Need to run: python seed.py")
        else:
            print(f"\n[ERROR] User not found in database!")
            print(f"\n[FIX] Need to run: python seed.py")

        print("\n" + "="*80)

except Exception as e:
    print(f"Error: {e}")
