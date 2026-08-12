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
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, func
from sqlalchemy.orm import Session, joinedload

from database import get_vendor_db
from auth_utils import get_current_user
from models import (
    CategoryMaster,
    Equipment,
    EquipmentAnalytics,
    HierarchyAnalytics,
    OrgDepartment,
    OrgTestTemplate,
    OverhaulRecommendation,
    ParameterAnalytics,
    RepairWorkflow,
    TestAnalytics,
    TestResult,
    TestingRequest,
)
from services.condition_recommendation_service import evaluate_for_equipment
from services.analytics_engine import AnalyticsEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

_CAPACITY_NUM_RE = re.compile(r"[\d.]+")


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
    rows = db.query(
        TestingRequest.equipment_id, TestResult.test_data,
        TestResult.tested_at, TestResult.cts,
    ).join(TestResult, TestResult.testing_request_id == TestingRequest.id).filter(
        TestingRequest.equipment_id.in_(eq_ids),
    ).all()
    best: dict = {}
    for eq_id, test_data, tr_tested_at, tr_cts in rows:
        mva = _parse_capacity_mva((test_data or {}).get("capacity_mva"))
        if mva is None:
            continue
        eff_date = tr_tested_at or tr_cts
        cur = best.get(eq_id)
        if cur is None or (eff_date and (cur[1] is None or eff_date > cur[1])):
            best[eq_id] = (mva, eff_date)
    return {eq_id: v[0] for eq_id, v in best.items()}


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

    def _empty_health() -> dict:
        return {"critical": 0, "high": 0, "healthy": 0, "untested": 0, "sum": 0.0, "cnt": 0}

    def _add_health(bucket: dict, eq_id, tested: bool, source=None) -> None:
        """Fold one equipment into exactly one bucket, so critical + high +
        healthy + untested always equals the group's total asset count.
        `tested` = has a qualifying completed test (in-range when a date
        filter is active, ever otherwise); equipment with no analytics row
        yet (never assessed) always lands in "untested" regardless.
        `source` supplies risk_level/health_score — EquipmentAnalytics for
        the all-time view, or a date-scoped TestAnalytics snapshot when a
        range is active; falls back to the all-time ea_map lookup when
        omitted."""
        src = source if source is not None else ea_map.get(eq_id)
        if tested and src:
            rl = (src.risk_level or "").strip()
            if rl == "Critical":
                bucket["critical"] += 1
            elif rl == "High":
                bucket["high"] += 1
            else:
                bucket["healthy"] += 1
            if src.health_score is not None:
                bucket["sum"] += float(src.health_score)
                bucket["cnt"] += 1
        else:
            bucket["untested"] += 1

    def _finalise(bucket: dict) -> dict:
        return {
            "critical":   bucket["critical"],
            "high":       bucket["high"],
            "healthy":    bucket["healthy"],
            "untested":   bucket["untested"],
            "avg_health": round(bucket["sum"] / bucket["cnt"], 1) if bucket["cnt"] > 0 else None,
        }

    by_voltage:       dict[str, int]  = {}
    by_voltage_h:     dict[str, dict] = {}
    by_type:          dict[str, int]  = {}
    by_type_h:        dict[str, dict] = {}
    by_make:          dict[str, int]  = {}
    by_make_h:        dict[str, dict] = {}
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
            .filter(TestAnalytics.equipment_id.in_(eq_id_set))
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
    by_type_tests:         dict[str, int] = {}
    by_voltage_tests:      dict[str, int] = {}
    by_year_tests:         dict[str, int] = {}
    by_capacity_tests:     dict[str, int] = {}
    by_failure_year_tests: dict[str, int] = {}
    by_replacement_year_tests: dict[str, int] = {}

    by_make_test_events:         dict[str, int] = {}
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
        # the all-time EquipmentAnalytics snapshot when no range is selected,
        # or the date-scoped TestAnalytics snapshot (dated_ta_map) when one
        # is — see dated_ta_map's comment above for why. When a filter is
        # active, also require a non-null health_score: /ai-graph/grouped's
        # _eff_health treats a scoreless snapshot as "not assessed" (excluded
        # from its count), so this must too or the two dashboards' counts
        # drift apart again on that edge case.
        src = dated_ta_map.get(eq.id) if _date_filter_active else ea_map.get(eq.id)
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

    eq_query = db.query(EquipmentAnalytics)
    if org_id:
        eq_query = eq_query.filter(EquipmentAnalytics.organization_id == org_id)
    if dept_ids:
        eq_query = eq_query.filter(EquipmentAnalytics.department_id.in_(dept_ids))
    all_ea: list[EquipmentAnalytics] = eq_query.all()

    # ── 2. KPI summary ───────────────────────────────────────────────────────
    ea_eq_ids = [ea.equipment_id for ea in all_ea if ea.equipment_id]
    _TERMINAL_STATUSES_KPI = ("completed", "closed")

    # All equipment IDs in scope (from Equipment table — includes untested equipment)
    _scope_eq_q = db.query(Equipment.id).filter(Equipment.status != "retired")
    if org_id:
        _scope_eq_q = _scope_eq_q.filter(Equipment.organization_id == org_id)
    if dept_ids:
        _scope_eq_q = _scope_eq_q.filter(Equipment.department_id.in_(dept_ids))
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

    risk_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
    for ea in active_ea:
        risk_counts[ea.risk_level or "Unknown"] = risk_counts.get(ea.risk_level or "Unknown", 0) + 1

    total = len(active_ea)
    avg_score = round(
        sum(float(ea.health_score) for ea in active_ea if ea.health_score is not None) / total, 1
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
            db.query(func.count(TestingRequest.id))
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
        fresh_eval = EvaluationService.evaluate_test_data(template_data, tr.test_data or {})
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

    # All equipment in scope
    eq_q = db.query(Equipment)
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
    if commission_year:
        from sqlalchemy import extract
        eq_q = eq_q.filter(extract("year", Equipment.commissioned_date) == commission_year)
    if failure_year:
        from sqlalchemy import extract as _extract
        eq_q = eq_q.filter(Equipment.status == "retired")
        eq_q = eq_q.filter(_extract("year", Equipment.retired_date) == failure_year)
    all_eq: list[Equipment] = eq_q.all()

    # Apply equipment_type filter after type_map is built (done below)
    _filter_equipment_type = equipment_type

    eq_ids = [e.id for e in all_eq]

    # Analytics map — only equipment that has been tested has a row here
    ea_rows = db.query(EquipmentAnalytics).filter(
        EquipmentAnalytics.equipment_id.in_(eq_ids)
    ).all()
    ea_map = {r.equipment_id: r for r in ea_rows}

    # Exclude untested equipment when caller requests it (AI Analytics)
    if tested_only:
        all_eq = [e for e in all_eq if e.id in ea_map]

    # Apply risk_level filter
    if risk_level:
        all_eq = [e for e in all_eq if (ea_map.get(e.id) and ea_map[e.id].risk_level == risk_level)]

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

    _risk_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

    def _sort_key(eq: Equipment):
        ea = ea_map.get(eq.id)
        if ea is not None and ea.risk_level and ea.risk_level in _risk_order:
            score = float(ea.health_score) if ea.health_score is not None else 999.0
            return (0, _risk_order[ea.risk_level], score)
        return (1, 99, 999.0)

    sorted_eq = sorted(all_eq, key=_sort_key, reverse=True)
    total = len(sorted_eq)
    start = (page - 1) * page_size
    page_eq = sorted_eq[start: start + page_size]

    items = []
    for eq in page_eq:
        ea = ea_map.get(eq.id)
        # Build plain-English reason from critical_findings
        reason = None
        if ea and ea.critical_findings:
            findings = ea.critical_findings or []
            # Use rich per-finding reason if available, else fall back to label
            parts = []
            seen = set()
            for f in findings:
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
            "health_score":            float(ea.health_score) if ea and ea.health_score is not None else None,
            "risk_level":              ea.risk_level if ea else "Unknown",
            "condition_summary":       reason,
            "critical_findings":       ea.critical_findings or [] if ea else [],
            "parameters_at_risk":      ea.parameters_at_risk if ea else 0,
            "at_risk_parameter_names": at_risk_params_map.get(eq.id, []),
            "last_test_date":          ea.last_test_date.isoformat() if ea and ea.last_test_date else None,
            "test_count":              test_count_map.get(eq.id, 0),
            "tested":                  ea is not None,
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
    # Latest row per template_key — one subquery rank or just fetch all and dedupe in Python
    rows = (
        db.query(TestAnalytics)
        .filter(TestAnalytics.equipment_id == equipment_id)
        .order_by(TestAnalytics.template_key, TestAnalytics.calculated_at.desc())
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
    rows = q.order_by(ParameterAnalytics.calculated_at.desc()).all()

    # Hide "Previous Test" parameters from the parameter list.
    # Historical values of the actual parameter are still preserved
    # and available through the history endpoint.
    rows = [
        r for r in rows
        if "previous test" not in (r.parameter_label or "").lower()
        and "previous_test" not in (r.parameter_key or "").lower()
    ]
    result_ids = [r.test_result_id for r in rows]
    tested_at_map = {
        r.id: (r.tested_at or r.cts)
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }
    return [_serialize_parameter_analytics(r, tested_at_map.get(r.test_result_id)) for r in rows]


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
    q = (
        db.query(ParameterAnalytics)
        .join(TestResult, TestResult.id == ParameterAnalytics.test_result_id)
        .filter(
            ParameterAnalytics.equipment_id  == equipment_id,
            ParameterAnalytics.parameter_key == parameter_key,
        )
        .order_by(func.coalesce(TestResult.tested_at, TestResult.cts,
                                 ParameterAnalytics.calculated_at).asc())
    )
    if template_key:
        q = q.filter(ParameterAnalytics.template_key == template_key)
    rows = q.limit(limit).all()

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


def _serialize_parameter_analytics(row: ParameterAnalytics, tested_at=None) -> dict:
    return {
        "last_tested_at": tested_at.isoformat() if tested_at else None,
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
        "breach_threshold":     float(row.breach_threshold)  if row.breach_threshold  is not None else None,
        "breach_predicted_at":  row.breach_predicted_at.isoformat() if row.breach_predicted_at else None,
        "days_to_breach":       row.days_to_breach,
        "is_anomaly":           row.is_anomaly,
        "anomaly_type":         row.anomaly_type,
        "anomaly_detail":       row.anomaly_detail,
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
