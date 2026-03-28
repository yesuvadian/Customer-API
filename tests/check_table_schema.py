import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

print("="*60)
print("CHECKING TABLE SCHEMA")
print("="*60)

with engine.connect() as conn:
    # Check if table exists
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'tester_role_module_requirements'
        );
    """))
    exists = result.scalar()
    print(f"\nTable exists: {exists}")

    if exists:
        # Check constraints
        result = conn.execute(text("""
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_schema = 'public'
            AND table_name = 'tester_role_module_requirements';
        """))
        constraints = result.fetchall()
        print(f"\nConstraints:")
        for c in constraints:
            print(f"  - {c[0]}: {c[1]}")

        # Check columns
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'tester_role_module_requirements'
            ORDER BY ordinal_position;
        """))
        columns = result.fetchall()
        print(f"\nColumns:")
        for col in columns:
            print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")

print("\n" + "="*60)
