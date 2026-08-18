"""
Run migration 044: add license_server_org_id and upgrade_token to organizations.
"""
from database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE organizations
                ADD COLUMN IF NOT EXISTS license_server_org_id VARCHAR(64),
                ADD COLUMN IF NOT EXISTS upgrade_token          VARCHAR(64);
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_organizations_license_server_org_id
                ON organizations (license_server_org_id)
                WHERE license_server_org_id IS NOT NULL;
        """))
        db.commit()
        print("Migration 044 complete: license_server_org_id and upgrade_token added to organizations.")
    except Exception as e:
        db.rollback()
        print(f"Migration 044 failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
