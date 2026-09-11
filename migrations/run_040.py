"""
Run migration 040: add is_recurring to test_request_schedules.

False marks a one-off operational schedule (created via
POST /test-register/schedules/operational/one-off) — create_one_ticket()
deactivates it after firing once instead of advancing next_run_date.
Defaults to True so existing master schedules and their instantiated
operational schedules keep recurring exactly as before.
"""
from database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE public.test_request_schedules
                ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN NOT NULL DEFAULT true;
        """))
        db.commit()
        print("Migration 040 complete: is_recurring added to test_request_schedules.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
