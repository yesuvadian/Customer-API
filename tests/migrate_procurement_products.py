"""
Migration: Add replacement_products JSONB column to procurement_requests
and outcome_schedule to recommendations.

Run once:
    python tests/migrate_procurement_products.py
"""
import sys
sys.path.insert(0, "C:/Yesu/CustomerAPI/Customer-API")

from database import engine
from sqlalchemy import text

SQL = """
-- Add replacement_products to procurement_requests (idempotent)
ALTER TABLE public.procurement_requests
    ADD COLUMN IF NOT EXISTS replacement_products JSONB;

-- Add scheduled_start_date to testing_requests if missing (idempotent)
ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS scheduled_start_date TIMESTAMPTZ;
"""

print("=" * 60)
print("MIGRATION: procurement_requests.replacement_products")
print("=" * 60)

with engine.begin() as conn:
    conn.execute(text(SQL))
    print("[OK] Migration applied.")

    # Verify
    r = conn.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'procurement_requests'
          AND column_name  = 'replacement_products'
    """))
    row = r.fetchone()
    if row:
        print(f"[OK] Column verified: {row[0]}  type={row[1]}")
    else:
        print("[WARN] Column NOT found after migration -- check permissions")

print("=" * 60)
print("DONE")
print("=" * 60)
