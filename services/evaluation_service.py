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
                    result = EvaluationService._eval_table_field(field, test_data)
                elif field_type in ("dropdown", "radio"):
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
        """Evaluate a table field: aggregate rules + per-column evaluation."""
        ev = field.get("table_evaluation")
        if not ev or not ev.get("enabled"):
            return None

        key = field.get("key")
        table_data = test_data.get(key)
        if not isinstance(table_data, list) or not table_data:
            return None

        # Aggregate evaluation
        agg_status = NORMAL
        agg_result = None
        if ev.get("aggregate_type") and ev.get("aggregate_column"):
            agg_status, agg_result = EvaluationService._eval_table_aggregate(
                table_data, ev
            )

        # Per-column evaluation
        col_results = []
        col_evals = ev.get("column_evaluations") or {}
        for col_key, col_ev in col_evals.items():
            for row_idx, row in enumerate(table_data):
                val = row.get(col_key)
                if val is None:
                    continue
                try:
                    num_val = float(val)
                    col_status = EvaluationService._classify_number(num_val, col_ev)
                    col_results.append({
                        "column": col_key,
                        "row": row_idx,
                        "value": num_val,
                        "status": col_status,
                    })
                    if _STATUS_RANK[col_status] > _STATUS_RANK[agg_status]:
                        agg_status = col_status
                except (ValueError, TypeError):
                    continue

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
    def get_template_data(template_key: str, db: Session) -> Optional[dict]:
        """
        Resolve template_data from OrgTestTemplate (DB-first) or
        static test_templates.py dict.
        """
        from models import OrgTestTemplate
        row = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == template_key)
            .order_by(OrgTestTemplate.org_id.nullslast())   # org-specific before global
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

    @staticmethod
    def run(template_key: str, test_data: dict, db: Session) -> dict:
        """Convenience: resolve template then evaluate."""
        tpl = EvaluationService.get_template_data(template_key, db)
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
