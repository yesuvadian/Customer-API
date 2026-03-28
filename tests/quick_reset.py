import sys
sys.path.insert(0, 'C:/Yesu/CustomerAPI/Customer-API')

from database import engine
from sqlalchemy import text

print("="*60)
print("DROPPING ALL TABLES")
print("="*60)

# Drop all tables using CASCADE
with engine.begin() as conn:
    # Get all table names
    result = conn.execute(text("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
    """))
    tables = [row[0] for row in result]

    print(f"\nFound {len(tables)} tables to drop")

    # Drop each table
    for table in tables:
        try:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table}" CASCADE'))
            print(f"  [OK] Dropped {table}")
        except Exception as e:
            print(f"  [WARN] Could not drop {table}: {e}")

print(f"\n[OK] All tables dropped")
print("="*60)
