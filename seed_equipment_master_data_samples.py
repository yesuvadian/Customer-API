"""
SAMPLE DATA: fill missing equipment nameplate / master data with realistic
generated values, so equipment reports (Inventory, Condition Summary,
Lifecycle, ALERT/CRITICAL, OLTC/CB Operations, Failure Performance) have no
blank columns. For dev/demo databases only — not for production, where these
gaps are real data-quality issues the DQI dashboard should flag.

Only EMPTY fields are filled; a value that's already there is never changed.

  Field                   Generated value
  ──────────────────────  ─────────────────────────────────────────────────
  factory_serial_number   SN-<type code>-<6 chars of the equipment id>
  model_number            <manufacturer prefix>-<type code><voltage>
  manufacturer            the most common manufacturer for that type
  voltage_class           parsed from the UEIC ("-400-" → 400), else LV
  year_of_manufacture     commissioned year - 1, else a stable 2008–2022 value
  commissioned_date       15th of a stable month in year_of_manufacture + 1
  capacity (nameplate)    by type/voltage, e.g. Power TR 400 kV → 315 MVA,
                          CT → 30 VA burden, PT → 100 VA burden

Every original value is saved to equipment_master_data_backup.json first.

Usage:
    python seed_equipment_master_data_samples.py --check   # count what would change
    python seed_equipment_master_data_samples.py           # fill (writes backup)
    python seed_equipment_master_data_samples.py --undo    # restore from backup
"""

from __future__ import annotations

import json
import os
import re
import sys
import zlib
from datetime import datetime, timezone

from sqlalchemy import text

from database import SessionLocal

BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "equipment_master_data_backup.json")

TYPE_CODE = {
    "Power Transformer": "PTR", "Current Transformer": "CT", "Potential Transformer": "PT",
    "Protection Relay": "RLY", "Testing Kit": "KIT", "Isolator / Disconnector": "ISO",
    "Station Auxiliary Transformer": "SAT", "Wave Trap": "WT",
}
# Keys the reports read a capacity from (reporting_service nameplate key list).
CAPACITY_KEYS = ("rated_mva", "rated_mva_onan", "rated_mva_onan_mva", "capacity_mva",
                 "mva_rating", "rated_capacity", "capacity", "kva_rating")


def _stable(eid, mod: int) -> int:
    """Deterministic pseudo-random number from the equipment id."""
    return zlib.crc32(str(eid).encode()) % mod


def _capacity(type_name: str, volt: str) -> tuple[str, str]:
    v = re.sub(r"\D", "", volt or "")
    if type_name == "Power Transformer":
        return "rated_mva", {"400": "315", "220": "100", "66": "20", "11": "5"}.get(v, "50")
    return "capacity", {
        "Current Transformer": "30 VA", "Potential Transformer": "100 VA",
        "Protection Relay": "1 A / 110 V", "Testing Kit": "Portable",
        "Isolator / Disconnector": "2000 A", "Station Auxiliary Transformer": "630 kVA",
        "Wave Trap": "2000 A",
    }.get(type_name, "Standard")


