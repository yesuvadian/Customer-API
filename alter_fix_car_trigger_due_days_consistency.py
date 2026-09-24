#!/usr/bin/env python3
"""
One-time data fix: for every active CarTriggerConfig row where the CAR's own
effective due-days (car_due_in_days, or the CAR_DUE_DAYS_CRITICAL/ALERT
global default when unset) is SHORTER than its worst active follow-up's
due_in_days, widen car_due_in_days to match -- otherwise the CAR gets
flagged overdue (main.py's _check_car_overdue) before the very follow-up
that's supposed to resolve it has even come due.

Widens the CAR's SLA to the follow-up's timeline, not the other way
around: a follow-up's due_in_days reflects how long that specific action
realistically takes (sourcing a test kit, scheduling downtime on live
equipment isn't always same-day) -- compressing it to fit an arbitrary
default would just produce chronic false-overdue alerts rather than a
real, achievable SLA. car_due_in_days=None (never explicitly set) is the
common case this fixes, since CAR_DUE_DAYS_CRITICAL's factory default (3
days) was never a deliberate choice for any specific equipment type.

Same violation the CarTriggerConfig create/update endpoints now reject at
save time (routers/car_trigger_config.py's _validate_due_days_consistency)
-- this is the one-time backfill for rows that predate that check.

Idempotent: only touches rows that are actually inconsistent; safe to
re-run (a second run finds nothing left to fix).

Usage:
    python alter_fix_car_trigger_due_days_consistency.py
"""
from database import VendorSessionLocal
from models import CarTriggerConfig, CategoryMaster
from config import CAR_DUE_DAYS_CRITICAL, CAR_DUE_DAYS_ALERT


def _default_car_due_days(severity: str) -> int:
    return CAR_DUE_DAYS_CRITICAL if severity == "CRITICAL" else CAR_DUE_DAYS_ALERT


def main():
    db = VendorSessionLocal()
    try:
        configs = db.query(CarTriggerConfig).filter(CarTriggerConfig.is_active.is_(True)).all()
        print(f"Checking {len(configs)} active CAR trigger config row(s)...\n")

        fixed = 0
        for c in configs:
            active_fu = [f for f in c.followups if f.is_active]
            if not active_fu:
                continue

            car_due = c.car_due_in_days if c.car_due_in_days is not None else _default_car_due_days(c.severity)
            worst = max(f.due_in_days for f in active_fu)
            if worst <= car_due:
                continue

            eq = db.query(CategoryMaster).filter(CategoryMaster.id == c.equipment_type_id).first()
            eq_name = eq.name if eq else str(c.equipment_type_id)
            print(
                f"[FIX] {eq_name} / {c.severity}: car_due_in_days "
                f"{c.car_due_in_days!r} (effective {car_due}) -> {worst} "
                f"(worst active follow-up due-days)"
            )
            c.car_due_in_days = worst
            fixed += 1

        db.commit()
        print(f"\n[DONE] {fixed} config row(s) corrected." if fixed else "\n[DONE] Nothing to fix -- all consistent already.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
