"""
Check if orgadmin@kptcl.com exists in the custom database
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

print(f"Connecting to database: {DB_NAME} as {DB_USER}@{DB_HOST}:{DB_PORT}")

# Create connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

try:
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        print("="*80)
        print("Checking KPTCL users...")
        print("="*80)

        # Check all KPTCL users
        result = conn.execute(text("""
            SELECT
                u.id,
                u.email,
                u.firstname,
                u.lastname,
                u.organization_id,
                u.isactive,
                u.email_confirmed,
                o.name as org_name,
                o.code as org_code
            FROM users u
            LEFT JOIN organizations o ON o.id = u.organization_id
            WHERE u.email LIKE '%kptcl.com'
            ORDER BY u.email
        """))

        users = result.fetchall()

        if users:
            print(f"\n[OK] Found {len(users)} KPTCL user(s):\n")
            for user in users:
                print(f"Email: {user[1]}")
                print(f"   Name: {user[2]} {user[3]}")
                print(f"   Organization: {user[8] or 'None'} ({user[7] or 'N/A'})")
                print(f"   Organization ID: {user[4] or 'None'}")
                print(f"   Is Active: {user[5]}")
                print(f"   Email Confirmed: {user[6]}")

                # Check roles for this user
                if user[0]:
                    roles_result = conn.execute(text("""
                        SELECT
                            r.name,
                            our.is_active,
                            r.is_org_admin
                        FROM org_user_roles our
                        JOIN org_roles r ON r.id = our.org_role_id
                        WHERE our.user_id = :user_id
                    """), {"user_id": user[0]})

                    roles = roles_result.fetchall()
                    if roles:
                        print(f"   Roles:")
                        for role in roles:
                            admin_flag = " [ORG ADMIN]" if role[2] else ""
                            print(f"      - {role[0]} (Active: {role[1]}){admin_flag}")
                    else:
                        print(f"   [ERROR] No roles assigned!")
                print()

            # Check KPTCL organization
            org_result = conn.execute(text("""
                SELECT id, name, code, is_active, is_verified
                FROM organizations
                WHERE code = 'KPTCL'
            """))

            org = org_result.fetchone()
            if org:
                print(f"[OK] KPTCL Organization:")
                print(f"   ID: {org[0]}")
                print(f"   Name: {org[1]}")
                print(f"   Code: {org[2]}")
                print(f"   Is Active: {org[3]}")
                print(f"   Is Verified: {org[4]}")

                # Count departments
                dept_result = conn.execute(text("""
                    SELECT COUNT(*) FROM org_departments
                    WHERE organization_id = :org_id
                """), {"org_id": org[0]})
                dept_count = dept_result.fetchone()[0]
                print(f"   Departments: {dept_count}")
            else:
                print(f"\n[ERROR] KPTCL organization not found!")

        else:
            print(f"\n[ERROR] No KPTCL users found in database!")
            print(f"\n[FIX] Run: python seed.py")

        print("\n" + "="*80)
        print("\n[INFO] Login credentials from seed.py:")
        print("   Email: orgadmin@kptcl.com")
        print("   Password: admin123")
        print("="*80)

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
