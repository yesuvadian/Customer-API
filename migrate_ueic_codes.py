"""
migrate_ueic_codes.py — One-time migration to fix OrgDepartment codes and regenerate Equipment UEICs.

Phases:
  1. Update zone (depth=0) codes to proper 2-char unique codes
  2. Generate proper 4-char substation (depth=3) codes from station names
  3. Resolve any 4-char collisions (append digit suffix)
  4. Regenerate all Equipment UEICs using the corrected codes

Usage:
  python migrate_ueic_codes.py --dry-run    # preview changes, no DB writes
  python migrate_ueic_codes.py              # apply changes
"""

import re
import sys
import argparse
from collections import defaultdict
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

EQUIPMENT_TYPE_CODES = {
    "Power Transformer":            "PT",
    "Current Transformer":          "CT",
    "Potential Transformer":        "VT",
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


# Common filler words seen in real KPTCL substation/department names that are
# NOT part of the place name and should never leak into an abbreviation.
_STATION_FILLER_WORDS = (
    "receiving", "station", "substation", "ss", "tl", "sub", "division",
    "circle", "zone", "grid", "switching",
)


def strip_voltage_prefix(name: str) -> str:
    """
    Remove voltage rating tokens from a station name, wherever they appear —
    e.g. '110kV Achanur' (leading) or 'BIAL Begur 220/66/11kV receiving station'
    (embedded compound ratio). Real KPTCL names commonly use slash-separated
    compound ratios like '220/66/11kV', not just a single leading voltage.
    """
    # Compound or single voltage ratio, e.g. "220/66/11kV", "110kV", "66/11kV"
    cleaned = re.sub(r"\d+(?:\s*/\s*\d+)*\s*kv\b", "", name, flags=re.IGNORECASE)
    return cleaned.strip()


def make_4char_code(base_name: str) -> str | None:
    """
    Generate a 4-char code candidate from a substation base name (voltage
    tokens already stripped). This is a best-effort fallback for the one-time
    backfill only — it is NOT used at runtime. Real substation abbreviations
    (e.g. "Bellary" -> "BLRY") are a curated editorial choice that can't be
    reliably reproduced by string-mangling the name, so every code produced
    here should be reviewed by a human before being treated as final.

    Returns None if no usable letters remain after stripping filler words,
    so the caller can flag the row for manual attention instead of emitting
    a meaningless numeric/placeholder code.
    """
    # Remove punctuation except letters/digits/spaces
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", base_name)
    words = [w for w in cleaned.split() if w.lower() not in _STATION_FILLER_WORDS]
    letters = "".join(words)
    # Drop any leading digits left over (e.g. a stray ratio fragment) — a code
    # should read as an abbreviation, not a number.
    letters = re.sub(r"^\d+", "", letters)
    if not letters:
        return None
    code = letters[:4].upper()
    return code.ljust(4, "X")  # pad if shorter than 4


def resolve_collisions(code_map: dict) -> dict:
    """
    code_map: {dept_id: proposed_code}
    Returns:  {dept_id: final_code} with numeric suffixes on duplicates.
    Keeps the first occurrence unchanged; subsequent duplicates get suffix 2, 3, …
    """
    seen: dict[str, int] = {}       # code -> occurrence count
    result: dict = {}
    for dept_id, code in code_map.items():
        if code not in seen:
            seen[code] = 1
            result[dept_id] = code
        else:
            seen[code] += 1
            suffix = str(seen[code])
            new_code = (code[:3] + suffix).upper()  # e.g. ACH2
            result[dept_id] = new_code
    return result


def build_dept_tree(all_depts):
    id_map = {d.id: d for d in all_depts}
    parent_ids = {d.parent_department_id for d in all_depts if d.parent_department_id}

    def get_depth(d):
        depth = 0
        current = d
        while current.parent_department_id and current.parent_department_id in id_map:
            current = id_map[current.parent_department_id]
            depth += 1
        return depth

    return id_map, get_depth


def get_zone_ancestor(dept, id_map, get_depth):
    """Walk up to depth=0 ancestor."""
    current = dept
    while True:
        if not current.parent_department_id or current.parent_department_id not in id_map:
            return current
        current = id_map[current.parent_department_id]


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
            status = "  (unchanged)" if old_code == new_code else f"  {old_code} -> {new_code}"
            print(f"  {z.name}: {status}")
            if not dry_run and old_code != new_code:
                z.code = new_code

        # ── Phase 2: Substation codes ─────────────────────────────────────────
        print("\n=== Phase 2: Substation codes ===")
        substations = [d for d in all_depts if get_depth(d) == 3]

        # Group by zone to resolve collisions per-zone (not globally)
        by_zone: dict[UUID, list] = defaultdict(list)
        for s in substations:
            zone = get_zone_ancestor(s, id_map, get_depth)
            by_zone[zone.id].append(s)

        sub_id_to_new_code: dict[UUID, str] = {}
        collision_count = 0

        for zone_id, subs in by_zone.items():
            zone = id_map[zone_id]
            # Build proposed codes
            proposed = {}
            needs_manual_review = []
            for s in subs:
                base = strip_voltage_prefix(s.name)
                code = make_4char_code(base)
                if code is None:
                    needs_manual_review.append(s.name)
                    code = "TODO"  # visibly wrong placeholder — must be fixed by hand before use
                proposed[s.id] = code
            if needs_manual_review:
                print(f"  MANUAL REVIEW NEEDED for zone '{zone.name}' — no usable name left after "
                      f"stripping voltage/filler words, set OrgDepartment.code by hand for:")
                for name in needs_manual_review:
                    print(f"    - {name}")

            # Detect collisions within zone
            code_to_ids: dict[str, list] = defaultdict(list)
            for sid, code in proposed.items():
                code_to_ids[code].append(sid)

            zone_collisions = sum(1 for ids in code_to_ids.values() if len(ids) > 1)
            collision_count += zone_collisions

            # Resolve: stable-sort by name so collision resolution is deterministic
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

        # Show sample changes
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

        # ── Phase 3: Regenerate Equipment UEICs ───────────────────────────────
        print("\n=== Phase 3: Regenerate Equipment UEICs ===")

        all_equipment = db.query(Equipment).filter(
            Equipment.organization_id == kptcl.id
        ).all()

        # Serial counter: track per (zone, substation, voltage, bay, type)
        serial_tracker: dict[str, int] = defaultdict(int)

        ueic_changes = []
        for eq in sorted(all_equipment, key=lambda e: str(e.ueic or "")):
            dept = id_map.get(eq.department_id)
            if not dept:
                print(f"  WARN: equipment {eq.id} has unknown department {eq.department_id}")
                continue

            zone = get_zone_ancestor(dept, id_map, get_depth)
            zone_code = zone_id_to_new_code.get(zone.id, (zone.code or "XX")[:2])

            # Equipment may be registered at depth=2 (division) instead of depth=3
            # Generate a 4-char code on the fly for those departments if not in map
            if dept.id in sub_id_to_new_code:
                sub_code = sub_id_to_new_code[dept.id]
            else:
                base = strip_voltage_prefix(dept.name)
                sub_code = make_4char_code(base) or "TODO"

            type_row = db.query(CategoryMaster).filter(
                CategoryMaster.id == eq.equipment_type_id
            ).first()
            type_name = type_row.name if type_row else ""
            type_code = EQUIPMENT_TYPE_CODES.get(type_name, "XX")

            v_class = str(eq.voltage_class or "").zfill(3)
            bay     = str(eq.bay_number or "").zfill(2)

            prefix = f"{zone_code}-{sub_code}-{v_class}-{bay}-{type_code}"
            serial_tracker[prefix] += 1
            serial = str(serial_tracker[prefix]).zfill(2)

            new_ueic = f"{prefix}-{serial}"
            old_ueic = eq.ueic or ""

            if old_ueic != new_ueic:
                ueic_changes.append((eq, old_ueic, new_ueic))

        print(f"  {len(all_equipment)} equipment records scanned")
        print(f"  {len(ueic_changes)} UEICs will change")
        for eq, old, new in ueic_changes[:20]:
            print(f"    {old:30s} -> {new}")
        if len(ueic_changes) > 20:
            print(f"    ... and {len(ueic_changes) - 20} more")

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