"""
backfill_fr_due_dates.py
────────────────────────
Backfills due_date for existing Failure Registry records that have
outcome_end_date stored in form_data but no due_date set on the row.

Usage:
    python backfill_fr_due_dates.py           # dry run (preview only)
    python backfill_fr_due_dates.py --apply   # apply changes
"""

import argparse
from datetime import datetime, timezone
from database import SessionLocal
from sqlalchemy import text

def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        s = str(raw).strip()
        if len(s) == 10:
            return datetime.fromisoformat(s + "T00:00:00+00:00")
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def main(apply: bool):
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, request_number, form_data
            FROM testing_requests
            WHERE request_category = 'failure_registry'
              AND due_date IS NULL
              AND form_data IS NOT NULL
        """)).fetchall()

        print(f"Found {len(rows)} FR records with no due_date\n")

        updated = 0
        skipped = 0

        for row in rows:
            req_id, req_num, form_data = row
            if not isinstance(form_data, dict):
                skipped += 1
                continue

            raw = (
                form_data.get("outcome_end_date")
                or form_data.get("outcome_due_date")
            )
            due = parse_date(raw)

            if not due:
                print(f"  SKIP  {req_num} — no outcome_end_date in form_data")
                skipped += 1
                continue

            print(f"  {'SET ' if apply else 'DRY'} {req_num}  due_date = {due.date()}")

            if apply:
                db.execute(
                    text("UPDATE testing_requests SET due_date = :d WHERE id = :id"),
                    {"d": due, "id": req_id},
                )
                updated += 1

        if apply:
            db.commit()
            print(f"\nDone. Updated {updated} records, skipped {skipped}.")
        else:
            print(f"\nDry run complete. Would update {len(rows) - skipped} records.")
            print("Re-run with --apply to commit changes.")

    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()
    main(apply=args.apply)
