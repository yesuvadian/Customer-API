"""
Generic Analytics Engine
========================
Processes any test template configured in OrgTestTemplate.
No hardcoded knowledge of specific test types.

Capabilities per parameter:
  - Condition evaluation  (Good / Fair / Poor)
  - Trend analysis        (Increasing / Decreasing / Stable)
  - Degradation rate      (annual change, % change)
  - Threshold breach forecast
  - Anomaly detection     (sudden change, outlier)

Health scoring uses optional `weight` values on template fields.

Trigger flow:
  run_for_test(test_result_id)
    → updates ParameterAnalytics + TestAnalytics
    → calls run_for_equipment(equipment_id)
      → updates EquipmentAnalytics
      → calls run_for_department(department_id) up the hierarchy
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

import config
from models import (
    Equipment,
    EquipmentAnalytics,
    HierarchyAnalytics,
    OrgDepartment,
    OrgTestTemplate,
    ParameterAnalytics,
    TestAnalytics,
    TestResult,
    TestingRequest,
)

logger = logging.getLogger(__name__)

# ── Status / condition constants ───────────────────────────────────────────────
# Single source for the fixed NORMAL/ALERT/CRITICAL vocabulary — previously
# also independently redeclared in services/evaluation_service.py (identical
# strings, so never actually able to drift, but no reason to say it twice).
# evaluation_service.py now imports these three from here; this module can't
# import back from evaluation_service.py at module level without creating a
# circular import (evaluation_service.py already does `from
# services.analytics_engine import ...` — the dependency only works in this
# direction), which is why the constants live here and not there.
NORMAL   = "NORMAL"
ALERT    = "ALERT"
CRITICAL = "CRITICAL"

# Safety fallback only, same role as _DEFAULT_RISK_BANDS below — the
# admin-configurable source of truth is TestStatusCondition (KPTCL spec
# §12.1's "EHS computation logic"; see _load_condition_labels).
_DEFAULT_CONDITION = {NORMAL: "Good", ALERT: "Fair", CRITICAL: "Poor"}
# Safety fallback only, same role as _DEFAULT_RISK_BANDS below — the
# admin-configurable source of truth is ParameterConditionScore (KPTCL
# spec §12.1's "EHS computation logic", the input side of it: see
# _load_condition_scores).
_DEFAULT_SCORE = {"Good": 100.0, "Fair": 50.0, "Poor": -100.0}  # negative so critical fields actively drag the score down

# _RANK (was {NORMAL: 0, ALERT: 1, CRITICAL: 2}) is removed, not migrated
# to a table: grep confirms nothing in this file ever read it — dead code.
# The real "worst status wins" ordinal used throughout the app is
# services/evaluation_service.py's own _STATUS_RANK, a separate constant
# with 5 real call sites there. That one is left hardcoded on purpose: it
# is not a business threshold an admin would tune, it is the definition of
# the fixed NORMAL/ALERT/CRITICAL vocabulary itself (CRITICAL cannot stop
# being worse than ALERT without the labels no longer meaning what they
# say) — the same reason NORMAL/ALERT/CRITICAL's own spelling isn't a
# config row either.

# Safety fallback only — used when the DB lookup below has nothing to
# return (table not yet seeded, or no `db` session was passed in). The
# admin-configurable source of truth is EquipmentHealthBandThreshold
# (KPTCL spec §12.1); see _load_risk_bands.
_DEFAULT_RISK_BANDS = [
    (80, "Low"),
    (50, "Medium"),
    (25, "High"),
    (0,  "Critical"),
]


def _load_risk_bands(db: Optional[Session]) -> list[tuple[float, str]]:
    """Admin-configured (threshold, label) pairs, highest threshold first —
    same ordering _DEFAULT_RISK_BANDS always had, just no longer hardcoded.
    Falls back to _DEFAULT_RISK_BANDS if no db session was given or the
    table has no active rows yet, so a not-yet-seeded environment behaves
    exactly as before rather than breaking.
    """
    if db is None:
        return _DEFAULT_RISK_BANDS
    from models import EquipmentHealthBandThreshold
    rows = (
        db.query(EquipmentHealthBandThreshold)
        .filter(EquipmentHealthBandThreshold.is_active.is_(True))
        .order_by(EquipmentHealthBandThreshold.threshold.desc())
        .all()
    )
    if not rows:
        return _DEFAULT_RISK_BANDS
    return [(float(r.threshold), r.label) for r in rows]


def _load_condition_labels(db: Optional[Session]) -> dict[str, str]:
    """Admin-configured {status: condition_label} map. Falls back to
    _DEFAULT_CONDITION if no db session was given or the table has no
    active rows yet, same reasoning as _load_risk_bands.
    """
    if db is None:
        return _DEFAULT_CONDITION
    from models import TestStatusCondition
    rows = (
        db.query(TestStatusCondition)
        .filter(TestStatusCondition.is_active.is_(True))
        .all()
    )
    if not rows:
        return _DEFAULT_CONDITION
    return {r.status: r.condition_label for r in rows}


def _load_condition_scores(db: Optional[Session]) -> dict[str, float]:
    """Admin-configured {condition: point_value} map. Falls back to
    _DEFAULT_SCORE if no db session was given or the table has no active
    rows yet, same reasoning as _load_risk_bands.
    """
    if db is None:
        return _DEFAULT_SCORE
    from models import ParameterConditionScore
    rows = (
        db.query(ParameterConditionScore)
        .filter(ParameterConditionScore.is_active.is_(True))
        .all()
    )
    if not rows:
        return _DEFAULT_SCORE
    return {r.condition: float(r.score) for r in rows}


_DEFAULT_BAND_RANK_WORDS: dict[str, int] = {
    "good": 0, "normal": 0, "pass": 0, "ok": 0, "excellent": 0,
    "fair": 1, "alert": 1, "warning": 1, "monitor": 1,
    "poor": 2, "critical": 2, "abnormal": 2, "fail": 2, "not ok": 2,
}


def _load_band_rank_words(db: Optional[Session]) -> dict[str, int]:
    """Admin-configured {phrase: rank} map (ConditionBandRankWord) used to
    rank an arbitrary free-text band label (e.g. "Good", "Fair", "Not OK")
    by severity. Falls back to _DEFAULT_BAND_RANK_WORDS if no db session
    was given or the table has no active rows yet, same reasoning as
    _load_risk_bands. Shared by routers/analytics.py's _band_rank (breach
    forecasting) and services/evaluation_service.py's _cond_rank
    (test-evaluation-time band ranking) — was two independently hardcoded,
    already-drifted copies of the same word list before this.
    """
    if db is None:
        return _DEFAULT_BAND_RANK_WORDS
    from models import ConditionBandRankWord
    rows = (
        db.query(ConditionBandRankWord)
        .filter(ConditionBandRankWord.is_active.is_(True))
        .all()
    )
    if not rows:
        return _DEFAULT_BAND_RANK_WORDS
    return {r.phrase.lower(): r.rank for r in rows}


def _risk_from_score(
    score: Optional[float],
    critical_findings: list | None = None,
    db: Optional[Session] = None,
) -> str:
    # If any finding has CRITICAL status, the equipment risk is at least Critical,
    # regardless of its composite health score.
    if critical_findings and any(
        isinstance(f, dict) and f.get("status") == "CRITICAL"
        for f in critical_findings
    ):
        return "Critical"
    if score is None:
        return "Unknown"
    for threshold, label in _load_risk_bands(db):
        if score >= threshold:
            return label
    return "Critical"


def _condition_from_score(score: Optional[float]) -> str:
    # Good/Fair/Poor is a separate, coarser 3-tier summary of the same
    # score — not the spec's 4-tier EHS band (Low/Medium/High/Critical,
    # the thing §12.1 asks to be configurable) and not wired to
    # EquipmentHealthBandThreshold. Left as-is; revisit only if the spec's
    # configurability requirement is ever read to cover this label too.
    if score is None:
        return "Unknown"
    if score >= 80:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Poor"


# ── Linear regression helper ──────────────────────────────────────────────────

def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """
    Returns (slope, intercept, r_squared).
    x = elapsed days from first observation; y = parameter values.
    """
    n = len(x)
    if n < 2:
        return 0.0, y[0] if y else 0.0, 0.0

    xm = mean(x)
    ym = mean(y)
    ss_xx = sum((xi - xm) ** 2 for xi in x)
    ss_xy = sum((xi - xm) * (yi - ym) for xi, yi in zip(x, y))

    if ss_xx == 0:
        return 0.0, ym, 0.0

    slope     = ss_xy / ss_xx
    intercept = ym - slope * xm

    y_pred    = [slope * xi + intercept for xi in x]
    ss_res    = sum((yi - yp) ** 2 for yi, yp in zip(y, y_pred))
    ss_tot    = sum((yi - ym) ** 2 for yi in y)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot else 1.0

    return slope, intercept, max(0.0, min(1.0, r_squared))


# ── Parameter-level analytics ─────────────────────────────────────────────────

class ParameterAnalyzer:
    """
    Computes trend, degradation, breach forecast, and anomaly
    for a single numeric parameter using its historical readings.
    """

    # Minimum readings needed for trend calculation
    MIN_TREND_POINTS = config.ANALYTICS_MIN_TREND_POINTS
    # Slope considered "stable" if |slope * 365| < this fraction of the value range
    STABLE_FRACTION  = config.ANALYTICS_STABLE_FRACTION
    # Z-score threshold for anomaly
    ANOMALY_Z        = config.ANALYTICS_ANOMALY_Z
    # Minimum goodness-of-fit before a slope's DIRECTION is trusted at all.
    # Confirmed live: Acidity readings bouncing noisily between 0.004 and
    # 0.017 mg KOH/g across 10 real tests over 6 years (r_squared=0.0837 —
    # the line explains 8% of the variance) still came out confidently
    # labeled "Increasing", because trend classification only ever compared
    # the slope's annualized MAGNITUDE against STABLE_FRACTION and never
    # looked at how well the line actually fits. This is a property of the
    # shared ParameterAnalyzer.analyse() every parameter goes through
    # (table-row and flat-field alike, every test template), not a
    # per-template special case, so gating on it here fixes it everywhere
    # at once rather than needing a separate patch per test type. Tunable
    # via config.py/ANALYTICS_MIN_TREND_R_SQUARED without a code deploy.
    MIN_TREND_R_SQUARED = config.ANALYTICS_MIN_TREND_R_SQUARED

    @staticmethod
    def analyse(
        history: list[tuple[datetime, float]],
        evaluation: dict,
        current_value: Optional[float] = None,
        current_date:  Optional[datetime] = None,
    ) -> dict:
        """
        history  : [(tested_at, float_value), ...] sorted oldest-first
        evaluation: the field's `evaluation` dict from template
        current_value/current_date: the reading being analysed right now -
          only needed for the single-prior-reading case below.

        Returns a dict with trend, slope, r_squared, annual_change,
        pct_change_annual, breach_threshold, breach_predicted_at,
        days_to_breach, is_anomaly, anomaly_type, anomaly_detail,
        history_count.
        """
        result: dict = {
            "history_count":      len(history) + 1,  # +1 for current reading
            "trend":              "Insufficient_Data",
            "trend_slope":        None,
            "trend_r_squared":    None,
            "annual_change":      None,
            "pct_change_annual":  None,
            "breach_threshold":   None,
            "breach_predicted_at":None,
            "days_to_breach":     None,
            "is_anomaly":         False,
            "anomaly_type":       None,
            "anomaly_detail":     None,
        }

        if not history:
            return result

        values = [v for _, v in history]
        dates  = [d for d, _ in history]

        # Fold the current reading into the series - previously the
        # regression/anomaly-check/breach-forecast below used `history`
        # alone (the current reading is explicitly excluded from it by
        # _fetch_history_map), so every one of these figures was computed as
        # of the PREVIOUS test - one full cycle stale by the time this
        # test's own analytics are shown. A parameter that just crashed from
        # a stable trend, for example, would report the old upward trend and
        # no anomaly until the *next* test recomputes it.
        if current_value is not None and current_date is not None:
            values = values + [current_value]
            dates  = dates + [current_date]

        # Anomaly detection (needs ≥ 4 values for meaningful std) - now
        # includes the current reading, so an actual anomalous reading is
        # caught immediately rather than one test cycle later.
        if len(values) >= 4:
            ParameterAnalyzer._detect_anomaly(values, result)

        if len(history) < ParameterAnalyzer.MIN_TREND_POINTS:
            return result

        # Exactly one prior reading (now two points total, with the current
        # reading folded in above) can't feed a real OLS goodness-of-fit -
        # any 2-point line fits perfectly by construction, which would
        # misleadingly report r_squared as 1.0 rather than "not meaningful".
        # Slope itself is still a real, non-degenerate calculation for two
        # points, so compute that directly instead of leaving it as
        # _linear_regression's degenerate single-point fallback.
        if len(history) == 1:
            prior_date, prior_value = history[0]
            elapsed_days = (dates[-1] - prior_date).total_seconds() / 86400.0
            slope = (values[-1] - prior_value) / elapsed_days if elapsed_days > 0 else 0.0
            result["trend_slope"] = round(slope, 8)
            result["trend_r_squared"] = None

            annual_change = slope * 365
            result["annual_change"] = round(annual_change, 6)
            if prior_value:
                result["pct_change_annual"] = round(annual_change / abs(prior_value) * 100, 2)

            val_range = abs(prior_value) or abs(values[-1]) or 1
            stable_threshold = val_range * ParameterAnalyzer.STABLE_FRACTION
            if annual_change > stable_threshold:
                result["trend"] = "Increasing"
            elif annual_change < -stable_threshold:
                result["trend"] = "Decreasing"
            else:
                result["trend"] = "Stable"

            # No breach forecast off just 2 points: a 2-point line fits
            # "perfectly" by construction with no way to check it (that's
            # exactly why r_squared is left None above), which is even less
            # reliable than a real regression that fails the r² gate below —
            # forecasting a crossing date from it would be worse than the
            # low-r² case this fix targets, not better just because r² can't
            # be computed to catch it.
            return result

        # Build x-axis as elapsed days from first observation
        t0 = dates[0]
        x  = [(d - t0).total_seconds() / 86400.0 for d in dates]
        y  = values

        slope, intercept, r_sq = _linear_regression(x, y)

        result["trend_slope"]     = round(slope, 8)
        result["trend_r_squared"] = round(r_sq, 4)

        annual_change = slope * 365
        result["annual_change"] = round(annual_change, 6)

        # % change relative to first (baseline) value
        baseline = values[0]
        if baseline and baseline != 0:
            result["pct_change_annual"] = round(annual_change / abs(baseline) * 100, 2)

        # Trend classification
        val_range = max(values) - min(values) if len(values) > 1 else abs(values[0])
        stable_threshold = (val_range or abs(values[-1]) or 1) * ParameterAnalyzer.STABLE_FRACTION
        fit_is_reliable = r_sq >= ParameterAnalyzer.MIN_TREND_R_SQUARED
        if not fit_is_reliable:
            # The line doesn't explain enough of the actual variance to
            # trust a direction from it, regardless of how large the
            # slope's annualized magnitude looks — see MIN_TREND_R_SQUARED's
            # docstring. trend_slope/annual_change/trend_r_squared above are
            # still the real, honest numbers (a low r² is itself useful
            # information), just not promoted into a confident direction.
            result["trend"] = "Stable"
        elif annual_change > stable_threshold:
            result["trend"] = "Increasing"
        elif annual_change < -stable_threshold:
            result["trend"] = "Decreasing"
        else:
            result["trend"] = "Stable"

        # Breach forecast — only if slope is non-zero, we have thresholds,
        # AND the fit is reliable enough to trust a direction from at all
        # (see fit_is_reliable above) — forecasting a crossing date off a
        # slope that barely fits the data would be actively misleading, not
        # just an unconfirmed trend label.
        if slope != 0 and fit_is_reliable:
            ParameterAnalyzer._forecast_breach(
                values[-1], dates[-1], slope, evaluation, result
            )

        return result

    # ── internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _detect_anomaly(values: list[float], result: dict) -> None:
        """Z-score anomaly detection on the latest value."""
        if len(values) < 4:
            return

        history = values[:-1]
        latest  = values[-1]
        prev    = values[-2]

        mu  = mean(history)
        sig = stdev(history) if len(history) > 1 else 0

        if sig == 0:
            return

        z = (latest - mu) / sig
        if abs(z) >= ParameterAnalyzer.ANOMALY_Z:
            result["is_anomaly"]    = True
            result["anomaly_detail"] = f"Z-score {z:.2f} (mean={mu:.3f}, σ={sig:.3f})"
            if latest > mu:
                result["anomaly_type"] = "sudden_increase"
            else:
                result["anomaly_type"] = "sudden_decrease"
            return

        # Step-change: latest vs previous > 50 % of historical σ × 3
        step = abs(latest - prev)
        if step > 3 * sig:
            result["is_anomaly"]    = True
            result["anomaly_type"]  = "sudden_increase" if latest > prev else "sudden_decrease"
            result["anomaly_detail"] = (
                f"Step change {step:.3f} exceeds 3σ={3*sig:.3f}"
            )

    @staticmethod
    def _forecast_breach(
        latest_value: float,
        latest_date:  datetime,
        slope:        float,
        evaluation:   dict,
        result:       dict,
    ) -> None:
        """
        For a numeric parameter, find the nearest threshold it will breach
        given the current trend slope, and predict the crossing date.
        """
        now = datetime.now(timezone.utc)
        if latest_date.tzinfo is None:
            latest_date = latest_date.replace(tzinfo=timezone.utc)

        # Candidate thresholds to check
        candidates: list[tuple[float, str]] = []

        alert_min = evaluation.get("alert_min")
        alert_max = evaluation.get("alert_max")
        crit_bel  = evaluation.get("critical_below")
        crit_abo  = evaluation.get("critical_above")
        norm_min  = evaluation.get("normal_min")
        norm_max  = evaluation.get("normal_max")

        if slope < 0:
            # Decreasing — will it breach lower bounds?
            for th in [crit_bel, alert_min, norm_min]:
                if th is not None and latest_value > th:
                    candidates.append((th, "lower"))
        elif slope > 0:
            # Increasing — will it breach upper bounds?
            for th in [crit_abo, alert_max, norm_max]:
                if th is not None and latest_value < th:
                    candidates.append((th, "upper"))

        if not candidates:
            return

        # Pick the nearest threshold in the direction of travel
        best_days  = None
        best_th    = None
        slope_per_day = slope  # slope is already in units/day from regression

        for th, direction in candidates:
            gap = th - latest_value  # positive if threshold is above current
            if slope_per_day == 0:
                continue
            days = gap / slope_per_day
            if days > 0 and (best_days is None or days < best_days):
                best_days = days
                best_th   = th

        if best_days is None or best_days > 3650:  # ignore predictions > 10 years
            return

        predicted_at = latest_date + timedelta(days=best_days)
        days_from_now = (predicted_at - now).days

        result["breach_threshold"]    = best_th
        result["breach_predicted_at"] = predicted_at
        result["days_to_breach"]      = max(0, days_from_now)


# ── Health scoring ────────────────────────────────────────────────────────────

class HealthScorer:
    """
    Computes weighted health score for a test result.
    Weight is taken from field.evaluation.weight (defaults to 1.0).
    """

    @staticmethod
    def score_test(
        template_data: dict,
        evaluation_result: dict,
        test_data: dict | None = None,
        condition_labels: dict[str, str] | None = None,
        scores: dict[str, float] | None = None,
    ) -> tuple[float, list[dict]]:
        """
        Returns (health_score 0–100, critical_findings list).

        evaluation_result is the JSONB stored in TestResult.evaluation_result,
        which has {overall, fields: [{key, label, status, ...}]}.
        test_data is the raw submitted form data — when provided, table fields
        are re-evaluated fresh so that row_label/breach_limit are available.
        condition_labels/scores: admin-configured maps from
        _load_condition_labels(db)/_load_condition_scores(db) — callers with
        a db session should pass both through rather than relying on the
        _DEFAULT_CONDITION/_DEFAULT_SCORE fallback this defaults to.
        """
        condition_labels = condition_labels if condition_labels is not None else _DEFAULT_CONDITION
        scores = scores if scores is not None else _DEFAULT_SCORE
        if not evaluation_result:
            return None, []

        field_statuses: dict[str, str] = {
            f["key"]: f["status"]
            for f in evaluation_result.get("fields", [])
        }

        total_weight = 0.0
        weighted_sum = 0.0
        critical_findings: list[dict] = []

        # Build a lookup of field defs by key so we can read weight later
        field_defs: dict[str, dict] = {}
        for section in template_data.get("sections", []):
            for field in section.get("fields", []):
                field_defs[field.get("key", "")] = field

        # Score every field that the evaluation engine produced a result for.
        # The eval engine is the authority on what is evaluatable — we don't
        # re-check ev blocks here so that THRESHOLD / column_evaluation paths
        # are included automatically.
        # Build a lookup of field detail (value, thresholds) from evaluation_result
        eval_field_map: dict[str, dict] = {
            f["key"]: f
            for f in evaluation_result.get("fields", [])
            if isinstance(f, dict) and "key" in f
        }

        # For table fields: re-evaluate fresh from test_data so that row_label
        # and breach_limit are available (stored evaluation_result may be stale).
        if test_data:
            from services.evaluation_service import EvaluationService as _EvalSvc
            for section in template_data.get("sections", []):
                for field in section.get("fields", []):
                    if field.get("type") == "table":
                        fkey = field.get("key", "")
                        fresh = (
                            _EvalSvc._eval_table_field(field, test_data)
                            or _EvalSvc._eval_threshold_table(field, test_data)
                        )
                        if fresh:
                            # Merge fresh result over the stored one (keep status from stored)
                            stored = eval_field_map.get(fkey, {})
                            eval_field_map[fkey] = {**stored, **fresh}

        for fkey, status in field_statuses.items():
            field = field_defs.get(fkey, {})
            ef    = eval_field_map.get(fkey, {})

            # Weight: read from whichever eval block is present, default 1.0
            ev = (
                field.get("evaluation")
                or field.get("table_evaluation")
                or field.get("dropdown_evaluation")
                or field.get("date_evaluation")
                or {}
            )
            weight    = float(ev.get("weight", 1.0))
            condition = condition_labels.get(status, "Poor")
            score     = scores.get(condition, 0.0)

            weighted_sum  += score  * weight
            total_weight  += weight

            # "Poor" (CRITICAL overall) or "Fair" (ALERT overall) - gating on
            # "Poor" alone meant a table field whose worst row was only ALERT
            # never reached this block at all, no matter how many ALERT rows
            # it had. Individual row status is still filtered explicitly
            # below (CRITICAL/ALERT only), so widening this gate doesn't
            # pull in NORMAL rows - it just stops silently dropping every
            # ALERT-only field's findings depending on whether some unrelated
            # sibling row in the same table happened to also be CRITICAL.
            if condition in ("Poor", "Fair"):
                value       = ef.get("value")
                unit        = ef.get("unit") or field.get("unit")
                thresholds  = ef.get("thresholds") or {}
                breach_limit = (
                    thresholds.get("critical_above")
                    or thresholds.get("normal_max")
                    or thresholds.get("alert_max")
                )

                # For TABLE fields: pull the individual row failures instead.
                # evaluation_service returns column_results (one entry per cell)
                # with row_label and breach_limit already populated.
                row_results = ef.get("row_results") or []
                col_results = ef.get("column_results") or []

                # Build row_results from col_results when the legacy key is absent.
                if not row_results and col_results:
                    for _cr in col_results:
                        if _cr.get("status") not in ("CRITICAL", "ALERT"):
                            continue
                        row_results.append({
                            "row_id":       _cr.get("row_label") or f"Row {_cr.get('row', 0) + 1}",
                            "value":        _cr.get("value"),
                            "status":       _cr.get("status"),
                            "breach_limit": _cr.get("breach_limit"),
                            "unit":         field.get("unit") or "",
                        })

                critical_rows = [r for r in row_results if r.get("status") in ("CRITICAL", "ALERT")]

                # Build a lookup of allowable limits from template threshold config
                # Key: row_id (lowercase) → allowable value (Good band lower bound or Poor band upper bound)
                _tmpl_limits: dict = {}
                for col in field.get("columns", []):
                    rule = (col.get("rule") or {})
                    if rule.get("type") == "THRESHOLD":
                        cfg = rule.get("config") or {}
                        ths = cfg.get("thresholds") or {}
                        for row_name, row_bands in ths.items():
                            # row_bands may be { band: [lo, hi] } or { sub_key: { band: [lo, hi] } }
                            bands = row_bands
                            if isinstance(bands, dict):
                                first_val = next(iter(bands.values()), None)
                                if isinstance(first_val, dict):
                                    # Two-level — pick first sub-key's bands
                                    bands = first_val
                            if isinstance(bands, dict):
                                # Find the Good/Normal band boundary that marks the allowable limit
                                for band_name, band_range in bands.items():
                                    bn_lower = band_name.lower().split()[0]
                                    if bn_lower in ("good", "normal", "pass", "ok"):
                                        if isinstance(band_range, list) and len(band_range) >= 2:
                                            lo, hi = band_range[0], band_range[1]
                                            # If Good band has a finite upper bound → upper is the allowable max
                                            # If Good band has no upper bound (hi=None) → lo is the allowable min
                                            limit = hi if hi is not None else lo
                                            if limit is not None:
                                                _tmpl_limits[row_name.lower()] = limit
                                        break

                if critical_rows:
                    for row in critical_rows:
                        rv    = row.get("value")
                        ru    = row.get("unit", "")
                        rs    = row.get("status", "")
                        name  = row.get("row_id", "")
                        # Use stored breach_limit if available; fall back to template lookup
                        rl    = row.get("breach_limit") or _tmpl_limits.get(name.lower())
                        u     = f" {ru}" if ru else ""
                        if rv is not None and rl is not None:
                            r_reason = f"{name}: {rv}{u} — allowable {rl}{u} ({rs})"
                        elif rv is not None:
                            r_reason = f"{name}: {rv}{u} — {rs}"
                        else:
                            r_reason = f"{name} — evaluated as {rs}"
                        critical_findings.append({
                            "key":          f"{fkey}.{name}",
                            "label":        name,
                            "condition":    "Poor",
                            "status":       rs,
                            "unit":         ru or None,
                            "value":        rv,
                            "breach_limit": rl,
                            "reason":       r_reason,
                        })
                else:
                    # Non-table field
                    if value is not None and breach_limit is not None:
                        u = f" {unit}" if unit else ""
                        reason = f"Value {value}{u} exceeds the critical limit of {breach_limit}{u}"
                    elif value is not None:
                        reason = f"Value {value} {unit or ''} triggered {status} evaluation".strip()
                    else:
                        reason = f"Evaluated as {status} based on test result"

                    critical_findings.append({
                        "key":           fkey,
                        "label":         field.get("label", fkey),
                        "condition":     condition,
                        "status":        status,
                        "unit":          unit,
                        "value":         value,
                        "breach_limit":  breach_limit,
                        "reason":        reason,
                    })

        if total_weight == 0:
            return None, critical_findings

        raw = weighted_sum / total_weight
        return round(max(0.0, raw), 2), critical_findings


# ── Main analytics engine ─────────────────────────────────────────────────────

class AnalyticsEngine:
    """
    Stateless engine — every method takes a db session.
    Call run_for_test() after each new TestResult is saved.
    """

    def __init__(self, db: Session):
        self.db = db

    # ── Public entry points ───────────────────────────────────────────────────

    def run_for_test(self, test_result_id: uuid.UUID) -> Optional[TestAnalytics]:
        """
        Compute ParameterAnalytics + TestAnalytics for one TestResult.
        Then triggers equipment-level and hierarchy aggregation.
        """
        result = self.db.get(TestResult, test_result_id)
        if not result:
            logger.warning("run_for_test: TestResult %s not found", test_result_id)
            return None

        template_key      = result.template_key
        organization_id   = result.organization_id
        test_data         = result.test_data or {}
        evaluation_result = result.evaluation_result or {}

        # Resolve equipment_id via the testing request
        request = self.db.get(TestingRequest, result.testing_request_id)
        if not request or not request.equipment_id:
            logger.warning("run_for_test: no equipment for TestResult %s", test_result_id)
            return None

        equipment_id = request.equipment_id

        # organization_id is sometimes missing on the TestResult itself
        # (e.g. rows created by an import path that didn't set it) — fall
        # back to the testing request's, then the equipment's, before
        # giving up. TestAnalytics.organization_id is NOT NULL, so an
        # unresolved value here must not proceed to the insert below.
        if not organization_id:
            organization_id = request.organization_id
        if not organization_id:
            equipment_for_org = self.db.get(Equipment, equipment_id)
            organization_id = equipment_for_org.organization_id if equipment_for_org else None
        if not organization_id:
            logger.warning(
                "run_for_test: could not resolve organization_id for TestResult %s "
                "(equipment %s, testing_request %s)",
                test_result_id, equipment_id, result.testing_request_id,
            )
            return None

        # Load template
        template_data = self._load_template(template_key, organization_id)
        if not template_data:
            logger.warning("run_for_test: template '%s' not found", template_key)
            return None

        # Load historical test data for trend analysis
        history_map = self._fetch_history_map(
            equipment_id, template_key, test_result_id,
            before=result.tested_at or result.cts,
            template_data=template_data,
        )

        # Admin-configured §12.1 lookups, resolved once per test and reused
        # for every field/row below (score_test, and the two per-row/per-
        # cell condition+score computations further down this method) —
        # not re-queried per field.
        condition_labels = _load_condition_labels(self.db)
        condition_scores = _load_condition_scores(self.db)

        # Score the test
        health_score, critical_findings = HealthScorer.score_test(
            template_data, evaluation_result, test_data=test_data,
            condition_labels=condition_labels, scores=condition_scores,
        )

        # Fallback for calibration templates (DATE_ADD rule) where evaluation_result
        # may be empty. Score based on days remaining vs validity period.
        if health_score is None and template_data.get("enable_calibration"):
            try:
                from datetime import date, datetime as _dt
                cal_date_str  = test_data.get("calibration_date") or test_data.get("reading_date")
                validity_val  = test_data.get("validity_months")
                if cal_date_str and validity_val:
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                        try:
                            cal_date = _dt.strptime(str(cal_date_str)[:10], fmt).date(); break
                        except ValueError:
                            cal_date = None
                    validity_months = float(validity_val)
                    if cal_date and validity_months > 0:
                        from dateutil.relativedelta import relativedelta
                        due_date     = cal_date + relativedelta(months=int(validity_months))
                        total_days   = (due_date - cal_date).days
                        days_left    = (due_date - date.today()).days
                        pct_used     = 1 - (days_left / total_days) if total_days > 0 else 1
                        if days_left <= 0:
                            health_score = 0.0
                            critical_findings = [{"key": "calibration_date", "label": "Calibration",
                                                  "status": "Fail", "message": f"Calibration overdue by {abs(days_left)} days"}]
                        elif pct_used >= 0.8:
                            # Clamped to 100 - a future-dated calibration_date
                            # (data entered ahead of the actual calibration,
                            # or a future-dated backfill) makes days_left
                            # exceed total_days, which would otherwise push
                            # the score above 100.
                            health_score = min(100.0, round(days_left / total_days * 100, 1))
                            critical_findings = [{"key": "calibration_date", "label": "Calibration",
                                                  "status": "Warning", "message": f"Calibration due in {days_left} days"}]
                        else:
                            health_score = min(100.0, round(days_left / total_days * 100, 1))
            except Exception as _cal_err:
                logger.warning(f"Calibration fallback scoring failed: {_cal_err}")

        # Fallback for cumulative templates (OLTC ops, CB ops) where evaluation_result
        # may be empty because the reading field had no evaluation block at submission time.
        # Derive a score from cumulative value vs the rule's default_threshold.
        if health_score is None and template_data.get("enable_cumulative"):
            try:
                from services.cumulative_service import CumulativeService
                rules = template_data.get("rules", [])
                threshold = next(
                    (r["config"].get("default_threshold") for r in rules if r.get("type") == "CUMULATIVE_DIFF"),
                    None,
                )
                if threshold:
                    cumulative = CumulativeService(self.db).calculate_cumulative(equipment_id)
                    pct = cumulative / threshold if threshold else 0
                    if pct >= 1.0:
                        health_score = 0.0
                        critical_findings = [{"key": "reading", "label": "Operations Counter Reading",
                                              "status": "Fail", "message": f"Cumulative ops ({cumulative:.0f}) reached overhaul threshold ({threshold:.0f})"}]
                    elif pct >= 0.7:
                        health_score = round(100 * (1 - pct), 1)
                    else:
                        health_score = round(100 * (1 - pct * 0.5), 1)
            except Exception as _cum_err:
                logger.warning(f"Cumulative fallback scoring failed: {_cum_err}")

        evaluated_count = len(evaluation_result.get("fields", []))
        total_params    = sum(
            len(s.get("fields", [])) for s in template_data.get("sections", [])
        )

        # Build evaluation_result lookup: key → {status, ...}
        ev_fields_map = {
            f.get("key"): f
            for f in evaluation_result.get("fields", [])
        }

        # For table fields: re-evaluate fresh from test_data so that row_label
        # and breach_limit are available (stored evaluation_result may be
        # stale) - mirrors the same fix in HealthScorer.score_test() above.
        # Without this, ParameterAnalytics.breach_threshold below is built
        # from whatever band-boundary logic was in effect at submission time,
        # which can disagree with the freshly-recomputed critical_findings
        # from score_test() for the exact same field.
        if test_data:
            from services.evaluation_service import EvaluationService as _EvalSvc
            for section in template_data.get("sections", []):
                for field in section.get("fields", []):
                    if field.get("type") == "table":
                        fkey = field.get("key", "")
                        fresh = (
                            _EvalSvc._eval_table_field(field, test_data)
                            or _EvalSvc._eval_threshold_table(field, test_data)
                        )
                        if fresh:
                            stored = ev_fields_map.get(fkey, {})
                            ev_fields_map[fkey] = {**stored, **fresh}

        # Per-parameter analytics
        param_rows: list[ParameterAnalytics] = []
        for section in template_data.get("sections", []):
            for field in section.get("fields", []):
                field_type = field.get("type", "text")
                field_key  = field.get("key", "")
                ev         = field.get("evaluation") or {}

                if field_type == "number":
                    # ── Scalar numeric field ────────────────────────────────
                    raw = test_data.get(field_key)
                    if raw is None or raw == "":
                        continue
                    try:
                        current_val = float(raw)
                    except (ValueError, TypeError):
                        continue

                    field_ev  = ev_fields_map.get(field_key)
                    status    = field_ev.get("status") if field_ev else None
                    condition = condition_labels.get(status, "Poor") if status else None
                    score     = max(0.0, condition_scores.get(condition, 50.0)) if condition else None


                    history  = history_map.get(field_key, [])
                    analysis = ParameterAnalyzer.analyse(
                        history, ev,
                        current_value=current_val,
                        current_date=result.tested_at or result.cts,
                    )

                    pa = self._upsert_parameter_analytics(
                        test_result_id  = test_result_id,
                        equipment_id    = equipment_id,
                        organization_id = organization_id,
                        template_key    = template_key,
                        field           = field,
                        current_value   = current_val,
                        condition       = condition,
                        status          = status,
                        score           = score,
                        analysis        = analysis,
                        remedial_action_text = field_ev.get("remedial_action_text") if field_ev else None,
                    )
                    if pa:
                        param_rows.append(pa)

                elif field_type == "table":
                    # ── Numeric table columns ───────────────────────────────
                    # Sweep/curve tables (DFR/SFRA measurements) opt out of
                    # per-row parameter analytics via analytics_skip - their
                    # data is a curve rendered by Test Graphs, not a set of
                    # trendable named parameters.
                    if field.get("analytics_skip"):
                        continue
                    table_data = test_data.get(field_key)
                    if not isinstance(table_data, list) or not table_data:
                        continue

                    # Find the label/identifier column (first text/dropdown col)
                    cols = field.get("columns", [])
                    id_col = next(
                        (c.get("key") for c in cols
                         if c.get("type") in ("text", "dropdown", "readonly")
                         and c.get("key") not in ("unit", "remarks", "formula")),
                        None,
                    )

                    # Tables evaluated via _eval_threshold_table (e.g. DGA -
                    # one THRESHOLD-rule column per row, keyed by row_id/gas
                    # name, not by column+row_idx) return their per-row
                    # results in "row_results" instead of "column_results".
                    # Only the column that rule actually classifies (its
                    # input_field) should pick up that status.
                    threshold_input_field = next(
                        (
                            (c.get("rule") or {}).get("config", {}).get("input_field")
                            for c in cols
                            if c.get("type") == "calculated"
                            and (c.get("rule") or {}).get("type") == "THRESHOLD"
                        ),
                        None,
                    )

                    for col in cols:
                        if col.get("type") not in ("number", "calculated"):
                            continue
                        col_key   = col.get("key", "")
                        col_label = col.get("label") or col_key
                        col_unit  = col.get("unit")

                        field_ev    = ev_fields_map.get(field_key) or {}
                        col_results = field_ev.get("column_results", []) if field_ev else []
                        row_results = field_ev.get("row_results", []) if field_ev else []

                        # Track per-row separately when a row-identifier exists
                        rows_to_track = []
                        if id_col:
                            for row_idx, row in enumerate(table_data):
                                row_id  = str(row.get(id_col, row_idx)).strip()
                                raw     = row.get(col_key)
                                if raw is None or raw == "":
                                    continue
                                try:
                                    row_unit = row.get("unit") or None
                                    rows_to_track.append((row_id, float(raw), row_idx, row_unit))
                                except (ValueError, TypeError):
                                    continue
                        else:
                            # No identifier — aggregate last non-null value
                            for row_idx, row in enumerate(table_data):
                                raw = row.get(col_key)
                                if raw is None or raw == "":
                                    continue
                                try:
                                    row_unit = row.get("unit") or None
                                    rows_to_track.append((str(row_idx), float(raw), row_idx, row_unit))
                                except (ValueError, TypeError):
                                    continue

                        table_label = field.get("label") or field_key

                        # Sweep-style tables (DFR/SFRA measurements) repeat the
                        # identifier value (e.g. measurement_mode "GST" or
                        # winding "HV-N") across many frequency rows. Such a
                        # table is a curve, not a set of named parameters - no
                        # single point is a meaningful trendable value, and the
                        # repeated ids would violate the (test_result_id,
                        # parameter_key) unique constraint. Skip it; curves are
                        # rendered by the equipment Test Graphs feature instead.
                        row_ids = [e[0] for e in rows_to_track]
                        if len(set(row_ids)) < len(row_ids):
                            continue

                        for row_id, current_val, row_idx, row_unit in rows_to_track:
                            # Build a stable parameter key scoped to this row
                            param_key = f"{field_key}.{row_id}.{col_key}"
                            # Prefixed with the table's own label because row
                            # identifiers (e.g. "B Phase") are only unique
                            # within their own table — a template can have
                            # multiple tables (220kV vs 66kV bushing, etc.)
                            # that reuse the same row names, which otherwise
                            # renders as indistinguishable duplicate entries.
                            row_label = f"{table_label} — {row_id} — {col_label}"

                            # Per-row status (+ breach limit, when the eval
                            # engine flagged this cell) from col_results, or
                            # from row_results (_eval_threshold_table shape)
                            # when this column is the one that rule classifies.
                            row_matches = [
                                r for r in col_results
                                if r.get("column") == col_key
                                and r.get("row") == row_idx
                            ]
                            if not row_matches and col_key == threshold_input_field:
                                row_matches = [
                                    r for r in row_results
                                    if str(r.get("row_id", "")).strip().lower() == row_id.lower()
                                ]
                            status    = next((r.get("status") for r in reversed(row_matches) if r.get("status")), None)
                            row_breach_limit = next((r.get("breach_limit") for r in reversed(row_matches) if r.get("breach_limit") is not None), None)
                            row_remedial_text = next((r.get("remedial_action_text") for r in reversed(row_matches) if r.get("remedial_action_text")), None)
                            condition = condition_labels.get(status, "Poor") if status else None
                            score     = max(0.0, condition_scores.get(condition, 50.0)) if condition else None

                            # Unit: prefer column-level, fall back to per-row unit
                            effective_unit = col_unit or row_unit
                            synth_field = {"key": param_key, "label": row_label}
                            if effective_unit:
                                synth_field["unit"] = effective_unit

                            history  = history_map.get(param_key, [])
                            analysis = ParameterAnalyzer.analyse(
                                history, {},
                                current_value=current_val,
                                current_date=result.tested_at or result.cts,
                            )

                            pa = self._upsert_parameter_analytics(
                                test_result_id  = test_result_id,
                                equipment_id    = equipment_id,
                                organization_id = organization_id,
                                template_key    = template_key,
                                field           = synth_field,
                                current_value   = current_val,
                                condition       = condition,
                                status          = status,
                                score           = score,
                                analysis        = analysis,
                                static_breach_limit = row_breach_limit,
                                remedial_action_text = row_remedial_text,
                            )
                            if pa:
                                param_rows.append(pa)

        # Upsert TestAnalytics
        ta = self._upsert_test_analytics(
            test_result_id      = test_result_id,
            equipment_id        = equipment_id,
            organization_id     = organization_id,
            testing_request_id  = result.testing_request_id,
            template_key        = template_key,
            health_score        = health_score,
            critical_findings   = critical_findings,
            parameter_count     = total_params,
            evaluated_count     = evaluated_count,
        )

        self.db.flush()

        # Propagate up
        self.run_for_equipment(equipment_id)

        return ta

    def run_for_equipment(self, equipment_id: uuid.UUID) -> Optional[EquipmentAnalytics]:
        """
        Aggregate all TestAnalytics for this equipment into EquipmentAnalytics.
        Then triggers department-level aggregation.
        """
        equipment = self.db.get(Equipment, equipment_id)
        if not equipment:
            return None

        from models import TestResult as _TR2, TestingRequest as _TReq, TestingRequestStatus as _TRS, TrWfInstance as _TWI

        _OPEN_STATUSES = {
            _TRS.draft, _TRS.submitted, _TRS.assigned,
            _TRS.accepted, _TRS.in_progress,
        }
        # IDs of TRs that are wf-active (not yet completed)
        _wf_active_tr_ids = {
            row.testing_request_id
            for row in self.db.query(_TWI.testing_request_id)
            .filter(_TWI.status == "active").all()
        }

        all_rows = (
            self.db.query(TestAnalytics)
            .filter(TestAnalytics.equipment_id == equipment_id)
            .order_by(
                TestAnalytics.tested_at.desc().nullslast(),
                TestAnalytics.calculated_at.desc(),
            )
            .all()
        )

        # Filter out analytics whose TR is still open/in-progress
        _tr_id_map: dict = {}
        for _ta in all_rows:
            if _ta.test_result_id not in _tr_id_map:
                _res = self.db.get(_TR2, _ta.test_result_id)
                _tr_id_map[_ta.test_result_id] = _res

        rows = [
            _ta for _ta in all_rows
            if (_res := _tr_id_map.get(_ta.test_result_id)) is not None
            and _res.testing_request is not None
            and _res.testing_request.status not in _OPEN_STATUSES
            and _res.testing_request_id not in _wf_active_tr_ids
        ]

        if not rows:
            return None

        # Keep only the latest analytics per template_key
        seen: set[str] = set()
        latest_per_template: list[TestAnalytics] = []
        for row in rows:
            if row.template_key not in seen:
                seen.add(row.template_key)
                latest_per_template.append(row)

        scores = [float(r.health_score) for r in latest_per_template if r.health_score is not None]
        equipment_score = round(mean(scores), 2) if scores else None

        test_type_scores = {
            r.template_key: {
                "score":     float(r.health_score) if r.health_score is not None else None,
                "risk":      r.risk_level,
                "tested_at": (r.tested_at or r.calculated_at).isoformat() if (r.tested_at or r.calculated_at) else None,
            }
            for r in latest_per_template
        }

        all_findings = []
        for r in latest_per_template:
            for f in (r.critical_findings or []):
                all_findings.append({**f, "template_key": r.template_key})

        # Count parameters at risk from ParameterAnalytics - scoped to the
        # same latest_per_template test results used for equipment_score
        # above, not the equipment's entire history. Unscoped, a parameter
        # that was Poor in one test months ago (since retested and now fine)
        # kept counting forever, and a parameter Poor across several old
        # tests of the same template counted multiple times instead of
        # reflecting its one current state.
        _latest_result_ids = [r.test_result_id for r in latest_per_template]
        at_risk = (
            self.db.query(ParameterAnalytics)
            .filter(
                ParameterAnalytics.equipment_id == equipment_id,
                ParameterAnalytics.test_result_id.in_(_latest_result_ids),
                ParameterAnalytics.condition == "Poor",
            )
            .count()
        ) if _latest_result_ids else 0

        last_test = max(
            (r.calculated_at for r in latest_per_template if r.calculated_at),
            default=None,
        )

        ea = self._upsert_equipment_analytics(
            equipment_id        = equipment_id,
            organization_id     = equipment.organization_id,
            department_id       = equipment.department_id,
            health_score        = equipment_score,
            test_type_scores    = test_type_scores,
            critical_findings   = all_findings,
            parameters_at_risk  = at_risk,
            test_types_assessed = len(latest_per_template),
            last_test_date      = last_test,
        )

        self.db.flush()

        # Propagate up the department hierarchy
        if equipment.department_id:
            self.run_for_department(equipment.department_id)

        return ea

    def _build_children_map(self) -> dict:
        """Load all OrgDepartment rows once and return {parent_id_str: [child_id, ...]}."""
        if not hasattr(self, '_children_map_cache'):
            all_depts = self.db.query(OrgDepartment).all()
            cm: dict = {}
            for d in all_depts:
                if d.parent_department_id:
                    cm.setdefault(str(d.parent_department_id), []).append(d.id)
            self._children_map_cache = cm
        return self._children_map_cache

    def _collect_descendant_dept_ids(self, department_id: uuid.UUID) -> list:
        """Return department_id plus all descendant IDs (breadth-first), using cached map."""
        children_map = self._build_children_map()
        result = [department_id]
        queue  = [department_id]
        while queue:
            current = queue.pop(0)
            for child_id in children_map.get(str(current), []):
                result.append(child_id)
                queue.append(child_id)
        return result

    def run_for_department(self, department_id: uuid.UUID) -> None:
        """
        Aggregate EquipmentAnalytics scores for all equipment in this department
        and all descendant departments, then walk up parent_department_id chain.
        """
        dept = self.db.get(OrgDepartment, department_id)
        if not dept:
            return

        level_type = self._resolve_level_type(dept)

        # Gather equipment from this department AND all descendants (single query)
        all_dept_ids = self._collect_descendant_dept_ids(department_id)
        eq_rows = (
            self.db.query(EquipmentAnalytics)
            .filter(EquipmentAnalytics.department_id.in_(all_dept_ids))
            .all()
        )

        scores = [float(r.health_score) for r in eq_rows if r.health_score is not None]
        dept_score = round(mean(scores), 2) if scores else None

        risk_counts = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
        for r in eq_rows:
            risk_counts[r.risk_level or "Unknown"] = risk_counts.get(r.risk_level, 0) + 1

        self._upsert_hierarchy_analytics(
            department_id        = department_id,
            parent_department_id = dept.parent_department_id,
            organization_id      = dept.organization_id,
            level_type           = level_type,
            health_score         = dept_score,
            equipment_count      = len(eq_rows),
            risk_counts          = risk_counts,
        )

        self.db.flush()

        # Walk up the hierarchy (children_map already cached, no extra DB hit)
        if dept.parent_department_id:
            self.run_for_department(dept.parent_department_id)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_template(
        self, template_key: str, organization_id: Optional[uuid.UUID]
    ) -> Optional[dict]:
        """Load template_data: prefer org-specific, fall back to global."""
        row = (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.template_key == template_key,
                OrgTestTemplate.org_id == organization_id,
            )
            .first()
        )
        if not row:
            row = (
                self.db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.template_key == template_key,
                    OrgTestTemplate.org_id.is_(None),
                )
                .first()
            )
        return row.template_data if row else None

    def _fetch_history_map(
        self,
        equipment_id:    uuid.UUID,
        template_key:    str,
        exclude_result:  uuid.UUID,
        before:          Optional[datetime] = None,
        template_data:   Optional[dict] = None,
    ) -> dict[str, list[tuple[datetime, float]]]:
        """
        Returns {param_key: [(tested_at, value), ...]} sorted oldest-first
        for all historical results of this equipment + template, excluding
        the current test result.

        [before] must be the current test's own tested_at (or cts fallback).
        Without it, "history" means every *other* result regardless of its
        own date - so recomputing an old result would see readings taken
        years after it, scrambling history_count/trend for anything but
        the most recently-recomputed row (e.g. after a bulk recompute that
        doesn't process results in chronological order). Trend analysis
        must only ever look at what came before the point being evaluated.

        [template_data], when given, is used to resolve each table field's
        identifier column from the template's own column definitions - the
        same source of truth run_for_test()'s main loop uses. Without it,
        history built from a plain field_key.row_id.col_key guess (scanning
        the row dict for "the first string column") is unreliable: JSONB
        does not preserve key insertion order, so which column comes first
        when iterating a stored row dict is arbitrary and can silently pick
        a different column (e.g. voltage_kv) than the real identifier
        (e.g. test_configuration) - producing history keys that never match
        the parameter_key the main loop actually generates, so trend/
        history_count silently stay wrong for table fields.
        """
        id_col_map: dict[str, Optional[str]] = {}
        skip_tables: set[str] = set()
        if template_data:
            for section in template_data.get("sections", []):
                for field in section.get("fields", []):
                    if field.get("type") != "table":
                        continue
                    if field.get("analytics_skip"):
                        skip_tables.add(field.get("key", ""))
                        continue
                    cols = field.get("columns", [])
                    id_col_map[field.get("key", "")] = next(
                        (c.get("key") for c in cols
                         if c.get("type") in ("text", "dropdown", "readonly")
                         and c.get("key") not in ("unit", "remarks", "formula")),
                        None,
                    )

        coalesced = func.coalesce(TestResult.tested_at, TestResult.cts)
        q = (
            self.db.query(TestResult)
            .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestResult.template_key     == template_key,
                TestResult.id               != exclude_result,
                TestResult.test_data.isnot(None),
            )
        )
        if before is not None:
            q = q.filter(coalesced < before)
        rows = q.order_by(TestResult.tested_at.asc()).all()

        history_map: dict[str, list[tuple[datetime, float]]] = {}
        for row in rows:
            dt = row.tested_at or row.cts
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            for key, raw in (row.test_data or {}).items():
                if raw is None or raw == "":
                    continue
                try:
                    val = float(raw)
                    history_map.setdefault(key, []).append((dt, val))
                    continue
                except (ValueError, TypeError):
                    pass

                # Table column: raw is a list of row dicts — key per row identifier
                if isinstance(raw, list):
                    if key in skip_tables:
                        continue
                    if key in id_col_map:
                        id_col_hist = id_col_map[key]
                    else:
                        # No template available for this field — fall back to
                        # scanning row dict order (unreliable, see docstring).
                        _ID_SKIP = {"unit", "remarks", "formula"}
                        id_col_hist = None
                        for row_dict in raw:
                            if not isinstance(row_dict, dict):
                                continue
                            for k2, v2 in row_dict.items():
                                if k2 not in _ID_SKIP and isinstance(v2, str) and v2.strip():
                                    id_col_hist = k2
                                    break
                            if id_col_hist:
                                break

                    for row_idx, row_dict in enumerate(raw):
                        if not isinstance(row_dict, dict):
                            continue
                        row_id = str(row_dict.get(id_col_hist, row_idx)).strip() if id_col_hist else str(row_idx)
                        for col_key, col_val in row_dict.items():
                            if col_val is None or col_val == "":
                                continue
                            try:
                                fval = float(col_val)
                                composite = f"{key}.{row_id}.{col_key}"
                                history_map.setdefault(composite, []).append((dt, fval))
                            except (ValueError, TypeError):
                                continue

        return history_map

    def _resolve_level_type(self, dept: OrgDepartment) -> Optional[str]:
        """Attempt to determine hierarchy level from department type."""
        # Walk up to count depth — crude but avoids importing DeptType query
        depth = 0
        current = dept
        while current.parent_department_id and depth < 10:
            depth += 1
            current = self.db.get(OrgDepartment, current.parent_department_id)
            if not current:
                break
        # Typical mapping: depth 0=zone, 1=circle, 2=division, 3=substation
        level_map = {0: "zone", 1: "circle", 2: "division", 3: "substation"}
        return level_map.get(depth, f"level_{depth}")

    # ── Upsert helpers ────────────────────────────────────────────────────────

    def _upsert_parameter_analytics(
        self,
        test_result_id,
        equipment_id,
        organization_id,
        template_key,
        field,
        current_value,
        condition,
        status,
        score,
        analysis,
        static_breach_limit=None,
        remedial_action_text=None,
    ) -> ParameterAnalytics:
        key = field.get("key")
        pa  = (
            self.db.query(ParameterAnalytics)
            .filter(
                ParameterAnalytics.test_result_id == test_result_id,
                ParameterAnalytics.parameter_key  == key,
            )
            .first()
        )
        if not pa:
            pa = ParameterAnalytics(
                id              = uuid.uuid4(),
                test_result_id  = test_result_id,
                equipment_id    = equipment_id,
                organization_id = organization_id,
                template_key    = template_key,
                parameter_key   = key,
            )
            self.db.add(pa)

        pa.parameter_label    = field.get("label", key)
        pa.parameter_type     = field.get("type")
        pa.current_value      = current_value
        pa.unit               = field.get("unit")
        pa.condition          = condition
        pa.status             = status
        pa.score              = score
        def _clamp(v, lo, hi):
            return None if v is None else max(lo, min(hi, v))

        pa.trend              = analysis.get("trend")
        pa.trend_slope        = analysis.get("trend_slope")
        pa.trend_r_squared    = analysis.get("trend_r_squared")
        pa.history_count      = analysis.get("history_count", 0)
        pa.annual_change      = analysis.get("annual_change")
        # NUMERIC(8,2) → max ±999999.99
        pa.pct_change_annual  = _clamp(analysis.get("pct_change_annual"), -999999.99, 999999.99)
        # Prefer the static evaluation-rule limit (the fixed pass/fail line
        # from the template, e.g. "alert above 0.7%") over the trend-forecast
        # crossing value - it's what "is above the alert limit of X" on the
        # UI card actually means. The forecast one (when will the current
        # trend cross a limit) is a different, narrower signal that's often
        # unset (needs a non-zero slope), which is why this field showed no
        # number at all for ALERT-status parameters before this fix.
        pa.breach_threshold   = (
            static_breach_limit
            if static_breach_limit is not None
            else analysis.get("breach_threshold")
        )
        pa.breach_predicted_at= analysis.get("breach_predicted_at")
        pa.days_to_breach     = analysis.get("days_to_breach")
        pa.is_anomaly         = analysis.get("is_anomaly", False)
        pa.anomaly_type       = analysis.get("anomaly_type")
        pa.anomaly_detail     = analysis.get("anomaly_detail")
        pa.remedial_action_text = remedial_action_text
        pa.calculated_at      = datetime.now(timezone.utc)
        return pa

    def _upsert_test_analytics(
        self,
        test_result_id,
        equipment_id,
        organization_id,
        testing_request_id,
        template_key,
        health_score,
        critical_findings,
        parameter_count,
        evaluated_count,
    ) -> TestAnalytics:
        ta = (
            self.db.query(TestAnalytics)
            .filter(TestAnalytics.test_result_id == test_result_id)
            .first()
        )
        if not ta:
            ta = TestAnalytics(
                id             = uuid.uuid4(),
                test_result_id = test_result_id,
                equipment_id   = equipment_id,
                organization_id= organization_id,
            )
            self.db.add(ta)

        ta.testing_request_id= testing_request_id
        ta.template_key      = template_key
        ta.health_score      = health_score
        ta.risk_level        = _risk_from_score(health_score, critical_findings, self.db)
        ta.condition_summary = _condition_from_score(health_score)
        ta.critical_findings = critical_findings
        ta.parameter_count   = parameter_count
        ta.evaluated_count   = evaluated_count
        # Resolve actual test date: prefer test_result.tested_at, fall back to requested_date
        tr = self.db.get(TestResult, test_result_id) if test_result_id else None
        req = self.db.get(TestingRequest, testing_request_id) if testing_request_id else None
        ta.tested_at = (
            (tr.tested_at if tr and tr.tested_at else None)
            or (req.requested_date if req and req.requested_date else None)
        )
        ta.calculated_at     = datetime.now(timezone.utc)
        return ta

    def _upsert_equipment_analytics(
        self,
        equipment_id,
        organization_id,
        department_id,
        health_score,
        test_type_scores,
        critical_findings,
        parameters_at_risk,
        test_types_assessed,
        last_test_date,
    ) -> EquipmentAnalytics:
        ea = (
            self.db.query(EquipmentAnalytics)
            .filter(EquipmentAnalytics.equipment_id == equipment_id)
            .first()
        )
        if not ea:
            ea = EquipmentAnalytics(
                id           = uuid.uuid4(),
                equipment_id = equipment_id,
            )
            self.db.add(ea)

        ea.organization_id     = organization_id
        ea.department_id       = department_id
        ea.health_score        = health_score
        ea.risk_level          = _risk_from_score(health_score, critical_findings, self.db)
        ea.condition_summary   = _condition_from_score(health_score)
        ea.test_type_scores    = test_type_scores
        ea.critical_findings   = critical_findings
        ea.parameters_at_risk  = parameters_at_risk
        ea.test_types_assessed = test_types_assessed
        ea.last_test_date      = last_test_date
        ea.calculated_at       = datetime.now(timezone.utc)
        return ea

    def _upsert_hierarchy_analytics(
        self,
        department_id,
        parent_department_id,
        organization_id,
        level_type,
        health_score,
        equipment_count,
        risk_counts,
    ) -> HierarchyAnalytics:
        ha = (
            self.db.query(HierarchyAnalytics)
            .filter(HierarchyAnalytics.department_id == department_id)
            .first()
        )
        if not ha:
            ha = HierarchyAnalytics(
                id            = uuid.uuid4(),
                department_id = department_id,
            )
            self.db.add(ha)

        ha.parent_department_id = parent_department_id
        ha.organization_id      = organization_id
        ha.level_type           = level_type
        ha.health_score         = health_score
        ha.risk_level           = _risk_from_score(health_score, db=self.db)
        ha.equipment_count      = equipment_count
        ha.equipment_critical   = risk_counts.get("Critical", 0)
        ha.equipment_high       = risk_counts.get("High", 0)
        ha.equipment_medium     = risk_counts.get("Medium", 0)
        ha.equipment_low        = risk_counts.get("Low", 0)
        ha.calculated_at        = datetime.now(timezone.utc)
        return ha
