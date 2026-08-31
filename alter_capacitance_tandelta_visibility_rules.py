#!/usr/bin/env python3
"""
One-time fix for the capacitance_tandelta_transformer template, applied to
every already-provisioned OrgTestTemplate row:

  1. Set "visibility_rule" (COMPARE type) on the voltage-tier-specific
     bushing sections, based on the single plain value stored in
     voltage_ratio (equipment.voltage_class, e.g. "400" or "220" - NOT a
     composite "400/220/33" string). Overwrites any earlier CONTAINS/
     MIN_SEGMENTS rule from a prior version of this script.
  1b. Replace winding_test_results' and idax_test_results' default_rows
     with the family-scoped, correctly-ordered row set (see _WINDING_ROWS
     below) - both tables test the same electrode combinations.
  2. Give each of the five voltage tiers its own standalone "{tier} kV
     Bushing Details" SECTION (Details / R-phase / Y-phase / B-phase
     columns, Make / Sl. No. / Y.O. Mfg. rows), inserted immediately before
     its "{tier} kV Bushing Test Results" section - matching KPTCL's own
     Tan-Delta report format exactly (its "b./c.", "d./e." etc. sub-heading
     pairs are two separate tables, not one). An earlier revision of this
     script embedded the details table as the first FIELD inside the Test
     Results section instead, with the axes transposed (phase-per-row
     instead of attribute-per-row) - this version detects and migrates
     that intermediate shape too.
  3. Remove fields/columns/section retired from test_templates.py:
     - "% D.F @ 20°C (Previous Test)" column from all 6 test-results tables
       (Winding + every bushing tier)
     - "% Moisture (Previous Test)" column from the IDAX table
     - "Previous Test Date" field for Winding, all 5 bushing tiers, and IDAX
       (all six - none are kept)
     - the "Overall Assessment" section (redundant - the RecommendationWizard
       already renders its own version; this section's fields were suppressed
       from the tester's form regardless, see _wizardOwnedKeys in
       test_result_form.dart)
  4. Convert idax_test_results' tr_analysis_moisture / tr_analysis_oil
     columns from tester-picked dropdowns to auto-computed THRESHOLD rules
     against moisture_percent / oil_conductivity_psm in the same row:
       % Moisture:      <1.0 As New, 1.0-2.0 Dry, 2.0-3.0 Moderately Wet, >3.0 Wet
       Oil Conductivity: <0.37 As New, 0.37-3.7 Good, 3.7-37 Service Aged, >37 Deteriorated

OrgTestTemplate rows are seeded once from test_templates.py by
provision_global_defaults() and never auto-synced afterward - editing
test_templates.py alone does not fix already-seeded rows in the DB, which is
what the tester's form and the report/analytics services actually read (see
OrgTestTemplateService.get_for_test_type / get_by_template_key, DB-first
resolution). This script applies the same additions that were made to
test_templates.py directly to every stored OrgTestTemplate row for this
template_key, org-specific or global.

Family logic: KPTCL's fleet has two transformer families, and voltage_ratio
holds ONE plain value naming which family a unit belongs to -
  "400" -> 400/220/33 kV family (400 + 220 + 33 kV bushings, tertiary winding)
  "220" or "66" -> 220/66/11 kV family (220 + 66 + 11 kV bushings, tertiary
                   winding). Both values are registered in practice - some
                   220/66/11kV units are tagged "220", others "66" - so every
                   220-family check accepts either via operator "in", not a
                   plain "=" against "220" alone (that was the original bug:
                   "66"-tagged equipment matched nothing, so its entire
                   bushing/winding/IDAX area rendered with zero visible rows).
220 kV is additionally common to BOTH families (400/220/33's own MV bushing),
so its section (and the tertiary-only winding rows, since both families are
3-winding) use operator "in" over all three of "400", "220", "66"; the 400kV
and 33kV sections use a plain "=" against "400" since only the 400-family
uses them.

Sections are matched by the voltage tier embedded in their fields' keys
(e.g. any field key starting with "bushing_400kv_"), not by title, so a
renamed section title doesn't break the match. Idempotent - re-running after
it has already applied the current shape reports zero changes.

Usage:
    python alter_capacitance_tandelta_visibility_rules.py --dry-run   # report only
    python alter_capacitance_tandelta_visibility_rules.py             # apply
"""
import argparse

