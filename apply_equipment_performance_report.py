#!/usr/bin/env python3
"""
One-time setup: seed the new "Equipment Performance Report" (single-equipment
scoped, query_key=equipment_performance_report) so the equipment context
menu's Performance Report action can use it.

Previously that action ran equipment_failure_performance_report - a
fleet-cohort comparison (grouped by equipment_type/manufacturer/voltage_class/
age_band across every matching unit, not just the one clicked), which reads
as confusing when launched from a single equipment's own menu. That old
report is untouched and still available in the Reporting Center on its own -
this just adds a new, separate report and repoints the context-menu action
at it (frontend change, see equipment_actions_menu.dart / reporting_center_
page.dart).

Uses the same idempotent upsert functions seed.py's own startup seeding
calls (seed_report_definitions, seed_report_query_keys) - safe to re-run,
and safe to run alongside the rest of seed.py's data since it only touches
report_definitions / report_query_keys rows matching the query_keys defined
in seed.py's own DEFINITIONS/KEYS lists.

Usage:
    python apply_equipment_performance_report.py
"""
from seed import get_db_session, seed_report_definitions, seed_report_query_keys


def main():
    with get_db_session() as session:
        print("Seeding report_definitions...")
        seed_report_definitions(session)
        print("Seeding report_query_keys...")
        seed_report_query_keys(session)
    print("Done.")


if __name__ == "__main__":
    main()
