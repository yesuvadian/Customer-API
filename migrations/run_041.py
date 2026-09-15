"""
Run migration 041: relax test_request_schedules uniqueness to recurring-only.

Replaces the blanket UNIQUE(equipment_id, test_type_id) constraint with a
partial unique index that only applies to recurring schedules
(is_recurring = true). A one-off schedule (is_recurring = false) is a
single ad-hoc test, not a cadence, so any number of them may now coexist
for the same equipment + test type, including alongside an existing
recurring schedule, without blocking or needing to overwrite it.
"""
from database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE public.test_request_schedules
                DROP CONSTRAINT IF EXISTS uq_equipment_test_schedule;
        """))
        db.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_equipment_test_schedule_recurring
                ON public.test_request_schedules (equipment_id, test_type_id)
                WHERE is_recurring = true AND is_deleted = false;
        """))
        db.commit()
        print("Migration 041 complete: uniqueness on test_request_schedules "
              "now scoped to recurring schedules only.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