from database import VendorSessionLocal
from models import OrgTestTemplate
from sqlalchemy.orm.attributes import flag_modified

TEMPLATE_KEY = "capacitance_tandelta_transformer"
VOLTAGE_FIELD = "voltage_ratio"

# All bushing tiers this template covers.
_ALL_TIERS = ("400", "220", "66", "33", "11")

# tier -> target COMPARE visibility_rule for that tier's sections.
#
# "66" is folded into the 220kV family alongside "220" itself:
# equipment.voltage_class is registered as a plain "66" for standalone
# 220/66/11kV-family transformers (not just "220"/"400") - confirmed against
# live data, where 16 real testing requests for this template already exist
# against voltage_class="66" equipment. Without this, every tier check below
# ("=220"/"in [400,220]") evaluates false for that equipment, so the entire
# bushing + winding + IDAX area renders with zero visible rows/sections.
_TIER_RULES = {
    "400": {"type": "COMPARE", "config": {"field": VOLTAGE_FIELD, "operator": "=", "value": "400"}},
    "220": {"type": "COMPARE", "config": {"field": VOLTAGE_FIELD, "operator": "in", "values": ["400", "220", "66"]}},
    "66":  {"type": "COMPARE", "config": {"field": VOLTAGE_FIELD, "operator": "in", "values": ["220", "66"]}},
    "33":  {"type": "COMPARE", "config": {"field": VOLTAGE_FIELD, "operator": "=", "value": "400"}},
    "11":  {"type": "COMPARE", "config": {"field": VOLTAGE_FIELD, "operator": "in", "values": ["220", "66"]}},
}


def _row_rule(operator: str, **kw) -> dict:
    return {"type": "COMPARE", "config": {"field": VOLTAGE_FIELD, "operator": operator, **kw}}


# Canonical winding_test_results / idax_test_results default_rows - matches
# the utility's own convention: 400/220/33kV units test combined (HV+LV)
# electrodes plus TV-GND; 220/66/11kV units test each winding pair
# individually. TV-GND is the one configuration common to both families.
# Order matters (rendered top to bottom exactly as listed here).
_WINDING_ROWS = [
    {"test_configuration": "(HV+LV)-GND", "visibility_rule": _row_rule("=", value="400")},
    {"test_configuration": "(HV+LV)-TV",  "visibility_rule": _row_rule("=", value="400")},
    {"test_configuration": "TV-GND",      "visibility_rule": _row_rule("in", values=["400", "220", "66"])},
    {"test_configuration": "HV-LV",       "visibility_rule": _row_rule("in", values=["220", "66"])},
    {"test_configuration": "HV-GND",      "visibility_rule": _row_rule("in", values=["220", "66"])},
    {"test_configuration": "LV-TV",       "visibility_rule": _row_rule("in", values=["220", "66"])},
    {"test_configuration": "LV-GND",      "visibility_rule": _row_rule("in", values=["220", "66"])},
    {"test_configuration": "TV-HV",       "visibility_rule": _row_rule("in", values=["220", "66"])},
]

# Retired in a later revision - "% D.F @ 20°C (Previous Test)" (winding +
# every bushing tier) and "% Moisture (Previous Test)" (IDAX) manual-entry
# columns.
_REMOVED_COLUMN_KEYS = {"df_previous_corrected", "moisture_percent_previous"}

# Retired "Previous Test Date" fields - all six.
_REMOVED_FIELD_KEYS = {
    "winding_previous_test_date",
    "bushing_400kv_previous_test_date",
    "bushing_220kv_previous_test_date",
    "bushing_66kv_previous_test_date",
    "bushing_33kv_previous_test_date",
    "bushing_11kv_previous_test_date",
    "idax_previous_test_date",
}

# Retired section - redundant with the RecommendationWizard.
_REMOVED_SECTION_TITLES = {"Overall Assessment"}

