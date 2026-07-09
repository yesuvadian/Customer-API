"""
migrate_ueic_add_make_serial.py — Regenerate Equipment UEICs to the new format
that includes Equipment Make and Equipment Serial No.

OLD format:
  {Zone}-{Substation}-{VoltageClass}-{Bay}-{TypeCode}-{Incremental}
  e.g.  BN-BBXX-220-100MVA Power TR-1-CT-01

NEW format:
  {Zone}-{Substation}-{Bay}-{VoltageClass}-{TypeCode}-{Make}-{SerialNo}
  e.g.  BN-BBXX-Begur-Vidyanagar line-66-CT-KAPE-HT1690/122569   (real serial no.)
  e.g.  BN-BBXX-Begur-Vidyanagar line-66-CT-KAPE-KAPE2022-1      (fallback, no serial no. in DB)

  - Zone         = 2-char, from department.code at the zone (depth=0) level
  - Substation   = 4-char, generated fresh from the substation's name (not
                   trusted from department.code, which may be stale)
  - Bay          = bay_number, exactly as stored in DB
  - VoltageClass = voltage_class, exactly as stored in DB (no zfill, no "KV" suffix)
  - TypeCode     = 2-char equipment type code (TR for Power Transformer, CT,
                   VT for Potential Transformer, ...)
  - Make         = up to the first 4 alpha-numeric chars of manufacturer,
                   uppercase. Not padded — a 3-char make (e.g. "ABB") stays
                   3 chars; anything longer than 4 chars is truncated to 4.
  - SerialNo     = factory_serial_number as-is (full string, as per DB);
                   if missing, falls back to: {Make}{Year of Manufacture}-
                   {auto-increment counter starting at 1}, e.g. "KAPE2022-1"
                   (same Make code as the segment before it). If
                   year_of_manufacture is also missing, the current calendar
                   year is used instead. The counter is scoped to the (bay,
                   voltage, type, make) prefix, so equipment sharing that
                   prefix (e.g. separate phases of the same bay) still get
                   distinct UEICs.

Assumes OrgDepartment.code is already correct for zones (2-char) only —
i.e. migrate_ueic_codes.py Phase 1 has already run. Substation codes are
regenerated fresh from the department name every time this script runs, so
stale/placeholder values in department.code for substations no longer matter.
This script only rebuilds the UEIC string itself (Phase 3 equivalent), with
the new make/serial segments added.

Usage:
  python migrate_ueic_add_make_serial.py --dry-run    # preview changes only
  python migrate_ueic_add_make_serial.py              # apply changes
"""

import re
import argparse
from collections import defaultdict
from datetime import datetime

from database import SessionLocal
from models import OrgDepartment, Equipment, CategoryMaster, Organization

KPTCL_ORG_NAME = "Karnataka Power Transmission Corporation Limited"

