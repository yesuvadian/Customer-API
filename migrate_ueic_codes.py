"""
migrate_ueic_codes.py — One-time migration to fix OrgDepartment codes and regenerate
Equipment UEICs in the new make/serial format.

Phases:
  1. Update zone (depth=0) codes to proper 2-char unique codes
  2. Generate proper 4-char substation (depth=3) codes from station names
     (collision-resolved per zone) — kept on OrgDepartment.code for reference,
     though Phase 3 always re-derives the substation code fresh from the name
  3. Regenerate all Equipment UEICs in the NEW format:
       {Zone}-{Substation}-{Bay}-{VoltageClass}-{TypeCode}-{Make}-{SerialNo}
     e.g.  BN-BBXX-Begur-Vidyanagar line-66-CT-KAPE-HT1690/122569  (real serial no.)
     e.g.  BN-BBXX-Begur-Vidyanagar line-66-CT-KAPE-KAPE2022-1     (fallback, no serial no. in DB)

     - Zone         = 2-char, from department.code at the zone (depth=0) level
                       (set in Phase 1)
     - Substation    = 4-char, generated fresh from the substation's name
                       (not trusted from department.code, which may be stale)
     - Bay           = bay_number, exactly as stored in DB
     - VoltageClass  = voltage_class, exactly as stored in DB (no zfill, no "KV" suffix)
     - TypeCode      = 2-char equipment type code (TR for Power Transformer, CT,
                       PT for Potential Transformer, ...)
     - Make          = up to the first 4 alpha-numeric chars of manufacturer,
                       uppercase. Not padded — a 3-char make (e.g. "ABB") stays
                       3 chars; anything longer than 4 chars is truncated to 4.
     - SerialNo      = factory_serial_number as-is (full string, as per DB);
                       if missing, falls back to: {Make}{Year of Manufacture}-
                       {auto-increment counter starting at 1}, e.g. "KAPE2022-1"
                       (same Make code as the segment before it). If
                       year_of_manufacture is also missing, the current calendar
                       year is used instead. The counter is scoped to the (bay,
                       voltage, type, make) prefix, so equipment sharing that
                       prefix (e.g. separate phases of the same bay) still get
                       distinct UEICs.

Usage:
  python migrate_ueic_codes.py --dry-run    # preview changes, no DB writes
  python migrate_ueic_codes.py              # apply changes
"""

import re
import sys
import argparse
from collections import defaultdict
from datetime import datetime
from uuid import UUID

from database import SessionLocal
from models import OrgDepartment, Equipment, CategoryMaster, Organization
from sqlalchemy import func

KPTCL_ORG_NAME = "Karnataka Power Transmission Corporation Limited"

# Manual zone code assignments — 2-char unique codes
ZONE_CODE_MAP = {
    "Bagalkot Zone":   "BK",
    "Bangalore Zone":  "BN",
    "Hassan Zone":     "HS",
    "Kalaburagi Zone": "KL",
    "Mysuru Zone":     "MY",
    "Tumkur Zone":     "TK",
}

