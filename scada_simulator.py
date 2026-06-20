"""
SCADA Simulator for KPTCL — Karnataka Power Transmission Corporation Limited
=============================================================================
Uses equipment.scada_tag as the primary tag identifier.
For each equipment the simulator generates one reading per parameter
(e.g. CT -> OIL_TEMP, IR, TAN_DELTA; PT -> IR, TAN_DELTA, RATIO_ERROR;
Power Transformer -> OIL_TEMP, WINDING_TEMP, LOAD_CURRENT, BDV).

Modes:
  python scada_simulator.py seed      – create tag maps + alert rules + 30-day backfill
  python scada_simulator.py run       – continuous live posting (every 15 min)
  python scada_simulator.py seed run  – seed then immediately start live posting
"""

from __future__ import annotations

import math
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import ScadaAlertRule, ScadaReading, ScadaTagMap

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

KPTCL_ORG_ID = uuid.UUID("9c974233-26f8-4004-be48-9915da8bd4cf")

BACKFILL_DAYS              = 30
BACKFILL_INTERVAL_MINUTES  = 60   # one reading/hour during backfill
LIVE_INTERVAL_SECONDS      = 900  # 15 min

# ─────────────────────────────────────────────────────────────
# Parameter profiles
# Each tuple: (param_suffix, parameter_name, unit,
#              nominal, drift_per_day, noise_sigma,
#              warning_min, warning_max,
#              alarm_min,   alarm_max,
#              critical_min, critical_max)
# ─────────────────────────────────────────────────────────────

CT_PARAMS: List[Tuple] = [
    ("IR",  "Insulation Resistance", "MOhm",  5000,  -0.80, 80,   2000, None,  1000, None,  500,  None),
    ("TD",  "Tan Delta",             "%",     0.40,   0.005, 0.02, None, 0.80,  None, 1.20,  None, 2.00),
    ("BRD", "Burden",                "VA",    15.0,   0.0,   0.30, None, 25.0,  None, 30.0,  None, 35.0),
]

PT_PARAMS: List[Tuple] = [
    ("IR",  "Insulation Resistance", "MOhm",  4000,  -0.60, 60,   1500, None,  800,  None,  400,  None),
    ("TD",  "Tan Delta",             "%",     0.35,   0.004, 0.015,None, 0.70,  None, 1.00,  None, 1.80),
    ("RE",  "Ratio Error",           "%",     0.10,   0.001, 0.010,None, 0.50,  None, 1.00,  None, 2.00),
]

PTX_PARAMS: List[Tuple] = [
    ("OTI", "Oil Temperature",       "degC",  45.0,   0.0,   0.80, None, 75.0,  None, 85.0,  None, 95.0),
    ("WTI", "Winding Temperature",   "degC",  60.0,   0.0,   1.00, None, 90.0,  None, 100.0, None, 110.0),
    ("LC",  "Load Current",          "A",     200.0,  0.0,   5.00, None, 800.0, None, 900.0, None, 1000.0),
    ("BDV", "Oil BDV",               "kV",    60.0,  -0.05,  1.00, 40.0, None,  30.0, None,  20.0, None),
]

TYPE_PARAMS = {
    "Current Transformer":   CT_PARAMS,
    "Potential Transformer": PT_PARAMS,
    "Power Transformer":     PTX_PARAMS,
}

# CategoryMaster IDs for equipment-type-level alert rules
EQUIPMENT_TYPE_IDS = {
    "Current Transformer":   18,
    "Potential Transformer": 20,
    "Power Transformer":     12,
}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _param_tag(base_tag: str, suffix: str) -> str:
    return f"{base_tag}_{suffix}"


def _generate_value(nominal: float, drift: float, sigma: float,
                    days_elapsed: float) -> float:
    base     = max(nominal + drift * days_elapsed, nominal * 0.05)
    hour     = (_now().hour + days_elapsed * 24) % 24
    diurnal  = nominal * 0.02 * math.sin(2 * math.pi * (hour - 6) / 24)
    return round(base + diurnal + random.gauss(0, sigma), 4)


