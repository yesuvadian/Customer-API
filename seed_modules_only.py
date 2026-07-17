"""
Re-seeds modules and updates Admin privileges without touching any other data.
Safe to run on a live database — uses upsert logic (insert if not exists).

Usage:
    python seed_modules_only.py
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from database import SessionLocal
from seed import seed_modules, seed_privileges, seed_roles
from models import Role, Module

session = SessionLocal()
try:
    print("=" * 60)
    print("  Step 1: Seeding modules ...")
    print("=" * 60)
    module_ids = seed_modules(session)

    print("\n" + "=" * 60)
    print("  Step 2: Resolving role IDs ...")
    print("=" * 60)
    roles = session.query(Role).all()
    role_ids = {r.name: r.id for r in roles}
    print(f"  Found {len(role_ids)} roles.")

    print("\n" + "=" * 60)
    print("  Step 3: Seeding privileges ...")
    print("=" * 60)
    seed_privileges(session, role_ids, module_ids)

    print("\n[OK] Done.")
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    session.close()
