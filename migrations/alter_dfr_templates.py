"""
alter_dfr_templates.py
──────────────────────
Updates existing DFR test template records in org_test_templates:
  1. Removes "IDAX" from template names, descriptions, and section titles
  2. Adds "Measurement Mode" dropdown (GST/UST/GSTg) as first column
     in dfr_measurements table
  3. Adds visibility_rule on TV rows (LV-TV, TV-GND, TV-HV) in the
     DFR Analysis Results table — hidden when transformer_type != "Three Winding"
  4. Adds transformer_type dropdown + hv/lv/tv_voltage_kv fields to
     dfr_routine Test Conditions (tv_voltage_kv has visibility rule)

Usage:
    python migrations/alter_dfr_templates.py           # dry run
    python migrations/alter_dfr_templates.py --apply   # apply changes
"""

import argparse
import copy
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from sqlalchemy import text

# ── Constants ────────────────────────────────────────────────────────────────

MEASUREMENT_MODE_COLUMN = {
    "key": "measurement_mode",
    "label": "Measurement Mode",
    "type": "dropdown",
    "options": ["GST", "UST", "GSTg"],
}

TV_VISIBILITY = {
    "type": "COMPARE",
    "config": {"field": "voltage_ratio", "operator": "in", "values": ["400", "220", "230"]},
}

TV_CONFIGURATIONS = {"LV-TV", "TV-GND", "TV-HV"}

DFR_REMEDIAL_TEXT = (
    "Tan delta above the acceptable limit (normal ≤ 0.5%, critical above 1.0%) — "
    "investigate insulation moisture/aging; consider oil reconditioning or drying."
)

VOLTAGE_RATIO_FIELD = {"key": "voltage_ratio", "label": "Voltage Ratio", "type": "readonly"}
HV_FIELD  = {"key": "hv_voltage_kv", "label": "HV Voltage",       "type": "number", "unit": "kV", "required": True}
LV_FIELD  = {"key": "lv_voltage_kv", "label": "LV Voltage",       "type": "number", "unit": "kV", "required": True}
TV_FIELD  = {
    "key": "tv_voltage_kv", "label": "Tertiary Voltage", "type": "number", "unit": "kV",
    "visibility_rule": TV_VISIBILITY,
}

NAME_REPLACEMENTS = [
    ("Dielectric Frequency Response (DFR / IDAX)", "Dielectric Frequency Response (DFR)"),
    ("DFR / IDAX insulation diagnostics", "DFR insulation diagnostics"),
    ("IDAX Analysis Results", "DFR Analysis Results"),
]


def clean_text(val: str) -> str:
    for old, new in NAME_REPLACEMENTS:
        val = val.replace(old, new)
    return val


def has_column(columns: list, key: str) -> bool:
    return any(c.get("key") == key for c in columns)


def has_field(fields: list, key: str) -> bool:
    return any(f.get("key") == key for f in fields)


