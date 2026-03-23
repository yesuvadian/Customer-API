import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

print("="*60)
print("RUNNING TESTER ROLE MIGRATION")
print("="*60)

migration_sql = """
-- Seed global default configuration
INSERT INTO public.tester_role_module_requirements (
    organization_id,
    required_module_ids,
    description,
    is_active
) VALUES (
    NULL,
    ARRAY[45, 46, 49, 51],
    'Global default: Roles must have full permissions on Testing Requests, Testing, Testing Request Approvals, and Tester Mapping modules',
    TRUE
) ON CONFLICT (organization_id) DO NOTHING;
"""

with engine.begin() as conn:
    result = conn.execute(text(migration_sql))
    print(f"[OK] Migration executed successfully")

    # Verify
    verify = conn.execute(text("""
        SELECT id, organization_id, required_module_ids, description
        FROM public.tester_role_module_requirements
    """))

    rows = verify.fetchall()
    print(f"\nConfiguration entries: {len(rows)}")
    for row in rows:
        org = "Global" if row[1] is None else str(row[1])
        print(f"  - Org: {org}")
        print(f"    Modules: {row[2]}")
        print(f"    Description: {row[3]}")

print("\n" + "="*60)
print("MIGRATION COMPLETED")
print("="*60)