def _condition(value: float, w_min, w_max, a_min, a_max, c_min, c_max) -> str:
    v = float(value)
    if (c_min is not None and v < c_min) or (c_max is not None and v > c_max):
        return "CRITICAL"
    if (a_min is not None and v < a_min) or (a_max is not None and v > a_max):
        return "ALARM"
    if (w_min is not None and v < w_min) or (w_max is not None and v > w_max):
        return "WARNING"
    return "NORMAL"


def _fetch_instrumented(db: Session) -> list:
    """Return all KPTCL equipment that have a scada_tag set."""
    return db.execute(text("""
        SELECT e.id, e.ueic, e.scada_tag, cm.name AS eq_type
        FROM   public.equipment e
        JOIN   public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        WHERE  e.organization_id = :org
        AND    e.scada_tag IS NOT NULL
        AND    cm.name IN ('Current Transformer',
                           'Potential Transformer',
                           'Power Transformer')
        ORDER  BY cm.name, e.ueic
    """), {"org": str(KPTCL_ORG_ID)}).fetchall()


# ─────────────────────────────────────────────────────────────
# SEED
# ─────────────────────────────────────────────────────────────

def seed(db: Session):
    print("=" * 60)
    print("SCADA Simulator — SEED")
    print("=" * 60)

    equipment = _fetch_instrumented(db)
    print(f"\nInstrumented equipment: {len(equipment)}")

    # ── 1. Equipment-type-level alert rules (one set per type) ───
    print("\n-- Creating equipment-type alert rules --")
    rule_count = 0

    for eq_type, params in TYPE_PARAMS.items():
        type_id = EQUIPMENT_TYPE_IDS[eq_type]
        for (suffix, param_name, unit,
             nominal, drift, sigma,
             w_min, w_max, a_min, a_max, c_min, c_max) in params:

            # Tag pattern uses suffix only — matches any equipment of this type
            tag_pattern = suffix   # used as scada_tag on the rule (suffix match)

            if not db.query(ScadaAlertRule).filter(
                ScadaAlertRule.organization_id == KPTCL_ORG_ID,
                ScadaAlertRule.equipment_id == None,
                ScadaAlertRule.equipment_type_id == type_id,
                ScadaAlertRule.scada_tag == tag_pattern,
            ).first():
                db.add(ScadaAlertRule(
                    organization_id=KPTCL_ORG_ID,
                    equipment_type_id=type_id,
                    scada_tag=tag_pattern,
                    parameter_name=param_name,
                    unit=unit,
                    warning_min=w_min,  warning_max=w_max,
                    alarm_min=a_min,    alarm_max=a_max,
                    critical_min=c_min, critical_max=c_max,
                    is_active=True,
                ))
                rule_count += 1

    db.commit()
    print(f"  Created {rule_count} equipment-type alert rules "
          f"({sum(len(p) for p in TYPE_PARAMS.values())} total params across 3 types)")

    # ── 2. Tag maps (per equipment, per parameter) ────────────
    print("\n-- Creating tag maps --")
    map_count = 0

    for row in equipment:
        equip_id  = row[0]
        base_tag  = row[2]
        eq_type   = row[3]
        params    = TYPE_PARAMS.get(eq_type, [])

        for (suffix, param_name, unit,
             nominal, drift, sigma,
             w_min, w_max, a_min, a_max, c_min, c_max) in params:

            tag = _param_tag(base_tag, suffix)

            if not db.query(ScadaTagMap).filter(
                ScadaTagMap.organization_id == KPTCL_ORG_ID,
                ScadaTagMap.scada_tag == tag,
            ).first():
                db.add(ScadaTagMap(
                    organization_id=KPTCL_ORG_ID,
                    scada_tag=tag,
                    equipment_id=equip_id,
                    parameter_name=param_name,
                    unit=unit,
                    is_active=True,
                ))
                map_count += 1

        if map_count % 500 == 0 and map_count > 0:
            db.flush()

    db.commit()
    print(f"  Created {map_count} tag maps")

    # ── 2. Backfill ───────────────────────────────────────────
    print(f"\n-- Backfilling {BACKFILL_DAYS} days "
          f"(interval {BACKFILL_INTERVAL_MINUTES} min) --")

    start     = _now() - timedelta(days=BACKFILL_DAYS)
    step      = timedelta(minutes=BACKFILL_INTERVAL_MINUTES)
    epoch_ref = datetime(2025, 1, 1, tzinfo=timezone.utc)
    total     = 0
    batch: List[ScadaReading] = []

    for row in equipment:
        equip_id = row[0]
        base_tag = row[2]
        eq_type  = row[3]
        params   = TYPE_PARAMS.get(eq_type, [])
        ts       = start

        while ts <= _now():
            days_elapsed = (ts - epoch_ref).total_seconds() / 86400.0

            for (suffix, param_name, unit,
                 nominal, drift, sigma,
                 w_min, w_max, a_min, a_max, c_min, c_max) in params:

                tag   = _param_tag(base_tag, suffix)
                value = _generate_value(nominal, drift, sigma, days_elapsed)
                cond  = _condition(value, w_min, w_max, a_min, a_max,
                                   c_min, c_max)

                batch.append(ScadaReading(
                    organization_id=KPTCL_ORG_ID,
                    equipment_id=equip_id,
                    scada_tag=tag,
                    parameter_name=param_name,
                    value=value,
                    unit=unit,
                    alarm_condition=cond,
                    recorded_at=ts,
                    received_at=_now(),
                ))

                if len(batch) >= 1000:
                    db.bulk_save_objects(batch)
                    db.commit()
                    total += len(batch)
                    print(f"  {total:>8,} readings inserted", end="\r")
                    batch = []

            ts += step

    if batch:
        db.bulk_save_objects(batch)
        db.commit()
        total += len(batch)

    print(f"\n  Backfill complete — {total:,} readings")
    print("\nSeed done.")


