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

from sqlalchemy import text
from sqlalchemy.orm import Session

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
NORMAL   = "NORMAL"
ALERT    = "ALERT"
CRITICAL = "CRITICAL"

_CONDITION = {NORMAL: "Good", ALERT: "Fair", CRITICAL: "Poor"}
_SCORE     = {"Good": 100.0, "Fair": 50.0, "Poor": 0.0}
_RANK      = {NORMAL: 0, ALERT: 1, CRITICAL: 2}

_RISK_BANDS = [
    (80, "Low"),
    (50, "Medium"),
    (25, "High"),
    (0,  "Critical"),
]


def _risk_from_score(score: Optional[float]) -> str:
    if score is None:
        return "Unknown"
    for threshold, label in _RISK_BANDS:
        if score >= threshold:
            return label
    return "Critical"


def _condition_from_score(score: Optional[float]) -> str:
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
    MIN_TREND_POINTS = 3
    # Slope considered "stable" if |slope * 365| < this fraction of the value range
    STABLE_FRACTION  = 0.05
    # Z-score threshold for anomaly
    ANOMALY_Z        = 3.0

    @staticmethod
    def analyse(
        history: list[tuple[datetime, float]],
        evaluation: dict,
    ) -> dict:
        """
        history  : [(tested_at, float_value), ...] sorted oldest-first
        evaluation: the field's `evaluation` dict from template

        Returns a dict with trend, slope, r_squared, annual_change,
        pct_change_annual, breach_threshold, breach_predicted_at,
        days_to_breach, is_anomaly, anomaly_type, anomaly_detail,
        history_count.
        """
        result: dict = {
            "history_count":      len(history),
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

        # Anomaly detection (needs ≥ 4 values for meaningful std)
        if len(values) >= 4:
            ParameterAnalyzer._detect_anomaly(values, result)

        if len(history) < ParameterAnalyzer.MIN_TREND_POINTS:
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
        if annual_change > stable_threshold:
            result["trend"] = "Increasing"
        elif annual_change < -stable_threshold:
            result["trend"] = "Decreasing"
        else:
            result["trend"] = "Stable"

        # Breach forecast — only if slope is non-zero and we have thresholds
        if slope != 0:
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
    ) -> tuple[float, list[dict]]:
        """
        Returns (health_score 0–100, critical_findings list).

        evaluation_result is the JSONB stored in TestResult.evaluation_result,
        which has {overall, fields: [{key, label, status, ...}]}.
        """
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
        for fkey, status in field_statuses.items():
            field = field_defs.get(fkey, {})

            # Weight: read from whichever eval block is present, default 1.0
            ev = (
                field.get("evaluation")
                or field.get("table_evaluation")
                or field.get("dropdown_evaluation")
                or field.get("date_evaluation")
                or {}
            )
            weight    = float(ev.get("weight", 1.0))
            condition = _CONDITION.get(status, "Poor")
            score     = _SCORE.get(condition, 0.0)

            weighted_sum  += score  * weight
            total_weight  += weight

            if condition == "Poor":
                critical_findings.append({
                    "key":       fkey,
                    "label":     field.get("label", fkey),
                    "condition": condition,
                    "status":    status,
                    "unit":      field.get("unit"),
                })

        if total_weight == 0:
            return None, critical_findings

        return round(weighted_sum / total_weight, 2), critical_findings


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

        # Load template
        template_data = self._load_template(template_key, organization_id)
        if not template_data:
            logger.warning("run_for_test: template '%s' not found", template_key)
            return None

        # Load historical test data for trend analysis
        history_map = self._fetch_history_map(equipment_id, template_key, test_result_id)

        # Score the test
        health_score, critical_findings = HealthScorer.score_test(
            template_data, evaluation_result
        )

        evaluated_count = len(evaluation_result.get("fields", []))
        total_params    = sum(
            len(s.get("fields", [])) for s in template_data.get("sections", [])
        )

        # Per-parameter analytics
        param_rows: list[ParameterAnalytics] = []
        for section in template_data.get("sections", []):
            for field in section.get("fields", []):
                field_type = field.get("type", "text")
                if field_type != "number":
                    continue  # trend analysis only for numeric fields currently
                ev = field.get("evaluation") or {}
                if not ev.get("enabled"):
                    continue

                key   = field.get("key")
                raw   = test_data.get(key)
                if raw is None or raw == "":
                    continue

                try:
                    current_val = float(raw)
                except (ValueError, TypeError):
                    continue

                # Find status from evaluation_result
                field_ev = next(
                    (f for f in evaluation_result.get("fields", []) if f.get("key") == key),
                    None,
                )
                status    = field_ev.get("status") if field_ev else None
                condition = _CONDITION.get(status, "Poor") if status else None
                score     = _SCORE.get(condition, 50.0) if condition else None

                # Historical data for trend
                history = history_map.get(key, [])
                analysis = ParameterAnalyzer.analyse(history, ev)

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

        rows = (
            self.db.query(TestAnalytics)
            .filter(TestAnalytics.equipment_id == equipment_id)
            .order_by(TestAnalytics.calculated_at.desc())
            .all()
        )

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
                "tested_at": r.calculated_at.isoformat() if r.calculated_at else None,
            }
            for r in latest_per_template
        }

        all_findings = []
        for r in latest_per_template:
            for f in (r.critical_findings or []):
                all_findings.append({**f, "template_key": r.template_key})

        # Count parameters at risk from ParameterAnalytics
        at_risk = (
            self.db.query(ParameterAnalytics)
            .filter(
                ParameterAnalytics.equipment_id == equipment_id,
                ParameterAnalytics.condition == "Poor",
            )
            .count()
        )

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
    ) -> dict[str, list[tuple[datetime, float]]]:
        """
        Returns {param_key: [(tested_at, value), ...]} sorted oldest-first
        for all historical results of this equipment + template, excluding
        the current test result.
        """
        rows = (
            self.db.query(TestResult)
            .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestResult.template_key     == template_key,
                TestResult.id               != exclude_result,
                TestResult.test_data.isnot(None),
            )
            .order_by(TestResult.tested_at.asc())
            .all()
        )

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
                except (ValueError, TypeError):
                    continue
                history_map.setdefault(key, []).append((dt, val))

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
        pa.trend              = analysis.get("trend")
        pa.trend_slope        = analysis.get("trend_slope")
        pa.trend_r_squared    = analysis.get("trend_r_squared")
        pa.history_count      = analysis.get("history_count", 0)
        pa.annual_change      = analysis.get("annual_change")
        pa.pct_change_annual  = analysis.get("pct_change_annual")
        pa.breach_threshold   = analysis.get("breach_threshold")
        pa.breach_predicted_at= analysis.get("breach_predicted_at")
        pa.days_to_breach     = analysis.get("days_to_breach")
        pa.is_anomaly         = analysis.get("is_anomaly", False)
        pa.anomaly_type       = analysis.get("anomaly_type")
        pa.anomaly_detail     = analysis.get("anomaly_detail")
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
        ta.risk_level        = _risk_from_score(health_score)
        ta.condition_summary = _condition_from_score(health_score)
        ta.critical_findings = critical_findings
        ta.parameter_count   = parameter_count
        ta.evaluated_count   = evaluated_count
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
        ea.risk_level          = _risk_from_score(health_score)
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
        ha.risk_level           = _risk_from_score(health_score)
        ha.equipment_count      = equipment_count
        ha.equipment_critical   = risk_counts.get("Critical", 0)
        ha.equipment_high       = risk_counts.get("High", 0)
        ha.equipment_medium     = risk_counts.get("Medium", 0)
        ha.equipment_low        = risk_counts.get("Low", 0)
        ha.calculated_at        = datetime.now(timezone.utc)
        return ha
