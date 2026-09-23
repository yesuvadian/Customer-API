#!/usr/bin/env python3
"""
One-time setup: register the new "Monthly Result Review Compliance
Report" (closes the SRS D.8 gap "Monthly Result Review Compliance
Report -- Does not exist").

Purely data seeding -- no schema migration needed, no new Python
report-generation code (see seed.py's own comment: "Generic report
engine: 14 SRS reports = 14 query_key values, not 14 code paths").
Adds:
  1. ReportDefinition row (name, query_key, frequency=monthly, etc.)
  2. ReportQueryKey row (the actual SQL template)
  3. NotificationEventType row (result_review_report_ready)

All three come from seed.py's own DEFINITIONS lists, so this script
just re-runs the same three idempotent seed functions seed.py itself
calls during a full run -- safe to run standalone without re-running
the entire seed.py.

Idempotent: get-or-create throughout (each function's own existing
convention), safe to re-run.

Usage:
    python alter_seed_result_review_compliance_report.py
"""
from database import VendorSessionLocal
from seed import (
    seed_report_definitions,
    seed_report_query_keys,
    seed_notification_defaults,
)


def main():
    db = VendorSessionLocal()
    try:
        seed_report_definitions(db)
        db.commit()

        seed_report_query_keys(db)
        db.commit()

        result = seed_notification_defaults(db)
        db.commit()
        print(f"[OK] Notification defaults: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
