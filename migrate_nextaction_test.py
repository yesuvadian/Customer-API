"""
Migration: Add 'test' value to nextactiontype PostgreSQL enum.
Run once after adding NextActionType.test to models.py.

    python migrate_nextaction_test.py
"""
import sys
sys.path.insert(0, "C:/Yesu/CustomerAPI/Customer-API")

from database import engine
from sqlalchemy import text

print("=" * 60)
print("MIGRATION: Add 'test' to nextactiontype enum")
print("=" * 60)

with engine.begin() as conn:
    # Check current values
    r = conn.execute(text("""
        SELECT enumlabel FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname ILIKE 'nextactiontype'
        ORDER BY e.enumsortorder
    """))
    current = [row[0] for row in r.fetchall()]
    print(f"Current enum values: {current}")

    if 'test' not in current:
        conn.execute(text("ALTER TYPE nextactiontype ADD VALUE IF NOT EXISTS 'test'"))
        print("[OK] Added 'test' to nextactiontype enum")
    else:
        print("[SKIP] 'test' already present in enum")

print("=" * 60)
print("DONE")
print("=" * 60)
