"""
ALTER: Activate test types found deactivated against the TNEB TSMS POC
proposal's CM/PM matrix (docs/TNEB_TSMS_POC_PROPOSAL.html), plus link two
templates whose OrgTestTemplate.test_type_id was never set at all.

Looked up by NAME (CategoryMaster name + CategoryDetails name), never by
numeric id — ids are auto-increment and differ per environment/database,
so a script driven by hardcoded ids from one DB would silently corrupt an
unrelated row on another.

1. Power Transformer procedures that already have a fully-built, linked,
   is_active:True template but were sitting on CategoryDetails.is_active=
   False for no on-record reason (17 of them). Flips CategoryDetails.
   is_active only — nothing else needed, their test_type_id links were
   already correct.

   Deliberately EXCLUDES 3 look-alike Power Transformer procedures that are
   NOT bugs: "Short Circuit Test HV-LV", "Open Circuit Test HV-LV (1Ph)",
   "Open Circuit Test HV-LV (3Ph)" were intentionally deactivated by
   alter_merge_sc_oc_test_hv_lv.py when superseded by the combined
   "Short Circuit & Open Circuit Test (HV-LV)" form — reactivating them
   would reintroduce duplicate test types alongside their replacement.

2. Templates that had is_active:False AND test_type_id:None (never linked
   to their own CategoryDetails row at all, so the Template Designer's
   category-type grouping filed them under "Other" even if activated):
   transformer_ttr_test, oltc_drm_test, plus the Test+Maintenance pair for
   Potential Transformer, Battery Charger, LTAC Panel, PLCC Panel, and
   Digital Communication Panel (5 of the 11 brand-new equipment types from
   commit ac3166c — confirmed via manual Template Designer activation on
   local, replicated here so other environments match). Fixes each: sets
   template_data is_active True, links test_type_id, and activates the
   CategoryDetails row. The other 6 of the 11 (Isolator, Control & Relay
   Panel, Station Auxiliary Transformer, DG Set, Wave Trap, Fire Fighting
   System) are deliberately NOT included — still pending review.

3. partial_discharge_test — shared by name across 4 equipment types
   (Power Transformer, Current Transformer, Potential Transformer,
   Capacitor Voltage Transformer), each with its OWN CategoryDetails row,
   but only ONE OrgTestTemplate row can hold a test_type_id. Links it to
   the Power Transformer row (arbitrary but consistent pick — the other 3
   resolve via routers/testing_requests.py's list_equipment_types()
   name-based fallback, canonical_by_name, once their own CategoryDetails
   row is active) and activates all 4 CategoryDetails rows.

Safe to run multiple times — every write is a plain "set to True" on
whatever the current row is, not an insert; a row already active is left
as-is, never duplicated.

Usage:
    python alter_activate_tneb_matrix_gaps.py
"""

from __future__ import annotations

from database import SessionLocal
from models import CategoryDetails, CategoryMaster, OrgTestTemplate

# ── 1. Straightforward CategoryDetails.is_active flips (Power Transformer) ──
POWER_TRANSFORMER_NAMES_TO_ACTIVATE = [
    "220kV Bushing Tan-Delta Test",
    "66kV Bushing Tan-Delta Test",
    "Capacitance & Tan Delta Comparison",
    "Insulation Diagnostics (IDAX)",
    "Magnetic Balance Test HV",
    "Magnetic Balance Test IV",
    "Magnetic Balance Test LV",
    "Open Circuit Test HV-IV (1Ph)",
    "Open Circuit Test HV-IV (3Ph)",
    "Open Circuit Test IV-LV (1Ph)",
    "Open Circuit Test IV-LV (3Ph)",
    "Power Transformer Nameplate Details",
    "Ratio Test HV-IV",
    "Ratio Test HV-LV",
    "Short Circuit Test HV-IV",
    "Tan-Delta, Capacitance & Insulation Diagnostics",
    "Transformer Physical Inspection",
]

# ── 2. Templates needing is_active + test_type_id link fixed together ──
# (template_key, CategoryDetails name, CategoryMaster name)
LINK_AND_ACTIVATE = [
    ("transformer_ttr_test", "Transformer Turns Ratio (TTR)", "Power Transformer"),
    ("oltc_drm_test", "OLTC Dynamic Resistance Measurement (DRM)", "Power Transformer"),
    ("potential_transformer_test", "Potential Transformer Test", "Potential Transformer"),
    ("potential_transformer_maintenance", "Potential Transformer Preventive Maintenance", "Potential Transformer"),
    ("battery_charger_test", "Battery Charger Output & Ripple Test", "Battery Charger"),
    ("battery_charger_maintenance", "Battery Charger Preventive Maintenance", "Battery Charger"),
    ("ltac_panel_test", "LTAC Panel Tuning & Insertion Loss Test", "LTAC Panel"),
    ("ltac_panel_maintenance", "LTAC Panel Preventive Maintenance", "LTAC Panel"),
    ("plcc_panel_test", "PLCC Panel Carrier & Signal Test", "PLCC Panel"),
    ("plcc_panel_maintenance", "PLCC Panel Preventive Maintenance", "PLCC Panel"),
    ("comm_panel_test", "Digital Communication Panel Functional Test", "Digital Communication Panel"),
    ("comm_panel_maintenance", "Digital Communication Panel Preventive Maintenance", "Digital Communication Panel"),
]

