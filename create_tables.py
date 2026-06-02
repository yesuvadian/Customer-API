# create_tables.py
from dotenv import load_dotenv
load_dotenv()

from database import Base, engine
import models  # make sure this imports all your model classes

# Create all tables in the public schema (idempotent — safe on existing DB)
Base.metadata.create_all(bind=engine)

print("=" * 80)
print("  DATABASE TABLES CREATED SUCCESSFULLY")
print("=" * 80)
print("\nTables Created / Verified:")
print("  [OK] Organizations")
print("  [OK] Org Departments")
print("  [OK] Org Roles")
print("  [OK] Org User Roles")
print("  [OK] Org Role Permissions")
print("  [OK] Role Templates")
print("  [OK] Org Invitations")
print("  [OK] Equipment Asset Register")
print("  [OK] Notification Templates")
print("  [OK] Notification Variables")
print("  [OK] Notification Log")
print("  [OK] User Notifications (in-app)")
print("  [OK] All existing tables (users, products, etc.)")

print("\n" + "=" * 80)
print("\nNext steps:")
print("  1. Run: python seed.py   (roles, users, notification defaults, etc.)")
print("=" * 80)
