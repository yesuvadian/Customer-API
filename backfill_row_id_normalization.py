#!/usr/bin/env python3
"""
Backfill: normalize legacy row-id spellings (CHG, HV-Ground, ...) already
stored in TestResult.test_data to their canonical form (HV-GND, ...), for
winding_test_results / idax_test_results table rows.

Fixes trend-history fragmentation for data imported BEFORE normalize_row_id()
was wired into the import paths (see test_templates.py). New imports no
longer need this - this is a one-time catch-up for existing records.

Also cleans up the ParameterAnalytics fallout: once test_data is rewritten,
a recompute (see run_recompute_all_analytics.py) creates fresh rows under
the new canonical parameter_key, but never deletes the old rows still sitting
under the pre-normalization key - upsert only touches keys it currently
generates. Those orphans render as duplicate/stale entries in the UI (e.g.
"IDAX Test Data - CHG - ..." still showing up after the row was renamed to
HV-GND). This script deletes exactly those orphans: for every row it renames,
it deletes any ParameterAnalytics row for that same test_result_id whose
parameter_key still carries the pre-normalization row_id - nothing else.

Usage:
    python backfill_row_id_normalization.py --dry-run   # report only, no writes
    python backfill_row_id_normalization.py              # apply, then run
                                                           # run_recompute_all_analytics.py
"""
import argparse

from database import VendorSessionLocal
from models import TestResult, ParameterAnalytics
from test_templates import normalize_row_id
from sqlalchemy.orm.attributes import flag_modified

_TABLE_KEYS = ("winding_test_results", "idax_test_results")


def _row_id_from_parameter_key(parameter_key: str, table_key: str) -> str | None:
    """Extract the row_id segment from a 'table_key.row_id.col_key' parameter_key."""
    prefix = f"{table_key}."
    if not parameter_key.startswith(prefix):
        return None
    rest = parameter_key[len(prefix):]
    row_id, _, _col_key = rest.rpartition(".")
    return row_id or None


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
        # {test_result_id: {(table_key, old_row_id), ...}}
        renames: dict = {}

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
                    old_row_id = str(raw).strip()
                    canonical = normalize_row_id(raw)
                    if canonical != raw:
                        if len(examples) < 20:
                            examples.append(f"  {tr.id}  {table_key}: {raw!r} -> {canonical!r}")
                        row["test_configuration"] = canonical
                        row_changed = True
                        changed_rows += 1
                        renames.setdefault(tr.id, set()).add((table_key, old_row_id))

            if row_changed:
                changed_results += 1
                if not dry_run:
                    flag_modified(tr, "test_data")

        print(f"{'[DRY RUN] ' if dry_run else ''}Rows to normalize: {changed_rows} across {changed_results} test results (of {len(results)} total)")
        if examples:
            print("Examples:")
            for ex in examples:
                print(ex)

        if dry_run:
            db.rollback()
            _preview_orphans(db, renames)
            return

        db.commit()
        print("Backfill committed.")

        deleted = _delete_orphans(db, renames)
        print(f"Deleted {deleted} orphaned ParameterAnalytics row(s) left under pre-normalization keys.")
        print("Now run: python run_recompute_all_analytics.py")
    finally:
        db.close()


def _find_orphans(db, renames: dict) -> list:
    if not renames:
        return []
    orphans = []
    test_result_ids = list(renames.keys())
    candidates = (
        db.query(ParameterAnalytics)
        .filter(ParameterAnalytics.test_result_id.in_(test_result_ids))
        .all()
    )
    for pa in candidates:
        renamed_pairs = renames.get(pa.test_result_id)
        if not renamed_pairs:
            continue
        for table_key, old_row_id in renamed_pairs:
            row_id = _row_id_from_parameter_key(pa.parameter_key, table_key)
            if row_id == old_row_id:
                orphans.append(pa)
                break
    return orphans


def _preview_orphans(db, renames: dict):
    orphans = _find_orphans(db, renames)
    print(f"[DRY RUN] Orphaned ParameterAnalytics rows that would be deleted: {len(orphans)}")
    for pa in orphans[:20]:
        print(f"  {pa.test_result_id}  {pa.parameter_key!r}")


def _delete_orphans(db, renames: dict) -> int:
    orphans = _find_orphans(db, renames)
    for pa in orphans:
        db.delete(pa)
    db.commit()
    return len(orphans)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run)
