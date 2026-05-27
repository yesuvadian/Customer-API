#!/usr/bin/env python3
"""Quick check for notification tables"""
from database import get_db
from sqlalchemy import text

db = next(get_db())

# Check notification_log
result = db.execute(text(
    "SELECT COUNT(*) as cnt FROM information_schema.tables "
    "WHERE table_schema = 'public' AND table_name = 'notification_log'"
)).scalar()
print(f"[OK] notification_log table exists: {result > 0}")

# Check notification_events
result2 = db.execute(text(
    "SELECT COUNT(*) as cnt FROM information_schema.tables "
    "WHERE table_schema = 'public' AND table_name = 'notification_events'"
)).scalar()
print(f"[OK] notification_events table exists: {result2 > 0}")

# Check notification_event_catalogue
result3 = db.execute(text(
    "SELECT event_type, label FROM notification_event_catalogue "
    "WHERE event_type IN ('test_result_normal', 'test_result_alert', 'test_result_critical') "
    "ORDER BY event_type"
)).fetchall()

print(f"\n[INFO] Event types in catalogue: {len(result3)}")
for row in result3:
    print(f"  - {row.event_type}: {row.label}")

db.close()
print("\n[DONE] All checks complete!")
