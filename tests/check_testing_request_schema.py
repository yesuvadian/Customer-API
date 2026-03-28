import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

print("="*60)
print("CHECKING testing_requests TABLE SCHEMA")
print("="*60)

with engine.connect() as conn:
    # Check columns
    result = conn.execute(text("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'testing_requests'
        ORDER BY ordinal_position;
    """))
    columns = result.fetchall()
    print(f"\nColumns in testing_requests:")
    has_org_id = False
    for col in columns:
        if col[0] == 'organization_id':
            has_org_id = True
            print(f"  [FOUND] {col[0]}: {col[1]} (nullable: {col[2]})")
        else:
            print(f"  - {col[0]}: {col[1]}")

    if not has_org_id:
        print(f"\n[ERROR] organization_id column NOT FOUND in testing_requests table!")

print("\n" + "="*60)