# ─────────────────────────────────────────────────────────────
# LIVE RUN
# ─────────────────────────────────────────────────────────────

def run_live():
    print("=" * 60)
    print("SCADA Simulator — LIVE  (every 15 min, Ctrl-C to stop)")
    print("=" * 60)

    epoch_ref = datetime(2025, 1, 1, tzinfo=timezone.utc)

    while True:
        db = next(get_db())
        try:
            equipment = _fetch_instrumented(db)
            if not equipment:
                print("No instrumented equipment found — run seed first.")
                time.sleep(60)
                continue

            now          = _now()
            days_elapsed = (now - epoch_ref).total_seconds() / 86400.0
            batch: List[ScadaReading] = []

            for row in equipment:
                equip_id = row[0]
                base_tag = row[2]
                eq_type  = row[3]
                params   = TYPE_PARAMS.get(eq_type, [])

                for (suffix, param_name, unit,
                     nominal, drift, sigma,
                     w_min, w_max, a_min, a_max, c_min, c_max) in params:

                    tag   = _param_tag(base_tag, suffix)
                    value = _generate_value(nominal, drift, sigma, days_elapsed)
                    cond  = _condition(value, w_min, w_max, a_min, a_max,
                                       c_min, c_max)

                    batch.append(ScadaReading(
                        organization_id=KPTCL_ORG_ID,
                        equipment_id=equip_id,
                        scada_tag=tag,
                        parameter_name=param_name,
                        value=value,
                        unit=unit,
                        alarm_condition=cond,
                        recorded_at=now,
                        received_at=now,
                    ))

            db.bulk_save_objects(batch)
            db.commit()

            ts_str = now.strftime("%Y-%m-%d %H:%M UTC")
            alarms = sum(1 for r in batch if r.alarm_condition != "NORMAL")
            print(f"[{ts_str}]  {len(batch):,} readings posted"
                  f"  ({alarms} non-normal)")

            # Best-effort analytics run
            try:
                from services.scada_analytics_runner import run_for_organization
                run_for_organization(db, KPTCL_ORG_ID)
            except Exception as ae:
                print(f"  Analytics skipped: {ae}")

        except Exception as e:
            print(f"  ERROR: {e}")
        finally:
            db.close()

        time.sleep(LIVE_INTERVAL_SECONDS)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = set(sys.argv[1:])

    if not args or (args - {"seed", "run"}):
        print(__doc__)
        print("Usage:  python scada_simulator.py [seed] [run]")
        sys.exit(0)

    if "seed" in args:
        db = next(get_db())
        try:
            seed(db)
        finally:
            db.close()

    if "run" in args:
        run_live()
