#!/usr/bin/env python3
"""
Backfill: normalize legacy row-id spellings (CHG, HV-Ground, ...) already
stored in TestResult.test_data to their canonical form (HV-GND, ...), for
winding_test_results / idax_test_results table rows.

Fixes trend-history fragmentation for data imported BEFORE normalize_row_id()
was wired into the import paths (see test_templates.py). New imports no
longer need this - this is a one-time catch-up for existing records.

Usage:
    python backfill_row_id_normalization.py --dry-run   # report only, no writes
    python backfill_row_id_normalization.py              # apply + recompute analytics
"""
import argparse

from database import VendorSessionLocal
from models import TestResult
from test_templates import normalize_row_id
from sqlalchemy.orm.attributes import flag_modified

_TABLE_KEYS = ("winding_test_results", "idax_test_results")


def run_backfill(dry_run: bool):
    db = VendorSessionLocal()
    try:
        results = (
            db.query(TestResult)
            .filter(TestResult.test_data.isnot(None))
            .all()
        )

        changed_results = 0
        changed_rows = 0
        examples: list[str] = []

        for tr in results:
            test_data = tr.test_data or {}
            row_changed = False

            for table_key in _TABLE_KEYS:
                rows = test_data.get(table_key)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    raw = row.get("test_configuration")
                    if not raw:
                        continue
                    canonical = normalize_row_id(raw)
                    if canonical != raw:
                        if len(examples) < 20:
                            examples.append(f"  {tr.id}  {table_key}: {raw!r} -> {canonical!r}")
                        row["test_configuration"] = canonical
                        row_changed = True
                        changed_rows += 1

            if row_changed:
                changed_results += 1
                if not dry_run:
                    flag_modified(tr, "test_data")

        print(f"{'[DRY RUN] ' if dry_run else ''}Rows to normalize: {changed_rows} across {changed_results} test results (of {len(results)} total)")
        if examples:
            print("Examples:")
            for ex in examples:
                print(ex)

        if not dry_run:
            db.commit()
            print("Backfill committed.")
        else:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run)
