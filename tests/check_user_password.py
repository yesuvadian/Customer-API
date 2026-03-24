#!/usr/bin/env python3
"""Check user password in database"""

from sqlalchemy import text
from database import VendorSessionLocal
from security_utils import verify_password

session = VendorSessionLocal()

try:
    # Get engineer user
    result = session.execute(
        text("SELECT email, password_hash FROM users WHERE email = 'engineer@kptcl.com'")
    ).fetchone()

    if result:
        email, password_hash = result
        print(f"User found: {email}")
        print(f"Password hash exists: {password_hash is not None}")
        print(f"Password hash length: {len(password_hash) if password_hash else 0}")

        if password_hash:
            print(f"Password hash preview: {password_hash[:50]}...")

            # Test verification
            is_valid = verify_password("admin123", password_hash)
            print(f"Password 'admin123' verification: {is_valid}")
        else:
            print("ERROR: Password hash is NULL!")
    else:
        print("ERROR: User not found!")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    session.close()