# NOTE: this is the single source of truth for equipment type codes. It must
# match EquipmentService.EQUIPMENT_TYPE_CODES in services/equipment_service.py
# exactly, or migrated UEICs and freshly-created UEICs will disagree.
EQUIPMENT_TYPE_CODES = {
    "Power Transformer":             "TR",
    "Circuit Breaker":               "CB",
    "Current Transformer":           "CT",
    "Potential Transformer":         "PT",
    "Voltage Transformer":           "PT",
    "Capacitor Voltage Transformer": "VT",
    "CVT":                           "VT",
    "Surge Arrestor":                "SA",
    "Isolator":                      "IS",
    "Isolator / Disconnector":       "IS",
    "Disconnector":                  "IS",
    "Control & Relay Panel":         "CR",
    "Battery Set":                   "BS",
    "Battery Charger":               "BC",
    "Wave Trap":                     "WT",
    "Station Auxiliary Transformer": "AT",
    "LTAC Panel":                    "LP",
    "Fire Fighting System":          "FF",
    "PLCC Panel":                    "PL",
    "Digital Communication Panel":   "DC",
    "Diesel Generator Set":          "DG",
    "Electronic Tri-vector Meter":   "EM",
    "ETV Meter":                     "EM",
    "Protection Relay":              "RL",
    "Distribution Transformer":      "DT",
    "Bus Bar":                       "BB",
    "Cable":                         "CA",
    "Capacitor Bank":                "CP",
    "Reactor":                       "RC",
    "Lightning Arrester":            "LA",
    "Control Valve":                 "CV",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def strip_voltage_prefix(name: str) -> str:
    """Remove leading voltage prefix like '110kV ', '220kV ', '66kV ', '400kV '."""
    if not name:
        return ""
    return re.sub(r"^\d+\s*kV\s*", "", name, flags=re.IGNORECASE).strip()


def make_4char_code(base_name: str) -> str:
    """
    Generate a 4-char code from a name (voltage prefix already stripped).
    Strategy: take first 4 alpha-numeric chars, uppercase, pad with 'X'.
    Examples:
      Achanur        -> ACHA
      Navanagar-2    -> NAVA
      Kulageri Cross -> KULA
    """
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", base_name)
    letters = re.sub(r"\s+", "", cleaned)
    code = letters[:4].upper()
    return code.ljust(4, "X")


def make_code_upto4(name: str) -> str:
    """Up to 4 alpha-numeric chars, uppercase — NOT padded. A 3-char make
    stays 3 chars; anything longer than 4 is truncated to 4."""
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", name)
    return cleaned[:4].upper()


def resolve_collisions(code_map: dict) -> dict:
    """
    code_map: {dept_id: proposed_code}
    Returns:  {dept_id: final_code} with numeric suffixes on duplicates.
    Keeps the first occurrence unchanged; subsequent duplicates get suffix 2, 3, …
    """
    seen: dict[str, int] = {}
    result: dict = {}
    for dept_id, code in code_map.items():
        if code not in seen:
            seen[code] = 1
            result[dept_id] = code
        else:
            seen[code] += 1
            suffix = str(seen[code])
            new_code = (code[:3] + suffix).upper()
            result[dept_id] = new_code
    return result


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


def get_zone_ancestor(dept, id_map, get_depth=None):
    """Walk up to the depth=0 ancestor."""
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

        # ── Phase 1: Zone codes ───────────────────────────────────────────────
        print("\n=== Phase 1: Zone codes ===")
        zones = [d for d in all_depts if get_depth(d) == 0]
        zone_id_to_new_code: dict[UUID, str] = {}

        for z in zones:
            new_code = ZONE_CODE_MAP.get(z.name)
            if not new_code:
                print(f"  WARN: No mapping for zone '{z.name}' (code={z.code}) — skipping")
                continue
            old_code = z.code
            zone_id_to_new_code[z.id] = new_code
            status_msg = "  (unchanged)" if old_code == new_code else f"  {old_code} -> {new_code}"
            print(f"  {z.name}: {status_msg}")
            if not dry_run and old_code != new_code:
                z.code = new_code

        # ── Phase 2: Substation codes (kept on OrgDepartment.code for reference) ──
        print("\n=== Phase 2: Substation codes ===")
        substations = [d for d in all_depts if get_depth(d) == 3]

        by_zone: dict[UUID, list] = defaultdict(list)
        for s in substations:
            zone = get_zone_ancestor(s, id_map)
            by_zone[zone.id].append(s)

        sub_id_to_new_code: dict[UUID, str] = {}
        collision_count = 0

        for zone_id, subs in by_zone.items():
            proposed = {}
            for s in subs:
                base = strip_voltage_prefix(s.name)
                code = make_4char_code(base)
                proposed[s.id] = code

            code_to_ids: dict[str, list] = defaultdict(list)
            for sid, code in proposed.items():
                code_to_ids[code].append(sid)

            zone_collisions = sum(1 for ids in code_to_ids.values() if len(ids) > 1)
            collision_count += zone_collisions

            subs_sorted = sorted(subs, key=lambda s: s.name)
            seen_codes: dict[str, int] = {}
            for s in subs_sorted:
                code = proposed[s.id]
                if code not in seen_codes:
                    seen_codes[code] = 1
                    final = code
                else:
                    seen_codes[code] += 1
                    suffix = str(seen_codes[code])
                    final = (code[:4 - len(suffix)] + suffix).upper()
                sub_id_to_new_code[s.id] = final

        print(f"  {len(substations)} substations processed, {collision_count} collision groups resolved")

        changed_subs = [(id_map[sid], new) for sid, new in sub_id_to_new_code.items()
                        if id_map[sid].code != new]
        print(f"  {len(changed_subs)} codes will change")
        for dept, new_code in changed_subs[:20]:
            print(f"    {dept.name:40s} {dept.code or '':6s} -> {new_code}")
        if len(changed_subs) > 20:
            print(f"    ... and {len(changed_subs) - 20} more")

        if not dry_run:
            for sid, new_code in sub_id_to_new_code.items():
                dept = id_map[sid]
                if dept.code != new_code:
                    dept.code = new_code
            db.flush()

        # ── Phase 3: Regenerate Equipment UEICs (NEW make/serial format) ──────
        print("\n=== Phase 3: Regenerate Equipment UEICs (make/serial format) ===")

        all_equipment = db.query(Equipment).filter(
            Equipment.organization_id == kptcl.id
        ).all()

        # Fallback incremental counter, scoped per (zone-sub-bay-voltage-type-make)
        # prefix — used only when factory_serial_number is missing.
        serial_tracker: dict[str, int] = defaultdict(int)

        ueic_changes = []
        skipped = []

        for eq in sorted(all_equipment, key=lambda e: str(e.ueic or "")):
            dept = id_map.get(eq.department_id)
            if not dept:
                skipped.append((eq, "unknown department"))
                continue

            zone = get_zone_ancestor(dept, id_map)
            zone_code = zone_id_to_new_code.get(zone.id, (zone.code or "XX")[:2].upper())

            # Always derive the substation code fresh from the department name —
            # don't trust dept.code, even the value just written in Phase 2,
            # to guarantee Phase 3 output matches EquipmentService.generate_ueic()
            # exactly for newly-created equipment going forward.
            sub_code = make_4char_code(strip_voltage_prefix(dept.name))

            type_row = db.query(CategoryMaster).filter(
                CategoryMaster.id == eq.equipment_type_id
            ).first()
            type_name = type_row.name if type_row else ""
            type_code = EQUIPMENT_TYPE_CODES.get(type_name, "XX")

            bay = str(eq.bay_number or "").strip()
            vclass = str(eq.voltage_class or "").strip()  # as stored, no reformatting
            make_code = make_code_upto4(eq.manufacturer or "") or "Unknown"

            serial_no = (eq.factory_serial_number or "").strip()
            if not serial_no:
                # Fallback: {make code}{year of manufacture}-{counter}, e.g. "KAPE2022-1".
                # If year_of_manufacture is missing, use the current calendar year.
                # Counter increments per (zone, sub, bay, voltage, type, make) prefix
                # so equipment sharing that prefix (e.g. R/Y/B phases of the same
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
            print(f"\n  ERROR: {len(dupes)} duplicate UEICs would be created — aborting. Fix data and re-run.")
            for d in list(dupes)[:10]:
                print(f"    duplicate: {d}")
            return

        if not dry_run:
            # ── Two-phase write ────────────────────────────────────────────
            # Postgres checks the UNIQUE constraint on `ueic` per-statement, not
            # at end-of-transaction. Some old UEICs are the *new* UEIC target of
            # another row in this same batch (e.g. old "...2008-1" -> new
            # "...2008-3", while a different row's old value IS "...2008-3").
            # Writing final values directly can hit that not-yet-vacated old
            # value mid-transaction and raise UniqueViolation, even though the
            # end state has no duplicates. Fix: stage every changing row to a
            # temp value derived from its own UUID (guaranteed unique, and
            # guaranteed not to collide with any real UEIC), flush, then write
            # the real final UEICs. Order no longer matters.
            print("\n  Writing (two-phase, to avoid mid-transaction UEIC collisions)...")

            for eq, old, new in ueic_changes:
                eq.ueic = f"__TMP_MIGRATE__{eq.id}"
            db.flush()

            for eq, old, new in ueic_changes:
                # serial_in_bay now mirrors the real serial segment used in the UEIC,
                # not a zero-padded incremental counter — keep it consistent with
                # EquipmentService.create_equipment()'s new assignment logic.
                eq.serial_in_bay = (eq.factory_serial_number or "").strip() or new.rsplit("-", 1)[-1]
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