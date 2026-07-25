"""
Idempotent seeder for BillingScope rows and org backfill.
Delegates to the canonical _seed_billing_scope step in migrate_billing_dept.
Safe to run multiple times.

Usage:
    python seed_billing_scope.py
"""
from database import SessionLocal
from migrate_billing_dept import _seed_billing_scope


def seed_billing_scopes(session) -> None:
    """Seed BillingScope rows and backfill existing orgs. Idempotent."""
    _seed_billing_scope(session)
    session.commit()


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_billing_scopes(db)
        print("[OK] BillingScope seeding complete.")
    finally:
        db.close()
