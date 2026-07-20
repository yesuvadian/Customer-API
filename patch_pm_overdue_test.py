"""
Patch maintenance schedules to test overdue display.
Sets next_run_date = 2026-07-03, end_date = 2026-07-04 for all active maintenance schedules.
"""
from datetime import datetime, timezone
from database import VendorSessionLocal
from models import TestRequestSchedule

db = VendorSessionLocal()
try:
    schedules = (
        db.query(TestRequestSchedule)
        .filter(
            TestRequestSchedule.request_category == 'maintenance',
            TestRequestSchedule.is_active == True,
            TestRequestSchedule.is_deleted == False,
        )
        .all()
    )

    print(f"Found {len(schedules)} maintenance schedule(s)")
    for s in schedules:
        s.next_run_date = datetime(2026, 7, 3, tzinfo=timezone.utc)
        s.end_date      = None  # keep visible; overdue determined by next_run_date < now
        print(f"  Patched: id={s.id} equipment_id={s.equipment_id}")

    db.commit()
    print("Done.")
except Exception as e:
    db.rollback()
    print(f"ERROR: {e}")
    import traceback; traceback.print_exc()
finally:
    db.close()
