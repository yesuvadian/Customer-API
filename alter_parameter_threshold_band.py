#!/usr/bin/env python3
"""
One-time setup: create the parameter_threshold_bands table (via the
ParameterThresholdBand model in models.py) and populate it by extracting
every table-row THRESHOLD rule config already defined in test_templates.py
(TEST_TEMPLATES) — transformer_oil_test's Acidity/Resistivity/etc bands,
transformer_dga's per-gas IS/IEC bands, and any other template with a table
field whose calculated column uses rule.type == "THRESHOLD".

This is an ETL/projection, not a new classification: every bound extracted
here is exactly what's already in test_templates.py's own thresholds
config (the same one services/evaluation_service.py's _eval_threshold_table
already parses at test-submission time) — just flattened into queryable
rows so breach-proximity forecasting doesn't have to re-parse nested JSON
per request. The template config stays authoritative; re-run this script
after editing a template's thresholds to refresh the projection (it
replaces existing rows for a (template_key, parameter_key) pair rather
than accumulating duplicates, so a corrected bound in the template
actually takes effect here too).

Usage:
    python alter_parameter_threshold_band.py
"""
from database import VendorSessionLocal
from models import Base, ParameterThresholdBand
from test_templates import TEST_TEMPLATES


def _extract_bands(template_key: str, template_def: dict) -> list[dict]:
    """Walk one template's sections/fields/columns for THRESHOLD-rule table
    fields and flatten their thresholds config into rows. Handles both
    shapes _eval_threshold_table itself handles: flat ({band: [lo,hi]})
    and two-level ({context_key: {band: [lo,hi]}}).
    """
    rows: list[dict] = []
    for section in template_def.get("sections", []):
        for field in section.get("fields", []):
            if field.get("type") != "table":
                continue
            for col in field.get("columns", []):
                rule = col.get("rule") or {}
                if col.get("type") != "calculated" or rule.get("type") != "THRESHOLD":
                    continue
                thresholds = (rule.get("config") or {}).get("thresholds") or {}
                for parameter_key, row_val in thresholds.items():
                    if not isinstance(row_val, dict) or not row_val:
                        continue
                    first_val = next(iter(row_val.values()))
                    if isinstance(first_val, list):
                        # Flat: {band_label: [lo, hi]}
                        for band_label, bounds in row_val.items():
                            lo, hi = (list(bounds) + [None, None])[:2]
                            rows.append(dict(
                                template_key=template_key, parameter_key=parameter_key,
                                context_key=None, band_label=band_label,
                                lower_bound=lo, upper_bound=hi,
                            ))
                    elif isinstance(first_val, dict):
                        # Two-level: {context_key: {band_label: [lo, hi]}}
                        for context_key, bands in row_val.items():
                            if not isinstance(bands, dict):
                                continue
                            for band_label, bounds in bands.items():
                                if not isinstance(bounds, (list, tuple)):
                                    continue
                                lo, hi = (list(bounds) + [None, None])[:2]
                                rows.append(dict(
                                    template_key=template_key, parameter_key=parameter_key,
                                    context_key=context_key, band_label=band_label,
                                    lower_bound=lo, upper_bound=hi,
                                ))
    return rows


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[ParameterThresholdBand.__table__],
    )
    print("Ensured parameter_threshold_bands table exists.")

    all_rows: list[dict] = []
    template_count = 0
    for template_key, template_def in TEST_TEMPLATES.items():
        if not isinstance(template_def, dict):
            continue
        extracted = _extract_bands(template_key, template_def)
        if extracted:
            template_count += 1
            all_rows.extend(extracted)

    db = VendorSessionLocal()
    try:
        inserted = updated = 0
        for row in all_rows:
            existing = (
                db.query(ParameterThresholdBand)
                .filter(
                    ParameterThresholdBand.template_key == row["template_key"],
                    ParameterThresholdBand.parameter_key == row["parameter_key"],
                    ParameterThresholdBand.context_key == row["context_key"],
                    ParameterThresholdBand.band_label == row["band_label"],
                )
                .first()
            )
            if existing:
                existing.lower_bound = row["lower_bound"]
                existing.upper_bound = row["upper_bound"]
                updated += 1
            else:
                db.add(ParameterThresholdBand(**row))
                inserted += 1

        db.commit()
        print(f"Extracted from {template_count} template(s): "
              f"{inserted} band row(s) inserted, {updated} refreshed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
