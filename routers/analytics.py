"""
Analytics API Router
====================

Drill-down chain:

  Zone / Circle / Division analytics
    GET /analytics/departments/{id}                    ← node KPIs
    GET /analytics/departments/{id}/tree               ← node + one level of child nodes
    GET /analytics/departments/{id}/equipment          ← every equipment in this dept (with scores)

  Equipment analytics
    GET /analytics/equipment/{id}                      ← aggregated health
    GET /analytics/equipment/{id}/tests                ← test history (all templates, latest-first)
    GET /analytics/equipment/{id}/parameters           ← latest param analytics (all templates)
    GET /analytics/equipment/{id}/parameters/{key}/history
                                                       ← time-series of one parameter across all tests

  Test-result analytics
    GET  /analytics/test-results/{id}                  ← test-level scores + findings
    GET  /analytics/test-results/{id}/raw              ← test-level scores + actual test_data JSONB

  Trigger / recompute
    POST /analytics/test-results/{id}/run
    POST /analytics/equipment/{id}/run
"""

import uuid
import re
import logging
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from types import SimpleNamespace
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import asc, func
from sqlalchemy.orm import Session, joinedload

import config
from database import get_vendor_db
from auth_utils import get_current_user
from models import (
    CategoryMaster,
    Equipment,
    User,
    EquipmentAnalytics,
    EquipmentCriticalityMapping,
    HierarchyAnalytics,
    OrgDepartment,
    OrgTestTemplate,
    OverhaulRecommendation,
    ParameterAnalytics,
    ParameterThresholdBand,
    DeteriorationReviewRecord,
    RepairWorkflow,
    TestAnalytics,
    TestResult,
    TestingRequest,
)
from services.condition_recommendation_service import evaluate_for_equipment
from services.analytics_engine import AnalyticsEngine, _risk_from_score, _load_risk_bands, _load_band_rank_words
from category_labels import RiskLevelColors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

_CAPACITY_NUM_RE = re.compile(r"[\d.]+")


def _severity_order_labels(db: Session) -> list[str]:
    """Risk-band labels, worst first (Critical..Low by default) — derived
    from EquipmentHealthBandThreshold (services/analytics_engine.py's
    _load_risk_bands, which already reads that table) rather than a second
    independent hardcoded list. _load_risk_bands returns highest-threshold
    (least severe) first; reversed here for "worst first" ordering.

    Reused for both the Condition Risk Matrix's axis labels and equipment
    worst-first sort order — those two concerns (which band names exist,
    and which order counts as "worse") previously lived in two more
    separate hardcoded copies (CRITICALITY_TIERS/HEALTH_BANDS and
    _risk_order) that could silently drift out of sync with each other and
    with the admin-configurable table if, say, an admin renamed a band.
    """
    return [label for _, label in reversed(_load_risk_bands(db))]


def _severity_rank_map(db: Session) -> dict[str, int]:
    """{label: rank} from _severity_order_labels, 0 = most severe."""
    return {label: i for i, label in enumerate(_severity_order_labels(db))}


# ── Table-based threshold breach forecasting (ParameterThresholdBand) ──────
# Real fix for the Deterioration Watch List's original gap: it could tell a
# parameter was trending, but not whether that trend was actually heading
# toward a real problem, because services/analytics_engine.py's breach-
# forecast logic only reads a flat evaluation dict (alert_min/alert_max/
# etc) — table-row tests (oil tests, DGA, most others: this app's dominant
# real pattern) store their thresholds keyed by row/parameter name instead,
# a shape that logic never reads, so days_to_breach was effectively always
# None for them. ParameterThresholdBand (alter_parameter_threshold_band.py)
# is a flattened, queryable projection of those same table-row threshold
# configs; the functions below use it to compute a real breach distance
# on demand, without touching the core engine or needing a full recompute.

def _band_rank(label: str, rank_words: dict[str, int]) -> int:
    """0 = best band, higher = worse. rank_words comes from
    services/analytics_engine.py's _load_band_rank_words (admin-configured
    ConditionBandRankWord table, same word-matching convention
    services/evaluation_service.py's own _cond_rank uses) — not a
    hardcoded copy, so a template's bands are ranked the same way here as
    they are at test-evaluation time, from the same source."""
    low = (label or "").lower()
    for word, rank in rank_words.items():
        if word in low:
            return rank
    return 1  # unrecognized band name — treat as a middle tier, not best/worst


_VOLTAGE_CONTEXT_RE = [
    (re.compile(r"^>\s*([\d.]+)\s*kV$", re.I), lambda v, lo: v > lo),
    (re.compile(r"^<=\s*([\d.]+)\s*kV$", re.I), lambda v, lo: v <= lo),
]
_VOLTAGE_RANGE_RE = re.compile(r"^([\d.]+)\s*-\s*([\d.]+)\s*kV$", re.I)


def _resolve_context_key(context_keys: list[str], voltage_class: str | None) -> str | None:
    """Picks which context_key applies to this equipment. If the available
    context_keys look like voltage bands (>170kV, 72.5-170kV, <=72.5kV —
    the oil-test template's own shape), matches the equipment's own
    voltage_class against them directly from the label text, without
    needing a separate hardcoded copy of the template's voltage->bucket
    mapping. Falls back to the first available context otherwise (e.g.
    DGA's context_key is a calibration standard name, not a voltage band —
    same fallback services/evaluation_service.py's own _eval_threshold_table
    uses when it can't resolve a sub_key)."""
    if not context_keys:
        return None
    try:
        v = float(str(voltage_class)) if voltage_class else None
    except (TypeError, ValueError):
        v = None
    if v is not None:
        for ck in context_keys:
            for pattern, test in _VOLTAGE_CONTEXT_RE:
                m = pattern.match(ck.strip())
                if m and test(v, float(m.group(1))):
                    return ck
            m = _VOLTAGE_RANGE_RE.match(ck.strip())
            if m and float(m.group(1)) < v <= float(m.group(2)):
                return ck
    return context_keys[0]


def _table_row_id(parameter_key: str) -> str:
    """ParameterAnalytics.parameter_key for a table-row field is a 3-part
    composite key: "{table_field_key}.{row_id}.{column_key}" (confirmed
    live, e.g. "oil_test_results.Acidity.measured_value"). Extracts just
    the row_id — what ParameterThresholdBand.parameter_key stores — since
    a flat field's parameter_key has no dots and passes through unchanged."""
    parts = parameter_key.split(".")
    return parts[1] if len(parts) == 3 else parameter_key


def _next_worse_boundary(bands: list, current_value: float, slope_per_day: float,
                          rank_words: dict[str, int]):
    """Returns (breach_value, band_label) for the next threshold boundary
    this parameter will cross, moving in slope_per_day's direction, into a
    WORSE band than the one current_value is in now — or (None, None) if
    there isn't one (already in the worst band, or trending toward a
    better one, not a worse one)."""
    def lb(r):
        return float(r.lower_bound) if r.lower_bound is not None else float("-inf")

    def ub(r):
        return float(r.upper_bound) if r.upper_bound is not None else float("inf")

    sorted_bands = sorted(bands, key=lb)
    current_rank = None
    for r in sorted_bands:
        if lb(r) <= current_value < ub(r):
            current_rank = _band_rank(r.band_label, rank_words)
            break
    if current_rank is None:
        # current_value outside every defined range — treat as whichever
        # end it's beyond (already past the last band's bound, or below
        # the first's).
        edge = sorted_bands[-1] if current_value >= lb(sorted_bands[-1]) else sorted_bands[0]
        current_rank = _band_rank(edge.band_label, rank_words)

    if slope_per_day > 0:
        for r in sorted_bands:
            if lb(r) > current_value and _band_rank(r.band_label, rank_words) > current_rank:
                return lb(r), r.band_label
    elif slope_per_day < 0:
        for r in reversed(sorted_bands):
            if ub(r) <= current_value and _band_rank(r.band_label, rank_words) > current_rank:
                return ub(r), r.band_label
    return None, None


def _parse_capacity_mva(raw) -> float | None:
    """Parse values like '100MVA', '167.5MVA', '' into a float, or None."""
    if not raw:
        return None
    m = _CAPACITY_NUM_RE.search(str(raw))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _capacity_bucket(mva) -> str:
    """Return a display-friendly MVA capacity label (mirrors ai_graph.py's
    bucket boundaries so both dashboards group equipment the same way)."""
    if mva is None:
        return "Unknown"
    try:
        v = float(mva)
    except (TypeError, ValueError):
        return "Unknown"
    if v < 10:    return "< 10 MVA"
    if v < 50:    return "10–50 MVA"
    if v < 100:   return "50–100 MVA"
    if v < 200:   return "100–200 MVA"
    return "200+ MVA"


def _eq_capacity_map(eq_ids: list, db: Session) -> dict:
    """Resolve each equipment's capacity (MVA), keyed by equipment_id.
    Equipment.nameplate_data doesn't carry this for the actual fleet (only a
    handful of portable testing kits have any nameplate_data at all) —
    capacity is captured per-test instead, inside
    TestResult.test_data['capacity_mva'] (e.g. "100MVA"). Uses each
    equipment's most recent test that has a parseable value."""
    if not eq_ids:
        return {}
    # Ordered so the first row seen per equipment is deterministically its
    # most recent test (tiebroken by TestResult.id) - previously unordered,
    # so on two tests dated the same day the "most recent" pick was whatever
    # order Postgres happened to return, and could flip between calls.
    rows = db.query(
        TestingRequest.equipment_id, TestResult.test_data,
    ).join(TestResult, TestResult.testing_request_id == TestingRequest.id).filter(
        TestingRequest.equipment_id.in_(eq_ids),
    ).order_by(
        TestingRequest.equipment_id,
        func.coalesce(TestResult.tested_at, TestResult.cts).desc(),
        TestResult.id.desc(),
    ).all()
    best: dict = {}
    for eq_id, test_data in rows:
        if eq_id in best:
            continue
        mva = _parse_capacity_mva((test_data or {}).get("capacity_mva"))
        if mva is not None:
            best[eq_id] = mva
    return best


# Cumulative operations-counter templates (enable_cumulative=True on the
# backend) - these track a running counter (tap-change count, breaker
# operations count) rather than a one-off lab measurement, and have their own
# workflow elsewhere in the app. They always have test_category == NULL, same
# as genuine lab tests, so they can't be excluded by test_category alone.
# Mirrors the Flutter AI Analytics modal's _nonLabTemplateKeys.
_NON_LAB_TEMPLATE_KEYS = {"oltc_operations", "circuit_breaker_operations"}


def _lab_only_scores(eq_ids: list, db: Session) -> dict:
    """
    Recompute a lab-tests-only health_score/risk_level/critical_findings per
    equipment, for the AI Analytics equipment list - matching the same
    exclusion the AI Analytics modal's chip row applies (TA&QC/Failure
    Registry direct submissions, identified by a non-null test_category, and
    cumulative-counter templates in _NON_LAB_TEMPLATE_KEYS). Returns
    {equipment_id: (score, risk_level, critical_findings)}; equipment whose
    only tests are excluded types get (None, "Unknown", []) - same as
    genuinely untested equipment, since AI Analytics has nothing lab-based to
    show for them.
    """
    if not eq_ids:
        return {}

    rows = (
        db.query(TestAnalytics)
        .join(TestResult, TestResult.id == TestAnalytics.test_result_id)
        .filter(TestAnalytics.equipment_id.in_(eq_ids))
        .order_by(
            TestAnalytics.equipment_id,
            TestAnalytics.template_key,
            func.coalesce(TestResult.tested_at, TestResult.cts).desc(),
            TestAnalytics.calculated_at.desc(),
            # Final deterministic tiebreak - same reasoning as
            # get_equipment_test_types()'s identical tiebreak.
            TestAnalytics.id.desc(),
        )
        .all()
    )

    result_ids = [r.test_result_id for r in rows]
    tr_map = {
        r.id: r
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    } if result_ids else {}

    # Dedupe to the latest row per (equipment_id, template_key)
    seen: set = set()
    latest: list[TestAnalytics] = []
    for row in rows:
        key = (row.equipment_id, row.template_key)
        if key not in seen:
            seen.add(key)
            latest.append(row)

    by_equipment: dict = {}
    for row in latest:
        by_equipment.setdefault(row.equipment_id, []).append(row)

    out: dict = {}
    for eq_id, eq_rows in by_equipment.items():
        lab_rows = [
            r for r in eq_rows
            if r.template_key not in _NON_LAB_TEMPLATE_KEYS
            and (tr_map.get(r.test_result_id) is None
                 or tr_map[r.test_result_id].test_category is None)
        ]
        scores = [float(r.health_score) for r in lab_rows if r.health_score is not None]
        score = round(mean(scores), 2) if scores else None
        findings = [f for r in lab_rows for f in (r.critical_findings or [])]
        risk = _risk_from_score(score, findings, db)
        out[eq_id] = (score, risk, findings)
    return out


