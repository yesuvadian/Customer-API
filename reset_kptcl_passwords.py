#!/usr/bin/env python3
"""Reset all KPTCL user passwords to admin123"""

from datetime import datetime
from sqlalchemy import text
from database import VendorSessionLocal
from security_utils import get_password_hash

session = VendorSessionLocal()

try:
    print("\n" + "=" * 60)
    print("  RESET KPTCL USER PASSWORDS")
    print("=" * 60 + "\n")

    # Get KPTCL organization ID
    result = session.execute(
        text("SELECT id FROM organizations WHERE code = 'KPTCL'")
    ).fetchone()

    if not result:
        print("[ERROR] KPTCL organization not found!")
        exit(1)

    org_id = str(result[0])
    password_hash = get_password_hash("admin123")

    # Get all KPTCL users
    users = session.execute(
        text("SELECT id, email, firstname, lastname FROM users WHERE organization_id = :org_id"),
        {'org_id': org_id}
    ).fetchall()

    if not users:
        print("[ERROR] No KPTCL users found!")
        exit(1)

    print(f"Found {len(users)} KPTCL users\n")

    # Update passwords
    for user_id, email, firstname, lastname in users:
        session.execute(
            text("""
            UPDATE users
            SET password_hash = :password_hash, mts = :mts
            WHERE id = :user_id
            """),
            {
                'password_hash': password_hash,
                'mts': datetime.now(),
                'user_id': user_id
            }
        )
        print(f"[OK] Updated password for: {email} ({firstname} {lastname})")

    session.commit()

    print("\n" + "=" * 60)
    print("  [SUCCESS] All passwords reset to: admin123")
    print("=" * 60 + "\n")

    print("You can now login with any of these accounts:")
    for _, email, firstname, lastname in users:
        print(f"  {email} / admin123")

    print("\n" + "=" * 60 + "\n")

except Exception as e:
    session.rollback()
    print(f"\n[ERROR] Failed to reset passwords: {e}")
    import traceback
    traceback.print_exc()
finally:
    session.close()
