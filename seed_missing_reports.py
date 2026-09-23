"""
Seeds the "Calibration Compliance Report" and "Network Health Summary Report"
report definitions (+ their query-key SQL templates), which exist in
seed.py's DEFINITIONS/KEYS lists but are only written to the DB when those
functions actually run. Safe to run on any environment, any number of
times — seed_report_definitions()/seed_report_query_keys() upsert by
query_key, so re-running just refreshes existing rows instead of
duplicating them. Also re-syncs every other standard report definition
that seed.py defines but this environment's DB hasn't picked up yet.

Usage:
    python seed_missing_reports.py
"""

from database import VendorSessionLocal
from seed import seed_report_definitions, seed_report_query_keys

if __name__ == "__main__":
    db = VendorSessionLocal()
    try:
        seed_report_definitions(db)
        seed_report_query_keys(db)
    finally:
        db.close()