def patch_template(tmpl: dict) -> tuple[dict, list[str]]:
    changes = []
    patched = copy.deepcopy(tmpl)
    tmpl_key = patched.get("key", "")
    is_routine = tmpl_key == "dfr_routine"
    is_dfr = "dfr" in tmpl_key
    is_sfra = "sfra" in tmpl_key

    # 0. Add / merge context_bindings
    bindings = patched.setdefault("context_bindings", {})
    if "hv_voltage_kv" not in bindings:
        bindings["hv_voltage_kv"] = "equipment.voltage_class"
        changes.append("context_bindings: hv_voltage_kv -> equipment.voltage_class")
    if "voltage_ratio" not in bindings:
        bindings["voltage_ratio"] = "equipment.voltage_class"
        changes.append("context_bindings: voltage_ratio -> equipment.voltage_class")
    if not is_routine:
        if "manufacturer" not in bindings:
            bindings["manufacturer"] = "equipment.manufacturer"
        if "serial_number" not in bindings:
            bindings["serial_number"] = "equipment.factory_serial_number"

    # 1. Fix name / description
    for attr in ("name", "description"):
        orig = patched.get(attr, "")
        new = clean_text(orig)
        if new != orig:
            patched[attr] = new
            changes.append(f"{attr}: removed IDAX reference")

    for section in patched.get("sections", []):
        # 2. Fix section title
        orig_title = section.get("title", "")
        new_title = clean_text(orig_title)
        if new_title != orig_title:
            section["title"] = new_title
            changes.append(f"section '{orig_title}' -> '{new_title}'")

        # 4c. Replace transformer_type dropdown with voltage_ratio readonly in Transformer Configuration
        if section.get("title") == "Transformer Configuration":
            sec_fields = section.get("fields", [])
            orig_len = len(sec_fields)
            sec_fields = [f for f in sec_fields if f.get("key") != "transformer_type"]
            if len(sec_fields) < orig_len:
                changes.append("Transformer Configuration: removed 'Transformer Type' dropdown")
            section["fields"] = sec_fields
            # Update tv_voltage_kv visibility rule if present
            for f in sec_fields:
                if f.get("key") == "tv_voltage_kv":
                    f["visibility_rule"] = copy.deepcopy(TV_VISIBILITY)
                    changes.append("Transformer Configuration: updated tv_voltage_kv visibility rule")

        # Add voltage_ratio to Equipment Details
        if section.get("title") == "Equipment Details":
            eq_fields = section.get("fields", [])
            if not has_field(eq_fields, "voltage_ratio"):
                eq_fields.append(copy.deepcopy(VOLTAGE_RATIO_FIELD))
                changes.append("Equipment Details: added 'Voltage Ratio' readonly field")

        for field in section.get("fields", []):
            # 2b. Sweep tables opt out of parameter analytics (curve data,
            # rendered by Test Graphs; repeated row ids would collide on the
            # parameter_analytics unique constraint)
            if (field.get("key") in ("dfr_measurements", "sfra_measurements")
                    and field.get("type") == "table"
                    and not field.get("analytics_skip")):
                field["analytics_skip"] = True
                changes.append(f"{field['key']}: set analytics_skip = true")

            # 3. Add measurement_mode column to dfr_measurements table
            if field.get("key") == "dfr_measurements" and field.get("type") == "table":
                cols = field.get("columns", [])
                if not has_column(cols, "measurement_mode"):
                    field["columns"] = [copy.deepcopy(MEASUREMENT_MODE_COLUMN)] + cols
                    changes.append("dfr_measurements: added 'Measurement Mode' column")

                # 3b. Remedial guidance text on the static table_evaluation
                # (dfr_routine only — dfr_idax_transformer's dfr_measurements
                # uses cross_session_evaluation instead, which doesn't read
                # remedial_action_text)
                tbl_ev = field.get("table_evaluation")
                if tbl_ev and not tbl_ev.get("remedial_action_text"):
                    tbl_ev["remedial_action_text"] = DFR_REMEDIAL_TEXT
                    changes.append("dfr_measurements: added remedial_action_text")

                # 4a. Add visibility rules on TV rows (multi-session only)
                if not is_routine:
                    for row in field.get("default_rows", []):
                        if row.get("test_configuration") in TV_CONFIGURATIONS:
                            if "visibility_rule" not in row:
                                row["visibility_rule"] = copy.deepcopy(TV_VISIBILITY)
                                changes.append(f"dfr_measurements row '{row['test_configuration']}': added TV visibility rule")

            # 4b. Also patch DFR Analysis Results table TV rows (multi-session)
            if field.get("key") == "analysis_results" and field.get("type") == "table":
                for row in field.get("default_rows", []):
                    if row.get("test_configuration") in TV_CONFIGURATIONS:
                        if "visibility_rule" not in row:
                            row["visibility_rule"] = copy.deepcopy(TV_VISIBILITY)
                            changes.append(f"analysis_results row '{row['test_configuration']}': added TV visibility rule")

        # 5. Add voltage_ratio + voltage fields to dfr_routine Test Conditions
        if is_routine and section.get("title") == "Test Conditions":
            fields = section.get("fields", [])
            # Remove old transformer_type dropdown if present
            orig_len = len(fields)
            fields = [f for f in fields if f.get("key") != "transformer_type"]
            if len(fields) < orig_len:
                changes.append("Test Conditions: removed 'Transformer Type' dropdown")
            new_fields = []
            inserted = False
            for f in fields:
                new_fields.append(f)
                if f.get("key") == "test_kit" and not inserted:
                    if not has_field(fields, "voltage_ratio"):
                        new_fields.append(copy.deepcopy(VOLTAGE_RATIO_FIELD))
                        changes.append("Test Conditions: added 'Voltage Ratio' readonly field")
                    if not has_field(fields, "hv_voltage_kv"):
                        new_fields.append(copy.deepcopy(HV_FIELD))
                        changes.append("Test Conditions: added 'HV Voltage' field")
                    if not has_field(fields, "lv_voltage_kv"):
                        new_fields.append(copy.deepcopy(LV_FIELD))
                        changes.append("Test Conditions: added 'LV Voltage' field")
                    if not has_field(fields, "tv_voltage_kv"):
                        new_fields.append(copy.deepcopy(TV_FIELD))
                        changes.append("Test Conditions: added 'Tertiary Voltage' field (Three Winding only)")
                    inserted = True
            section["fields"] = new_fields

    return patched, changes


def main(apply: bool):
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, template_key, template_data
            FROM org_test_templates
            WHERE
                template_key ILIKE '%dfr%'
                OR template_key ILIKE '%sfra%'
                OR template_data->>'name' ILIKE '%DFR%'
                OR template_data->>'name' ILIKE '%IDAX%'
                OR template_data->>'name' ILIKE '%Dielectric Frequency%'
                OR template_data->>'name' ILIKE '%SFRA%'
                OR template_data->>'name' ILIKE '%Sweep Frequency%'
        """)).fetchall()

        if not rows:
            print("No DFR template rows found in org_test_templates.")
            return

        print(f"Found {len(rows)} DFR template row(s)\n")
        total_updated = 0

        for row_id, template_key, tmpl_data in rows:
            if not isinstance(tmpl_data, dict):
                print(f"  SKIP  id={row_id} '{template_key}' — template_data is not a dict")
                continue

            patched, changes = patch_template(tmpl_data)

            if not changes:
                print(f"  OK    id={row_id} '{template_key}' — no changes needed")
                continue

            print(f"  {'SET ' if apply else 'DRY'} id={row_id} '{template_key}'")
            for c in changes:
                print(f"         - {c}")

            if apply:
                db.execute(
                    text("UPDATE org_test_templates SET template_data = :d WHERE id = :id"),
                    {"d": json.dumps(patched), "id": row_id},
                )
                total_updated += 1

        if apply:
            db.commit()
            print(f"\nDone. Updated {total_updated} row(s).")
        else:
            print(f"\nDry run complete. Re-run with --apply to commit changes.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()
    main(apply=args.apply)
