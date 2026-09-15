"""
ALTER: Refresh template_data for templates whose Pass/Fail-style dropdown
and table-column fields lacked severity evaluation — a broader audit
following the same class of bug already fixed for boolean fields (see
alter_evaluate_booleans_and_fault_desc.py).

15 fields across 8 templates fixed in test_templates.py:
  - differential_protection_test.stability_result       -> _EV_TRIP (already
    defined, just never wired here)
  - transformer_protection_commissioning: 2 table columns (setting_verified,
    trip_test_ok) -> new Yes/No severity map
  - physical_inspection: paint_condition, silica_gel_condition -> new maps
  - circuit_breaker_travel_timing: closing_times table's "result" column
    -> _EV_PF (its sibling opening_times table already had this — a
    copy-paste gap)
  - surge_arrestor_power_freq_withstand: flashover table column -> new
    inverted No/Yes map
  - tan_delta_capacitance_idax: moisture_analysis + oil_conductivity_analysis
    table columns -> _EV_MOISTURE / _EV_OIL_COND (both already defined,
    never wired here; a near-identical template elsewhere already used
    _EV_OIL_COND correctly)
  - oltc_drm_test (added this session): anomaly_detected table column —
    BUG FIX, was using dropdown_evaluation (wrong key for a table column)
    instead of column_evaluation, so it silently evaluated nothing
  - transformer_repair_lifecycle: 10 fields across its 10-stage form
    (s5_inspection_outcome, s7_stage_insp_1/2/3_result, s10_turns_ratio_ok,
    s10_winding_resistance_ok, s10_no_load_test_ok, dga_result_1m,
    bdv_result_1m, ir_result_6m, overall_quality_rating)

Deliberately NOT touched (confirmed false positives — config/attribution/
classification fields, not health outcomes): oc_phase_curve, all 10
*_delay_reason fields, transformer_dga.recommended_action,
partial_discharge_test.pd_pattern.

Safe to run multiple times (each run just re-syncs template_data to the
current TEST_TEMPLATES content for whichever of these keys are actually
live in the DB).

Usage:
    python alter_evaluate_remaining_functional_fields.py
"""

from __future__ import annotations

from database import SessionLocal
from models import OrgTestTemplate
from test_templates import TEST_TEMPLATES

TEMPLATE_KEYS = [
    "differential_protection_test",
    "transformer_protection_commissioning",
    "physical_inspection",
    "circuit_breaker_travel_timing",
    "surge_arrestor_power_freq_withstand",
    "tan_delta_capacitance_idax",
    "oltc_drm_test",
    "transformer_repair_lifecycle",
]


def run(db) -> None:
    updated = 0
    for key in TEMPLATE_KEYS:
        template_data = TEST_TEMPLATES.get(key)
        if not template_data:
            print(f"[WARN] {key!r} not found in TEST_TEMPLATES — skipping")
            continue

        row = db.query(OrgTestTemplate).filter(
            OrgTestTemplate.org_id.is_(None),
            OrgTestTemplate.template_key == key,
        ).first()
        if not row:
            print(f"[WARN] No live OrgTestTemplate row for {key!r} — nothing to refresh")
            continue

        row.template_data = template_data
        updated += 1
        print(f"[OK] {key!r} template_data refreshed")

    db.commit()
    print(f"\n[DONE] {updated} OrgTestTemplate rows refreshed.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
