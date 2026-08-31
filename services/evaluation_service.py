"""
Automated Test Result Evaluation Service
=========================================
Compares JSONB test_data values against per-field evaluation criteria
embedded in OrgTestTemplate field definitions.

Field evaluation schemas:

1. NUMBER field (evaluation):
    {
        "enabled": true,
        "normal_min": 1000, "normal_max": null,
        "alert_min": 100, "alert_max": null,
        "critical_below": 50, "critical_above": null,
        "revised_interval_days": 90,
        "trend_watch": true,
        "remedial_action_text": "...",
        "suggested_products": [...]
    }

2. TABLE field (table_evaluation):
    {
        "enabled": true,
        "aggregate_type": "sum" | "average" | "count" | "max" | "min",
        "aggregate_column": "operations_count",
        "aggregate_threshold": 10000,
        "threshold_condition": "gte" | "gt" | "lte" | "lt",
        "remedial_action_text": "...",
        "suggested_products": [...],
        "column_evaluations": {
            "pickup_current": {"normal_min": 4.8, "critical_below": 4.0},
            ...
        }
    }

3. DROPDOWN/RADIO field (dropdown_evaluation):
    {
        "enabled": true,
        "value_severities": {
            "Good": "NORMAL",
            "Fair": "ALERT",
            "Poor": "CRITICAL",
            "Failed": "CRITICAL"
        },
        "remedial_action_text": "..."
    }

4. DATE field (date_evaluation):
    {
        "enabled": true,
        "warning_days_before": 30,
        "alert_days_before": 15,
        "critical_when_overdue": true,
        "remedial_action_text": "..."
    }

Status priority: CRITICAL > ALERT > NORMAL
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session


# ─── Status constants ──────────────────────────────────────────────────────────
NORMAL   = "NORMAL"
ALERT    = "ALERT"
CRITICAL = "CRITICAL"

_STATUS_RANK = {NORMAL: 0, ALERT: 1, CRITICAL: 2}


class EvaluationService:
    """Stateless service — all methods are static."""

    # ─── Core evaluation ──────────────────────────────────────────────────────

    @staticmethod
    def evaluate_test_data(template_data: dict, test_data: dict) -> dict:
        """
        Walk every field in *template_data* that has evaluation enabled,
        read its value from *test_data*, compare against criteria, and return:

            {
                "overall": "NORMAL" | "ALERT" | "CRITICAL",
                "evaluated_at": "<ISO-8601>",
                "fields": [
                    {
                        "key": "ir_hv_to_earth_mohm",
                        "label": "IR — HV to Earth",
                        "type": "number",
                        "value": 85.0,
                        "unit": "MOhm",
                        "status": "CRITICAL",
                        "thresholds": { ... },
                        "trend_watch": true,
                        "remedial_action_text": "...",
                        "suggested_products": [...],
                        "revised_interval_days": null
                    },
                    ...
                ]
            }

        Supports: number, table, dropdown/radio, date field evaluations.
        """
        field_results: list[dict] = []
        overall_rank = 0  # 0=NORMAL, 1=ALERT, 2=CRITICAL

        for section in template_data.get("sections", []):
            for field in section.get("fields", []):
                field_type = field.get("type", "text")

                # Route to appropriate evaluator
                result = None
                if field_type == "number":
                    result = EvaluationService._eval_number_field(field, test_data)
                elif field_type == "table":
                    # Try standard table_evaluation first; fall back to
                    # rule-based THRESHOLD calculated-column evaluation.
                    result = EvaluationService._eval_table_field(field, test_data)
                    if result is None:
                        result = EvaluationService._eval_threshold_table(field, test_data)
                elif field_type in ("dropdown", "radio", "readonly"):
                    result = EvaluationService._eval_dropdown_field(field, test_data)
                elif field_type == "date":
                    result = EvaluationService._eval_date_field(field, test_data)

                if result:
                    rank = _STATUS_RANK.get(result.get("status"), 0)
                    if rank > overall_rank:
                        overall_rank = rank
                    field_results.append(result)

        overall_labels = [NORMAL, ALERT, CRITICAL]
        return {
            "overall": overall_labels[overall_rank],
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "fields": field_results,
        }

    # ─── Field-type specific evaluators ──────────────────────────────────────

    @staticmethod
    def _eval_number_field(field: dict, test_data: dict) -> Optional[dict]:
        """Evaluate a numeric field against thresholds."""
        ev = field.get("evaluation")
        if not ev or not ev.get("enabled"):
            return None

        key = field.get("key")
        raw = test_data.get(key)
        if raw is None or raw == "":
            return None

        try:
            value = float(raw)
        except (ValueError, TypeError):
            return None

        status = EvaluationService._classify_number(value, ev)
        return {
            "key": key,
            "label": field.get("label", key),
            "type": "number",
            "value": value,
            "unit": field.get("unit"),
            "status": status,
            "thresholds": {
                "normal_min": _f(ev.get("normal_min")),
                "normal_max": _f(ev.get("normal_max")),
                "alert_min": _f(ev.get("alert_min")),
                "alert_max": _f(ev.get("alert_max")),
                "critical_below": _f(ev.get("critical_below")),
                "critical_above": _f(ev.get("critical_above")),
            },
            "trend_watch": bool(ev.get("trend_watch", False)),
            "remedial_action_text": ev.get("remedial_action_text")
                if status in (ALERT, CRITICAL) else None,
            "suggested_products": ev.get("suggested_products") or []
                if status in (ALERT, CRITICAL) else [],
            "revised_interval_days": int(ev["revised_interval_days"])
                if status == ALERT and ev.get("revised_interval_days") is not None
                else None,
        }

    @staticmethod
    def _eval_table_field(field: dict, test_data: dict) -> Optional[dict]:
        """
        Evaluate a table field using any combination of:
          • table_evaluation.column_evaluations  — numeric threshold per column
          • table_evaluation aggregate rules     — aggregate threshold
          • column_evaluation on column def      — dropdown severity map per column
                                                   (template-driven, no table_evaluation
                                                    block required for this path)
        """
        ev = field.get("table_evaluation") or {}
        table_ev_enabled = bool(ev.get("enabled"))

        # Also fire when any column carries a dropdown column_evaluation map
        has_col_ev = any(
            col.get("column_evaluation")
            for col in field.get("columns", [])
            if col.get("type") in ("dropdown", "radio")
        )

        if not table_ev_enabled and not has_col_ev:
            return None

        key = field.get("key")
        table_data = test_data.get(key)
        if not isinstance(table_data, list) or not table_data:
            return None

        agg_status = NORMAL
        agg_result = None
        col_results: list[dict] = []

        # Find the first readonly/text/dropdown column to use as row label -
        # dropdown counts too (e.g. DFR's "measurement_mode": GST/UST/GSTg),
        # not just readonly/text, or such tables fall back to meaningless
        # "Row 1"/"Row 2" labels in critical findings.
        _label_col = next(
            (c.get("key") for c in field.get("columns", [])
             if c.get("type") in ("readonly", "text", "dropdown") and c.get("key")),
            None,
        )

        def _row_label_for(row: dict, row_idx: int) -> str:
            base = (row.get(_label_col) if _label_col else None) or f"Row {row_idx + 1}"
            # When the label column repeats across rows (e.g. every GST row
            # is just "GST"), append the frequency so each finding is still
            # individually identifiable instead of merging into one label.
            freq = row.get("frequency_hz")
            if freq not in (None, "") and _label_col != "frequency_hz":
                base = f"{base} @ {freq}Hz"
            return base

        if table_ev_enabled:
            # Aggregate evaluation
            if ev.get("aggregate_type") and ev.get("aggregate_column"):
                agg_status, agg_result = EvaluationService._eval_table_aggregate(
                    table_data, ev
                )

            # Numeric per-column evaluation
            for col_key, col_ev in (ev.get("column_evaluations") or {}).items():
                for row_idx, row in enumerate(table_data):
                    val = row.get(col_key)
                    if val is None:
                        continue
                    try:
                        num_val = float(val)
                        col_status, col_breach_limit = EvaluationService._classify_number_with_limit(num_val, col_ev)
                        _row_label = _row_label_for(row, row_idx)
                        col_results.append({
                            "column":       col_key,
                            "row":          row_idx,
                            "row_label":    _row_label,
                            "value":        num_val,
                            "status":       col_status,
                            "breach_limit": col_breach_limit,
                            "remedial_action_text": col_ev.get("remedial_action_text")
                                if col_status in (ALERT, CRITICAL) else None,
                        })
                        if _STATUS_RANK[col_status] > _STATUS_RANK[agg_status]:
                            agg_status = col_status
                    except (ValueError, TypeError):
                        continue

        # Dropdown per-column evaluation — reads column_evaluation from column defs
        if has_col_ev:
            for col in field.get("columns", []):
                if col.get("type") not in ("dropdown", "radio"):
                    continue
                col_ev = col.get("column_evaluation")
                if not col_ev:
                    continue
                col_key = col.get("key")
                for row_idx, row in enumerate(table_data):
                    val = row.get(col_key)
                    if val is None:
                        continue
                    col_status = col_ev.get(str(val), NORMAL)
                    _row_label = _row_label_for(row, row_idx)
                    col_results.append({
                        "column":    col_key,
                        "row":       row_idx,
                        "row_label": _row_label,
                        "value":     val,
                        "status":    col_status,
                    })
                    if _STATUS_RANK.get(col_status, 0) > _STATUS_RANK[agg_status]:
                        agg_status = col_status

        # If no cells were evaluatable (all blank), treat the section as unentered
        if not col_results and agg_result is None:
            return None

        return {
            "key": key,
            "label": field.get("label", key),
            "type": "table",
            "status": agg_status,
            "aggregate_result": agg_result,
            "column_results": col_results,
            "remedial_action_text": ev.get("remedial_action_text")
                if agg_status in (ALERT, CRITICAL) else None,
            "suggested_products": ev.get("suggested_products") or []
                if agg_status in (ALERT, CRITICAL) else [],
        }

    @staticmethod
    def _eval_threshold_table(field: dict, test_data: dict) -> Optional[dict]:
        """
        Generic evaluator for table fields whose condition column uses
        rule.type == "THRESHOLD".

        Algorithm (fully template-driven):
          1. Find the first column with type="calculated" and rule.type="THRESHOLD".
          2. Read config: input_field, lookup_fields, thresholds.
          3. lookup_fields is a list where:
               - plain strings  → column key in each row  (row-identifier, e.g. "gas")
               - dicts          → {"field": "$form.<key>", "mapping": {...}}
                                   resolve $form.<key> from test_data and map through
                                   the provided mapping to get the sub-key used to
                                   narrow the threshold table (e.g. standard name,
                                   voltage band).
          4. thresholds structure:
               { row_id: { sub_key: { band_name: [lo, hi], ... }, ... } }
             OR flat (no sub_key level):
               { row_id: { band_name: [lo, hi], ... } }
          5. For each table row: read value from input_field, look up the band,
             map to NORMAL / ALERT / CRITICAL.
        """
        key = field.get("key")
        table_data = test_data.get(key)
        if not isinstance(table_data, list) or not table_data:
            return None

        # 1. Find the THRESHOLD calculated column
        threshold_col = None
        for col in field.get("columns", []):
            rule = col.get("rule") or {}
            if col.get("type") == "calculated" and rule.get("type") == "THRESHOLD":
                threshold_col = col
                break
        if threshold_col is None:
            return None

        cfg           = threshold_col["rule"]["config"]
        input_field   = cfg.get("input_field")
        lookup_fields = cfg.get("lookup_fields", [])
        thresholds    = cfg.get("thresholds", {})
        # Optional: { row_id: "remedial text" }, e.g. per-gas DGA guidance -
        # keyed the same way as thresholds (row_id, case-insensitive).
        remedial_by_row = cfg.get("remedial_action_text", {})

        if not input_field or not thresholds:
            return None

        # 2. Parse lookup_fields:
        #    - row_id_key:  plain string → key inside each table row
        #    - sub_key:     resolved from $form.<field> via mapping dict
        #    - empty list   → global threshold, applies to all rows regardless of row identity
        row_id_key = None
        resolved_sub_key: Optional[str] = None

        for lf in lookup_fields:
            if isinstance(lf, str):
                if row_id_key is None:
                    row_id_key = lf
            elif isinstance(lf, dict):
                field_ref = lf.get("field", "")          # "$form.dga_standard"
                mapping   = lf.get("mapping") or {}
                if field_ref.startswith("$form."):
                    form_key = field_ref[len("$form."):]  # "dga_standard"
                    form_val = str(test_data.get(form_key, ""))
                    resolved_sub_key = mapping.get(form_val)  # e.g. "IS 10593:2017" or "<=72.5kV"

        # When lookup_fields is empty → global threshold; flatten first entry to bands
        global_bands: Optional[dict] = None
        if not row_id_key:
            if not thresholds:
                return None
            first_entry = next(iter(thresholds.values()))
            if isinstance(first_entry, dict):
                # Could be { band: [lo,hi] } or { sub_key: { band: [lo,hi] } }
                first_sub = next(iter(first_entry.values()), None)
                if isinstance(first_sub, list):
                    global_bands = first_entry   # flat: { band: [lo,hi] }
                elif isinstance(first_sub, dict):
                    # two-level: pick first sub-key
                    global_bands = first_sub
            if global_bands is None:
                return None

        # Band name → NORMAL / ALERT / CRITICAL (template bands are free-text)
        # Full band-name phrases checked first (e.g. "not ok" must resolve to
        # CRITICAL, not fall through to the "not" first-word default below).
        _cond_rank: dict = {
            "good": 0, "normal": 0, "pass": 0, "ok": 0,
            "fair": 1, "alert": 1, "warning": 1, "monitor": 1,
            "poor": 2, "critical": 2, "abnormal": 2, "fail": 2, "not ok": 2,
        }

        row_results: list = []
        worst_rank  = 0

        for row_idx, row in enumerate(table_data):
            raw_val = row.get(input_field)
            if raw_val is None:
                continue
            try:
                value = float(raw_val)
            except (ValueError, TypeError):
                continue

            if global_bands is not None:
                # Global-threshold path: same bands apply to every row
                bands = global_bands
                row_id = row_idx
            else:
                # Per-row lookup path
                row_id = row.get(row_id_key)
                if row_id is None:
                    continue

                # 3. Find threshold entry for this row_id
                row_thresholds = None
                for tkey, tval in thresholds.items():
                    if tkey.lower() == str(row_id).lower():
                        row_thresholds = tval
                        break
                if not row_thresholds:
                    continue

                # 4. Narrow to sub_key if the threshold is two-level (standard/band)
                # Detect structure by inspecting the first value:
                #   flat:      { band_name: [lo, hi] }      → first_val is a list
                #   two-level: { sub_key: { band: [lo,hi] } } → first_val is a dict
                first_val = next(iter(row_thresholds.values()), None) if row_thresholds else None
                if isinstance(first_val, list):
                    bands = row_thresholds          # flat: { band_name: [lo, hi] }
                else:
                    # Two-level: { sub_key: { band_name: [lo, hi] } }
                    if resolved_sub_key and resolved_sub_key in row_thresholds:
                        bands = row_thresholds[resolved_sub_key]
                    else:
                        # fallback: use first sub_key's bands
                        bands = first_val if isinstance(first_val, dict) else {}

            # 5. Find which band the value falls into.
            # Boundary rule (mirrors RuleEngine._threshold in rule_engine.dart —
            # keep both in sync):
            #   "<X"      -  strictly less than     -> upper edge EXCLUSIVE
            #   "X - Y"   -  inclusive both ends     -> BOTH edges INCLUSIVE
            #   ">Y"      -  strictly greater than   -> lower edge EXCLUSIVE
            # Position is determined by sorting on the numeric lower bound
            # (not band label / dict insertion order), so a value sitting
            # exactly on a shared boundary lands in the bounded "X - Y" band
            # rather than being pulled into the open-ended band next to it.
            numeric_bands = []
            for band_name, band_range in bands.items():
                if not isinstance(band_range, list) or len(band_range) < 2:
                    continue
                numeric_bands.append((band_name, band_range[0], band_range[1]))
            numeric_bands.sort(
                key=lambda b: b[1] if b[1] is not None else float("-inf")
            )

            def _band_rank(name: str) -> int:
                key = name.lower().strip()
                return _cond_rank.get(key, _cond_rank.get(key.split()[0], 0))

            band_ranks = [_band_rank(b[0]) for b in numeric_bands]

            row_status = NORMAL
            row_breach_limit = None
            for idx, (band_name, lo, hi) in enumerate(numeric_bands):
                is_first = idx == 0
                is_last = idx == len(numeric_bands) - 1
                last_exclusive = is_last and len(numeric_bands) > 2

                if lo is None:
                    min_ok = True
                elif last_exclusive:
                    min_ok = value > lo and not _epsilon_equals(value, lo)
                else:
                    min_ok = value > lo or _epsilon_equals(value, lo)

                if hi is None:
                    max_ok = True
                elif is_first:
                    max_ok = value < hi and not _epsilon_equals(value, hi)
                else:
                    max_ok = value < hi or _epsilon_equals(value, hi)

                if not (min_ok and max_ok):
                    continue

                rank = band_ranks[idx]
                row_status = [NORMAL, ALERT, CRITICAL][min(rank, 2)]
                # breach_limit: the boundary adjacent to a BETTER neighboring
                # band - direction depends on whether this parameter is
                # ascending-is-bad (e.g. DGA gases: better band is below,
                # so lo is the value crossed) or descending-is-bad (e.g.
                # oil BDV: better band is above, so hi is the value needed
                # to improve - using lo there would show a meaningless "0").
                if rank >= 1:
                    next_rank = band_ranks[idx + 1] if idx + 1 < len(band_ranks) else None
                    prev_rank = band_ranks[idx - 1] if idx > 0 else None
                    if next_rank is not None and next_rank < rank:
                        row_breach_limit = hi
                    elif prev_rank is not None and prev_rank < rank:
                        row_breach_limit = lo
                    else:
                        row_breach_limit = lo
                break

            rank = _STATUS_RANK.get(row_status, 0)
            if rank > worst_rank:
                worst_rank = rank

            remedial_text = None
            if row_status in (ALERT, CRITICAL):
                for rkey, rtext in remedial_by_row.items():
                    if rkey.lower() == str(row_id).lower():
                        remedial_text = rtext
                        break

            row_results.append({
                "row_id":       row_id,
                "value":        value,
                "unit":         row.get("unit"),
                "status":       row_status,
                "breach_limit": row_breach_limit,
                "remedial_action_text": remedial_text,
            })

        if not row_results:
            return None

        overall_status = [NORMAL, ALERT, CRITICAL][worst_rank]
        return {
            "key":            key,
            "label":          field.get("label", key),
            "type":           "table",
            "status":         overall_status,
            "row_results":    row_results,
            "aggregate_result": None,
            "column_results": [],
        }

    @staticmethod
    def _eval_table_aggregate(table_data: list, ev: dict) -> tuple[str, dict]:
        """
        Apply aggregate function (sum/avg/count/max/min) on target column,
        compare to threshold with condition (gte/gt/lte/lt).
        Returns (status, result_dict).
        """
        agg_type = ev.get("aggregate_type")
        agg_col = ev.get("aggregate_column")
        threshold = _f(ev.get("aggregate_threshold"))
        condition = ev.get("threshold_condition", "gte")

        # Extract numeric values from column
        values = []
        for row in table_data:
            val = row.get(agg_col)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    pass

        if not values:
            return NORMAL, {"aggregate_type": agg_type, "value": None}

        # Compute aggregate
        if agg_type == "sum":
            agg_val = sum(values)
        elif agg_type == "average":
            agg_val = sum(values) / len(values)
        elif agg_type == "count":
            agg_val = len(values)
        elif agg_type == "max":
            agg_val = max(values)
        elif agg_type == "min":
            agg_val = min(values)
        else:
            return NORMAL, {"aggregate_type": agg_type, "value": None}

        # Compare to threshold
        status = NORMAL
        if threshold is not None:
            if condition == "gte" and agg_val >= threshold:
                status = CRITICAL
            elif condition == "gt" and agg_val > threshold:
                status = CRITICAL
            elif condition == "lte" and agg_val <= threshold:
                status = CRITICAL
            elif condition == "lt" and agg_val < threshold:
                status = CRITICAL

        return status, {
            "aggregate_type": agg_type,
            "column": agg_col,
            "value": agg_val,
            "threshold": threshold,
            "condition": condition,
            "threshold_met": status == CRITICAL,
        }

    @staticmethod
    def _eval_dropdown_field(field: dict, test_data: dict) -> Optional[dict]:
        """Evaluate dropdown/radio field based on value-to-severity mapping."""
        ev = field.get("dropdown_evaluation")
        if not ev or not ev.get("enabled"):
            return None

        key = field.get("key")
        value = test_data.get(key)
        if not value:
            return None

        value_severities = ev.get("value_severities") or {}
        status = value_severities.get(str(value), NORMAL)

        return {
            "key": key,
            "label": field.get("label", key),
            "type": field.get("type"),
            "value": value,
            "status": status,
            "value_severities": value_severities,
            "remedial_action_text": ev.get("remedial_action_text")
                if status == CRITICAL else None,
        }

    @staticmethod
    def _eval_date_field(field: dict, test_data: dict) -> Optional[dict]:
        """Evaluate date field: warn/alert before due, critical when overdue."""
        ev = field.get("date_evaluation")
        if not ev or not ev.get("enabled"):
            return None

        key = field.get("key")
        date_str = test_data.get(key)
        if not date_str:
            return None

        try:
            from dateutil import parser
            target_date = parser.parse(str(date_str))
        except (ValueError, ImportError):
            return None

        now = datetime.now(timezone.utc)
        if target_date.tzinfo is None:
            target_date = target_date.replace(tzinfo=timezone.utc)

        days_until = (target_date - now).days

        status = NORMAL
        if days_until < 0 and ev.get("critical_when_overdue"):
            status = CRITICAL
        elif days_until <= (ev.get("alert_days_before") or 0):
            status = ALERT
        elif days_until <= (ev.get("warning_days_before") or 0):
            status = ALERT  # or introduce WARNING status if desired

        return {
            "key": key,
            "label": field.get("label", key),
            "type": "date",
            "value": date_str,
            "days_until": days_until,
            "status": status,
            "remedial_action_text": ev.get("remedial_action_text")
                if status == CRITICAL else None,
        }

    @staticmethod
    def _classify_number(value: float, ev: dict) -> str:
        """Map a numeric value to NORMAL / ALERT / CRITICAL using field evaluation config."""
        cb = _f(ev.get("critical_below"))
        ca = _f(ev.get("critical_above"))
        al_min = _f(ev.get("alert_min"))
        al_max = _f(ev.get("alert_max"))
        nm_min = _f(ev.get("normal_min"))
        nm_max = _f(ev.get("normal_max"))

        # CRITICAL is highest priority
        if cb is not None and value < cb:
            return CRITICAL
        if ca is not None and value > ca:
            return CRITICAL

        # ALERT
        if al_min is not None and value < al_min:
            return ALERT
        if al_max is not None and value > al_max:
            return ALERT

        # Normal range check (out-of-normal = ALERT, not CRITICAL)
        if nm_min is not None and value < nm_min:
            return ALERT
        if nm_max is not None and value > nm_max:
            return ALERT

        return NORMAL

    @staticmethod
    def _classify_number_with_limit(value: float, ev: dict) -> tuple[str, Optional[float]]:
        """
        Same classification as _classify_number, but also returns the
        specific boundary that was actually crossed to reach that status -
        e.g. an ALERT from crossing normal_max returns normal_max, not
        critical_above. Mirrors _classify_number's priority order exactly
        so the two can never disagree on the status itself; only this one
        also reports which limit is relevant to explain *why*.
        """
        cb = _f(ev.get("critical_below"))
        ca = _f(ev.get("critical_above"))
        al_min = _f(ev.get("alert_min"))
        al_max = _f(ev.get("alert_max"))
        nm_min = _f(ev.get("normal_min"))
        nm_max = _f(ev.get("normal_max"))

        if cb is not None and value < cb:
            return CRITICAL, cb
        if ca is not None and value > ca:
            return CRITICAL, ca

        if al_min is not None and value < al_min:
            return ALERT, al_min
        if al_max is not None and value > al_max:
            return ALERT, al_max

        if nm_min is not None and value < nm_min:
            return ALERT, nm_min
        if nm_max is not None and value > nm_max:
            return ALERT, nm_max

        return NORMAL, None

    # ─── Helper extractors ────────────────────────────────────────────────────

    @staticmethod
    def get_critical_fields(ev_result: dict) -> list[dict]:
        return [f for f in ev_result.get("fields", []) if f.get("status") == CRITICAL]

    @staticmethod
    def get_alert_fields(ev_result: dict) -> list[dict]:
        return [f for f in ev_result.get("fields", []) if f.get("status") == ALERT]

    @staticmethod
    def build_remedial_summary(ev_result: dict, request_title: str = "") -> Optional[str]:
        """
        Build a human-readable recommendation summary from CRITICAL fields.
        Returns None if no critical fields have remedial_action_text.
        """
        critical = EvaluationService.get_critical_fields(ev_result)
        parts: list[str] = []
        for f in critical:
            txt = f.get("remedial_action_text")
            label = f.get("label", f.get("key", ""))
            if txt:
                parts.append(f"[{label}] {txt}")

        if not parts:
            # Fall back to alert fields
            for f in EvaluationService.get_alert_fields(ev_result):
                txt = f.get("remedial_action_text")
                label = f.get("label", f.get("key", ""))
                if txt:
                    parts.append(f"[{label}] {txt}")

        if not parts:
            return None

        header = f"[AUTO-EVAL CRITICAL] {request_title} — " if request_title else "[AUTO-EVAL] "
        return header + " | ".join(parts)

    @staticmethod
    def collect_suggested_products(ev_result: dict) -> list:
        """
        Collect unique suggested_products from all CRITICAL/ALERT fields.
        Products may be strings or dicts; deduplication is by string representation.
        """
        seen: set = set()
        products: list = []
        for f in ev_result.get("fields", []):
            if f.get("status") not in (ALERT, CRITICAL):
                continue
            for p in f.get("suggested_products") or []:
                key = str(p)
                if key not in seen:
                    seen.add(key)
                    # Normalise string products to dict for consistency
                    products.append(
                        {"item_name": p, "category": "suggested"} if isinstance(p, str) else p
                    )
        return products

    @staticmethod
    def get_min_revised_interval(ev_result: dict) -> Optional[int]:
        """Return the shortest revised_interval_days across ALERT fields."""
        intervals = [
            f["revised_interval_days"]
            for f in ev_result.get("fields", [])
            if f.get("status") == ALERT and f.get("revised_interval_days") is not None
        ]
        return min(intervals) if intervals else None

    # ─── DB-aware helpers ─────────────────────────────────────────────────────

    @staticmethod
    def get_template_data(
        template_key: str, db: Session, org_id=None
    ) -> Optional[dict]:
        """
        Resolve template_data from OrgTestTemplate (DB-first) or
        static test_templates.py dict.

        Resolution order:
          1. Org-specific row matching org_id (when provided)
          2. Global row (org_id IS NULL)
          3. Static test_templates.py dict
        """
        from models import OrgTestTemplate
        if org_id:
            row = (
                db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.template_key == template_key,
                    OrgTestTemplate.org_id == org_id,
                )
                .first()
            )
            if row:
                return row.template_data or {}

        # Global fallback
        row = (
            db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.template_key == template_key,
                OrgTestTemplate.org_id.is_(None),
            )
            .first()
        )
        if row:
            return row.template_data or {}

        # Fall back to static file
        try:
            from test_templates import TEST_TEMPLATES
            return TEST_TEMPLATES.get(template_key, {})
        except ImportError:
            return {}

    # ─── Cross-session comparison ─────────────────────────────────────────────

    @staticmethod
    def evaluate_cross_session(
        template_data: dict,
        baseline_data: dict,
        current_data: dict,
    ) -> dict:
        """
        Compare current_data against baseline_data for every field that has
        cross_session_evaluation.enabled = true.

        Returns the same shape as evaluate_test_data():
            {
                "overall": "NORMAL" | "ALERT" | "CRITICAL",
                "evaluated_at": "<ISO-8601>",
                "fields": [
                    {
                        "key": ..., "label": ..., "type": ...,
                        "baseline_value": ..., "current_value": ...,
                        "deviation": ..., "status": ...,
                        "config": { aggregate_type, deviation_type, ... }
                    }
                ]
            }

        Supports:
          - NUMBER fields  — compute deviation, classify via _classify_number()
          - TABLE fields   — per-column, two modes:
              aggregate_type set  → collapse rows to scalar, then compare
              match_by_column set → row-by-row comparison
        """
        field_results: list[dict] = []
        overall_rank = 0

        for section in template_data.get("sections", []):
            for field in section.get("fields", []):
                cs_ev = field.get("cross_session_evaluation")
                if not cs_ev or not cs_ev.get("enabled"):
                    continue

                field_type = field.get("type", "text")
                results: list[dict] = []

                if field_type == "number":
                    r = EvaluationService._cross_eval_number(field, cs_ev, baseline_data, current_data)
                    if r:
                        results = [r]
                elif field_type == "table":
                    results = EvaluationService._cross_eval_table(field, cs_ev, baseline_data, current_data)

                for r in results:
                    rank = _STATUS_RANK.get(r.get("status"), 0)
                    if rank > overall_rank:
                        overall_rank = rank
                    field_results.append(r)

        overall_labels = [NORMAL, ALERT, CRITICAL]
        return {
            "overall": overall_labels[overall_rank],
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "fields": field_results,
        }

    @staticmethod
    def _cross_eval_number(
        field: dict, cs_ev: dict, baseline_data: dict, current_data: dict
    ) -> Optional[dict]:
        """Cross-session comparison for a single number field."""
        key = field.get("key")
        b_raw = baseline_data.get(key)
        c_raw = current_data.get(key)
        if b_raw is None or c_raw is None:
            return None
        try:
            b_val = float(b_raw)
            c_val = float(c_raw)
        except (ValueError, TypeError):
            return None

        deviation = EvaluationService._compute_deviation(b_val, c_val, cs_ev.get("deviation_type", "absolute"))
        if deviation is None:
            return None

        status = EvaluationService._classify_number(deviation, cs_ev)
        return {
            "key": key,
            "label": field.get("label", key),
            "type": "number",
            "source": "cross_session",          # marker for _build_threshold_config_html
            "baseline_value": b_val,
            "current_value": c_val,
            "deviation": round(deviation, 6),
            "deviation_type": cs_ev.get("deviation_type", "absolute"),
            "status": status,
        }

    @staticmethod
    def _cross_eval_table(
        field: dict, cs_ev: dict, baseline_data: dict, current_data: dict
    ) -> list[dict]:
        """Cross-session comparison for a table field."""
        key = field.get("key")
        baseline_rows = baseline_data.get(key)
        current_rows  = current_data.get(key)
        if not isinstance(baseline_rows, list) or not isinstance(current_rows, list):
            return []

        col_comparisons: dict = cs_ev.get("column_comparisons") or {}
        match_col: Optional[str] = cs_ev.get("match_by_column")
        results: list[dict] = []

        for col_key, col_cfg in col_comparisons.items():
            agg_type = col_cfg.get("aggregate_type")
            dev_type = col_cfg.get("deviation_type", "absolute")

            if agg_type:
                # ── Aggregate both sessions then compare ──────────────────────
                b_agg = EvaluationService._aggregate_column(baseline_rows, col_key, agg_type)
                c_agg = EvaluationService._aggregate_column(current_rows,  col_key, agg_type)
                if b_agg is None or c_agg is None:
                    continue
                deviation = EvaluationService._compute_deviation(b_agg, c_agg, dev_type)
                if deviation is None:
                    continue
                status = EvaluationService._classify_number(deviation, col_cfg)
                results.append({
                    "key": f"{key}.{col_key}",
                    "label": f"{field.get('label', key)} — {col_key} ({agg_type})",
                    "type": "table_aggregate",
                    "source": "cross_session",      # marker for _build_threshold_config_html
                    "aggregate_type": agg_type,
                    "baseline_value": round(b_agg, 6),
                    "current_value": round(c_agg, 6),
                    "deviation": round(deviation, 6),
                    "deviation_type": dev_type,
                    "status": status,
                })

            elif match_col:
                # ── Row-by-row matched by match_col ──────────────────────────
                baseline_idx = {str(r.get(match_col)): r for r in baseline_rows}
                for c_row in current_rows:
                    row_id = str(c_row.get(match_col))
                    b_row  = baseline_idx.get(row_id)
                    if not b_row:
                        continue
                    b_raw = b_row.get(col_key)
                    c_raw = c_row.get(col_key)
                    if b_raw is None or c_raw is None:
                        continue
                    try:
                        b_val = float(b_raw)
                        c_val = float(c_raw)
                    except (ValueError, TypeError):
                        continue
                    deviation = EvaluationService._compute_deviation(b_val, c_val, dev_type)
                    if deviation is None:
                        continue
                    status = EvaluationService._classify_number(deviation, col_cfg)
                    results.append({
                        "key": f"{key}.{col_key}",
                        "label": f"{field.get('label', key)} [{row_id}] — {col_key}",
                        "type": "table_row",
                        "source": "cross_session",  # marker for _build_threshold_config_html
                        "row_id": row_id,
                        "baseline_value": b_val,
                        "current_value": c_val,
                        "deviation": round(deviation, 6),
                        "deviation_type": dev_type,
                        "status": status,
                    })

            else:
                # aggregate_type is None/empty AND match_by_column not set — skip with warning
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "cross_session_evaluation: column '%s' on field '%s' has "
                    "aggregate_type=None but no match_by_column is set — skipping.",
                    col_key, key,
                )

        return results

    @staticmethod
    def _aggregate_column(rows: list, col_key: str, agg_type: str) -> Optional[float]:
        """Aggregate a column from table rows.
        Accepts: avg / average / sum / multiply / count / max / min
        ("average" accepted as alias for "avg" for compatibility with table_evaluation.)
        """
        values = []
        for row in rows:
            v = row.get(col_key)
            if v is None:
                continue
            try:
                values.append(float(v))
            except (ValueError, TypeError):
                pass
        if not values:
            return None
        _t = (agg_type or "").lower()
        if _t in ("avg", "average"):
            return sum(values) / len(values)
        if _t == "sum":
            return sum(values)
        if _t == "multiply":
            result = 1.0
            for v in values:
                result *= v
            return result
        if _t == "count":
            return float(len(values))
        if _t == "max":
            return max(values)
        if _t == "min":
            return min(values)
        return None

    @staticmethod
    def _compute_deviation(baseline: float, current: float, deviation_type: str) -> Optional[float]:
        """Compute deviation between baseline and current values."""
        if deviation_type == "relative_percent":
            if baseline == 0:
                return None
            return ((current - baseline) / abs(baseline)) * 100.0
        # default: absolute
        return current - baseline

    @staticmethod
    def run(template_key: str, test_data: dict, db: Session, org_id=None) -> dict:
        """Convenience: resolve template then evaluate."""
        tpl = EvaluationService.get_template_data(template_key, db, org_id=org_id)
        if not tpl:
            return {"overall": NORMAL, "evaluated_at": datetime.now(timezone.utc).isoformat(), "fields": []}
        return EvaluationService.evaluate_test_data(tpl, test_data)


# ─── Utility ──────────────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


_EPS = 1e-9


def _epsilon_equals(a: float, b: float) -> bool:
    """Close-enough-to-equal check for boundary comparisons (mirrors
    RuleEngine._epsilonEquals in lib/common/rule_engine.dart) so float
    rounding on multi-decimal inputs (0.15 stored as 0.1499999...) doesn't
    push a value to the wrong side of a threshold boundary."""
    return abs(a - b) < _EPS
