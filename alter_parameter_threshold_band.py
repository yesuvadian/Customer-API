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


def _worst_of_bands_rows(template_key: str, fields_cfg: dict, labels_cfg: dict) -> list[dict]:
    """WORST_OF_BANDS rule shape (e.g. sfra_transformer/sfra_routine's
    "Correlation Coefficient Analysis" table): {field_key: {normal_min,
    alert_min}}, one cutoff pair PER COLUMN (frequency band) — every row
    (winding pair) shares the same cutoff, unlike THRESHOLD-style tables
    (Acidity, DGA) where the cutoff varies PER ROW instead. So
    parameter_key here is the COLUMN key (e.g. "cc_mf"), not a row id —
    routers/analytics.py's breach-forecast lookup tries the row id first
    (matching THRESHOLD-style tables) and falls back to the column key
    (matching this shape) via _table_column_key.

    Synthesizes 3 bands per field from the 2 configured cutoffs, open-
    ended at both true extremes (no upper cap on the good side, no lower
    floor on the bad side) — same "None = open-ended" convention already
    used for THRESHOLD-style bands' own worst band.
    """
    rows: list[dict] = []
    label_normal = labels_cfg.get("NORMAL", "Normal")
    label_alert = labels_cfg.get("ALERT", "Alert")
    label_critical = labels_cfg.get("CRITICAL", "Critical")
    for field_key, cutoffs in fields_cfg.items():
        if not isinstance(cutoffs, dict):
            continue
        normal_min = cutoffs.get("normal_min")
        alert_min = cutoffs.get("alert_min")
        if normal_min is None or alert_min is None:
            continue
        rows.append(dict(
            template_key=template_key, parameter_key=field_key,
            context_key=None, band_label=label_normal,
            lower_bound=normal_min, upper_bound=None,
        ))
        rows.append(dict(
            template_key=template_key, parameter_key=field_key,
            context_key=None, band_label=label_alert,
            lower_bound=alert_min, upper_bound=normal_min,
        ))
        rows.append(dict(
            template_key=template_key, parameter_key=field_key,
            context_key=None, band_label=label_critical,
            lower_bound=None, upper_bound=alert_min,
        ))
    return rows


def _column_evaluation_rows(template_key: str, column_evaluations: dict) -> list[dict]:
    """table_evaluation.column_evaluations shape (e.g. tan_delta_winding's
    winding_test_results.df_corrected_20c, capacitance_tandelta_transformer's
    various bushing/IDAX columns): {column_key: {normal_min, normal_max,
    alert_min, alert_max, critical_below, critical_above, ...}} — the
    evaluation config services/evaluation_service.py's _classify_number
    already reads at submission time to grade a cell NORMAL/ALERT/CRITICAL.

    Unlike WORST_OF_BANDS (routers/analytics.py's rule.type check), a
    calculated column using this shape often carries no `rule` key at all
    (it's typically a plain FORMULA/read-only cell) — so _extract_bands's
    rule.type=="THRESHOLD"/"WORST_OF_BANDS" walk over columns[*].rule never
    sees it, and no ParameterThresholdBand row is ever produced. Confirmed
    live: tan_delta_winding's df_corrected_20c has real normal_max/
    critical_above cutoffs here but no rule dict, so its Deterioration
    Watch card was permanently stuck on plain "Trending" with no breach
    forecast, no matter how many times this script was rerun.

    Cutoffs can point either direction (SFRA's cc_mf: normal_min/alert_min,
    lower is bad; tan_delta's df_corrected_20c: normal_max/critical_above,
    higher is bad) — both directions collapse into the same 3-band
    {Normal, Alert, Critical} shape _next_worse_boundary already knows how
    to walk in either direction, using whichever bound side is actually
    set. Same column_key-as-parameter_key convention as
    _worst_of_bands_rows (cutoff is shared across every row of the table,
    e.g. every winding/bushing configuration), and
    routers/analytics.py's _table_column_key fallback lookup already
    expects exactly this.
    """
    rows: list[dict] = []
    for column_key, cfg in column_evaluations.items():
        if not isinstance(cfg, dict):
            continue
        normal_min = cfg.get("normal_min")
        normal_max = cfg.get("normal_max")
        alert_min = cfg.get("alert_min")
        alert_max = cfg.get("alert_max")
        critical_below = cfg.get("critical_below")
        critical_above = cfg.get("critical_above")

        # "Lower is bad" direction: normal_min set (optionally alert_min,
        # critical_below). Mirrors _worst_of_bands_rows's own shape.
        if normal_min is not None:
            alert_lo = alert_min if alert_min is not None else critical_below
            rows.append(dict(
                template_key=template_key, parameter_key=column_key,
                context_key=None, band_label="Normal",
                lower_bound=normal_min, upper_bound=None,
            ))
            if alert_lo is not None:
                rows.append(dict(
                    template_key=template_key, parameter_key=column_key,
                    context_key=None, band_label="Alert",
                    lower_bound=alert_lo, upper_bound=normal_min,
                ))
                rows.append(dict(
                    template_key=template_key, parameter_key=column_key,
                    context_key=None, band_label="Critical",
                    lower_bound=None, upper_bound=alert_lo,
                ))
        # "Higher is bad" direction: normal_max set (optionally alert_max,
        # critical_above) — tan_delta/IDAX moisture's own shape.
        elif normal_max is not None:
            alert_hi = alert_max if alert_max is not None else critical_above
            rows.append(dict(
                template_key=template_key, parameter_key=column_key,
                context_key=None, band_label="Normal",
                lower_bound=None, upper_bound=normal_max,
            ))
            if alert_hi is not None:
                rows.append(dict(
                    template_key=template_key, parameter_key=column_key,
                    context_key=None, band_label="Alert",
                    lower_bound=normal_max, upper_bound=alert_hi,
                ))
                rows.append(dict(
                    template_key=template_key, parameter_key=column_key,
                    context_key=None, band_label="Critical",
                    lower_bound=alert_hi, upper_bound=None,
                ))
    return rows