def plan(db):
    rows = db.execute(text("""
        SELECT e.id, e.ueic, COALESCE(cm.name, '') AS type_name, e.factory_serial_number,
               e.model_number, e.manufacturer, e.voltage_class, e.year_of_manufacture,
               e.commissioned_date, e.nameplate_data
        FROM   public.equipment e
        LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        WHERE  e.status <> 'retired'""")).mappings().all()
    common_mfr = {t: m for t, m in db.execute(text("""
        SELECT DISTINCT ON (cm.name) cm.name, e.manufacturer
        FROM   public.equipment e JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        WHERE  COALESCE(e.manufacturer, '') <> ''
        GROUP  BY cm.name, e.manufacturer ORDER BY cm.name, COUNT(*) DESC""")).all()}

    changes = []   # (id, {field: (old, new)})
    for r in rows:
        ch = {}
        tcode = TYPE_CODE.get(r["type_name"], "EQ")
        volt = r["voltage_class"]
        if not (volt or "").strip():
            m = re.search(r"-(\d{2,3})-", r["ueic"] or "")
            volt = m.group(1) if m else "LV"
            ch["voltage_class"] = (r["voltage_class"], volt)
        mfr = r["manufacturer"]
        if not (mfr or "").strip():
            mfr = common_mfr.get(r["type_name"], "ABB")
            ch["manufacturer"] = (r["manufacturer"], mfr)
        if not (r["factory_serial_number"] or "").strip():
            ch["factory_serial_number"] = (r["factory_serial_number"],
                                           f"SN-{tcode}-{str(r['id']).replace('-', '')[:6].upper()}")
        if not (r["model_number"] or "").strip():
            prefix = re.sub(r"[^A-Za-z]", "", mfr or "GEN")[:4].upper() or "GEN"
            ch["model_number"] = (r["model_number"],
                                  f"{prefix}-{tcode}{re.sub(r'[^0-9A-Za-z]', '', volt or '')}")
        year = r["year_of_manufacture"]
        comm = r["commissioned_date"]
        if year is None:
            year = (comm.year - 1) if comm else 2008 + _stable(r["id"], 15)
            ch["year_of_manufacture"] = (None, year)
        if comm is None:
            new_comm = datetime(year + 1, 1 + _stable(r["id"], 12), 15, tzinfo=timezone.utc)
            ch["commissioned_date"] = (None, new_comm.isoformat())
        npd = r["nameplate_data"] or {}
        if not any(str(npd.get(k) or "").strip() for k in CAPACITY_KEYS):
            key, val = _capacity(r["type_name"], volt)
            new_npd = dict(npd); new_npd[key] = val
            ch["nameplate_data"] = (r["nameplate_data"], new_npd)
        if ch:
            changes.append((str(r["id"]), ch))
    return changes


def apply(db, changes):
    backup = {eid: {f: old for f, (old, _new) in ch.items()} for eid, ch in changes}
    if os.path.exists(BACKUP):
        prev = json.load(open(BACKUP, encoding="utf-8"))
        for eid, fields in prev.items():          # keep the oldest original values
            backup.setdefault(eid, {}).update(fields)
    json.dump(backup, open(BACKUP, "w", encoding="utf-8"), default=str, indent=1)
    for eid, ch in changes:
        sets, params = [], {"id": eid}
        for f, (_old, new) in ch.items():
            if f == "nameplate_data":
                sets.append("nameplate_data = CAST(:nameplate_data AS jsonb)")
                params[f] = json.dumps(new)
            else:
                sets.append(f"{f} = :{f}")
                params[f] = new
        db.execute(text(f"UPDATE public.equipment SET {', '.join(sets)} WHERE id = :id"), params)
    db.commit()


def undo(db):
    if not os.path.exists(BACKUP):
        print("  no backup file — nothing to undo"); return
    backup = json.load(open(BACKUP, encoding="utf-8"))
    for eid, fields in backup.items():
        sets, params = [], {"id": eid}
        for f, old in fields.items():
            if f == "nameplate_data":
                sets.append("nameplate_data = CAST(:nameplate_data AS jsonb)")
                params[f] = json.dumps(old) if old is not None else None
            else:
                sets.append(f"{f} = :{f}")
                params[f] = old
        db.execute(text(f"UPDATE public.equipment SET {', '.join(sets)} WHERE id = :id"), params)
    db.commit()
    os.rename(BACKUP, BACKUP + ".restored")
    print(f"  [OK] restored {len(backup)} equipment record(s); backup renamed to *.restored")


def main():
    db = SessionLocal()
    try:
        if "--undo" in sys.argv:
            undo(db); return
        changes = plan(db)
        per_field = {}
        for _eid, ch in changes:
            for f in ch:
                per_field[f] = per_field.get(f, 0) + 1
        print(f"  equipment to update: {len(changes)}")
        for f, n in sorted(per_field.items()):
            print(f"    {f:22} {n}")
        if "--check" in sys.argv:
            print("\n  --check: nothing changed."); return
        apply(db, changes)
        print(f"\n  [OK] filled. Originals saved to {BACKUP}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