def _build_dept_rollup(equipment_list: list, scope_dept_id, db) -> dict:
    """Return {child_dept_id: count} rollup for a list of equipment objects."""
    counts: dict = {}
    if not equipment_list:
        return counts
    if scope_dept_id:
        children = db.query(OrgDepartment.id).filter(
            OrgDepartment.parent_department_id == scope_dept_id).all()
        child_ids = [r[0] for r in children]
        dept_to_child: dict = {}
        for cid in child_ids:
            for did in _collect_department_ids(cid, db):
                dept_to_child[did] = cid
        for eq in equipment_list:
            if eq.department_id:
                cid = dept_to_child.get(eq.department_id)
                if cid:
                    ck = str(cid)
                    counts[ck] = counts.get(ck, 0) + 1
    else:
        roots = db.query(OrgDepartment.id).filter(
            OrgDepartment.parent_department_id.is_(None)).all()
        dept_to_root: dict = {}
        for (rid,) in roots:
            for did in _collect_department_ids(rid, db):
                dept_to_root[did] = rid
        for eq in equipment_list:
            if eq.department_id:
                rid = dept_to_root.get(eq.department_id)
                if rid:
                    rk = str(rid)
                    counts[rk] = counts.get(rk, 0) + 1
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Asset Dashboard breakdown endpoint — all groupings in one DB round-trip
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/asset-breakdown", summary="Asset Dashboard grouping counts (voltage, type, make, year, dept)")
def get_asset_breakdown(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from:      Optional[date]      = Query(None, description="Filter test counts to TestResult.tested_at >= this date (YYYY-MM-DD)"),
    date_to:        Optional[date]      = Query(None, description="Filter test counts to TestResult.tested_at <= this date (YYYY-MM-DD)"),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns all grouping aggregations needed by the Asset Dashboard in one call:
      - by_voltage_class  : { "220": 450, "400": 380, ... }
      - by_type           : { "Power Transformer": 600, ... }
      - by_make           : { "ABB": 320, ... }
      - by_commissioned_year: { "2020": 150, ... }
      - by_capacity_mva   : { "10-50 MVA": 200, ... }
      - dept_equipment_counts: { "<dept-id>": 120, ... }  (direct children)
      - total             : total equipment count in scope
    """
    org_id   = user.get("organization_id") if isinstance(user, dict) else getattr(user, "organization_id", None)
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    # Resolve Testing Kit category IDs to exclude from asset counts
    testkit_type_ids = {
        c.id for c in db.query(CategoryMaster.id)
        .filter(CategoryMaster.name.ilike("%testing kit%"))
        .all()
        if c.id
    }

    # Active equipment — split into real assets vs test kits
    active_q = db.query(Equipment).filter(Equipment.status != "retired")
    if org_id:
        active_q = active_q.filter(Equipment.organization_id == org_id)
    if dept_ids:
        active_q = active_q.filter(Equipment.department_id.in_(dept_ids))
    _all_active: list[Equipment] = active_q.all()

    all_eq    = [e for e in _all_active if e.equipment_type_id not in testkit_type_ids]
    testkit_eq = [e for e in _all_active if e.equipment_type_id in testkit_type_ids]

    # Equipment added this month (cts = created timestamp)
    from datetime import date as _date
    _today = _date.today()
    added_this_month = sum(
        1 for eq in all_eq
        if eq.cts and eq.cts.month == _today.month and eq.cts.year == _today.year
    )

    # Retired equipment for failure-year breakdown
    retired_q = db.query(Equipment).filter(Equipment.status == "retired")
    if org_id:
        retired_q = retired_q.filter(Equipment.organization_id == org_id)
    if dept_ids:
        retired_q = retired_q.filter(Equipment.department_id.in_(dept_ids))
    retired_eq: list[Equipment] = retired_q.all()

    # Bulk-fetch type names
    type_ids = list({e.equipment_type_id for e in all_eq if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    } if type_ids else {}

    # Fetch analytics for health distribution per group
    eq_ids_all = [e.id for e in all_eq]
    ea_rows = db.query(EquipmentAnalytics).filter(
        EquipmentAnalytics.equipment_id.in_(eq_ids_all)
    ).all() if eq_ids_all else []
    ea_map = {r.equipment_id: r for r in ea_rows}

    # This endpoint is AI Analytics-specific (the only caller is the AI
    # Analytics Dashboard) - the all-time health/risk fallback below must
    # exclude the same TA&QC/Failure Registry/cumulative-counter test types
    # the equipment list and the modal do, or this endpoint's group rollups
    # (e.g. a "Power Transformer" row's Critical/Healthy counts) disagree
    # with the individual equipment rows shown underneath it.
    lab_map = _lab_only_scores(eq_ids_all, db)
    lab_ea_map = {
        eq_id: SimpleNamespace(health_score=score, risk_level=risk)
        for eq_id, (score, risk, _findings) in lab_map.items()
    }

    def _empty_health() -> dict:
        return {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0,
                "untested": 0, "sum": 0.0, "cnt": 0}

    def _add_health(bucket: dict, eq_id, tested: bool, source=None) -> None:
        """Fold one equipment into exactly one bucket, so critical + high +
        medium + low + unknown + untested always equals the group's total
        asset count. `tested` = has a qualifying completed test (in-range
        when a date filter is active, ever otherwise); equipment with no
        analytics row yet (never assessed) always lands in "untested"
        regardless. `source` supplies risk_level/health_score — a date-scoped
        TestAnalytics snapshot when a range is active; falls back to the
        all-time lab_ea_map lookup (lab-tests-only score/risk) when omitted.

        Four real bands (Critical/High/Medium/Low), not the previous
        Critical/High/"everything else called Healthy" — that collapsed
        Medium into the same bucket as Low, which visibly disagreed with
        the Condition Risk Matrix's own Critical/High/Medium/Low breakdown
        for the same equipment (confirmed live: 220kV BIAL Begur showed
        "4 Healthy" here while the matrix correctly showed 2 Medium + 2 Low).
        """
        src = source if source is not None else lab_ea_map.get(eq_id)
        if tested and src:
            rl = (src.risk_level or "").strip()
            if rl == "Critical":
                bucket["critical"] += 1
            elif rl == "High":
                bucket["high"] += 1
            elif rl == "Medium":
                bucket["medium"] += 1
            elif rl == "Low":
                bucket["low"] += 1
            else:
                bucket["unknown"] += 1
            if src.health_score is not None:
                bucket["sum"] += float(src.health_score)
                bucket["cnt"] += 1
        else:
            bucket["untested"] += 1

    def _finalise(bucket: dict) -> dict:
        return {
            "critical":   bucket["critical"],
            "high":       bucket["high"],
            "medium":     bucket["medium"],
            "low":        bucket["low"],
            "unknown":    bucket["unknown"],
            "untested":   bucket["untested"],
            "avg_health": round(bucket["sum"] / bucket["cnt"], 1) if bucket["cnt"] > 0 else None,
        }

    by_voltage:       dict[str, int]  = {}
    by_voltage_h:     dict[str, dict] = {}
    by_type:          dict[str, int]  = {}
    by_type_h:        dict[str, dict] = {}
    by_make:          dict[str, int]  = {}
    by_make_h:        dict[str, dict] = {}
    by_make_model:    dict[str, int]  = {}
    by_make_model_h:  dict[str, dict] = {}
    by_year:          dict[str, int]  = {}
    by_year_h:        dict[str, dict] = {}
    by_capacity:      dict[str, int]  = {}
    by_capacity_h:    dict[str, dict] = {}
    by_failure_year:  dict[str, int]  = {}
    by_failure_year_h: dict[str, dict] = {}
    by_replacement_year:  dict[str, int]  = {}
    by_replacement_year_h: dict[str, dict] = {}

    _date_filter_active = bool(date_from or date_to)

    # Test counts per equipment — completed/closed requests only, so this
    # matches the definition of "a conducted test" used by /analytics/dashboard
    # (kpi_summary.total_tests) and /analytics/dashboard/equipment. Without
    # this filter, in-progress/draft requests were being counted here but not
    # there, making the two endpoints' totals silently disagree.
    eq_id_set = {e.id for e in all_eq}
    # by_failure_year (below) looks up test counts for retired_eq, not all_eq —
    # eq_id_set alone would leave retired equipment's tests uncounted, so the
    # "Year of failure" test breakdown was always empty. Union both sets here.
    test_count_id_set = eq_id_set | {e.id for e in retired_eq}
    if test_count_id_set:
        tc_q = db.query(TestingRequest.equipment_id, func.count(func.distinct(TestingRequest.id))) \
            .filter(
                TestingRequest.equipment_id.in_(test_count_id_set),
                TestingRequest.status.in_(("completed", "closed")),
            )
        tc_q = _apply_tested_at_filter(tc_q, date_from, date_to)
        tc_rows_all = tc_q.group_by(TestingRequest.equipment_id).all()
    else:
        tc_rows_all = []
    eq_test_counts: dict = {str(r[0]): r[1] for r in tc_rows_all}
    eq_capacity_map = _eq_capacity_map(list(eq_id_set), db)

    # Per-test analytics snapshot dated within the selected range (latest one
    # per equipment) — mirrors /analytics/ai-graph/grouped's "assessed in
    # this period" definition, so the two dashboards agree on which equipment
    # counts as tested/healthy for the same scope and date range, instead of
    # this endpoint's looser "any completed test in range + any
    # EquipmentAnalytics row ever" check.
    dated_ta_map: dict = {}
    if _date_filter_active and eq_id_set:
        coalesced = func.coalesce(TestResult.tested_at, TestResult.cts)
        ta_q = (
            db.query(TestAnalytics, coalesced.label("eff_date"))
            .join(TestResult, TestResult.id == TestAnalytics.test_result_id)
            .filter(
                TestAnalytics.equipment_id.in_(eq_id_set),
                # This endpoint is AI Analytics-specific - exclude the same
                # TA&QC/Failure Registry/cumulative-counter test types the
                # equipment list (/dashboard/equipment) and the modal do, so
                # a date-scoped snapshot here can't pick an excluded test as
                # "the" latest test and disagree with everywhere else.
                TestAnalytics.template_key.notin_(_NON_LAB_TEMPLATE_KEYS),
                TestResult.test_category.is_(None),
            )
        )
        if date_from:
            ta_q = ta_q.filter(coalesced >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            ta_q = ta_q.filter(coalesced < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
        _best: dict = {}
        for ta, eff_date in ta_q.all():
            if eff_date is None:
                continue
            cur = _best.get(ta.equipment_id)
            if cur is None or eff_date > cur[1]:
                _best[ta.equipment_id] = (ta, eff_date)
        dated_ta_map = {eq_id: pair[0] for eq_id, pair in _best.items()}

    # Test groupings (parallel to asset groupings). The "_tests" maps count
    # distinct EQUIPMENT tested (so they reconcile with critical/high/healthy/
    # untested); the "_test_events" maps count raw test occurrences (an
    # equipment tested 3 times contributes 3), shown alongside as extra
    # context, e.g. "43 equipment (58 tests)".
    by_make_tests:         dict[str, int] = {}
    by_make_model_tests:   dict[str, int] = {}
    by_type_tests:         dict[str, int] = {}
    by_voltage_tests:      dict[str, int] = {}
    by_year_tests:         dict[str, int] = {}
    by_capacity_tests:     dict[str, int] = {}
    by_failure_year_tests: dict[str, int] = {}
    by_replacement_year_tests: dict[str, int] = {}

    by_make_test_events:         dict[str, int] = {}
    by_make_model_test_events:   dict[str, int] = {}
    by_type_test_events:         dict[str, int] = {}
    by_voltage_test_events:      dict[str, int] = {}
    by_year_test_events:         dict[str, int] = {}
    by_capacity_test_events:     dict[str, int] = {}
    by_failure_year_test_events: dict[str, int] = {}
    by_replacement_year_test_events: dict[str, int] = {}

    for eq in all_eq:
        tc  = eq_test_counts.get(str(eq.id), 0)
        # `src` supplies the risk_level/health_score used for bucketing (and,
        # once a date filter is active, also drives "tested"/"tested_n"):
        # the all-time lab-tests-only snapshot when no range is selected, or
        # the date-scoped TestAnalytics snapshot (dated_ta_map) when one is —
        # see dated_ta_map's comment above for why. When a filter is active,
        # also require a non-null health_score: /ai-graph/grouped's
        # _eff_health treats a scoreless snapshot as "not assessed" (excluded
        # from its count), so this must too or the two dashboards' counts
        # drift apart again on that edge case.
        src = dated_ta_map.get(eq.id) if _date_filter_active else lab_ea_map.get(eq.id)
        if _date_filter_active and src is not None and src.health_score is None:
            src = None
        tested   = (not _date_filter_active) or src is not None
        tested_n = (1 if tc > 0 else 0) if not _date_filter_active else (1 if src is not None else 0)

        vc = (eq.voltage_class or "").strip() or "Unknown"
        by_voltage[vc] = by_voltage.get(vc, 0) + 1
        by_voltage_h.setdefault(vc, _empty_health())
        _add_health(by_voltage_h[vc], eq.id, tested, source=src)
        by_voltage_tests[vc] = by_voltage_tests.get(vc, 0) + tested_n
        by_voltage_test_events[vc] = by_voltage_test_events.get(vc, 0) + tc

        tn = type_map.get(eq.equipment_type_id) or "Unknown"
        by_type[tn] = by_type.get(tn, 0) + 1
        by_type_h.setdefault(tn, _empty_health())
        _add_health(by_type_h[tn], eq.id, tested, source=src)
        by_type_tests[tn] = by_type_tests.get(tn, 0) + tested_n
        by_type_test_events[tn] = by_type_test_events.get(tn, 0) + tc

        mk = (eq.manufacturer or "").strip() or "Unknown"
        by_make[mk] = by_make.get(mk, 0) + 1
        by_make_h.setdefault(mk, _empty_health())
        _add_health(by_make_h[mk], eq.id, tested, source=src)
        by_make_tests[mk] = by_make_tests.get(mk, 0) + tested_n
        by_make_test_events[mk] = by_make_test_events.get(mk, 0) + tc

        # Make/model grouping key mirrors /analytics/ai-graph/grouped's
        # group_by == "make_model" (manufacturer + model_number joined with a
        # space, falling back to make-only when there's no model) so the two
        # dashboards bucket equipment the same way.
        mdl = (eq.model_number or "").strip()
        mk_mdl = f"{mk} {mdl}".strip() if mdl else mk
        by_make_model[mk_mdl] = by_make_model.get(mk_mdl, 0) + 1
        by_make_model_h.setdefault(mk_mdl, _empty_health())
        _add_health(by_make_model_h[mk_mdl], eq.id, tested, source=src)
        by_make_model_tests[mk_mdl] = by_make_model_tests.get(mk_mdl, 0) + tested_n
        by_make_model_test_events[mk_mdl] = by_make_model_test_events.get(mk_mdl, 0) + tc

        yr = str(eq.commissioned_date.year) if eq.commissioned_date else "Unknown"
        by_year[yr] = by_year.get(yr, 0) + 1
        by_year_h.setdefault(yr, _empty_health())
        _add_health(by_year_h[yr], eq.id, tested, source=src)
        by_year_tests[yr] = by_year_tests.get(yr, 0) + tested_n
        by_year_test_events[yr] = by_year_test_events.get(yr, 0) + tc

        cap_bucket = _capacity_bucket(eq_capacity_map.get(eq.id))
        by_capacity[cap_bucket] = by_capacity.get(cap_bucket, 0) + 1
        by_capacity_h.setdefault(cap_bucket, _empty_health())
        _add_health(by_capacity_h[cap_bucket], eq.id, tested, source=src)
        by_capacity_tests[cap_bucket] = by_capacity_tests.get(cap_bucket, 0) + tested_n
        by_capacity_test_events[cap_bucket] = by_capacity_test_events.get(cap_bucket, 0) + tc

        # Replacement-year breakdown — equipment installed to replace another
        # unit (replaces_equipment_id set), bucketed by its own commissioned
        # year, matching the "replacement_year" semantics used by
        # /equipment's group_by and filters (extract("year", commissioned_date)
        # restricted to replaces_equipment_id IS NOT NULL).
        if eq.replaces_equipment_id is not None:
            ry = str(eq.commissioned_date.year) if eq.commissioned_date else "Unknown"
            by_replacement_year[ry] = by_replacement_year.get(ry, 0) + 1
            by_replacement_year_h.setdefault(ry, _empty_health())
            _add_health(by_replacement_year_h[ry], eq.id, tested, source=src)
            by_replacement_year_tests[ry] = by_replacement_year_tests.get(ry, 0) + tested_n
            by_replacement_year_test_events[ry] = by_replacement_year_test_events.get(ry, 0) + tc

    for eq in retired_eq:
        yr = str(eq.retired_date.year) if eq.retired_date else "Unknown"
        by_failure_year[yr] = by_failure_year.get(yr, 0) + 1
        by_failure_year_h.setdefault(yr, _empty_health())
        tc = eq_test_counts.get(str(eq.id), 0)
        by_failure_year_tests[yr] = by_failure_year_tests.get(yr, 0) + (1 if tc > 0 else 0)
        by_failure_year_test_events[yr] = by_failure_year_test_events.get(yr, 0) + tc
        _add_health(by_failure_year_h[yr], eq.id, (not _date_filter_active) or tc > 0)

    # ── Hierarchical dept_equipment_counts: rollup per direct child of scope ──
    dept_counts = _build_dept_rollup(all_eq, department_id, db)

    def _sort(d: dict) -> dict:
        return dict(sorted(d.items(), key=lambda x: -x[1]))

    return {
        "total":                    len(all_eq),
        "testkit_total":            len(testkit_eq),
        "added_this_month":         added_this_month,
        "dept_testkit_counts":      _build_dept_rollup(testkit_eq, department_id, db),
        "by_voltage_class":         _sort(by_voltage),
        "by_voltage_class_health":  {k: _finalise(v) for k, v in by_voltage_h.items()},
        "by_type":                  _sort(by_type),
        "by_type_health":           {k: _finalise(v) for k, v in by_type_h.items()},
        "by_make":                  _sort(by_make),
        "by_make_health":           {k: _finalise(v) for k, v in by_make_h.items()},
        "by_make_tests":            _sort(by_make_tests),
        "by_make_test_events":      by_make_test_events,
        "by_make_model":            _sort(by_make_model),
        "by_make_model_health":     {k: _finalise(v) for k, v in by_make_model_h.items()},
        "by_make_model_tests":      _sort(by_make_model_tests),
        "by_make_model_test_events": by_make_model_test_events,
        "by_commissioned_year":     dict(sorted(by_year.items())),
        "by_commissioned_year_health": {k: _finalise(v) for k, v in by_year_h.items()},
        "by_commissioned_year_tests":  dict(sorted(by_year_tests.items())),
        "by_commissioned_year_test_events": dict(sorted(by_year_test_events.items())),
        "by_failure_year":          dict(sorted(by_failure_year.items())),
        "by_failure_year_health":   {k: _finalise(v) for k, v in by_failure_year_h.items()},
        "by_failure_year_tests":    dict(sorted(by_failure_year_tests.items())),
        "by_failure_year_test_events": dict(sorted(by_failure_year_test_events.items())),
        "by_replacement_year":          dict(sorted(by_replacement_year.items())),
        "by_replacement_year_health":   {k: _finalise(v) for k, v in by_replacement_year_h.items()},
        "by_replacement_year_tests":    dict(sorted(by_replacement_year_tests.items())),
        "by_replacement_year_test_events": dict(sorted(by_replacement_year_test_events.items())),
        "by_capacity_mva":          _sort(by_capacity),
        "by_capacity_mva_health":   {k: _finalise(v) for k, v in by_capacity_h.items()},
        "by_capacity_mva_tests":    _sort(by_capacity_tests),
        "by_capacity_mva_test_events": by_capacity_test_events,
        "by_type_tests":            _sort(by_type_tests),
        "by_type_test_events":      by_type_test_events,
        "by_voltage_class_tests":   _sort(by_voltage_tests),
        "by_voltage_class_test_events": by_voltage_test_events,
        "dept_equipment_counts":    dept_counts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard summary endpoint (consumed by the AI Analytics Dashboard UI)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", summary="AI Analytics Dashboard summary")
def get_analytics_dashboard(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from:     Optional[date]      = Query(None, description="Filter TestResult.tested_at >= this date (YYYY-MM-DD)"),
    date_to:       Optional[date]      = Query(None, description="Filter TestResult.tested_at <= this date (YYYY-MM-DD)"),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns a single payload for the AI Analytics Dashboard:

      - kpi_summary        : totals by risk level
      - hierarchy_node     : analytics for the selected department (or None)
      - top_critical       : up to 10 equipment with the lowest health scores
      - recent_anomalies   : up to 20 latest parameter anomalies
      - health_distribution: equipment count per risk band
      - department_scores  : one-level child breakdown (for drill-down)
    """
    # ── 1. Resolve equipment IDs in scope ────────────────────────────────────
    org_id = user.get("organization_id") if isinstance(user, dict) else getattr(user, "organization_id", None)
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    # Testing Kits are excluded from /asset-breakdown's equipment scope (they
    # aren't real substation assets), but this endpoint's KPI scope had no
    # matching exclusion — a Critical-risk Testing Kit inflated kpi_summary
    # .critical while staying invisible in the by-Make/by-type breakdown,
    # making the two endpoints' critical counts silently disagree (same
    # class of bug the test-count fix below already addressed).
    testkit_type_ids = {
        c.id for c in db.query(CategoryMaster.id)
        .filter(CategoryMaster.name.ilike("%testing kit%"))
        .all()
        if c.id
    }
    testkit_eq_ids: set = set()
    if testkit_type_ids:
        testkit_scope_q = db.query(Equipment.id).filter(
            Equipment.equipment_type_id.in_(testkit_type_ids))
        if org_id:
            testkit_scope_q = testkit_scope_q.filter(Equipment.organization_id == org_id)
        if dept_ids:
            testkit_scope_q = testkit_scope_q.filter(Equipment.department_id.in_(dept_ids))
        testkit_eq_ids = {row[0] for row in testkit_scope_q.all()}

    eq_query = db.query(EquipmentAnalytics)
    if org_id:
        eq_query = eq_query.filter(EquipmentAnalytics.organization_id == org_id)
    if dept_ids:
        eq_query = eq_query.filter(EquipmentAnalytics.department_id.in_(dept_ids))
    all_ea: list[EquipmentAnalytics] = [
        ea for ea in eq_query.all() if ea.equipment_id not in testkit_eq_ids
    ]

    # ── 2. KPI summary ───────────────────────────────────────────────────────
    ea_eq_ids = [ea.equipment_id for ea in all_ea if ea.equipment_id]
    _TERMINAL_STATUSES_KPI = ("completed", "closed")

    # All equipment IDs in scope (from Equipment table — includes untested equipment)
    _scope_eq_q = db.query(Equipment.id).filter(Equipment.status != "retired")
    if org_id:
        _scope_eq_q = _scope_eq_q.filter(Equipment.organization_id == org_id)
    if dept_ids:
        _scope_eq_q = _scope_eq_q.filter(Equipment.department_id.in_(dept_ids))
    if testkit_type_ids:
        _scope_eq_q = _scope_eq_q.filter(~Equipment.equipment_type_id.in_(testkit_type_ids))
    all_scope_eq_ids: set = {row[0] for row in _scope_eq_q.all()}
    # Use scope IDs for all test queries so untested equipment is accounted for
    all_eq_ids = list(all_scope_eq_ids) if all_scope_eq_ids else ea_eq_ids

    # Build per-equipment test count (respects date filter)
    if all_eq_ids:
        kpi_tc_q = (
            db.query(TestingRequest.equipment_id, func.count(func.distinct(TestingRequest.id)))
            .filter(
                TestingRequest.equipment_id.in_(all_eq_ids),
                TestingRequest.status.in_(_TERMINAL_STATUSES_KPI),
            )
        )
        kpi_tc_q = _apply_tested_at_filter(kpi_tc_q, date_from, date_to)
        kpi_tc_rows = kpi_tc_q.group_by(TestingRequest.equipment_id).all()
        kpi_test_count_map: dict = {row[0]: row[1] for row in kpi_tc_rows}
    else:
        kpi_test_count_map = {}

    total_tests = sum(kpi_test_count_map.values())

    # Tests-by-category breakdown for AI analytics tab
    if all_eq_ids:
        cat_q = (
            db.query(TestingRequest.request_category, func.count(func.distinct(TestingRequest.id)))
            .filter(
                TestingRequest.equipment_id.in_(all_eq_ids),
                TestingRequest.status.in_(_TERMINAL_STATUSES_KPI),
            )
        )
        cat_q = _apply_tested_at_filter(cat_q, date_from, date_to)
        cat_rows = cat_q.group_by(TestingRequest.request_category).all()
        tests_by_category = {
            (getattr(row[0], "value", str(row[0])) if row[0] else "unknown"): row[1]
            for row in cat_rows
        }
    else:
        tests_by_category = {}

    # Tests by year (completed_at year → count)
    if all_eq_ids:
        tby_rows = (
            db.query(
                func.extract("year", TestingRequest.completed_at).label("yr"),
                func.count(TestingRequest.id),
            )
            .filter(
                TestingRequest.equipment_id.in_(all_eq_ids),
                TestingRequest.status.in_(_TERMINAL_STATUSES_KPI),
                TestingRequest.completed_at.isnot(None),
            )
            .group_by("yr")
            .order_by("yr")
            .all()
        )
        tests_by_year = {str(int(r[0])): r[1] for r in tby_rows}
    else:
        tests_by_year = {}

    # Failures by year (retired_date year → count of retired equipment in scope)
    if all_eq_ids:
        eq_scope = db.query(Equipment).filter(
            Equipment.id.in_(all_eq_ids),
            Equipment.retired_date.isnot(None),
        ).all()
        failures_by_year: dict = {}
        for eq in eq_scope:
            yr = str(eq.retired_date.year)
            failures_by_year[yr] = failures_by_year.get(yr, 0) + 1
    else:
        failures_by_year = {}

    # Replacements by year (commissioned_date year of equipment that replaced another → count)
    if all_eq_ids:
        rep_scope = db.query(Equipment).filter(
            Equipment.id.in_(all_eq_ids),
            Equipment.replaced_by_id.isnot(None),
            Equipment.commissioned_date.isnot(None),
        ).all()
        replacements_by_year: dict = {}
        for eq in rep_scope:
            yr = str(eq.commissioned_date.year)
            replacements_by_year[yr] = replacements_by_year.get(yr, 0) + 1
    else:
        replacements_by_year = {}

    # Commissioned by year (fleet age breakdown for Asset Dashboard)
    if all_eq_ids:
        comm_scope = db.query(Equipment).filter(
            Equipment.id.in_(all_eq_ids),
            Equipment.commissioned_date.isnot(None),
        ).all()
        commissioned_by_year: dict = {}
        for eq in comm_scope:
            yr = str(eq.commissioned_date.year)
            commissioned_by_year[yr] = commissioned_by_year.get(yr, 0) + 1
    else:
        commissioned_by_year = {}

    # When a date filter is active, total_equipment = equipment with tests in that period.
    # Without a date filter, count all equipment in scope.
    if date_from or date_to:
        active_eq_ids = {eq_id for eq_id, cnt in kpi_test_count_map.items() if cnt > 0}
        active_ea     = [ea for ea in all_ea if ea.equipment_id in active_eq_ids]
    else:
        active_eq_ids = set(all_eq_ids)
        active_ea     = all_ea

    real_total_equipment: int = len(all_scope_eq_ids)

    # Equipment with at least one completed test
    tested_eq_ids: set = {eq_id for eq_id, cnt in kpi_test_count_map.items() if cnt > 0}

    # Per-category: which equipment have had that category of test (across all scope equipment)
    cat_tested: dict[str, set] = {}
    if all_scope_eq_ids:
        cat_eq_rows = (
            db.query(TestingRequest.request_category, TestingRequest.equipment_id)
            .filter(
                TestingRequest.equipment_id.in_(all_scope_eq_ids),
                TestingRequest.status.in_(_TERMINAL_STATUSES_KPI),
            )
        )
        cat_eq_rows = _apply_tested_at_filter(cat_eq_rows, date_from, date_to)
        for cat, eq_id in cat_eq_rows.all():
            key = getattr(cat, "value", str(cat)) if cat else "unknown"
            cat_tested.setdefault(key, set()).add(eq_id)

    # Equipment that have NEVER had each activity type (out of all in-scope equipment)
    no_test_count        = len(all_scope_eq_ids - cat_tested.get("test", set()) - cat_tested.get("testing", set()))
    no_maintenance_count = len(all_scope_eq_ids - cat_tested.get("maintenance", set()))
    no_inspection_count  = len(all_scope_eq_ids - cat_tested.get("inspection", set()) - cat_tested.get("taqc_inspection", set()))
    no_repair_count      = len(all_scope_eq_ids - cat_tested.get("repair_lifecycle", set()))

    # When a date filter is active, kpi_summary must classify each equipment
    # by the test that actually falls in-range (a date-scoped TestAnalytics
    # snapshot), not by its all-time EquipmentAnalytics.risk_level — an
    # equipment last assessed Critical outside the selected range but tested
    # Low/healthy inside it was otherwise still counted as Critical here,
    # while /asset-breakdown (which already uses this date-scoped snapshot)
    # correctly did not — the two endpoints' Critical counts silently
    # disagreed. Mirrors /asset-breakdown's dated_ta_map construction exactly
    # so both endpoints classify the same equipment the same way.
    if date_from or date_to:
        coalesced = func.coalesce(TestResult.tested_at, TestResult.cts)
        dated_ta_q = (
            db.query(TestAnalytics, coalesced.label("eff_date"))
            .join(TestResult, TestResult.id == TestAnalytics.test_result_id)
            .filter(TestAnalytics.equipment_id.in_(active_eq_ids))
        ) if active_eq_ids else None
        if dated_ta_q is not None:
            if date_from:
                dated_ta_q = dated_ta_q.filter(coalesced >= datetime.combine(date_from, datetime.min.time()))
            if date_to:
                dated_ta_q = dated_ta_q.filter(coalesced < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
            _best: dict = {}
            for ta, eff_date in dated_ta_q.all():
                if eff_date is None:
                    continue
                cur = _best.get(ta.equipment_id)
                if cur is None or eff_date > cur[1]:
                    _best[ta.equipment_id] = (ta, eff_date)
            dated_ta_map = {eq_id: pair[0] for eq_id, pair in _best.items()}
        else:
            dated_ta_map = {}
        risk_sources = []
        for eq_id in active_eq_ids:
            src = dated_ta_map.get(eq_id)
            if src is not None and src.health_score is None:
                src = None
            if src is not None:
                risk_sources.append(src)
    else:
        risk_sources = active_ea

    risk_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
    for src in risk_sources:
        risk_counts[src.risk_level or "Unknown"] = risk_counts.get(src.risk_level or "Unknown", 0) + 1

    total = len(risk_sources)
    avg_score = round(
        sum(float(src.health_score) for src in risk_sources if src.health_score is not None) / total, 1
    ) if total else None

    # ── 3. Hierarchy node ───────────────────────────────────────────────────
    ha_node = None
    dept_obj = None
    if department_id:
        ha_node = db.query(HierarchyAnalytics).filter(
            HierarchyAnalytics.department_id == department_id
        ).first()
        dept_obj = db.get(OrgDepartment, department_id)

    # ── 4. Top critical equipment (only equipment with at least 1 test) ─────
    _TERMINAL_STATUSES = ("completed", "closed")

    # Reuse the already-computed date-filtered test count map
    test_count_map: dict = kpi_test_count_map

    critical_ea = sorted(
        [ea for ea in active_ea if ea.health_score is not None
         and test_count_map.get(ea.equipment_id, 0) > 0],
        key=lambda e: e.health_score,
    )[:10]

    eq_ids = [ea.equipment_id for ea in critical_ea]
    eq_map = {e.id: e for e in db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all()}

    type_ids = list({e.equipment_type_id for e in eq_map.values() if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    }

    dept_ids_for_names = list({ea.department_id for ea in critical_ea if ea.department_id})
    dept_name_map = {
        d.id: d.name
        for d in db.query(OrgDepartment).filter(OrgDepartment.id.in_(dept_ids_for_names)).all()
    }

    top_critical = [
        {
            "equipment_id":     str(ea.equipment_id),
            "ueic":             eq_map[ea.equipment_id].ueic if ea.equipment_id in eq_map else None,
            "equipment_type":   type_map.get(eq_map[ea.equipment_id].equipment_type_id) if ea.equipment_id in eq_map else None,
            "department":       dept_name_map.get(ea.department_id),
            "department_id":    str(ea.department_id) if ea.department_id else None,
            "health_score":     float(ea.health_score),
            "risk_level":       ea.risk_level,
            "condition_summary":ea.condition_summary,
            "parameters_at_risk":ea.parameters_at_risk,
            "last_test_date":   ea.last_test_date.isoformat() if ea.last_test_date else None,
            "test_count":       test_count_map.get(ea.equipment_id, 0),
            "links": {
                "analytics":  f"/analytics/equipment/{ea.equipment_id}",
                "tests":      f"/analytics/equipment/{ea.equipment_id}/tests",
                "parameters": f"/analytics/equipment/{ea.equipment_id}/parameters",
            },
        }
        for ea in critical_ea
        if ea.equipment_id in eq_map
    ]

    # ── 5. Recent anomalies ──────────────────────────────────────────────────
    anom_query = (
        db.query(ParameterAnalytics)
        .filter(ParameterAnalytics.is_anomaly == True)  # noqa: E712
        .order_by(ParameterAnalytics.calculated_at.desc())
    )
    if dept_ids:
        anom_query = anom_query.filter(ParameterAnalytics.equipment_id.in_(
            [ea.equipment_id for ea in all_ea]
        ))
    recent_anomalies_rows = anom_query.limit(20).all()

    anom_eq_ids = list({r.equipment_id for r in recent_anomalies_rows})
    anom_eq_map = {e.id: e for e in db.query(Equipment).filter(Equipment.id.in_(anom_eq_ids)).all()}

    recent_anomalies = [
        {
            "equipment_id":   str(r.equipment_id),
            "ueic":           anom_eq_map[r.equipment_id].ueic if r.equipment_id in anom_eq_map else None,
            "template_key":   r.template_key,
            "parameter_key":  r.parameter_key,
            "parameter_label":r.parameter_label,
            "value":          float(r.current_value) if r.current_value is not None else None,
            "unit":           r.unit,
            "anomaly_type":   r.anomaly_type,
            "anomaly_detail": r.anomaly_detail,
            "condition":      r.condition,
            "detected_at":    r.calculated_at.isoformat() if r.calculated_at else None,
            "links": {
                "equipment":    f"/analytics/equipment/{r.equipment_id}",
                "parameter_history": (
                    f"/analytics/equipment/{r.equipment_id}"
                    f"/parameters/{r.parameter_key}/history"
                    f"?template_key={r.template_key}"
                ),
            },
        }
        for r in recent_anomalies_rows
    ]

    # ── 6. One-level child department scores (for drill-down picker) ─────────
    # Fetch HierarchyAnalytics rows for children that have analytics data
    if department_id:
        child_ha_rows = (
            db.query(HierarchyAnalytics)
            .filter(HierarchyAnalytics.parent_department_id == department_id)
            .all()
        )
        # Fetch ALL actual child OrgDepartments (includes zones/depts with 0 tests)
        all_child_depts = (
            db.query(OrgDepartment)
            .filter(OrgDepartment.parent_department_id == department_id)
            .all()
        )
    else:
        # No dept selected: return root departments (parent_department_id IS NULL)
        _scope_org_id = org_id  # use authenticated user's org directly
        _ha_q = db.query(HierarchyAnalytics).filter(
            HierarchyAnalytics.parent_department_id.is_(None)
        )
        if _scope_org_id:
            _ha_q = _ha_q.filter(HierarchyAnalytics.organization_id == _scope_org_id)
        child_ha_rows = _ha_q.all()
        all_child_depts = (
            db.query(OrgDepartment)
            .filter(
                OrgDepartment.parent_department_id.is_(None),
                OrgDepartment.organization_id == _scope_org_id,
            )
            .all()
        ) if _scope_org_id else []

    # Build lookup from HierarchyAnalytics by department_id
    ha_map: dict = {c.department_id: c for c in child_ha_rows}

    all_child_dept_ids = [d.id for d in all_child_depts]

    # Test counts + equipment counts per child dept — across entire subtree
    child_test_counts: dict = {}
    child_eq_counts: dict = {}
    for child_id in all_child_dept_ids:
        subtree_ids = _collect_department_ids(child_id, db)
        tc_q = (
            # DISTINCT - _apply_tested_at_filter joins TestResult below, and
            # a TestingRequest with multiple linked TestResults (e.g.
            # several test templates run under one request) would otherwise
            # fan out to multiple rows and get counted more than once, so
            # this could disagree with kpi_summary.total_tests (which does
            # use DISTINCT) for the same underlying requests.
            db.query(func.count(func.distinct(TestingRequest.id)))
            .join(Equipment, Equipment.id == TestingRequest.equipment_id)
            .filter(
                Equipment.department_id.in_(subtree_ids),
                TestingRequest.status.in_(("completed", "closed")),
            )
        )
        tc_q = _apply_tested_at_filter(tc_q, date_from, date_to)
        tc_rows = tc_q.scalar()
        eq_cnt = (
            db.query(func.count(Equipment.id))
            .filter(Equipment.department_id.in_(subtree_ids),
                    Equipment.status != "retired")
            .scalar()
        )
        child_test_counts[str(child_id)] = tc_rows or 0
        child_eq_counts[str(child_id)]   = eq_cnt or 0

    department_scores = []
    for d in all_child_depts:
        ha = ha_map.get(d.id)
        eq_count = ha.equipment_count if ha else child_eq_counts.get(str(d.id), 0)
        department_scores.append({
            "department_id":      str(d.id),
            "department_name":    d.name,
            "level_type":         ha.level_type if ha else None,
            "health_score":       float(ha.health_score) if ha and ha.health_score is not None else None,
            "risk_level":         ha.risk_level if ha else None,
            "equipment_count":    eq_count,
            "equipment_critical": ha.equipment_critical if ha else 0,
            "equipment_high":     ha.equipment_high if ha else 0,
            "test_count":         child_test_counts.get(str(d.id), 0),
            "has_analytics":      ha is not None,
        })

    return {
        "department_id":   str(department_id) if department_id else None,
        "department_name": dept_obj.name if dept_obj else None,
        "kpi_summary": {
            "total_equipment":   real_total_equipment,
            "avg_health_score":  avg_score,
            "total_tests":       total_tests,
            "critical":          risk_counts["Critical"],
            "high":              risk_counts["High"],
            "medium":            risk_counts["Medium"],
            "low":               risk_counts["Low"],
            "tests_by_category":   {
                **tests_by_category,
                "no_test":         no_test_count,
                "no_maintenance":  no_maintenance_count,
                "no_inspection":   no_inspection_count,
                "no_repair":       no_repair_count,
            },
            "untested_count":      max(0, real_total_equipment - len(tested_eq_ids)),
            "tests_by_year":       tests_by_year,
            "failures_by_year":    failures_by_year,
            "replacements_by_year":replacements_by_year,
            "commissioned_by_year":commissioned_by_year,
        },
        "hierarchy_node":    _serialize_hierarchy_analytics(ha_node, dept_obj) if ha_node else None,
        "top_critical":      top_critical,
        "recent_anomalies":  recent_anomalies,
        "department_scores": department_scores,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Trigger endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/test-results/{test_result_id}/run", summary="Run analytics for a test result")
def run_test_analytics(
    test_result_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    from models import TestResult as _TR
    from services.evaluation_service import EvaluationService

    # Re-evaluate the stored test_data so stale evaluation_result rows (e.g.
    # fields=[]) are refreshed before analytics runs.
    tr = db.get(_TR, test_result_id)
    if not tr:
        raise HTTPException(status_code=404, detail="Test result not found")

    template_data = EvaluationService.get_template_data(
        tr.template_key, db, org_id=tr.organization_id
    )
    if template_data:
        fresh_eval = EvaluationService.evaluate_test_data(template_data, tr.test_data or {}, db)
        tr.evaluation_result = fresh_eval
        db.flush()

    engine = AnalyticsEngine(db)
    ta = engine.run_for_test(test_result_id)
    if not ta:
        raise HTTPException(status_code=404, detail="Test result not found or template missing")
    db.commit()
    return {
        "status":         "ok",
        "test_result_id": str(test_result_id),
        "health_score":   float(ta.health_score) if ta.health_score is not None else None,
        "risk_level":     ta.risk_level,
        "condition":      ta.condition_summary,
        "eval_fields":    len(tr.evaluation_result.get("fields", [])) if tr.evaluation_result else 0,
    }


@router.post("/equipment/{equipment_id}/run", summary="Re-run equipment analytics")
def run_equipment_analytics(
    equipment_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    engine = AnalyticsEngine(db)
    ea = engine.run_for_equipment(equipment_id)
    if not ea:
        raise HTTPException(status_code=404, detail="Equipment not found or no test analytics available")
    db.commit()
    return {
        "status":        "ok",
        "equipment_id":  str(equipment_id),
        "health_score":  float(ea.health_score) if ea.health_score is not None else None,
        "risk_level":    ea.risk_level,
    }


@router.post("/recompute-all", summary="Recompute analytics for every test result (admin)")
def recompute_all_analytics(
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """Re-runs score_test + equipment aggregation for every submitted TestResult in the DB.
    Skips results whose testing request is still in draft/in-progress/assigned state.
    Use after changing the scoring formula to backfill historical scores."""
    from models import TestResult, TestingRequest, TestingRequestStatus, TrWfInstance
    from sqlalchemy import or_

    _SKIP_STATUSES = {
        TestingRequestStatus.draft,
        TestingRequestStatus.submitted,
        TestingRequestStatus.assigned,
        TestingRequestStatus.accepted,
        TestingRequestStatus.in_progress,
    }

    # Collect IDs of TRs that are wf-active (not yet completed)
    wf_active_ids = {
        row.testing_request_id
        for row in db.query(TrWfInstance.testing_request_id).filter(
            TrWfInstance.status == "active"
        ).all()
    }

    results = db.query(TestResult).all()
    # Filter: only run on results whose TR is in a terminal/submitted state
    results = [
        r for r in results
        if r.testing_request
        and r.testing_request.status not in _SKIP_STATUSES
        and r.testing_request_id not in wf_active_ids
    ]
    engine  = AnalyticsEngine(db)
    done, failed = 0, 0
    for tr in results:
        try:
            engine.run_for_test(tr.id)
            done += 1
        except Exception as exc:
            failed += 1
            logger.warning("recompute_all: failed for %s: %s", tr.id, exc)
    db.commit()
    return {"status": "ok", "recomputed": done, "failed": failed}


@router.get("/dashboard/equipment", summary="Paginated equipment list for dashboard")
def get_dashboard_equipment(
    department_id:    Optional[uuid.UUID] = Query(None),
    page:             int                 = Query(1, ge=1),
    page_size:        int                 = Query(20, ge=1, le=100),
    search:           Optional[str]       = Query(None, description="Filter by UEIC (partial match)"),
    date_from:        Optional[date]      = Query(None),
    date_to:          Optional[date]      = Query(None),
    voltage_class:    Optional[str]       = Query(None, description="Filter by voltage class"),
    equipment_type:   Optional[str]       = Query(None, description="Filter by equipment type name"),
    manufacturer:     Optional[str]       = Query(None, description="Filter by manufacturer"),
    model_number:     Optional[str]       = Query(None, description="Filter by model number"),
    make_model:       Optional[str]       = Query(None, description="Filter by manufacturer + model combined, as returned by by_make_model"),
    commission_year:  Optional[int]       = Query(None, description="Filter by commissioned year"),
    failure_year:     Optional[int]       = Query(None, description="Filter by retired/failure year"),
    risk_level:       Optional[str]       = Query(None, description="Filter by risk level: Critical, High, Medium, Low"),
    tested_only:      bool                = Query(False, description="If true, exclude equipment with no analytics data"),
    db:               Session             = Depends(get_vendor_db),
    user:             dict                = Depends(get_current_user),
):
    """
    Returns all equipment in scope (worst health first), paginated.
    Equipment with no analytics appear at the end with null scores.
    """
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    # All equipment in scope - ordered so the base list is deterministic:
    # the final sort below (by risk/score) is a stable Python sort, so ties
    # (e.g. two untested equipment, or two with identical risk/score) keep
    # whatever relative order this query returns them in. Without an
    # explicit ORDER BY here, that base order isn't guaranteed stable across
    # requests, so a tied pair could swap sides of a page boundary between
    # the page-1 and page-2 calls - showing one equipment twice and skipping
    # another.
    eq_q = db.query(Equipment).order_by(Equipment.id)
    if dept_ids:
        eq_q = eq_q.filter(Equipment.department_id.in_(dept_ids))
    if search:
        eq_q = eq_q.filter(Equipment.ueic.ilike(f"%{search}%"))
    if voltage_class:
        if voltage_class.lower() == "unknown":
            eq_q = eq_q.filter((Equipment.voltage_class == None) | (Equipment.voltage_class == ""))
        else:
            eq_q = eq_q.filter(Equipment.voltage_class == voltage_class)
    if manufacturer:
        if manufacturer.lower() == "unknown":
            eq_q = eq_q.filter((Equipment.manufacturer == None) | (Equipment.manufacturer == ""))
        else:
            eq_q = eq_q.filter(Equipment.manufacturer == manufacturer)
    if model_number:
        if model_number.lower() == "unknown":
            eq_q = eq_q.filter((Equipment.model_number == None) | (Equipment.model_number == ""))
        else:
            eq_q = eq_q.filter(Equipment.model_number == model_number)
    if commission_year:
        from sqlalchemy import extract
        eq_q = eq_q.filter(extract("year", Equipment.commissioned_date) == commission_year)
    if failure_year:
        from sqlalchemy import extract as _extract
        eq_q = eq_q.filter(Equipment.status == "retired")
        eq_q = eq_q.filter(_extract("year", Equipment.retired_date) == failure_year)
    all_eq: list[Equipment] = eq_q.all()

    # make_model is a derived key (manufacturer + model_number), not a raw
    # column, so it can't be pushed into the SQL filter above - re-derive it
    # per equipment the same way /analytics/asset-breakdown's by_make_model
    # does, and filter in Python.
    if make_model:
        def _make_model_key(e: Equipment) -> str:
            mk = (e.manufacturer or "").strip() or "Unknown"
            mdl = (e.model_number or "").strip()
            return f"{mk} {mdl}".strip() if mdl else mk
        all_eq = [e for e in all_eq if _make_model_key(e) == make_model]

    # Apply equipment_type filter after type_map is built (done below)
    _filter_equipment_type = equipment_type

    eq_ids = [e.id for e in all_eq]

    # Analytics map — only equipment that has been tested has a row here
    ea_rows = db.query(EquipmentAnalytics).filter(
        EquipmentAnalytics.equipment_id.in_(eq_ids)
    ).all()
    ea_map = {r.equipment_id: r for r in ea_rows}

    # This endpoint is AI Analytics-specific (the only caller is the AI
    # Analytics Dashboard), so its health_score/risk_level/critical_findings
    # must exclude TA&QC/Failure Registry/cumulative-counter test types the
    # same way the AI Analytics equipment-detail modal's chip row does -
    # otherwise this list disagrees with the modal for any equipment that
    # also has one of those test types (e.g. OLTC dragging the equipment's
    # overall EquipmentAnalytics score/risk down while the modal, which never
    # shows OLTC, reports a healthier one). lab_map is keyed by equipment_id
    # -> (score, risk_level, critical_findings); an equipment whose only
    # tests are excluded types gets (None, "Unknown", []) here, same as a
    # genuinely untested one.
    lab_map = _lab_only_scores(eq_ids, db)

    # Exclude untested equipment when caller requests it (AI Analytics)
    if tested_only:
        all_eq = [e for e in all_eq if lab_map.get(e.id, (None,))[0] is not None]

    # Apply risk_level filter
    if risk_level:
        all_eq = [e for e in all_eq if lab_map.get(e.id, (None, "Unknown"))[1] == risk_level]

    eq_ids = [e.id for e in all_eq]

    # Type names
    type_ids = list({e.equipment_type_id for e in all_eq if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    }

    # Apply equipment_type filter now that we have type_map
    if _filter_equipment_type:
        _ft = _filter_equipment_type.lower()
        if _ft == "unknown":
            all_eq = [e for e in all_eq if not type_map.get(e.equipment_type_id)]
        else:
            all_eq = [e for e in all_eq if (type_map.get(e.equipment_type_id) or "").strip().lower() == _ft.strip()]
        eq_ids = [e.id for e in all_eq]

    # Department names
    dept_ids_for_names = list({e.department_id for e in all_eq if e.department_id})
    dept_name_map = {
        d.id: d.name
        for d in db.query(OrgDepartment).filter(OrgDepartment.id.in_(dept_ids_for_names)).all()
    }

    # Test counts (respects date filter)
    tc_q = (
        db.query(TestingRequest.equipment_id, func.count(func.distinct(TestingRequest.id)))
        .filter(
            TestingRequest.equipment_id.in_(eq_ids),
            TestingRequest.status.in_(("completed", "closed")),
        )
    )
    tc_q = _apply_tested_at_filter(tc_q, date_from, date_to)
    test_count_map = {row[0]: row[1] for row in tc_q.group_by(TestingRequest.equipment_id).all()}

    # When a date filter is active, only show equipment that has tests in that period
    # so pagination is correct (avoids empty pages when client filters testCount > 0)
    if date_from or date_to:
        active_ids = {eq_id for eq_id, cnt in test_count_map.items() if cnt > 0}
        all_eq = [e for e in all_eq if e.id in active_ids]

    # At-risk parameter names per equipment (condition = Poor), deduplicated
    at_risk_params_rows = (
        db.query(ParameterAnalytics.equipment_id, ParameterAnalytics.parameter_label, ParameterAnalytics.parameter_key)
        .filter(
            ParameterAnalytics.equipment_id.in_(eq_ids),
            ParameterAnalytics.condition == "Poor",
        )
        .all()
    )
    at_risk_params_map: dict = {}
    for eq_id, label, key in at_risk_params_rows:
        at_risk_params_map.setdefault(eq_id, set()).add(label or key)
    at_risk_params_map = {k: sorted(v) for k, v in at_risk_params_map.items()}

    _risk_order = _severity_rank_map(db)

    def _sort_key(eq: Equipment):
        score, risk, _f = lab_map.get(eq.id, (None, "Unknown", []))
        if risk in _risk_order:
            s = score if score is not None else 999.0
            return (0, _risk_order[risk], s)
        return (1, 99, 999.0)

    # _sort_key already ranks worst-first in ascending order (0=tested before
    # 1=untested; within tested, risk_order 0=Critical before 3=Low; lower
    # score before higher) — reverse=True here would flip that to best-first,
    # burying Critical equipment at the end of the list instead of the top.
    sorted_eq = sorted(all_eq, key=_sort_key)
    total = len(sorted_eq)
    start = (page - 1) * page_size
    page_eq = sorted_eq[start: start + page_size]

    items = []
    for eq in page_eq:
        ea = ea_map.get(eq.id)
        lab_score, lab_risk, lab_findings = lab_map.get(eq.id, (None, "Unknown", []))
        # Build plain-English reason from the same lab-only critical_findings
        # shown in health_score/risk_level below, so the reason text can't
        # cite an excluded test type (e.g. an OLTC counter breach) for a row
        # that no longer counts OLTC toward its score/risk here.
        reason = None
        if lab_findings:
            # Use rich per-finding reason if available, else fall back to label
            parts = []
            seen = set()
            for f in lab_findings:
                label = f.get("label") or f.get("key", "")
                if label in seen:
                    continue
                seen.add(label)
                r = f.get("reason")
                if r:
                    parts.append(r)
                elif label:
                    parts.append(f"{label} exceeded threshold")
            if parts:
                if len(parts) == 1:
                    reason = parts[0]
                else:
                    reason = f"{len(parts)} parameters: " + "; ".join(parts[:3])
                    if len(parts) > 3:
                        reason += f" +{len(parts)-3} more"
        elif ea and ea.condition_summary:
            reason = ea.condition_summary

        items.append({
            "equipment_id":            str(eq.id),
            "ueic":                    eq.ueic,
            "equipment_type":          type_map.get(eq.equipment_type_id),
            "department":              dept_name_map.get(eq.department_id),
            "department_id":           str(eq.department_id) if eq.department_id else None,
            "health_score":            lab_score,
            "risk_level":              lab_risk,
            "condition_summary":       reason,
            "critical_findings":       lab_findings,
            "parameters_at_risk":      ea.parameters_at_risk if ea else 0,
            "at_risk_parameter_names": at_risk_params_map.get(eq.id, []),
            "last_test_date":          ea.last_test_date.isoformat() if ea and ea.last_test_date else None,
            "test_count":              test_count_map.get(eq.id, 0),
            "tested":                  lab_score is not None,
            # Equipment register fields for client-side view-by grouping
            "manufacturer":            eq.manufacturer,
            "model_number":            eq.model_number,
            "commissioned_date":       eq.commissioned_date.isoformat() if eq.commissioned_date else None,
            "retired_date":            eq.retired_date.isoformat() if getattr(eq, "retired_date", None) else None,
        })

    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  start + page_size < total,
        "items":     items,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchy drill-down
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/departments/{department_id}", summary="Hierarchy analytics for a department node")
def get_department_analytics(
    department_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    row = (
        db.query(HierarchyAnalytics)
        .filter(HierarchyAnalytics.department_id == department_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No hierarchy analytics for this department")
    dept = db.get(OrgDepartment, department_id)
    return _serialize_hierarchy_analytics(row, dept)


@router.get("/departments/{department_id}/tree", summary="Node + one level of children")
def get_department_tree(
    department_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    root     = db.query(HierarchyAnalytics).filter(HierarchyAnalytics.department_id == department_id).first()
    root_dept = db.get(OrgDepartment, department_id)

    child_rows = (
        db.query(HierarchyAnalytics)
        .filter(HierarchyAnalytics.parent_department_id == department_id)
        .all()
    )
    child_depts = {
        str(d.id): d
        for d in db.query(OrgDepartment)
        .filter(OrgDepartment.parent_department_id == department_id)
        .all()
    }

    return {
        "node":     _serialize_hierarchy_analytics(root, root_dept) if root else None,
        "children": [
            _serialize_hierarchy_analytics(c, child_depts.get(str(c.department_id)))
            for c in child_rows
        ],
    }


@router.get(
    "/departments/{department_id}/equipment",
    summary="All equipment in a department with their analytics scores",
)
def get_department_equipment(
    department_id: uuid.UUID,
    include_sub_departments: bool = Query(
        False,
        description="If true, include equipment from all nested child departments",
    ),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns every Equipment record in this department (and optionally all child
    departments) joined with its EquipmentAnalytics row (if computed).

    Each item in the response carries:
      - equipment_id   — use to call GET /analytics/equipment/{equipment_id}
      - ueic           — human-readable asset code
      - equipment_type — category name
      - health_score, risk_level, condition_summary from EquipmentAnalytics
      - links.analytics, links.tests, links.parameters
    """
    dept_ids = _collect_department_ids(department_id, db) if include_sub_departments else {department_id}

    equipment_rows = (
        db.query(Equipment)
        .filter(Equipment.department_id.in_(dept_ids), Equipment.status != "retired")
        .all()
    )

    # Bulk-fetch analytics for all equipment found
    eq_ids = [e.id for e in equipment_rows]
    analytics_map: dict[uuid.UUID, EquipmentAnalytics] = {
        ea.equipment_id: ea
        for ea in db.query(EquipmentAnalytics).filter(EquipmentAnalytics.equipment_id.in_(eq_ids)).all()
    }

    # Bulk-fetch category names
    type_ids  = list({e.equipment_type_id for e in equipment_rows if e.equipment_type_id})
    type_map  = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    }

    return [
        _serialize_equipment_summary(e, analytics_map.get(e.id), type_map)
        for e in equipment_rows
    ]


@router.get(
    "/condition-risk-matrix",
    summary="Criticality x health-band cross-tab (KPTCL spec §12.5)",
)
def get_condition_risk_matrix(
    department_id: Optional[uuid.UUID] = Query(
        None,
        description="Scope to this department + all its descendants. Omit for the org root "
                    "(Org Admin / no single department) — scoped by organization_id instead, "
                    "same fallback GET /asset-breakdown already uses.",
    ),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Cross-tabs equipment by criticality (consequence of failure — from
    EquipmentCriticalityMapping, admin-configurable, NOT derived from test
    data) against health band (EquipmentAnalytics.risk_level, the same
    Low/Medium/High/Critical bands already used everywhere else in the
    app — condition, not consequence). The two axes are independent by
    design: a Low-criticality unit in Critical health still needs
    attention, just less urgently than a Critical-criticality one in the
    same health band — that's the whole point of the matrix over a single
    health map.
    """
    org_id = user.get("organization_id") if isinstance(user, dict) else getattr(user, "organization_id", None)
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    equipment_q = db.query(Equipment).filter(Equipment.status != "retired")
    if org_id:
        equipment_q = equipment_q.filter(Equipment.organization_id == org_id)
    if dept_ids:
        equipment_q = equipment_q.filter(Equipment.department_id.in_(dept_ids))
    equipment_rows = (
        equipment_q
        .all()
    )
    eq_ids = [e.id for e in equipment_rows]

    analytics_map: dict[uuid.UUID, EquipmentAnalytics] = {
        ea.equipment_id: ea
        for ea in db.query(EquipmentAnalytics).filter(EquipmentAnalytics.equipment_id.in_(eq_ids)).all()
    }

    # Criticality lookup: an exact (equipment_type_id, voltage_class) row
    # first, falling back to the type-level default (voltage_class IS
    # NULL), falling back to "Low" if the type has no mapping configured
    # yet at all — see EquipmentCriticalityMapping's own docstring.
    mapping_rows = (
        db.query(EquipmentCriticalityMapping)
        .filter(EquipmentCriticalityMapping.is_active.is_(True))
        .all()
    )
    specific_criticality = {
        (m.equipment_type_id, m.voltage_class): m.criticality for m in mapping_rows if m.voltage_class
    }
    default_criticality = {
        m.equipment_type_id: m.criticality for m in mapping_rows if not m.voltage_class
    }

    severity_labels = _severity_order_labels(db)  # worst-first, from EquipmentHealthBandThreshold
    least_severe_label = severity_labels[-1] if severity_labels else "Low"

    def _criticality_for(eq: Equipment) -> str:
        key = (eq.equipment_type_id, eq.voltage_class)
        if key in specific_criticality:
            return specific_criticality[key]
        if eq.equipment_type_id in default_criticality:
            return default_criticality[eq.equipment_type_id]
        return least_severe_label

    # Both axes reuse the same admin-configured severity vocabulary
    # (EquipmentHealthBandThreshold) rather than two more independent
    # hardcoded label lists: HEALTH_BANDS directly because that table is
    # literally what produced every equipment's risk_level in the first
    # place, plus "Unknown" for equipment with no analytics yet.
    # CRITICALITY_TIERS is a deliberate simplification — criticality
    # (EquipmentCriticalityMapping) is a conceptually separate axis
    # (consequence-of-failure, not condition) that happens to share the
    # same 4 names today; if KPTCL ever wants criticality tiers named
    # differently from health bands, this reuse should be split into its
    # own small ordered table instead of assuming they always match.
    CRITICALITY_TIERS = severity_labels
    HEALTH_BANDS = severity_labels + ["Unknown"]

    cells: dict[tuple, list] = {}
    for e in equipment_rows:
        crit = _criticality_for(e)
        ea = analytics_map.get(e.id)
        health = (ea.risk_level if ea and ea.risk_level else "Unknown")
        cells.setdefault((crit, health), []).append({
            "equipment_id": str(e.id),
            "equipment_label": e.ueic,
            "health_score": float(ea.health_score) if ea and ea.health_score is not None else None,
        })

    matrix = [
        {
            "criticality": crit,
            "health_band": health,
            "count": len(cells.get((crit, health), [])),
            # Capped — this is a summary grid, not a full equipment list;
            # the department/equipment endpoints above already serve that.
            "equipment": cells.get((crit, health), [])[:25],
        }
        for crit in CRITICALITY_TIERS
        for health in HEALTH_BANDS
    ]

    return {
        "criticality_tiers": CRITICALITY_TIERS,
        "health_bands": HEALTH_BANDS,
        # Colors decided once, here, from RiskLevelColors — not left for the
        # frontend to guess per screen (that's exactly how this widget's own
        # earlier bug happened: analytics_dashboard_page.dart colored the
        # same bands differently from this matrix). The frontend renders
        # whichever hex string it's given rather than deciding one itself.
        "band_colors": {label: RiskLevelColors.get(label) for label in HEALTH_BANDS},
        "matrix": matrix,
        "total_equipment": len(equipment_rows),
        "unmapped_type_count": sum(
            1 for e in equipment_rows
            if e.equipment_type_id not in default_criticality
            and (e.equipment_type_id, e.voltage_class) not in specific_criticality
        ),
    }


@router.get(
    "/deterioration-watch-list",
    summary="Equipment trending toward a threshold breach, before they get there (KPTCL spec §12.2 / §14.3)",
)
def get_deterioration_watch_list(
    department_id: Optional[uuid.UUID] = Query(
        None,
        description="Scope to this department + all its descendants. Omit for the org root, "
                    "same organization_id fallback as /condition-risk-matrix and /asset-breakdown.",
    ),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Surfaces equipment with a statistically significant trend on a key test
    parameter, even though that parameter's latest reading hasn't crossed
    into ALERT/CRITICAL yet — the whole point being to catch deterioration
    before it becomes an incident, not after. Reuses computation the
    analytics engine already does and stores on every test
    (ParameterAnalytics.trend/trend_slope/days_to_breach from
    services/analytics_engine.py's linear-regression + breach-forecast
    logic) rather than re-deriving trend detection here — this endpoint is
    just the cross-equipment aggregation of that signal that didn't
    previously exist anywhere (it was only ever surfaced one equipment at
    a time, on that equipment's own profile page).

    Each flagged parameter's days_to_breach / breach_threshold /
    breach_predicted_at / is_overdue_for_retest are computed HERE, via the
    shared _real_breach_forecast() (also used by get_parameter_analytics),
    from ParameterThresholdBand — NOT read from the analytics engine's own
    days_to_breach/breach_predicted_at columns. Confirmed live those are
    populated only for flat-field parameters with a simple evaluation dict
    (alert_min/alert_max/etc); the table-row-based tests that are this
    app's dominant real pattern (oil tests, DGA, most others) store
    thresholds keyed by row/parameter name instead, a shape the engine's
    own breach-forecast code never reads, so those columns are effectively
    always None for them — a real architecture gap in the engine itself
    (tracked separately), not something to paper over here.
    ParameterThresholdBand (alter_parameter_threshold_band.py) is a
    flattened, queryable projection of those same table-row threshold
    configs, built from any test template's table field whose rule is
    THRESHOLD-typed — not specific to any one test type, so a new template
    that defines THRESHOLD bands on a table row is picked up automatically,
    the same way transformer_oil_test/transformer_dga/tan-delta templates
    already are; a template with no THRESHOLD-typed rule at all (or one
    using flat-field alert_min/alert_max instead) has no rows here and
    falls back to the _MIN_WATCH_HISTORY bar below. _real_breach_forecast
    walks the bands to find the real next worse-band boundary in the
    direction this parameter is actually trending, and only a genuine
    forecast toward a WORSE band qualifies — a parameter trending toward a
    BETTER band is correctly excluded, not just unmeasured — then anchors
    the predicted date to this parameter's own last real test date (not
    "today"), so equipment that hasn't been retested since the trend
    implied a breach comes back is_overdue_for_retest instead of a
    misleading future date.

    A parameter with no threshold config found at all (so materiality
    can't be checked against a real boundary) falls back to a minimum
    reading-count bar (_MIN_WATCH_HISTORY) instead of trend direction
    alone — confirmed live: with only 2-3 readings, a straight line
    trivially fits perfectly (trend_r_squared ~1.0) regardless of whether
    the movement is real or noise, which is how a 100%-health/"Low"-risk
    transformer with 3 historical readings per parameter first showed up
    here with 8 flagged parameters, none of them real.
    """
    org_id = user.get("organization_id") if isinstance(user, dict) else getattr(user, "organization_id", None)
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    equipment_q = db.query(Equipment).filter(Equipment.status != "retired")
    if org_id:
        equipment_q = equipment_q.filter(Equipment.organization_id == org_id)
    if dept_ids:
        equipment_q = equipment_q.filter(Equipment.department_id.in_(dept_ids))
    equipment_rows = equipment_q.all()
    eq_by_id = {e.id: e for e in equipment_rows}
    eq_ids = list(eq_by_id.keys())

    if not eq_ids:
        return {"total_equipment": 0, "watch_count": 0, "equipment": []}

    analytics_map = {
        ea.equipment_id: ea
        for ea in db.query(EquipmentAnalytics).filter(EquipmentAnalytics.equipment_id.in_(eq_ids)).all()
    }

    # Every historical row for these equipment, newest test first — deduped
    # below to the latest row per (equipment_id, parameter_key) before any
    # trend/status filtering, so a stale-but-trending reading superseded
    # by a newer stable (or already-breached) one is never surfaced.
    #
    # Ordered by history_count, NOT calculated_at: confirmed live these can
    # disagree — calculated_at is when the analytics engine happened to
    # (re)compute a row, which is processing order, not test chronology. A
    # batch recompute (or a re-run for one specific historical test) can
    # process an OLDER test's row after a NEWER test's row, so "most
    # recently calculated" silently picked a stale, small-history_count
    # snapshot instead of the equipment's actual latest test. history_count
    # is populated per-test as "how many readings existed as of THIS test",
    # so it strictly increases with true test chronology regardless of
    # when it was (re)computed — the reliable ordering key here.
    pa_rows = (
        db.query(ParameterAnalytics)
        .filter(ParameterAnalytics.equipment_id.in_(eq_ids))
        .order_by(ParameterAnalytics.history_count.desc(), ParameterAnalytics.calculated_at.desc())
        .all()
    )
    latest_by_key: dict[tuple, ParameterAnalytics] = {}
    for row in pa_rows:
        key = (row.equipment_id, row.parameter_key)
        if key not in latest_by_key:
            latest_by_key[key] = row

    equipment_type_names = {
        c.id: c.name for c in db.query(CategoryMaster).all()
    }

    # Minimum readings before a trend counts as a real signal at all, not
    # the engine's own bare computational minimum (2 points — services/
    # analytics_engine.py's MIN_TREND_POINTS = 1, i.e. 1 prior + current).
    # With only 2-3 points, trend_r_squared is trivially ~1.0 regardless of
    # whether the movement is real or noise (a line always fits 2-3 points
    # well). Still the only signal available for a parameter with no
    # ParameterThresholdBand config at all; superseded by a real breach
    # forecast below wherever one is available.
    _MIN_WATCH_HISTORY = config.ANALYTICS_MIN_WATCH_HISTORY

    # Real breach-proximity check, using ParameterThresholdBand (see the
    # module-level helpers above) instead of the engine's own
    # days_to_breach/breach_threshold columns — confirmed live those are
    # populated only for flat-field parameters, not table-row ones (oil
    # tests, DGA, most others), so relying on them here would silence this
    # endpoint almost entirely. Bulk-fetch every band this batch of
    # equipment could need, once, rather than one query per parameter.
    needed_templates = {row.template_key for row in latest_by_key.values()}
    band_rows = (
        db.query(ParameterThresholdBand)
        .filter(ParameterThresholdBand.template_key.in_(needed_templates),
                ParameterThresholdBand.is_active.is_(True))
        .all()
    ) if needed_templates else []
    bands_by_param: dict[tuple, list] = {}
    for b in band_rows:
        bands_by_param.setdefault((b.template_key, b.parameter_key), []).append(b)

    # Bulk-fetch each flagged-candidate row's real test date, same pattern
    # get_parameter_analytics uses — _real_breach_forecast anchors
    # breach_predicted_at to this (the last REAL test), not to today, so a
    # parameter that hasn't been retested in years correctly comes back
    # is_overdue_for_retest instead of a nonsensical future date computed
    # by adding the trend-fit's day-count to today's date.
    result_ids = [row.test_result_id for row in latest_by_key.values()]
    tested_at_map = {
        r.id: (r.tested_at or r.cts)
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    } if result_ids else {}

    flagged_by_equipment: dict = {}
    for row in latest_by_key.values():
        if row.status != "NORMAL":
            continue  # already breached — that's the alert feed's job, not this watch list's
        if row.trend not in ("Increasing", "Decreasing"):
            continue  # no directional signal yet
        if row.current_value is None or row.trend_slope is None:
            continue

        row_id = _table_row_id(row.parameter_key)
        candidate_bands = bands_by_param.get((row.template_key, row_id), [])
        forecast = None
        if candidate_bands:
            eq_for_row = eq_by_id.get(row.equipment_id)
            forecast = _real_breach_forecast(
                row, db,
                eq_for_row.voltage_class if eq_for_row else None,
                tested_at_map.get(row.test_result_id),
                candidate_bands=candidate_bands,
            )
            if forecast["breach_value"] is None:
                # Real threshold config exists and was checked — either the
                # trend is heading toward a BETTER band (or none at all,
                # the whole point of doing this lookup: a genuinely benign
                # trend, not just an unmeasured one), or the forecast crossed
                # the same 10-year cap services/analytics_engine.py's own
                # flat-field breach forecast already uses (a real forecast
                # 188 years out — confirmed live: Acidity trending at its
                # actual measured rate — is technically genuine but not
                # meaningfully "worth watching" over any equipment's real
                # service life).
                continue
        elif (row.history_count or 0) < _MIN_WATCH_HISTORY:
            # No threshold config to check materiality against at all —
            # fall back to the cruder "enough readings to trust the trend"
            # bar rather than silently including or excluding it.
            continue

        flagged_by_equipment.setdefault(row.equipment_id, []).append({
            "analytics_id":          str(row.id),
            "parameter_key":         row.parameter_key,
            "parameter_label":       row.parameter_label,
            "template_key":          row.template_key,
            "unit":                  row.unit,
            "current_value":         float(row.current_value) if row.current_value is not None else None,
            "trend":                 row.trend,
            "annual_change":         float(row.annual_change) if row.annual_change is not None else None,
            "breach_threshold":      forecast["breach_value"] if forecast else None,
            "breach_band":           forecast["breach_band"] if forecast else None,
            "breach_predicted_at":   forecast["breach_predicted_at"] if forecast else None,
            "days_to_breach":        forecast["days_to_breach"] if forecast else None,
            "is_overdue_for_retest": forecast["is_overdue_for_retest"] if forecast else False,
            "history_count":         row.history_count,
            # Real last-test date this snapshot is based on — how the
            # overdue-review scheduler (main.py's daily job) ages a pending
            # advisory for T+7/T+15 escalation, same "anchor to the real
            # test date" discipline _real_breach_forecast already uses.
            "tested_at": (
                tested_at_map.get(row.test_result_id).isoformat()
                if tested_at_map.get(row.test_result_id) else None
            ),
        })

    # Officer review state (KPTCL spec §14.3: "Deterioration Watch List
    # advisories pending officer review") — keyed to the exact snapshot
    # (equipment_id, parameter_key, history_count) each flagged parameter
    # was computed at, so a new test that changes the trend correctly shows
    # as unreviewed again rather than staying silently reviewed forever.
    review_keys = {
        (eq_id, p["parameter_key"], p["history_count"])
        for eq_id, params in flagged_by_equipment.items()
        for p in params
    }
    reviews_by_key: dict = {}
    if review_keys:
        review_rows = (
            db.query(DeteriorationReviewRecord)
            .filter(DeteriorationReviewRecord.equipment_id.in_({k[0] for k in review_keys}))
            .all()
        )
        for r in review_rows:
            reviews_by_key[(r.equipment_id, r.parameter_key, r.history_count)] = r

    pending_review_count = 0
    for eq_id, params in flagged_by_equipment.items():
        for p in params:
            review = reviews_by_key.get((eq_id, p["parameter_key"], p["history_count"]))
            p["is_reviewed"] = review is not None
            p["review_disposition"] = review.disposition if review else None
            p["review_note"] = review.note if review else None
            if review is None:
                pending_review_count += 1

    watch_list = []
    for eq_id, params in flagged_by_equipment.items():
        eq = eq_by_id.get(eq_id)
        if not eq:
            continue
        ea = analytics_map.get(eq_id)
        # Sort key: soonest forecast breach first; parameters with no
        # forecast yet (trend detected but not near enough to project a
        # crossing date) sort after those that do, ranked among themselves
        # by the steepest annual rate of change.
        forecast_days = [p["days_to_breach"] for p in params if p["days_to_breach"] is not None]
        soonest_days = min(forecast_days) if forecast_days else None
        steepest_change = max((abs(p["annual_change"]) for p in params if p["annual_change"] is not None), default=0.0)
        watch_list.append({
            "equipment_id":    str(eq_id),
            "equipment_label": eq.ueic,
            "equipment_type":  equipment_type_names.get(eq.equipment_type_id),
            "department_id":   str(eq.department_id) if eq.department_id else None,
            "health_score":    float(ea.health_score) if ea and ea.health_score is not None else None,
            "risk_level":      ea.risk_level if ea and ea.risk_level else "Unknown",
            "soonest_days_to_breach": soonest_days,
            "parameters": sorted(
                params,
                key=lambda p: (p["days_to_breach"] is None, p["days_to_breach"] or 0, -(abs(p["annual_change"] or 0))),
            ),
        })

    watch_list.sort(key=lambda w: (w["soonest_days_to_breach"] is None, w["soonest_days_to_breach"] or 0, -(
        max((abs(p["annual_change"]) for p in w["parameters"] if p["annual_change"] is not None), default=0.0)
    )))

    return {
        "total_equipment": len(equipment_rows),
        "watch_count": len(watch_list),
        "pending_review_count": pending_review_count,
        "equipment": watch_list,
    }


class DeteriorationReviewIn(BaseModel):
    equipment_id: uuid.UUID
    parameter_key: str
    template_key: str
    disposition: Literal[
        "monitor", "request_retest", "escalate_repair", "dismiss",
    ]
    note: Optional[str] = None


@router.post(
    "/deterioration-watch-list/review",
    summary="Record an officer's disposition on one Deterioration Watch List advisory",
)
def review_deterioration_advisory(
    body: DeteriorationReviewIn,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """KPTCL spec §14.3's "advisories pending officer review", same
    disposition-and-lock pattern as the Result Review workflow (§8) —
    'dismiss' requires a note (§8's "No Action" needs "mandatory
    justification"). Does NOT create a Testing Request itself for
    'request_retest' — the app already has a score-based recommendation/
    scheduling path (condition_recommendation_service.py) and an ad-hoc
    Quick Test Request flow; the Flutter side opens that existing dialog
    rather than a second request-creation path being built here.
    """
    if body.disposition == "dismiss" and not (body.note and body.note.strip()):
        raise HTTPException(status_code=422, detail="note is required when dismissing an advisory")

    # Resolve the CURRENT history_count server-side — never trust a value
    # from the client — so a stale client can't "review" a snapshot that's
    # already been superseded by a newer test.
    latest = (
        db.query(ParameterAnalytics)
        .filter(
            ParameterAnalytics.equipment_id == body.equipment_id,
            ParameterAnalytics.parameter_key == body.parameter_key,
        )
        .order_by(ParameterAnalytics.history_count.desc(), ParameterAnalytics.calculated_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No analytics found for this equipment/parameter")

    org_id = user.get("organization_id") if isinstance(user, dict) else getattr(user, "organization_id", None)
    reviewer_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)

    existing = (
        db.query(DeteriorationReviewRecord)
        .filter(
            DeteriorationReviewRecord.equipment_id == body.equipment_id,
            DeteriorationReviewRecord.parameter_key == body.parameter_key,
            DeteriorationReviewRecord.history_count == latest.history_count,
        )
        .first()
    )
    if existing:
        existing.disposition = body.disposition
        existing.note = body.note
        existing.reviewed_by = reviewer_id
        existing.reviewed_at = datetime.now(timezone.utc)
    else:
        db.add(DeteriorationReviewRecord(
            equipment_id=body.equipment_id,
            parameter_key=body.parameter_key,
            template_key=body.template_key,
            history_count=latest.history_count,
            disposition=body.disposition,
            note=body.note,
            reviewed_by=reviewer_id,
            organization_id=org_id,
        ))
    db.commit()

    # "Escalate to Repair Review" isn't just a label to record — it should
    # actually reach the officers who'd act on it (KPTCL spec's own pattern:
    # every escalation-shaped disposition elsewhere in this app fires a real
    # notification, not a silent audit row).
    if body.disposition == "escalate_repair":
        try:
            from services.notification_service import NotificationService
            eq = db.get(Equipment, body.equipment_id)
            reviewer = db.get(User, reviewer_id) if reviewer_id else None
            reviewer_name = (
                " ".join(filter(None, [reviewer.firstname, reviewer.lastname])) or reviewer.email
                if reviewer else "An officer"
            )
            NotificationService(db).notify_deterioration_escalated(
                equipment_label=eq.ueic if eq else "Equipment",
                parameter_label=latest.parameter_label or latest.parameter_key,
                trend=latest.trend,
                days_to_breach=None,  # not recomputed here — the review sheet already showed it
                escalated_by=reviewer_name,
                note=body.note or "",
                analytics_id=latest.id,
                organization_id=org_id,
                department_id=eq.department_id if eq else None,
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "deterioration_watch_escalated notification failed", exc_info=True
            )

    return {"status": "ok", "history_count": latest.history_count, "disposition": body.disposition}


# ─────────────────────────────────────────────────────────────────────────────
# Equipment drill-down
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/equipment/{equipment_id}", summary="Aggregated health analytics for one equipment")
def get_equipment_analytics(
    equipment_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    ea  = db.query(EquipmentAnalytics).filter(EquipmentAnalytics.equipment_id == equipment_id).first()
    if not ea:
        raise HTTPException(status_code=404, detail="No analytics available for this equipment")
    eq  = db.get(Equipment, equipment_id)
    return _serialize_equipment_analytics(ea, eq)


@router.get(
    "/equipment/{equipment_id}/tests",
    summary="Test history for equipment — each test result linked to its analytics",
)
def get_equipment_test_history(
    equipment_id: uuid.UUID,
    template_key: Optional[str] = Query(None, description="Filter to one test type"),
    limit:        int           = Query(50, ge=1, le=200),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns every TestAnalytics row for this equipment, latest-first.
    Each item includes:
      - test_result_id     → call GET /analytics/test-results/{id} for full analytics
      - testing_request_id → call GET /testing-requests/{id} for the request record
      - template_key, tested_at, health_score, risk_level, critical_findings
      - links.analytics, links.raw
    """
    from models import TestResult as _TR2, TestingRequest as _TReq, TestingRequestStatus as _TRS, TrWfInstance as _TWI
    from sqlalchemy import or_ as _or

    _SKIP = [
        _TRS.draft, _TRS.submitted, _TRS.assigned,
        _TRS.accepted, _TRS.in_progress,
    ]
    # Sub-select: test_result_ids whose TR is closed/completed
    _wf_done = db.query(_TWI.testing_request_id).filter(
        _TWI.status.in_(["completed", "terminated"])
    ).scalar_subquery()
    _closed_result_ids = (
        db.query(_TR2.id)
        .join(_TReq, _TR2.testing_request_id == _TReq.id)
        .filter(
            _or(
                _TReq.status.notin_(_SKIP),
                _TReq.id.in_(_wf_done),
            )
        )
        .scalar_subquery()
    )

    q = (
        db.query(TestAnalytics)
        .filter(
            TestAnalytics.equipment_id == equipment_id,
            TestAnalytics.test_result_id.in_(_closed_result_ids),
        )
        .order_by(TestAnalytics.calculated_at.desc())
    )
    if template_key:
        q = q.filter(TestAnalytics.template_key == template_key)
    rows = q.limit(limit).all()

    # Bulk-fetch tested_at from TestResult
    result_ids = [r.test_result_id for r in rows]
    tested_at_map = {
        r.id: r.tested_at or r.cts
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }

    return [_serialize_test_history_item(r, tested_at_map.get(r.test_result_id)) for r in rows]


@router.get(
    "/equipment/{equipment_id}/test-types",
    summary="Per-test-type AI analysis for one equipment (latest result per template)",
)
def get_equipment_test_types(
    equipment_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns the latest TestAnalytics row per template_key for this equipment,
    with AI narrative fields (condition_summary, trend_summary, critical_findings,
    recommendations) so the dashboard can show per-test-type AI analysis.
    """
    # Latest row per template_key. Order by tested_at (the actual test date),
    # not calculated_at (when it was last recomputed) - a bulk recompute
    # processes test results in arbitrary DB order, not chronological, so
    # calculated_at-ordering can pick an older test that simply happened to
    # be recomputed last, showing its score instead of the true latest
    # test's. This must match the tested_at-first ordering equipment_
    # analytics' own "latest per template" aggregation already uses, or the
    # per-template tab scores here can disagree with the equipment-level
    # health score derived from that other, correctly-ordered query.
    rows = (
        db.query(TestAnalytics)
        .join(TestResult, TestResult.id == TestAnalytics.test_result_id)
        .filter(TestAnalytics.equipment_id == equipment_id)
        .order_by(
            TestAnalytics.template_key,
            func.coalesce(TestResult.tested_at, TestResult.cts).desc(),
            TestAnalytics.calculated_at.desc(),
            # Final deterministic tiebreak - without this, two rows sharing
            # the same tested_at/calculated_at (e.g. bulk-imported together,
            # or recomputed in the same transaction) let Postgres pick either
            # one arbitrarily, so "the latest" could flip between requests.
            TestAnalytics.id.desc(),
        )
        .all()
    )

    # Dedupe: keep only the latest per template_key
    seen: set[str] = set()
    latest: list[TestAnalytics] = []
    for row in rows:
        if row.template_key not in seen:
            seen.add(row.template_key)
            latest.append(row)

    # Bulk-fetch test names from TestResult
    result_ids = [r.test_result_id for r in latest]
    tr_map = {
        r.id: r
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }

    result = []
    for row in latest:
        tr = tr_map.get(row.test_result_id)
        result.append({
            "template_key":      row.template_key,
            "test_name":         tr.test_name     if tr else row.template_key,
            "test_category":     tr.test_category if tr else None,
            "health_score":      float(row.health_score) if row.health_score is not None else None,
            "risk_level":        row.risk_level,
            "condition_summary": row.condition_summary,
            "trend_summary":     row.trend_summary,
            "critical_findings": row.critical_findings or [],
            "recommendations":   row.recommendations  or [],
            "parameter_count":   row.parameter_count,
            "tested_at":         (tr.tested_at or tr.cts).isoformat() if tr and (tr.tested_at or tr.cts) else None,
            "calculated_at":     row.calculated_at.isoformat() if row.calculated_at else None,
        })

    return result


@router.get(
    "/equipment/{equipment_id}/parameters",
    summary="Latest parameter analytics for all tracked parameters on an equipment",
)
def get_parameter_analytics(
    equipment_id: uuid.UUID,
    template_key: Optional[str] = Query(None),
    date_from:    Optional[date] = Query(None),
    date_to:      Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    ParameterAnalytics has one row per (test_result_id, parameter_key)  -  an
    equipment with N historical tests for "Acidity" has N separate Acidity
    rows, one per test. This endpoint surfaces the equipment's *current*
    snapshot per parameter, so it must collapse to the single most-recently
    -tested row per (parameter_key, template_key)  -  ordering by tested_at
    (not calculated_at, which is write time and can lag behind ingestion/
    recompute order) and keeping only the first row seen per group.
    """
    from sqlalchemy.orm import aliased
    TR = aliased(TestResult)
    q = (
        db.query(ParameterAnalytics)
        .join(TR, TR.id == ParameterAnalytics.test_result_id)
        .filter(ParameterAnalytics.equipment_id == equipment_id)
    )
    if template_key:
        q = q.filter(ParameterAnalytics.template_key == template_key)
    # Use COALESCE(tested_at, cts) so historical records with null tested_at are included
    coalesced = func.coalesce(TR.tested_at, TR.cts)
    if date_from:
        q = q.filter(coalesced >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(coalesced < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    rows = q.order_by(
        ParameterAnalytics.parameter_key,
        ParameterAnalytics.template_key,
        coalesced.desc(),
        # Final deterministic tiebreak - see the same tiebreak in
        # get_equipment_test_types() for why this matters.
        ParameterAnalytics.calculated_at.desc(),
        ParameterAnalytics.id.desc(),
    ).all()
    result_ids = [r.test_result_id for r in rows]
    tested_at_map = {
        r.id: (r.tested_at or r.cts)
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }

    # Collapse to the latest row per (parameter_key, template_key)  -  the
    # ORDER BY above puts the most-recently-tested row of each group first.
    latest: dict[tuple, ParameterAnalytics] = {}
    for r in rows:
        gkey = (r.parameter_key, r.template_key)
        if gkey not in latest:
            latest[gkey] = r

    # CRITICAL/ALERT first, then within each severity tier parameters with a
    # computable trend before ones stuck on "Insufficient_Data" (too few
    # readings for a regression), then alphabetical by parameter_key.
    severity_rank = {"CRITICAL": 0, "ALERT": 1}
    ordered = sorted(
        latest.values(),
        key=lambda r: (
            severity_rank.get(r.status, 2),
            r.trend == "Insufficient_Data",
            r.parameter_key or "",
        ),
    )

    eq_for_context = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    voltage_class = eq_for_context.voltage_class if eq_for_context else None

    return [
        _serialize_parameter_analytics(r, tested_at_map.get(r.test_result_id), db, voltage_class)
        for r in ordered
    ]


@router.get(
    "/equipment/{equipment_id}/parameters/{parameter_key}/history",
    summary="Time-series history of one parameter across all test runs",
)
def get_parameter_history(
    equipment_id:  uuid.UUID,
    parameter_key: str,
    template_key:  Optional[str] = Query(None),
    limit:         int           = Query(50, ge=1, le=500),
    date_from:     Optional[date] = Query(None),
    date_to:       Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns chronological readings for a single parameter, including the raw
    measured value, the test_result_id and testing_request_id so the caller
    can navigate to the actual stored result.

    Each item:
      {
        "tested_at":          "2024-03-15T09:30:00Z",
        "value":              42.5,
        "unit":               "MOhm",
        "condition":          "Good",
        "status":             "NORMAL",
        "score":              100,
        "is_anomaly":         false,
        "test_result_id":     "...",
        "testing_request_id": "...",
        "links": {
          "test_result":         "/analytics/test-results/{id}",
          "raw_data":            "/analytics/test-results/{id}/raw",
          "testing_request":     "/testing-requests/{id}"
        }
      }
    """
    # Trend always shows full history — the date filter controls the equipment list,
    # not the time-series chart. date_from / date_to are accepted but ignored here.
    #
    # Ordered by the actual test date (TestResult.tested_at, falling back to cts),
    # not ParameterAnalytics.calculated_at — calculated_at reflects when the
    # analytics row was computed, which can lag or precede the real test date
    # when results are imported/backfilled out of chronological order, producing
    # a chart that plots points in the wrong sequence despite correct date labels.
    # Ordered DESC + limit so a parameter with more history than `limit`
    # keeps its most RECENT readings (previously ordered ASC before the
    # limit, which kept the oldest `limit` readings instead - silently
    # dropping the newest data, including whatever test was just performed,
    # for any parameter with more than `limit` historical readings).
    # Reversed back to chronological (oldest-first) order below for display.
    q = (
        db.query(ParameterAnalytics)
        .join(TestResult, TestResult.id == ParameterAnalytics.test_result_id)
        .filter(
            ParameterAnalytics.equipment_id  == equipment_id,
            ParameterAnalytics.parameter_key == parameter_key,
        )
        .order_by(func.coalesce(TestResult.tested_at, TestResult.cts,
                                 ParameterAnalytics.calculated_at).desc(),
                  ParameterAnalytics.id.desc())
    )
    if template_key:
        q = q.filter(ParameterAnalytics.template_key == template_key)
    rows = list(reversed(q.limit(limit).all()))

    # Bulk-fetch tested_at + testing_request_id from TestResult
    result_ids = [r.test_result_id for r in rows]
    results_map = {
        r.id: r
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }

    # For cumulative templates (OLTC ops, CB ops): derive condition from the
    # running cumulative diff at each reading vs the overhaul threshold.
    # This is exactly the same logic that triggers the workflow ticket.
    cumulative_condition_map: dict = {}
    cumulative_raw_readings: list = []
    cumulative_equipment_id = None
    if rows:
        tpl_key = rows[0].template_key
        tpl_row = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == tpl_key)
            .first()
        )
        tpl_data = tpl_row.template_data if tpl_row else {}
        if tpl_data.get("enable_cumulative"):
            rules = tpl_data.get("rules", [])
            threshold = next(
                (r["config"].get("default_threshold")
                 for r in rules if r.get("type") == "CUMULATIVE_DIFF"),
                None,
            )
            if threshold:
                # Build readings list ordered by reading_date
                raw_readings = []
                for row in rows:
                    tr = results_map.get(row.test_result_id)
                    td = (tr.test_data or {}) if tr else {}
                    reading_val = td.get("reading")
                    order_val   = td.get("reading_date") or (tr.cts.isoformat() if tr and tr.cts else "")
                    if reading_val is not None:
                        eq_id = getattr(tr, "equipment_id", None)
                        if eq_id and not cumulative_equipment_id:
                            cumulative_equipment_id = eq_id
                        raw_readings.append({
                            "result_id":    row.test_result_id,
                            "reading_time": order_val,
                            "reading":      float(reading_val),
                        })
                raw_readings.sort(key=lambda x: x["reading_time"])
                cumulative_raw_readings = raw_readings
                # Running cumulative diff with reset on drop (same as CumulativeService)
                running  = 0.0
                prev_val = None
                for pt in raw_readings:
                    val = pt["reading"]
                    if prev_val is not None:
                        diff = val - prev_val
                        if diff > 0:
                            running += diff
                        elif diff < 0:
                            running = 0.0  # counter reset after overhaul
                    prev_val = val
                    pct = running / threshold
                    cond = "Poor" if pct >= 1.0 else "Fair" if pct >= 0.7 else "Good"
                    cumulative_condition_map[pt["result_id"]] = (cond, round(running, 1))

    # Build overhaul ticket map: result_id → (workflow_number, rec_status)
    overhaul_ticket_map: dict = {}
    if cumulative_condition_map and cumulative_equipment_id:
        overhaul_recs = (
            db.query(OverhaulRecommendation, RepairWorkflow)
            .outerjoin(RepairWorkflow, RepairWorkflow.id == OverhaulRecommendation.workflow_id)
            .filter(OverhaulRecommendation.equipment_id == cumulative_equipment_id)
            .order_by(OverhaulRecommendation.triggered_at)
            .all()
        )
        if overhaul_recs:
            rec_timeline = [
                {
                    "triggered_at": rec.triggered_at,
                    "workflow_number": wf.workflow_number if wf else None,
                    "status": rec.status,
                }
                for rec, wf in overhaul_recs
            ]
            for pt_dict in cumulative_raw_readings:
                rid = pt_dict["result_id"]
                if cumulative_condition_map.get(rid, ("Good", 0))[0] != "Poor":
                    continue
                reading_time_str = pt_dict.get("reading_time", "")
                matched = None
                for rec_entry in rec_timeline:
                    ta = rec_entry["triggered_at"]
                    ta_str = ta.isoformat() if ta else ""
                    if ta_str <= reading_time_str:
                        matched = rec_entry
                if matched:
                    overhaul_ticket_map[rid] = (matched["workflow_number"], matched["status"])

    points = []
    for row in rows:
        tr  = results_map.get(row.test_result_id)
        pt  = _serialize_parameter_history_point(row, tr)
        if row.test_result_id in cumulative_condition_map:
            cond, cum_val = cumulative_condition_map[row.test_result_id]
            pt["condition"]        = cond
            pt["cumulative_value"] = cum_val
        if row.test_result_id in overhaul_ticket_map:
            wf_num, rec_status = overhaul_ticket_map[row.test_result_id]
            pt["overhaul_ticket_number"] = wf_num
            pt["overhaul_ticket_status"] = rec_status
        points.append(pt)
    return points


# ─────────────────────────────────────────────────────────────────────────────
# Test-result drill-down
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/test-results/{test_result_id}", summary="Test-level analytics")
def get_test_analytics(
    test_result_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    row = db.query(TestAnalytics).filter(TestAnalytics.test_result_id == test_result_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Analytics not yet computed for this test result")
    tr = db.get(TestResult, test_result_id)
    return _serialize_test_analytics(row, tr)


@router.get(
    "/test-results/{test_result_id}/raw",
    summary="Test-level analytics + the actual stored test_data JSONB",
)
def get_test_analytics_with_raw(
    test_result_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns the full analytics alongside the raw `test_data` JSONB that was
    recorded by the tester, plus the per-field `evaluation_result`.
    This is the terminal drill-down: the user sees both the computed insights
    and the underlying measurements side-by-side.
    """
    row = db.query(TestAnalytics).filter(TestAnalytics.test_result_id == test_result_id).first()
    tr  = db.get(TestResult, test_result_id)

    if not tr:
        raise HTTPException(status_code=404, detail="Test result not found")

    req = db.get(TestingRequest, tr.testing_request_id) if tr.testing_request_id else None
    eq  = db.get(Equipment, req.equipment_id) if req and req.equipment_id else None

    analytics = _serialize_test_analytics(row, tr) if row else None

    return {
        "analytics":        analytics,
        "test_result": {
            "id":                  str(tr.id),
            "testing_request_id":  str(tr.testing_request_id) if tr.testing_request_id else None,
            "test_name":           tr.test_name,
            "test_category":       tr.test_category,
            "template_key":        tr.template_key,
            "overall_result":      tr.overall_result,
            "tested_at":           tr.tested_at.isoformat() if tr.tested_at else None,
            "test_data":           tr.test_data or {},
            "evaluation_result":   tr.evaluation_result or {},
            "remarks":             tr.remarks,
        },
        "equipment": _serialize_equipment_brief(eq) if eq else None,
        "testing_request": {
            "id":             str(req.id),
            "request_number": req.request_number,
            "title":          getattr(req, "title", None),
            "status":         req.status.value if req.status else None,
        } if req else None,
        "links": {
            "equipment_analytics": f"/analytics/equipment/{eq.id}" if eq else None,
            "equipment_tests":     f"/analytics/equipment/{eq.id}/tests" if eq else None,
            "parameter_analytics": f"/analytics/equipment/{eq.id}/parameters?template_key={tr.template_key}" if eq and tr.template_key else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _apply_tested_at_filter(q, date_from: Optional[date], date_to: Optional[date]):
    """Join TestResult onto a TestingRequest-based query and filter by
    TestResult.tested_at (coalesced with cts for legacy rows with no
    tested_at), both bounds optional. No-op (no join) when neither bound is
    given, so callers' row shape is unchanged for the unfiltered case."""
    if not date_from and not date_to:
        return q
    q = q.join(TestResult, TestResult.testing_request_id == TestingRequest.id)
    coalesced = func.coalesce(TestResult.tested_at, TestResult.cts)
    if date_from:
        q = q.filter(coalesced >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(coalesced < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return q


def _collect_department_ids(root_id: uuid.UUID, db: Session) -> set:
    """BFS to collect root + all descendant department IDs."""
    visited: set = set()
    queue = [root_id]
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        children = (
            db.query(OrgDepartment.id)
            .filter(OrgDepartment.parent_department_id == current)
            .all()
        )
        queue.extend(child_id for (child_id,) in children)
    return visited


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_hierarchy_analytics(row: HierarchyAnalytics, dept: Optional[OrgDepartment] = None) -> dict:
    return {
        "id":                    str(row.id),
        "department_id":         str(row.department_id),
        "department_name":       dept.name if dept else None,
        "department_code":       dept.code if dept else None,
        "parent_department_id":  str(row.parent_department_id) if row.parent_department_id else None,
        "level_type":            row.level_type,
        "health_score":          float(row.health_score) if row.health_score is not None else None,
        "risk_level":            row.risk_level,
        "equipment_count":       row.equipment_count,
        "equipment_critical":    row.equipment_critical,
        "equipment_high":        row.equipment_high,
        "equipment_medium":      row.equipment_medium,
        "equipment_low":         row.equipment_low,
        "child_count":           row.child_count,
        "child_breakdown":       row.child_breakdown or {},
        "calculated_at":         row.calculated_at.isoformat() if row.calculated_at else None,
        "links": {
            "self":      f"/analytics/departments/{row.department_id}",
            "tree":      f"/analytics/departments/{row.department_id}/tree",
            "equipment": f"/analytics/departments/{row.department_id}/equipment",
        },
    }


def _serialize_equipment_summary(
    eq: Equipment,
    ea: Optional[EquipmentAnalytics],
    type_map: dict,
) -> dict:
    return {
        "equipment_id":      str(eq.id),
        "ueic":              eq.ueic,
        "manufacturer":      eq.manufacturer,
        "model_number":      eq.model_number,
        "equipment_type":    type_map.get(eq.equipment_type_id),
        "department_id":     str(eq.department_id) if eq.department_id else None,
        "commissioned_date": eq.commissioned_date.isoformat() if eq.commissioned_date else None,
        "status":            eq.status.value if eq.status else None,
        # analytics (None if not yet computed)
        "health_score":      float(ea.health_score)      if ea and ea.health_score      is not None else None,
        "risk_level":        ea.risk_level                if ea else None,
        "condition_summary": ea.condition_summary         if ea else None,
        "last_test_date":    ea.last_test_date.isoformat() if ea and ea.last_test_date  else None,
        "parameters_at_risk":ea.parameters_at_risk        if ea else None,
        "test_types_assessed":ea.test_types_assessed      if ea else None,
        "analytics_computed":ea is not None,
        "links": {
            "analytics":   f"/analytics/equipment/{eq.id}",
            "tests":       f"/analytics/equipment/{eq.id}/tests",
            "parameters":  f"/analytics/equipment/{eq.id}/parameters",
        },
    }


def _serialize_equipment_analytics(ea: EquipmentAnalytics, eq: Optional[Equipment] = None) -> dict:
    return {
        "id":                   str(ea.id),
        "equipment_id":         str(ea.equipment_id),
        "ueic":                 eq.ueic          if eq else None,
        "manufacturer":         eq.manufacturer  if eq else None,
        "model_number":         eq.model_number  if eq else None,
        "department_id":        str(ea.department_id) if ea.department_id else None,
        "health_score":         float(ea.health_score) if ea.health_score is not None else None,
        "risk_level":           ea.risk_level,
        "condition_summary":    ea.condition_summary,
        "test_type_scores":     ea.test_type_scores     or {},
        "critical_findings":    ea.critical_findings    or [],
        "parameters_at_risk":   ea.parameters_at_risk,
        "test_types_assessed":  ea.test_types_assessed,
        "last_test_date":       ea.last_test_date.isoformat() if ea.last_test_date else None,
        "calculated_at":        ea.calculated_at.isoformat()  if ea.calculated_at  else None,
        "links": {
            "tests":      f"/analytics/equipment/{ea.equipment_id}/tests",
            "parameters": f"/analytics/equipment/{ea.equipment_id}/parameters",
            "department": f"/analytics/departments/{ea.department_id}" if ea.department_id else None,
        },
    }


def _serialize_equipment_brief(eq: Equipment) -> dict:
    return {
        "equipment_id":     str(eq.id),
        "ueic":             eq.ueic,
        "manufacturer":     eq.manufacturer,
        "model_number":     eq.model_number,
        "department_id":    str(eq.department_id) if eq.department_id else None,
        "status":           eq.status.value if eq.status else None,
    }


def _serialize_test_analytics(row: TestAnalytics, tr: Optional[TestResult] = None) -> dict:
    return {
        "id":                str(row.id),
        "test_result_id":    str(row.test_result_id),
        "testing_request_id":str(row.testing_request_id) if row.testing_request_id else None,
        "equipment_id":      str(row.equipment_id),
        "template_key":      row.template_key,
        "test_name":         tr.test_name      if tr else None,
        "test_category":     tr.test_category  if tr else None,
        "tested_at":         (tr.tested_at or tr.cts).isoformat() if tr and (tr.tested_at or tr.cts) else None,
        "overall_result":    tr.overall_result if tr else None,
        "health_score":      float(row.health_score) if row.health_score is not None else None,
        "risk_level":        row.risk_level,
        "condition_summary": row.condition_summary,
        "trend_summary":     row.trend_summary,
        "critical_findings": row.critical_findings or [],
        "recommendations":   row.recommendations  or [],
        "parameter_count":   row.parameter_count,
        "evaluated_count":   row.evaluated_count,
        "calculated_at":     row.calculated_at.isoformat() if row.calculated_at else None,
        "links": {
            "self":            f"/analytics/test-results/{row.test_result_id}",
            "raw":             f"/analytics/test-results/{row.test_result_id}/raw",
            "equipment":       f"/analytics/equipment/{row.equipment_id}",
            "parameters":      f"/analytics/equipment/{row.equipment_id}/parameters?template_key={row.template_key}",
            "testing_request": f"/testing-requests/{row.testing_request_id}" if row.testing_request_id else None,
        },
    }


def _serialize_test_history_item(row: TestAnalytics, tested_at) -> dict:
    return {
        "test_result_id":    str(row.test_result_id),
        "testing_request_id":str(row.testing_request_id) if row.testing_request_id else None,
        "template_key":      row.template_key,
        "tested_at":         tested_at.isoformat() if tested_at else None,
        "health_score":      float(row.health_score) if row.health_score is not None else None,
        "risk_level":        row.risk_level,
        "condition_summary": row.condition_summary,
        "critical_findings": row.critical_findings or [],
        "evaluated_count":   row.evaluated_count,
        "links": {
            "analytics":       f"/analytics/test-results/{row.test_result_id}",
            "raw":             f"/analytics/test-results/{row.test_result_id}/raw",
            "testing_request": f"/testing-requests/{row.testing_request_id}" if row.testing_request_id else None,
        },
    }


def _real_breach_forecast(
    row: ParameterAnalytics,
    db: Optional[Session],
    voltage_class: Optional[str],
    tested_at=None,
    candidate_bands: Optional[list] = None,
) -> dict:
    """{is_concerning, breach_value, breach_band, breach_predicted_at,
    days_to_breach, is_overdue_for_retest} computed from
    ParameterThresholdBand. Single shared implementation for both the
    Deterioration Watch List and the equipment/parameter-detail endpoint
    — was duplicated between the two, which is how the date-anchoring bug
    below only got caught in one of them.

    Pass candidate_bands when the caller already bulk-fetched
    ParameterThresholdBand rows for a batch of equipment (the Watch List
    does, to avoid one query per parameter) — skips the per-row query
    below. Leave it None (default) to have this function fetch them
    itself, one row at a time (fine for the single-equipment
    parameter-detail endpoint).

    is_concerning is None (not False) when there's no threshold config to
    judge by at all — the frontend should fall back to a neutral
    treatment then, not guess.

    Fixes three things table-row parameters previously got wrong: (1) the
    stored ParameterAnalytics.breach_threshold/days_to_breach columns are
    only ever populated for flat-field parameters, so they were always
    None here; (2) "Increasing = bad" was assumed universally, backwards
    for every parameter where lower is the bad direction (confirmed live:
    Interfacial Tension trending down toward its own real Fair boundary
    showed in green); (3) the trend-fit's own "N days to breach" is
    measured from the LAST TEST's own position on the line, not from
    today — confirmed live: an equipment last tested 25/11/2022 had a
    59-day trend-fit result, which one code path added to today's date
    (29/10/2026 — nonsensical, implies the countdown only started now)
    while another correctly added it to the actual test date (23/1/2023).
    Anchoring to the test date is the only one that's actually true: if
    nothing has been retested since, the trend already implied a probable
    breach almost 4 years ago — that's a "this needs retesting now" flag,
    is_overdue_for_retest, not a future date to display as if it hasn't
    happened yet.
    """
    out = {
        "is_concerning": None, "breach_value": None, "breach_band": None,
        "breach_predicted_at": None, "days_to_breach": None, "is_overdue_for_retest": False,
    }
    if db is None or row.trend not in ("Increasing", "Decreasing") or row.current_value is None or row.trend_slope is None:
        return out
    row_id = _table_row_id(row.parameter_key)
    if candidate_bands is None:
        candidate_bands = (
            db.query(ParameterThresholdBand)
            .filter(
                ParameterThresholdBand.template_key == row.template_key,
                ParameterThresholdBand.parameter_key == row_id,
                ParameterThresholdBand.is_active.is_(True),
            )
            .all()
        )
    if not candidate_bands:
        return out
    context_keys = sorted({b.context_key for b in candidate_bands if b.context_key})
    if context_keys:
        resolved_ctx = _resolve_context_key(context_keys, voltage_class)
        scoped_bands = [b for b in candidate_bands if b.context_key == resolved_ctx]
    else:
        scoped_bands = candidate_bands
    breach_value, breach_label = _next_worse_boundary(
        scoped_bands, float(row.current_value), float(row.trend_slope),
        _load_band_rank_words(db),
    )
    out["is_concerning"] = breach_value is not None
    if breach_value is None:
        return out

    days_from_test = (breach_value - float(row.current_value)) / float(row.trend_slope)
    if not (0 <= days_from_test <= 3650):  # same 10-year cap as before
        return out

    anchor = (tested_at.date() if hasattr(tested_at, "date") else tested_at) if tested_at else date.today()
    predicted_date = anchor + timedelta(days=round(days_from_test))
    days_from_today = (predicted_date - date.today()).days

    out["breach_value"] = breach_value
    out["breach_band"] = breach_label
    out["breach_predicted_at"] = predicted_date.isoformat()
    out["days_to_breach"] = max(0, days_from_today)
    out["is_overdue_for_retest"] = days_from_today < 0
    return out


def _serialize_parameter_analytics(row: ParameterAnalytics, tested_at=None,
                                    db: Optional[Session] = None,
                                    voltage_class: Optional[str] = None) -> dict:
    forecast = _real_breach_forecast(row, db, voltage_class, tested_at)
    return {
        "last_tested_at": tested_at.isoformat() if tested_at else None,
        "trend_is_concerning": forecast["is_concerning"],
        "is_overdue_for_retest": forecast["is_overdue_for_retest"],
        "id":                   str(row.id),
        "equipment_id":         str(row.equipment_id),
        "test_result_id":       str(row.test_result_id),
        "template_key":         row.template_key,
        "parameter_key":        row.parameter_key,
        "parameter_label":      row.parameter_label,
        "parameter_type":       row.parameter_type,
        "current_value":        float(row.current_value)     if row.current_value     is not None else None,
        "unit":                 row.unit,
        "condition":            row.condition,
        "status":               row.status,
        "score":                float(row.score)             if row.score             is not None else None,
        "trend":                row.trend,
        "trend_slope":          float(row.trend_slope)       if row.trend_slope       is not None else None,
        "trend_r_squared":      float(row.trend_r_squared)   if row.trend_r_squared   is not None else None,
        "history_count":        row.history_count,
        "annual_change":        float(row.annual_change)     if row.annual_change     is not None else None,
        "pct_change_annual":    float(row.pct_change_annual) if row.pct_change_annual is not None else None,
        "breach_threshold":     forecast["breach_value"],
        "breach_band":          forecast["breach_band"],
        "breach_predicted_at":  forecast["breach_predicted_at"],
        "days_to_breach":       forecast["days_to_breach"],
        "is_anomaly":           row.is_anomaly,
        "anomaly_type":         row.anomaly_type,
        "anomaly_detail":       row.anomaly_detail,
        "remedial_action_text": row.remedial_action_text,
        "calculated_at":        row.calculated_at.isoformat() if row.calculated_at else None,
        "links": {
            "test_result":   f"/analytics/test-results/{row.test_result_id}",
            "raw_data":      f"/analytics/test-results/{row.test_result_id}/raw",
            "history":       f"/analytics/equipment/{row.equipment_id}/parameters/{row.parameter_key}/history?template_key={row.template_key}",
        },
    }


def _serialize_parameter_history_point(row: ParameterAnalytics, tr: Optional[TestResult]) -> dict:
    tested_at = None
    if tr:
        dt = tr.tested_at or tr.cts
        tested_at = dt.isoformat() if dt else None

    return {
        "tested_at":          tested_at,
        "value":              float(row.current_value)  if row.current_value  is not None else None,
        "unit":               row.unit,
        "condition":          row.condition,
        "status":             row.status,
        "score":              float(row.score)          if row.score          is not None else None,
        "is_anomaly":         row.is_anomaly,
        "anomaly_type":       row.anomaly_type,
        "test_result_id":     str(row.test_result_id),
        "testing_request_id": str(tr.testing_request_id) if tr and tr.testing_request_id else None,
        "links": {
            "test_result":     f"/analytics/test-results/{row.test_result_id}",
            "raw_data":        f"/analytics/test-results/{row.test_result_id}/raw",
            "testing_request": f"/testing-requests/{tr.testing_request_id}" if tr and tr.testing_request_id else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Condition Monitoring Recommendations — evaluate for one equipment
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/equipment/{equipment_id}/recommendations",
    summary="Condition monitoring recommendations for one equipment based on health score",
)
def get_equipment_recommendations(
    equipment_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    return evaluate_for_equipment(db, equipment_id)