# ── 3. Shared-by-name template across multiple equipment types ──
PARTIAL_DISCHARGE_TEMPLATE_KEY = "partial_discharge_test"
PARTIAL_DISCHARGE_NAME = "Partial Discharge Measurement"
PARTIAL_DISCHARGE_CANONICAL_MASTER = "Power Transformer"
PARTIAL_DISCHARGE_MASTERS = [
    "Power Transformer", "Current Transformer", "Potential Transformer",
    "Capacitor Voltage Transformer",
]


def _get_master(db, name: str):
    m = db.query(CategoryMaster).filter_by(name=name).first()
    if not m:
        print(f"  [WARN] CategoryMaster {name!r} not found — skipping")
    return m


def _get_detail(db, master_id: int, name: str):
    cd = db.query(CategoryDetails).filter_by(
        category_master_id=master_id, name=name,
    ).first()
    if not cd:
        print(f"  [WARN] CategoryDetails {name!r} not found for master_id={master_id} — skipping")
    return cd


def run(db) -> None:
    activated = 0

    print("--- 1. Power Transformer procedures (CategoryDetails.is_active only) ---")
    pt_master = _get_master(db, "Power Transformer")
    if pt_master:
        for name in POWER_TRANSFORMER_NAMES_TO_ACTIVATE:
            cd = _get_detail(db, pt_master.id, name)
            if not cd:
                continue
            if cd.is_active:
                print(f"  [OK] {name!r} already active")
                continue
            cd.is_active = True
            activated += 1
            print(f"  [ACTIVATED] {name!r}")

    print("\n--- 2. Templates needing test_type_id linked + activated ---")
    for template_key, cd_name, master_name in LINK_AND_ACTIVATE:
        master = _get_master(db, master_name)
        if not master:
            continue
        cd = _get_detail(db, master.id, cd_name)
        if not cd:
            continue
        t = db.query(OrgTestTemplate).filter(
            OrgTestTemplate.org_id.is_(None),
            OrgTestTemplate.template_key == template_key,
        ).first()
        if not t:
            print(f"  [WARN] OrgTestTemplate {template_key!r} not found — skipping")
            continue

        changed = False
        if t.template_data.get("is_active") is False:
            t.template_data["is_active"] = True
            changed = True
        if t.test_type_id != cd.id:
            t.test_type_id = cd.id
            changed = True
        if not cd.is_active:
            cd.is_active = True
            changed = True

        if changed:
            activated += 1
            print(f"  [ACTIVATED] {cd_name!r} (template_key={template_key!r}, test_type_id={cd.id})")
        else:
            print(f"  [OK] {cd_name!r} already active and linked")

    print("\n--- 3. Partial Discharge Measurement (shared across 4 equipment types) ---")
    pd_template = db.query(OrgTestTemplate).filter(
        OrgTestTemplate.org_id.is_(None),
        OrgTestTemplate.template_key == PARTIAL_DISCHARGE_TEMPLATE_KEY,
    ).first()
    if not pd_template:
        print(f"  [WARN] OrgTestTemplate {PARTIAL_DISCHARGE_TEMPLATE_KEY!r} not found — skipping")
    else:
        canonical_master = _get_master(db, PARTIAL_DISCHARGE_CANONICAL_MASTER)
        canonical_cd = (
            _get_detail(db, canonical_master.id, PARTIAL_DISCHARGE_NAME)
            if canonical_master else None
        )
        if canonical_cd:
            if pd_template.template_data.get("is_active") is False:
                pd_template.template_data["is_active"] = True
                activated += 1
                print("  [ACTIVATED] template_data.is_active")
            if pd_template.test_type_id != canonical_cd.id:
                pd_template.test_type_id = canonical_cd.id
                activated += 1
                print(f"  [LINKED] test_type_id -> {canonical_cd.id} ({PARTIAL_DISCHARGE_CANONICAL_MASTER})")

        for master_name in PARTIAL_DISCHARGE_MASTERS:
            master = _get_master(db, master_name)
            if not master:
                continue
            cd = _get_detail(db, master.id, PARTIAL_DISCHARGE_NAME)
            if not cd:
                continue
            if cd.is_active:
                print(f"  [OK] {master_name!r} already active")
                continue
            cd.is_active = True
            activated += 1
            print(f"  [ACTIVATED] {master_name!r}")

    db.commit()
    print(f"\n[DONE] {activated} change(s) applied (0 on a rerun once fully applied).")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
