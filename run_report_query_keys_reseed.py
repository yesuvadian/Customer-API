#!/usr/bin/env python3
"""
Re-seed report_query_keys only.

Pushes the ReportQueryKey rows' sql_template / parameters_schema / etc. from
seed.py's KEYS list into the database, without touching anything else seed.py
does (roles, users, modules, departments, billing, ...).

Run this after any deploy that changes a report's sql_template in seed.py —
e.g. the equipment_failure_performance_report fix (broadened failure scope,
fleet-wide denominator, units_currently_critical column). Idempotent and
safe to re-run: existing rows are updated in place, nothing is duplicated.

Usage:
    python run_report_query_keys_reseed.py
"""
from seed import get_db_session, seed_report_query_keys


def main():
    print("=" * 70)
    print("  Re-seeding report_query_keys")
    print("=" * 70)
    with get_db_session() as session:
        seed_report_query_keys(session)
    print("Done.")


if __name__ == "__main__":
    main()
