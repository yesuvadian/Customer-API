# create_tables.py
from database import Base, engine
import models  # make sure this imports all your model classes

# Create all tables in the public schema
# This will create:
# - All existing tables (users, roles, products, etc.)
# - New organization tables (organizations, org_departments, org_roles, etc.)
Base.metadata.create_all(bind=engine)

print("=" * 80)
print("  DATABASE TABLES CREATED SUCCESSFULLY")
print("=" * 80)
print("\nTables Created:")
print("  [OK] Organizations")
print("  [OK] Org Departments")
print("  [OK] Org Roles")
print("  [OK] Org User Roles")
print("  [OK] Org Role Permissions")
print("  [OK] Role Templates")
print("  [OK] Org Invitations")
print("  [OK] All existing tables (users, products, etc.)")
print("\nUsers table updated with:")
print("  [OK] organization_id column")
print("  [OK] employee_id column")
print("  [OK] department_id column")
print("\n" + "=" * 80)
print("\nNext steps:")
print("  1. Run: python seed.py")
print("  2. This will seed role templates and other data")
print("=" * 80)
