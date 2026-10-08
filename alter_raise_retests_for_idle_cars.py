#!/usr/bin/env python3
"""
Manual run of the idle-CAR check (services/car_service.heal_idle_cars) -
the same check main.py runs daily (car_idle_check_job).

A CAR has no manual workflow - it is driven entirely by its linked TRs, and
the live hook keeps at least one TR expecting a result for every open CAR
it touches. A CAR can still end up idle: its only pending retest rejected
or cancelled in its workflow (closed with no result), or CARs created by
alter_backfill_car_from_critical_results.py "CARs only". For each OPEN /
REOPENED CAR this:
  - links any same-equipment/test request already in flight (a scheduled or
    manual test) - it is what's driving the CAR;
  - otherwise, if nothing in the chain is still expecting a result, raises
    one high-priority retest of the CAR's trigger test type, parented on the
    latest request with a result, submitted into the normal TR workflow.
Re-running is safe. --fix-titles also renames earlier auto-created TRs
titled "CAR-... retest: " with nothing after the colon.

Dry run by default - prints what it would do and writes nothing.

Usage:
    python alter_raise_retests_for_idle_cars.py                               # dry run
    python alter_raise_retests_for_idle_cars.py --apply                       # link / raise
    python alter_raise_retests_for_idle_cars.py --apply --exclude CAR-2026-0006
    python alter_raise_retests_for_idle_cars.py --fix-titles                  # dry run incl. title fixes
    python alter_raise_retests_for_idle_cars.py --reopen-unresolved           # dry run: CARs closed with a failed type unresolved
"""
import argparse
import sys
from collections import Counter

from database import VendorSessionLocal
from models import TestingRequest
from services.car_service import _tr_label, heal_idle_cars, reopen_closed_with_unresolved

BLANK_TITLE_RE = r"^CAR-[0-9]{4}-[0-9]+ (retest|follow-up):\s*$"


def main():
    parser = argparse.ArgumentParser(description="Link / raise retests for open CARs with nothing in progress.")
    parser.add_argument("--apply", action="store_true", help="Link / raise (default: dry run)")
    parser.add_argument("--exclude", nargs="*", default=[], metavar="CAR_NUMBER", help="CAR numbers to leave alone")
    parser.add_argument("--reopen-unresolved", action="store_true",
                        help="Also reopen CARs closed while another failed test type had no passing retest")
    parser.add_argument("--fix-titles", action="store_true",
                        help='Also rename auto-created TRs titled "CAR-... retest: " with nothing after it')
    args = parser.parse_args()

    print(f"=== Idle-CAR check ({'APPLY' if args.apply else 'DRY RUN'}) ===")
    db = VendorSessionLocal()
    try:
        if args.reopen_unresolved:
            for r in reopen_closed_with_unresolved(db, apply=args.apply):
                print(f"  {'reopen' if args.apply else 'reopen?':<7} {r['car_number']}  still needs a passing retest: {', '.join(r['pending'])}")
        report = heal_idle_cars(db, apply=args.apply, exclude={c.strip() for c in args.exclude})
        for r in report:
            print(f"  {r['action']:<7} {r['car_number']}  {r['detail']}")

        blank_titles = []
        if args.fix_titles:
            for t in db.query(TestingRequest).filter(TestingRequest.title.op("~")(BLANK_TITLE_RE)).all():
                parent = db.query(TestingRequest).filter(TestingRequest.id == t.parent_request_id).first() if t.parent_request_id else None
                label = _tr_label(parent) if parent else (getattr(t.test_type, "name", None) or "request")
                new_title = t.title.rstrip() + " " + label
                print(f"  title   {t.request_number}: {t.title!r} -> {new_title!r}")
                blank_titles.append((t, new_title))
            if args.apply and blank_titles:
                for t, new_title in blank_titles:
                    t.title = new_title
                db.commit()

        counts = Counter(r["action"] for r in report)
        verb = "" if args.apply else "would be "
        print(f"\n{counts.get('link', 0)} CAR(s) {verb}linked, {counts.get('retest', 0)} retest(s) {verb}raised, "
              f"{len(blank_titles)} title(s) {verb}fixed" + ("" if args.apply else ". Re-run with --apply to write."))
        if counts.get("failed"):
            print(f"[WARN] {counts['failed']} retest(s) not raised - see the server log.")
        return 1 if counts.get("failed") else 0
    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