def _table_row_ids(field: dict) -> list[str]:
    """Row identifiers for a table field's default_rows — same id-column
    detection services/analytics_engine.py's history builder uses at
    runtime (first column of type text/dropdown/readonly, excluding
    unit/remarks/formula) — so a row id extracted here matches the row id
    routers/analytics.py's _table_row_id() later pulls back out of
    ParameterAnalytics.parameter_key's "{table_field_key}.{row_id}.
    {column_key}" composite. Returns [] when there's no default_rows or
    no such column.
    """
    default_rows = field.get("default_rows") or []
    if not default_rows:
        return []
    id_col = next(
        (c.get("key") for c in field.get("columns", [])
         if c.get("type") in ("text", "dropdown", "readonly")
         and c.get("key") not in ("unit", "remarks", "formula")),
        None,
    )
    if not id_col:
        return []
    return [str(r[id_col]) for r in default_rows if isinstance(r, dict) and r.get(id_col)]


def _extract_bands(template_key: str, template_def: dict) -> list[dict]:
    """Walk one template's sections/fields/columns for THRESHOLD- or
    WORST_OF_BANDS-rule table fields and flatten their thresholds config
    into rows. THRESHOLD handles both shapes _eval_threshold_table itself
    handles: flat ({band: [lo,hi]}) and two-level ({context_key: {band:
    [lo,hi]}}). WORST_OF_BANDS is a different, column-keyed shape — see
    _worst_of_bands_rows's docstring.

    A third source, table_evaluation.column_evaluations, is walked
    separately per field below (not per-column like the other two) since
    it lives at the field level, not on any one column's rule — see
    _column_evaluation_rows's docstring for why that shape was being
    missed entirely before.
    """
    rows: list[dict] = []
    rule_covered_columns: set[str] = set()
    for section in template_def.get("sections", []):
        for field in section.get("fields", []):
            if field.get("type") != "table":
                continue
            for col in field.get("columns", []):
                rule = col.get("rule") or {}
                rule_type = rule.get("type")
                if col.get("type") != "calculated":
                    continue
                if rule_type == "WORST_OF_BANDS":
                    config = rule.get("config") or {}
                    rule_covered_columns.update((config.get("fields") or {}).keys())
                    rows.extend(_worst_of_bands_rows(
                        template_key, config.get("fields") or {}, config.get("labels") or {}))
                    continue
                if rule_type != "THRESHOLD":
                    continue
                rule_covered_columns.add(col.get("key"))
                thresholds = (rule.get("config") or {}).get("thresholds") or {}
                for parameter_key, row_val in thresholds.items():
                    if not isinstance(row_val, dict) or not row_val:
                        continue
                    first_val = next(iter(row_val.values()))
                    if isinstance(first_val, list):
                        # Flat: {band_label: [lo, hi]}. The outer key
                        # (parameter_key here) is sometimes a real row id
                        # (matches a THRESHOLD table like Acidity/DGA
                        # where the cutoff genuinely varies per row) and
                        # sometimes just a descriptive standard name meant
                        # to apply uniformly to every row of the table
                        # (confirmed live: tan_delta_capacitance_idax's
                        # winding_test_results table has ONE key, "Winding
                        # % D.F @ 20°C (IEEE/IEC)", covering all six
                        # HV-GND/HV-LV/.../TV-GND rows identically — same
                        # bushing tables) — a descriptive name never
                        # matches any row's real id, so extracting it
                        # verbatim produced bands the runtime breach-
                        # forecast lookup (routers/analytics.py's
                        # _real_breach_forecast, keyed by the actual row
                        # id) could never find, silently leaving every one
                        # of those rows stuck on "Trending" with no
                        # projected breach date. Detect that case by
                        # checking whether this outer key is actually one
                        # of the table's own row ids; if not, fan the same
                        # band definition out across every real row id
                        # instead of the fabricated one.
                        row_ids = _table_row_ids(field)
                        target_keys = (
                            row_ids if row_ids and parameter_key not in row_ids
                            else [parameter_key]
                        )
                        for band_label, bounds in row_val.items():
                            lo, hi = (list(bounds) + [None, None])[:2]
                            for pk in target_keys:
                                rows.append(dict(
                                    template_key=template_key, parameter_key=pk,
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

            col_evals = ((field.get("table_evaluation") or {}).get("column_evaluations")) or {}
            # Skip columns already covered by an explicit rule above — a
            # WORST_OF_BANDS/THRESHOLD rule and its own table_evaluation
            # entry are meant as the same cutoffs stated twice (e.g. SFRA's
            # cc_mf), never two independent configs; not skipping would
            # just re-insert the identical band values a second time.
            col_evals = {
                k: v for k, v in col_evals.items() if k not in rule_covered_columns
            }
            if col_evals:
                rows.extend(_column_evaluation_rows(template_key, col_evals))
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