EQUIPMENT_TYPE_CODES = {
    "Power Transformer":            "TR",
    "Current Transformer":          "CT",
    "Potential Transformer":        "PT",
    "Circuit Breaker":              "CB",
    "Isolator":                     "IS",
    "Lightning Arrester":           "LA",
    "Bus Bar":                      "BB",
    "Cable":                        "CA",
    "Capacitor Bank":               "CP",
    "Reactor":                      "RC",
    "Control Valve":                        "CV",
    "Distribution Transformer":             "DT",
    "Electronic Tri-vector Meter":          "EM",
    "ETV Meter":                            "EM",
    "Protection Relay":                     "RL",
    "Capacitor Voltage Transformer":        "VT",
    "Station Auxiliary Transformer":        "AT",
    "Isolator / Disconnector":              "IS",
    "Surge Arrestor":                       "SA",
    "Wave Trap":                            "WT",
    "Control & Relay Panel":                "CR",
    "LTAC Panel":                           "LP",
    "PLCC Panel":                           "PL",
    "Digital Communication Panel":          "DC",
    "Battery Set":                          "BS",
    "Battery Charger":                      "BC",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def strip_voltage_prefix(name: str) -> str:
    """Remove a leading voltage prefix like '110kV ', '220kV ', '66kV ', '400kV '."""
    if not name:
        return ""
    return re.sub(r"^\d+\s*kV\s*", "", name, flags=re.IGNORECASE).strip()


def make_code_upto4(name: str) -> str:
    """Up to 4 alpha-numeric chars, uppercase — no padding. A 3-char make
    stays 3 chars; anything longer than 4 is truncated to 4."""
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", name)
    return cleaned[:4].upper()


def make_4char_code(name: str) -> str:
    """4-char uppercase code from a name (letters/digits only, padded with X)."""
    if not name:
        return "XXXX"
    cleaned = re.sub(r"[^A-Za-z0-9]", "", name)
    code = cleaned[:4].upper()
    return code.ljust(4, "X")


def build_dept_tree(all_depts):
    id_map = {d.id: d for d in all_depts}

    def get_depth(d):
        depth = 0
        current = d
        while current.parent_department_id and current.parent_department_id in id_map:
            current = id_map[current.parent_department_id]
            depth += 1
        return depth

    return id_map, get_depth


def get_zone_ancestor(dept, id_map):
    current = dept
    while current.parent_department_id and current.parent_department_id in id_map:
        current = id_map[current.parent_department_id]
    return current


# ──────────────────────────────────────────────────────────────────────────────
# Main migration
# ──────────────────────────────────────────────────────────────────────────────

def run(dry_run: bool):
    db = SessionLocal()
    try:
        kptcl = db.query(Organization).filter(
            Organization.name == KPTCL_ORG_NAME
        ).first()
        if not kptcl:
            print("ERROR: KPTCL organization not found.")
            return

        all_depts = db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == kptcl.id
        ).all()
        id_map, get_depth = build_dept_tree(all_depts)

        all_equipment = db.query(Equipment).filter(
            Equipment.organization_id == kptcl.id
        ).all()

        # Fallback incremental counter, scoped per prefix (used only when
        # factory_serial_number is missing)
        serial_tracker: dict[str, int] = defaultdict(int)

        ueic_changes = []
        skipped = []

        for eq in sorted(all_equipment, key=lambda e: str(e.ueic or "")):
            dept = id_map.get(eq.department_id)
            if not dept:
                skipped.append((eq, "unknown department"))
                continue

            zone = get_zone_ancestor(dept, id_map)
            zone_code = (zone.code or "XX")[:2].upper()
            # Always derive from the department name — don't trust dept.code,
            # since some rows have stale/placeholder codes (e.g. Begur = "BBXX")
            # that were never correctly (re)generated.
            sub_code = make_4char_code(strip_voltage_prefix(dept.name))

            type_row = db.query(CategoryMaster).filter(
                CategoryMaster.id == eq.equipment_type_id
            ).first()
            type_name = type_row.name if type_row else ""
            type_code = EQUIPMENT_TYPE_CODES.get(type_name, "XX")

            bay = str(eq.bay_number or "").strip()
            vclass = str(eq.voltage_class or "").strip()  # as stored in DB, no reformatting
            make_code = make_code_upto4(eq.manufacturer or "") or "Unknown"

            serial_no = (eq.factory_serial_number or "").strip()
            if not serial_no:
                # Fallback: {make code}{year of manufacture}-{counter}, e.g. "KAPP2022-1".
                # If year_of_manufacture is missing, use the current calendar year.
                # Counter increments per (bay, voltage, type, make) prefix so
                # equipment sharing that prefix (e.g. R/Y/B phases of the same
                # bay) still get distinct UEICs even without a real serial no.
                yom = eq.year_of_manufacture or datetime.now().year
                prefix_key = f"{zone_code}-{sub_code}-{bay}-{vclass}-{type_code}-{make_code}"
                serial_tracker[prefix_key] += 1
                serial_no = f"{make_code}{yom}-{serial_tracker[prefix_key]}"

            parts = [zone_code, sub_code, bay, vclass, type_code, make_code, serial_no]
            new_ueic = "-".join(p for p in parts if p)

            old_ueic = eq.ueic or ""
            if old_ueic != new_ueic:
                ueic_changes.append((eq, old_ueic, new_ueic))

        print(f"  {len(all_equipment)} equipment records scanned")
        print(f"  {len(ueic_changes)} UEICs will change")
        for eq, old, new in ueic_changes[:30]:
            print(f"    {old:45s} -> {new}")
        if len(ueic_changes) > 30:
            print(f"    ... and {len(ueic_changes) - 30} more")

        if skipped:
            print(f"\n  WARN: {len(skipped)} equipment skipped:")
            for eq, reason in skipped[:10]:
                print(f"    {eq.id} — {reason}")

        # Guard against accidental duplicate UEICs before writing
        new_ueics = [new for _, _, new in ueic_changes]
        dupes = {u for u in new_ueics if new_ueics.count(u) > 1}
        if dupes:
            print(f"\n  ERROR: {len(dupes)} duplicate UEICs would be created — aborting.")
            for d in list(dupes)[:10]:
                print(f"    duplicate: {d}")
            return

        if not dry_run:
            for eq, old, new in ueic_changes:
                eq.ueic = new
            db.commit()
            print("\n  Committed.")
        else:
            print("\n  Dry-run — no changes written.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)