# idax_test_results: tr_analysis_moisture / tr_analysis_oil, converted from
# tester-picked dropdowns to auto-computed THRESHOLD rules.
_IDAX_ANALYSIS_COLUMNS = {
    "tr_analysis_moisture": {
        "key": "tr_analysis_moisture",
        "label": "Tr. Analysis (% Moisture)",
        "type": "calculated",
        "read_only": True,
        "rule": {
            "type": "THRESHOLD",
            "config": {
                "input_field": "moisture_percent",
                "thresholds": {
                    "% Moisture (IDAX)": {
                        "As New":         [None, 1.0],
                        "Dry":            [1.0, 2.0],
                        "Moderately Wet": [2.0, 3.0],
                        "Wet":            [3.0, None],
                    }
                },
            },
        },
    },
    "tr_analysis_oil": {
        "key": "tr_analysis_oil",
        "label": "Tr. Analysis (Oil Conductivity)",
        "type": "calculated",
        "read_only": True,
        "rule": {
            "type": "THRESHOLD",
            "config": {
                "input_field": "oil_conductivity_psm",
                "thresholds": {
                    "Oil Conductivity (IDAX)": {
                        "As New":       [None, 0.37],
                        "Good":         [0.37, 3.7],
                        "Service Aged": [3.7, 37],
                        "Deteriorated": [37, None],
                    }
                },
            },
        },
    },
}

# idax_test_results' table_evaluation.oil_conductivity_psm bands, aligned
# with tr_analysis_oil's THRESHOLD bands above (the old 0.1/1.0 bands were
# from before that column existed and don't match the new scale at all -
# a "Good" reading like 0.5 would have shown ALERT health status).
_IDAX_OIL_EVALUATION = {
    "normal_min": None, "normal_max": 3.7,
    "alert_min":  None, "alert_max":  None,
    "critical_below": None, "critical_above": 37,
    "trend_watch": True,
    "weight": 1.0,
    "remedial_action_text": "High oil conductivity — arrange oil reconditioning or replacement.",
}


def _test_results_tier(section: dict) -> str | None:
    """Return the voltage tier ("400"/"220"/"66"/"33"/"11") if this is a
    "{tier} kV Bushing Test Results" section, identified by its
    bushing_{tier}kv_test_results field, or None otherwise."""
    for field in section.get("fields", []):
        key = field.get("key", "")
        if key.startswith("bushing_") and key.endswith("kv_test_results"):
            tier = key[len("bushing_"):-len("kv_test_results")]
            if tier in _ALL_TIERS:
                return tier
    return None


def _details_field(tier: str) -> dict:
    """Build the bushing_{tier}kv_details table field, matching
    test_templates.py: rows are Make/Sl. No./Y.O. Mfg. (the attributes),
    columns are the R/Y/B phases - the transpose of the test-results table,
    matching KPTCL's own report layout exactly."""
    return {
        "key": f"bushing_{tier}kv_details",
        "label": f"{tier} kV Bushing Details",
        "type": "table",
        "allow_add_rows": True,
        "allow_delete_rows": True,
        "lock_default_rows": True,
        "columns": [
            {"key": "detail",  "label": "Details",              "type": "readonly"},
            {"key": "r_phase", "label": f"{tier} kV 'R' Phase", "type": "text"},
            {"key": "y_phase", "label": f"{tier} kV 'Y' Phase", "type": "text"},
            {"key": "b_phase", "label": f"{tier} kV 'B' Phase", "type": "text"},
        ],
        "default_rows": [
            {"detail": "Make"},
            {"detail": "Sl. No."},
            {"detail": "Y.O. Mfg."},
        ],
    }


def _details_section(tier: str) -> dict:
    """Build the standalone "{tier} kV Bushing Details" section."""
    return {
        "title": f"{tier} kV Bushing Details",
        "visibility_rule": _TIER_RULES[tier],
        "fields": [_details_field(tier)],
    }


def _fix_details_sections(template_data: dict) -> bool:
    """Ensure every bushing tier has its own standalone "{tier} kV Bushing
    Details" section, correctly shaped, immediately before its Test Results
    section. Handles three starting states per tier: never added, embedded
    as the Test Results section's first field (old shape, wrong axes), or
    already a standalone section (possibly with the old wrong-axes shape).
    Mutates template_data["sections"] in place. Returns True if changed."""
    sections = template_data.get("sections", [])
    changed = False
    details_key_re = "_kv_details"

    new_sections = []
    for section in sections:
        # Strip an old-shape details field embedded inside the Test Results
        # section itself (intermediate state from an earlier script version).
        tier = _test_results_tier(section)
        if tier:
            fields = section.get("fields", [])
            details_key = f"bushing_{tier}kv_details"
            kept = [f for f in fields if f.get("key") != details_key]
            if len(kept) != len(fields):
                section["fields"] = kept
                changed = True

            # Ensure the standalone Details section immediately precedes it.
            details_title = f"{tier} kV Bushing Details"
            if not (new_sections and new_sections[-1].get("title") == details_title):
                new_sections.append(_details_section(tier))
                changed = True

        new_sections.append(section)

    template_data["sections"] = new_sections

    # Fix the shape of any existing standalone Details section that has the
    # old wrong-axes column/row layout (bushing/make/serial_number/
    # year_of_manufacture columns, R/Y/B default_rows).
    for section in template_data["sections"]:
        title = section.get("title", "")
        if not title.endswith("kV Bushing Details"):
            continue
        tier = title.split(" ", 1)[0]
        if tier not in _ALL_TIERS:
            continue
        target_field = _details_field(tier)
        fields = section.get("fields", [])
        if fields != [target_field]:
            section["fields"] = [target_field]
            changed = True

    return changed


def apply_fix(template_data: dict) -> bool:
    """Mutate template_data in place. Returns True if anything changed."""
    changed = False

    # Retired section removal happens first since it changes the list a
    # later section-index-based edit would otherwise be iterating over.
    sections = template_data.get("sections", [])
    kept_sections = [s for s in sections if s.get("title") not in _REMOVED_SECTION_TITLES]
    if len(kept_sections) != len(sections):
        template_data["sections"] = kept_sections
        changed = True

    if _fix_details_sections(template_data):
        changed = True

    for section in template_data.get("sections", []):
        tier = _test_results_tier(section) or (
            section.get("title", "").split(" ", 1)[0]
            if section.get("title", "").endswith("kV Bushing Details")
            and section.get("title", "").split(" ", 1)[0] in _ALL_TIERS
            else None
        )

        if tier and section.get("visibility_rule") != _TIER_RULES[tier]:
            section["visibility_rule"] = _TIER_RULES[tier]
            changed = True

        # Retired "Previous Test Date" fields (all six).
        fields = section.get("fields", [])
        kept_fields = [f for f in fields if f.get("key") not in _REMOVED_FIELD_KEYS]
        if len(kept_fields) != len(fields):
            section["fields"] = kept_fields
            changed = True

        for field in section.get("fields", []):
            # Retired manual-entry "previous test" columns on any table field.
            if field.get("type") == "table":
                cols = field.get("columns", [])
                kept_cols = [c for c in cols if c.get("key") not in _REMOVED_COLUMN_KEYS]
                if len(kept_cols) != len(cols):
                    field["columns"] = kept_cols
                    changed = True

            # tr_analysis_moisture / tr_analysis_oil: dropdown -> auto-
            # computed THRESHOLD rule. Also realign table_evaluation's
            # oil_conductivity_psm bands to match (see _IDAX_OIL_EVALUATION).
            if field.get("key") == "idax_test_results":
                cols = field.get("columns", [])
                for i, col in enumerate(cols):
                    target = _IDAX_ANALYSIS_COLUMNS.get(col.get("key", ""))
                    if target and col != target:
                        cols[i] = dict(target)
                        changed = True

                col_evals = (field.get("table_evaluation") or {}).get("column_evaluations")
                if col_evals is not None and col_evals.get("oil_conductivity_psm") != _IDAX_OIL_EVALUATION:
                    col_evals["oil_conductivity_psm"] = dict(_IDAX_OIL_EVALUATION)
                    changed = True

            # Same family-scoped row set applies to both winding_test_results
            # and idax_test_results - they test the same electrode
            # combinations, just different measurements.
            if field.get("key") not in ("winding_test_results", "idax_test_results"):
                continue
            if field.get("default_rows") != _WINDING_ROWS:
                field["default_rows"] = [dict(r) for r in _WINDING_ROWS]
                changed = True

    return changed


def run_fix(dry_run: bool):
    db = VendorSessionLocal()
    try:
        rows = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == TEMPLATE_KEY)
            .all()
        )
        changed = []

        for row in rows:
            td = row.template_data or {}
            if apply_fix(td):
                changed.append((row.template_key, row.org_id))
                if not dry_run:
                    flag_modified(row, "template_data")

        print(f"{'[DRY RUN] ' if dry_run else ''}Rows to fix: {len(changed)} (of {len(rows)} total for {TEMPLATE_KEY})")
        for template_key, org_id in changed:
            print(f"  {template_key} | org_id={org_id}")

        if not dry_run:
            db.commit()
            print("Fix committed.")
        else:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_fix(dry_run=args.dry_run)
