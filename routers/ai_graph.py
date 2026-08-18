"""
AI Graph Dashboard API
======================

Feeds the 4-card AI Graph Dashboard in the Flutter portal.
All endpoints accept ?department_id= for scope filtering.

  GET /analytics/ai-graph/overview       ← KPIs + health distribution + trend
  GET /analytics/ai-graph/life-left      ← per-asset remaining life
  GET /analytics/ai-graph/ageing         ← ageing radar + DP trend
  GET /analytics/ai-graph/dielectric     ← dielectric radar + parameter trends
  GET /analytics/ai-graph/grouped        ← health grouped by VIEW BY dimension

Data sources (no new columns required):
  - EquipmentAnalytics.health_score / risk_level / test_type_scores
  - TestAnalytics.health_score / tested_at / template_key        (trend)
  - ParameterAnalytics.current_value / annual_change / pct_change_annual / condition
  - Equipment.commissioned_date / manufacturer / model_number     (life left + grouping)
"""

from __future__ import annotations

import uuid
import logging
from datetime import date, datetime, timedelta, timezone
from statistics import mean, stdev
from typing import Optional

from fastapi import APIRouter, Depends, Query
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_vendor_db
from auth_utils import get_current_user
from models import (
    CategoryMaster,
    Equipment,
    EquipmentAnalytics,
    OrgDepartment,
    ParameterAnalytics,
    TestAnalytics,
    TestingRequest,
    TestResult,
)

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics/ai-graph", tags=["AI Graph Dashboard"])

# ── Default expected life by equipment type keyword ───────────────────────────
_DEFAULT_LIFE = 30  # years — used when commissioned_date is known
_TYPE_LIFE: dict[str, int] = {
    "power transformer":   30,
    "current transformer": 25,
    "potential transformer": 25,
    "circuit breaker":     25,
    "capacitor":           20,
    "isolator":            30,
}


def _expected_life(type_name: str | None) -> int:
    if not type_name:
        return _DEFAULT_LIFE
    n = type_name.lower()
    for key, yrs in _TYPE_LIFE.items():
        if key in n:
            return yrs
    return _DEFAULT_LIFE


def _age_years(commissioned: datetime | None) -> float | None:
    if not commissioned:
        return None
    now = datetime.now(timezone.utc)
    if commissioned.tzinfo is None:
        commissioned = commissioned.replace(tzinfo=timezone.utc)
    return (now - commissioned).days / 365.25


def _life_left(commissioned: datetime | None, type_name: str | None) -> float | None:
    age = _age_years(commissioned)
    if age is None:
        return None
    return max(0.0, _expected_life(type_name) - age)


# ── Department scope helper ───────────────────────────────────────────────────

def _dept_ids(department_id: uuid.UUID | None, db: Session) -> set | None:
    if not department_id:
        return None
    visited: set = set()
    queue = [department_id]
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for (child_id,) in db.query(OrgDepartment.id).filter(
            OrgDepartment.parent_department_id == cur
        ).all():
            queue.append(child_id)
    return visited


def _scoped_ea(department_id: uuid.UUID | None, db: Session, organization_id=None) -> list[EquipmentAnalytics]:
    ids = _dept_ids(department_id, db)
    q = db.query(EquipmentAnalytics)
    if organization_id:
        q = q.filter(EquipmentAnalytics.organization_id == organization_id)
    if ids:
        q = q.filter(EquipmentAnalytics.department_id.in_(ids))
    return q.all()


def _ta_with_dates(eq_ids: list, db: Session) -> list[tuple]:
    """Fetch (TestAnalytics, effective_test_date) pairs for the given
    equipment. TestAnalytics.tested_at is NOT reliable for date filtering —
    it reflects whenever the analytics recompute job last ran (observed
    clustered within minutes of each other across all rows), not the actual
    test date. The real date lives on the linked TestResult, so resolve it
    from there (tested_at, falling back to cts for legacy rows)."""
    if not eq_ids:
        return []
    rows = db.query(TestAnalytics, TestResult.tested_at, TestResult.cts).join(
        TestResult, TestResult.id == TestAnalytics.test_result_id
    ).filter(TestAnalytics.equipment_id.in_(eq_ids)).all()
    result = []
    for ta, tr_tested_at, tr_cts in rows:
        eff_date = tr_tested_at or tr_cts
        if eff_date:
            result.append((ta, eff_date))
    return result


def _apply_test_date_scope(
    eq_ids: list,
    ea_list: list[EquipmentAnalytics],
    ea_map: dict | None,
    db: Session,
    date_from: date | None,
    date_to: date | None,
):
    """Narrow eq_ids/ea_list/ea_map down to equipment that have at least one
    test whose real date (via TestResult, see _ta_with_dates) falls within
    [date_from, date_to] (either bound optional). No-op when neither bound
    is given."""
    if not date_from and not date_to:
        return eq_ids, ea_list, ea_map
    if not eq_ids:
        return eq_ids, ea_list, ea_map

    allowed = {
        ta.equipment_id
        for ta, eff_date in _ta_with_dates(eq_ids, db)
        if _dt_in_range(eff_date, date_from, date_to)
    }

    eq_ids  = [i for i in eq_ids if i in allowed]
    ea_list = [ea for ea in ea_list if ea.equipment_id in allowed]
    if ea_map is not None:
        ea_map = {k: v for k, v in ea_map.items() if k in allowed}
    return eq_ids, ea_list, ea_map


def _dt_in_range(dt: datetime | None, date_from: date | None, date_to: date | None) -> bool:
    """True if `dt` falls within [date_from, date_to] (both bounds optional,
    date_to inclusive of its whole day). Used to trim trend arrays down to
    the selected date range — separate from `_apply_test_date_scope`, which
    only decides which *equipment* to include, not which *data points*."""
    if dt is None:
        return False
    if not date_from and not date_to:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if date_from:
        lo = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        if dt < lo:
            return False
    if date_to:
        hi_date = date_to + timedelta(days=1)
        hi = datetime(hi_date.year, hi_date.month, hi_date.day, tzinfo=timezone.utc)
        if dt >= hi:
            return False
    return True


def _trend_bucket(dt: datetime, span_days: int | None) -> tuple:
    """Choose a trend-chart bucket for `dt`, adapting granularity to the
    selected date range's span so a short range doesn't collapse into a
    single quarterly point. Returns (sort_key, label); sort_key is a plain
    `date` so callers can sort chronologically without re-parsing the label.
    Falls back to quarterly (the original behaviour) when there's no active
    range (span_days is None) or it's wide (>180 days)."""
    d = dt.date() if isinstance(dt, datetime) else dt
    if span_days is not None and span_days <= 31:
        return (d, d.strftime("%b %d"))
    if span_days is not None and span_days <= 180:
        iso_year, iso_week, _ = d.isocalendar()
        monday = d - timedelta(days=d.weekday())
        return (monday, f"W{iso_week} {iso_year}")
    q = (d.month - 1) // 3 + 1
    return (date(d.year, 3 * (q - 1) + 1, 1), f"Q{q} {d.year}")


def _life_bucket(years: float) -> str:
    if years < 5:   return "0–5 yrs"
    if years < 10:  return "5–10 yrs"
    if years < 15:  return "10–15 yrs"
    if years < 20:  return "15–20 yrs"
    if years < 25:  return "20–25 yrs"
    return "25+ yrs"


def _condition_from_score(score: float | None) -> str:
    if score is None:     return "Unknown"
    if score >= 88:       return "Excellent"
    if score >= 75:       return "Good"
    if score >= 65:       return "Fair"
    if score >= 50:       return "Poor"
    return "Critical"


def _condition_from_score_and_risk(score: float | None, risk_level: str | None) -> str:
    """Same score bands as _condition_from_score, but honors a stored
    risk_level of "Critical" the way _risk_from_score's critical-findings
    override does - otherwise an equipment/test with a critical finding but
    a score >=50 lands in "Poor" here while kpis.critical_count (which reads
    risk_level directly) still counts it as critical, so the two disagree."""
    if risk_level == "Critical":
        return "Critical"
    return _condition_from_score(score)


def _normalize_0_100(values: list[float]) -> float:
    """Map a list of raw deltas/rates to a 0-100 risk score."""
    if not values:
        return 0.0
    avg = mean([abs(v) for v in values])
    return min(100.0, round(avg, 1))


def _param_risk_score(condition: str | None) -> float:
    """Convert Good/Fair/Poor to a 0-100 risk number (higher = more risk)."""
    return {"Good": 10.0, "Fair": 50.0, "Poor": 85.0, "Unknown": 50.0}.get(condition or "Unknown", 50.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Overview — KPIs + health distribution + health trend
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/overview", summary="Fleet KPIs + health condition distribution + quarterly trend")
def get_overview(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns:
      kpis:
        fleet_health        — avg health score 0-100
        avg_life_left       — avg remaining years
        ageing_risk_index   — 0-100 (higher = more risk) derived from trend rates
        dielectric_index    — avg health score of dielectric-category tests

      health_distribution: [{bucket, critical, poor, fair, good, excellent, total}]
      health_trend:        [{period, avg_score, critical_count, fair_count, good_count}]
    """
    ids = _dept_ids(department_id, db)

    # ── Equipment analytics in scope ─────────────────────────────────────────
    ea_list: list[EquipmentAnalytics] = _scoped_ea(department_id, db, organization_id=user.organization_id)
    ea_map = {ea.equipment_id: ea for ea in ea_list}
    eq_ids = list(ea_map.keys())
    eq_ids, ea_list, ea_map = _apply_test_date_scope(
        eq_ids, ea_list, ea_map, db, date_from, date_to)

    # When a date range is active, use each equipment's most recent
    # TestAnalytics row *within that range* for health/risk, instead of
    # EquipmentAnalytics' current/all-time snapshot — otherwise the KPI cards
    # and health distribution chart below would keep showing today's health
    # even when looking at a past date range.
    _date_active = bool(date_from or date_to)
    _ta_dated = _ta_with_dates(eq_ids, db) if eq_ids else []
    latest_ta_map: dict = {}
    if _date_active:
        best: dict = {}
        for ta, eff_date in _ta_dated:
            if not _dt_in_range(eff_date, date_from, date_to):
                continue
            cur = best.get(ta.equipment_id)
            if cur is None or eff_date > cur[1]:
                best[ta.equipment_id] = (ta, eff_date)
        latest_ta_map = {eq_id: pair[0] for eq_id, pair in best.items()}

    def _eff_health(eq_id, ea) -> float | None:
        if _date_active:
            ta = latest_ta_map.get(eq_id)
            return float(ta.health_score) if ta and ta.health_score is not None else None
        return float(ea.health_score) if ea and ea.health_score is not None else None

    def _eff_risk(eq_id, ea) -> str | None:
        if _date_active:
            ta = latest_ta_map.get(eq_id)
            return ta.risk_level if ta else None
        return ea.risk_level if ea else None

    # ── Equipment register (for type name + commissioned_date) ───────────────
    eq_q = db.query(Equipment).filter(Equipment.id.in_(eq_ids)) if eq_ids else []
    eq_list: list[Equipment] = list(eq_q) if eq_ids else []

    type_ids = list({e.equipment_type_id for e in eq_list if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    } if type_ids else {}

    # ── KPI 1: Fleet Health ──────────────────────────────────────────────────
    scores: list[float] = []
    for ea in ea_list:
        s = _eff_health(ea.equipment_id, ea)
        if s is not None:
            scores.append(s)
    fleet_health = round(mean(scores), 1) if scores else None

    # ── KPI 2: Avg Life Left ─────────────────────────────────────────────────
    life_vals: list[float] = []
    for eq in eq_list:
        ll = _life_left(eq.commissioned_date, type_map.get(eq.equipment_type_id))
        if ll is not None:
            life_vals.append(ll)
    avg_life_left = round(mean(life_vals), 1) if life_vals else None

    # ── KPI 3: Ageing Risk Index ─────────────────────────────────────────────
    # Derived from ParameterAnalytics: mean absolute pct_change_annual across
    # fleet, trimmed to the selected date range (not just equipment inclusion).
    pa_age_rows = db.query(
        ParameterAnalytics.pct_change_annual, ParameterAnalytics.test_result_id,
    ).filter(
        ParameterAnalytics.equipment_id.in_(eq_ids),
        ParameterAnalytics.pct_change_annual.isnot(None),
    ).all()
    if date_from or date_to:
        _age_result_ids = list({r[1] for r in pa_age_rows})
        _age_tr_date_map = {
            r.id: (r.tested_at or r.cts)
            for r in db.query(TestResult).filter(TestResult.id.in_(_age_result_ids)).all()
        } if _age_result_ids else {}
        pct_changes = [float(r[0]) for r in pa_age_rows
                       if _dt_in_range(_age_tr_date_map.get(r[1]), date_from, date_to)]
    else:
        pct_changes = [float(r[0]) for r in pa_age_rows]
    if pct_changes:
        avg_abs_pct = mean([abs(v) for v in pct_changes])
        ageing_risk_index = round(min(100.0, avg_abs_pct * 2), 1)
    else:
        ageing_risk_index = None

    # ── KPI 4: Dielectric Index ──────────────────────────────────────────────
    # Avg health score from test_type_scores where template_key is dielectric-related
    _DIEL_KEYS = {"oil_bdv", "dissolved_gas", "tan_delta", "insulation_resistance",
                  "oil_quality", "dga", "oil_test", "dielectric"}
    diel_scores: list[float] = []
    for ea in ea_list:
        for tkey, tval in (ea.test_type_scores or {}).items():
            if any(k in tkey.lower() for k in _DIEL_KEYS):
                s = tval.get("score")
                if s is not None:
                    diel_scores.append(float(s))
    dielectric_index = round(mean(diel_scores), 1) if diel_scores else None

    # ── Health distribution: condition × life-left bucket ────────────────────
    BUCKETS = ["0–5 yrs", "5–10 yrs", "10–15 yrs", "15–20 yrs", "20–25 yrs", "25+ yrs"]
    CONDITIONS = ["critical", "poor", "fair", "good", "excellent"]
    dist: dict[str, dict] = {b: {c: 0 for c in CONDITIONS} | {"total": 0} for b in BUCKETS}

    eq_by_id = {e.id: e for e in eq_list}
    for ea in ea_list:
        eq = eq_by_id.get(ea.equipment_id)
        ll = _life_left(eq.commissioned_date if eq else None,
                        type_map.get(eq.equipment_type_id) if eq else None)
        bucket = _life_bucket(ll) if ll is not None else "25+ yrs"
        cond = _condition_from_score_and_risk(
            _eff_health(ea.equipment_id, ea), _eff_risk(ea.equipment_id, ea)
        )
        key = cond.lower()
        if key in CONDITIONS:
            dist[bucket][key] += 1
            dist[bucket]["total"] += 1

    health_distribution = [{"bucket": b, **dist[b]} for b in BUCKETS]

    # ── Health trend: adaptive-granularity avg score from TestAnalytics,
    # using each test's real date resolved via TestResult (see _ta_with_dates
    # — TestAnalytics.tested_at itself is not a reliable test date).
    ta_rows = [
        (ta, eff_date) for ta, eff_date in _ta_dated
        if ta.health_score is not None and _dt_in_range(eff_date, date_from, date_to)
    ]
    ta_rows.sort(key=lambda pair: pair[1])

    # Group adaptively (day/week/quarter — see _trend_bucket) so a short
    # selected range still yields multiple points instead of collapsing into
    # a single quarterly bucket.
    span_days = (date_to - date_from).days if (date_from and date_to) else None
    quarter_buckets: dict[str, list[float]] = {}
    quarter_conditions: dict[str, dict] = {}
    bucket_sort_key: dict[str, date] = {}
    for ta, dt in ta_rows:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        sort_key, q_key = _trend_bucket(dt, span_days)
        bucket_sort_key[q_key] = sort_key
        quarter_buckets.setdefault(q_key, []).append(float(ta.health_score))
        qc = quarter_conditions.setdefault(q_key, {"critical": 0, "fair": 0, "good": 0})
        cond = _condition_from_score_and_risk(float(ta.health_score), ta.risk_level)
        if cond in ("Critical", "Poor"):
            qc["critical"] += 1
        elif cond == "Fair":
            qc["fair"] += 1
        else:
            qc["good"] += 1

    health_trend = [
        {
            "period":          period,
            "avg_score":       round(mean(quarter_buckets[period]), 1),
            "critical_count":  quarter_conditions[period]["critical"],
            "fair_count":      quarter_conditions[period]["fair"],
            "good_count":      quarter_conditions[period]["good"],
        }
        for period in sorted(quarter_buckets.keys(), key=lambda p: bucket_sort_key[p])
    ]
    if span_days is None:
        health_trend = health_trend[-12:]  # no active range: cap at last 12 quarters

    return {
        "kpis": {
            "fleet_health":       fleet_health,
            "avg_life_left":      avg_life_left,
            "ageing_risk_index":  ageing_risk_index,
            "dielectric_index":   dielectric_index,
            "equipment_count":    len(eq_ids),
            "critical_count":     sum(1 for ea in ea_list if _eff_risk(ea.equipment_id, ea) == "Critical"),
            "high_count":         sum(1 for ea in ea_list if _eff_risk(ea.equipment_id, ea) == "High"),
        },
        "health_distribution": health_distribution,
        "health_trend":        health_trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Life Left — per-asset remaining service years
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/life-left", summary="Per-asset remaining life and life-trend")
def get_life_left(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns:
      assets: [{ueic, equipment_type, life_left_years, age_years,
                expected_life, condition, health_score, commissioned_year}]
      life_trend: [{period, avg_life_left}]  -- quarterly snapshot from TestAnalytics
    """
    ea_list = _scoped_ea(department_id, db, organization_id=user.organization_id)
    eq_ids = [ea.equipment_id for ea in ea_list]
    ea_map = {ea.equipment_id: ea for ea in ea_list}
    eq_ids, ea_list, ea_map = _apply_test_date_scope(
        eq_ids, ea_list, ea_map, db, date_from, date_to)

    eq_list: list[Equipment] = db.query(Equipment).filter(
        Equipment.id.in_(eq_ids)
    ).all() if eq_ids else []

    type_ids = list({e.equipment_type_id for e in eq_list if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    } if type_ids else {}

    assets = []
    for eq in eq_list:
        ea = ea_map.get(eq.id)
        type_name = type_map.get(eq.equipment_type_id)
        age = _age_years(eq.commissioned_date)
        exp_life = _expected_life(type_name)
        ll = _life_left(eq.commissioned_date, type_name)
        assets.append({
            "equipment_id":       str(eq.id),
            "ueic":               eq.ueic,
            "equipment_type":     type_name,
            "manufacturer":       eq.manufacturer or "—",
            "commissioned_year":  eq.commissioned_date.year if eq.commissioned_date else None,
            "age_years":          round(age, 1) if age is not None else None,
            "expected_life":      exp_life,
            "life_left_years":    round(ll, 1) if ll is not None else None,
            "health_score":       float(ea.health_score) if ea and ea.health_score is not None else None,
            "condition":          _condition_from_score(float(ea.health_score) if ea and ea.health_score is not None else None),
            "risk_level":         ea.risk_level if ea else "Unknown",
        })

    assets.sort(key=lambda x: (x["life_left_years"] or 999))

    # Life trend — from each test's real date (resolved via TestResult, see
    # _ta_with_dates) cross-joined with commissioned_date: for each period's
    # tests, calculate avg life_left at that time.
    ta_rows = [
        (ta.equipment_id, eff_date)
        for ta, eff_date in _ta_with_dates(eq_ids, db)
        if _dt_in_range(eff_date, date_from, date_to)
    ]

    span_days = (date_to - date_from).days if (date_from and date_to) else None
    eq_commissioned = {e.id: (e.commissioned_date, type_map.get(e.equipment_type_id)) for e in eq_list}
    quarter_life: dict[str, list[float]] = {}
    bucket_sort_key: dict[str, date] = {}
    for eq_id, tested_at in ta_rows:
        comm, tname = eq_commissioned.get(eq_id, (None, None))
        if not comm or not tested_at:
            continue
        if tested_at.tzinfo is None:
            tested_at = tested_at.replace(tzinfo=timezone.utc)
        if comm.tzinfo is None:
            comm = comm.replace(tzinfo=timezone.utc)
        age_at = (tested_at - comm).days / 365.25
        ll_at = max(0.0, _expected_life(tname) - age_at)
        sort_key, q_key = _trend_bucket(tested_at, span_days)
        bucket_sort_key[q_key] = sort_key
        quarter_life.setdefault(q_key, []).append(ll_at)

    life_trend = [
        {
            "period":        period,
            "avg_life_left": round(mean(vals), 1),
        }
        for period, vals in sorted(
            quarter_life.items(),
            key=lambda x: bucket_sort_key[x[0]],
        )
    ]
    if span_days is None:
        life_trend = life_trend[-12:]  # no active range: cap at last 12 quarters

    return {
        "assets":     assets,
        "life_trend": life_trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Ageing — radar axes + DP trend
# ─────────────────────────────────────────────────────────────────────────────

_AGEING_AXES = {
    "aging_rate":      ["pct_change", "annual_change", "rate"],
    "thermal_stress":  ["oti", "wti", "oil_temp", "winding_temp", "temperature"],
    "load_factor":     ["lc", "load_current", "current", "load"],
}

_DP_KEYS = ["dp", "degree_of_polymerization", "polymerisation", "cellulose"]


@router.get("/ageing", summary="Ageing risk radar axes + DP degree of polymerisation trend")
def get_ageing(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns:
      radar:
        fleet: {aging_rate, volatility, life_left_risk, thermal_stress, load_factor}  (0-100)
        benchmark: same shape with reference values
      asset_scores: [{ueic, ageing_index}]  -- per-asset ageing risk 0-100
      dp_trend: [{ueic, tested_at, value, unit, condition}]  -- DP history across fleet
    """
    ea_list = _scoped_ea(department_id, db, organization_id=user.organization_id)
    eq_ids = [ea.equipment_id for ea in ea_list]
    ea_map = {ea.equipment_id: ea for ea in ea_list}
    eq_ids, ea_list, ea_map = _apply_test_date_scope(
        eq_ids, ea_list, ea_map, db, date_from, date_to)

    eq_list = db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all() if eq_ids else []
    type_ids = list({e.equipment_type_id for e in eq_list if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    } if type_ids else {}

    pa_rows: list[ParameterAnalytics] = db.query(ParameterAnalytics).filter(
        ParameterAnalytics.equipment_id.in_(eq_ids),
    ).all() if eq_ids else []

    # Resolve each parameter's test date up front and trim pa_rows to the
    # selected range — otherwise the radar/asset-score/DP-trend numbers below
    # would silently ignore the date filter even though eq_ids was scoped by it.
    _all_result_ids = list({r.test_result_id for r in pa_rows})
    tr_date_map = {
        r.id: (r.tested_at or r.cts)
        for r in db.query(TestResult).filter(TestResult.id.in_(_all_result_ids)).all()
    } if _all_result_ids else {}
    _date_active = bool(date_from or date_to)
    if _date_active:
        pa_rows = [r for r in pa_rows if _dt_in_range(tr_date_map.get(r.test_result_id), date_from, date_to)]

    # ── Radar axes ────────────────────────────────────────────────────────────
    def _match(label: str, keys: list[str]) -> bool:
        l = (label or "").lower()
        return any(k in l for k in keys)

    # Aging rate: avg abs pct_change_annual across all params
    all_pct = [abs(float(r.pct_change_annual)) for r in pa_rows
               if r.pct_change_annual is not None]
    aging_rate = round(min(100.0, mean(all_pct) * 2), 1) if all_pct else 0.0

    # Volatility: std dev of pct_change_annual, normalized
    volatility = 0.0
    if len(all_pct) >= 2:
        volatility = round(min(100.0, stdev(all_pct) * 3), 1)

    # Life left risk: 100 = no life left, 0 = full life remaining
    life_vals = []
    for eq in eq_list:
        ll = _life_left(eq.commissioned_date, type_map.get(eq.equipment_type_id))
        exp = _expected_life(type_map.get(eq.equipment_type_id))
        if ll is not None:
            life_vals.append(max(0.0, 100.0 * (1 - ll / exp)))
    life_left_risk = round(mean(life_vals), 1) if life_vals else 0.0

    # Thermal stress: avg condition risk score for thermal params
    thermal_pa = [r for r in pa_rows if _match(r.parameter_label or r.parameter_key, _AGEING_AXES["thermal_stress"])]
    thermal_stress = round(mean([_param_risk_score(r.condition) for r in thermal_pa]), 1) if thermal_pa else 20.0

    # Load factor: avg condition risk score for load params
    load_pa = [r for r in pa_rows if _match(r.parameter_label or r.parameter_key, _AGEING_AXES["load_factor"])]
    load_factor = round(mean([_param_risk_score(r.condition) for r in load_pa]), 1) if load_pa else 20.0

    fleet_radar = {
        "aging_rate":     aging_rate,
        "volatility":     volatility,
        "life_left_risk": life_left_risk,
        "thermal_stress": thermal_stress,
        "load_factor":    load_factor,
    }
    benchmark_radar = {
        "aging_rate": 30.0, "volatility": 25.0, "life_left_risk": 35.0,
        "thermal_stress": 25.0, "load_factor": 30.0,
    }

    # ── Per-asset ageing index ────────────────────────────────────────────────
    eq_label_map = {e.id: e.ueic for e in eq_list}
    asset_pct: dict = {}
    for r in pa_rows:
        if r.pct_change_annual is not None:
            asset_pct.setdefault(r.equipment_id, []).append(abs(float(r.pct_change_annual)))

    asset_scores = []
    for eq_id, pcts in asset_pct.items():
        score = round(min(100.0, mean(pcts) * 2), 1)
        asset_scores.append({
            "equipment_id": str(eq_id),
            "ueic":         eq_label_map.get(eq_id, str(eq_id)),
            "ageing_index": score,
        })
    asset_scores.sort(key=lambda x: -x["ageing_index"])

    # ── DP trend — degree of polymerisation history (pa_rows already
    # trimmed to the selected range above) ─────────────────────────────────────
    dp_pa = [r for r in pa_rows if _match(r.parameter_label or r.parameter_key, _DP_KEYS)]

    dp_trend = sorted(
        [
            {
                "equipment_id": str(r.equipment_id),
                "ueic":         eq_label_map.get(r.equipment_id, str(r.equipment_id)),
                "tested_at":    tr_date_map[r.test_result_id].isoformat()
                                if tr_date_map.get(r.test_result_id) else None,
                "value":        float(r.current_value) if r.current_value is not None else None,
                "unit":         r.unit,
                "condition":    r.condition,
                "days_to_breach": r.days_to_breach,
                "breach_predicted_at": r.breach_predicted_at.isoformat()
                                       if r.breach_predicted_at else None,
            }
            for r in dp_pa
            if tr_date_map.get(r.test_result_id)
        ],
        key=lambda x: x["tested_at"] or "",
    )

    return {
        "radar": {
            "fleet":     fleet_radar,
            "benchmark": benchmark_radar,
        },
        "asset_scores": asset_scores,
        "dp_trend":     dp_trend,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Dielectric — radar axes + parameter trends (DGA, Tan Delta, BDV)
# ─────────────────────────────────────────────────────────────────────────────

_DIEL_AXIS_KEYS = {
    "c2h2":      ["c2h2", "acetylene"],
    "h2":        ["h2", "hydrogen"],
    "acidity":   ["acidity", "acid", "neutralisation"],
    "wco":       ["wco", "bdv", "breakdown_voltage", "oil_breakdown"],
    "dp_risk":   ["dp", "polymerization", "polymerisation", "cellulose"],
    "tan_delta": ["tan_delta", "td", "tan delta", "dissipation_factor"],
}

_TREND_GROUPS = {
    "tan_delta": ["tan_delta", "td", "tan delta"],
    "dga":       ["c2h2", "h2", "ch4", "co", "c2h4", "acetylene", "hydrogen", "methane"],
    "bdv":       ["bdv", "wco", "oil_breakdown", "breakdown_voltage"],
}


@router.get("/dielectric", summary="Dielectric risk radar + DGA / Tan Delta / BDV parameter trends")
def get_dielectric(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns:
      radar:
        fleet: {c2h2, h2, acidity, wco, dp_risk, tan_delta}  (0-100 risk)
        limit: same shape at 100 (full scale reference)
      trends:
        tan_delta: [{equipment_id, ueic, tested_at, value, unit, condition}]
        dga:       [{equipment_id, ueic, parameter_label, tested_at, value, unit, condition}]
        bdv:       [{equipment_id, ueic, tested_at, value, unit, condition}]
    """
    ea_list = _scoped_ea(department_id, db, organization_id=user.organization_id)
    eq_ids = [ea.equipment_id for ea in ea_list]
    eq_ids, ea_list, _ = _apply_test_date_scope(
        eq_ids, ea_list, None, db, date_from, date_to)

    eq_list = db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all() if eq_ids else []
    eq_label_map = {e.id: e.ueic for e in eq_list}

    pa_rows: list[ParameterAnalytics] = db.query(ParameterAnalytics).filter(
        ParameterAnalytics.equipment_id.in_(eq_ids),
    ).all() if eq_ids else []

    # Resolve each parameter's test date up front and trim pa_rows to the
    # selected range — otherwise the radar axes below would silently ignore
    # the date filter even though eq_ids was scoped by it (equipment
    # inclusion only, not per-row trimming).
    all_result_ids = list({r.test_result_id for r in pa_rows})
    tr_date_map = {
        r.id: (r.tested_at or r.cts)
        for r in db.query(TestResult).filter(TestResult.id.in_(all_result_ids)).all()
    } if all_result_ids else {}
    if date_from or date_to:
        pa_rows = [r for r in pa_rows if _dt_in_range(tr_date_map.get(r.test_result_id), date_from, date_to)]

    def _match(label: str, keys: list[str]) -> bool:
        l = (label or "").lower()
        return any(k in l for k in keys)

    # ── Radar: one risk score per axis ────────────────────────────────────────
    radar_fleet: dict[str, float] = {}
    for axis, keys in _DIEL_AXIS_KEYS.items():
        matched = [r for r in pa_rows
                   if _match(r.parameter_label or r.parameter_key, keys)]
        if matched:
            radar_fleet[axis] = round(mean([_param_risk_score(r.condition) for r in matched]), 1)
        else:
            radar_fleet[axis] = 0.0

    radar_limit = {k: 100.0 for k in _DIEL_AXIS_KEYS}

    # ── Trend data (pa_rows already trimmed to the selected range above) ──────
    def _build_trend(group_keys: list[str]) -> list[dict]:
        matched = [r for r in pa_rows
                   if _match(r.parameter_label or r.parameter_key, group_keys)
                   and tr_date_map.get(r.test_result_id)]
        return sorted(
            [
                {
                    "equipment_id":   str(r.equipment_id),
                    "ueic":           eq_label_map.get(r.equipment_id, str(r.equipment_id)),
                    "parameter_label":r.parameter_label or r.parameter_key,
                    "tested_at":      tr_date_map[r.test_result_id].isoformat(),
                    "value":          float(r.current_value) if r.current_value is not None else None,
                    "unit":           r.unit,
                    "condition":      r.condition,
                    "trend":          r.trend,
                    "annual_change":  float(r.annual_change) if r.annual_change is not None else None,
                    "is_anomaly":     r.is_anomaly,
                }
                for r in matched
            ],
            key=lambda x: x["tested_at"],
        )

    return {
        "radar": {
            "fleet": radar_fleet,
            "limit": radar_limit,
        },
        "trends": {
            "tan_delta": _build_trend(_TREND_GROUPS["tan_delta"]),
            "dga":       _build_trend(_TREND_GROUPS["dga"]),
            "bdv":       _build_trend(_TREND_GROUPS["bdv"]),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Grouped — health distribution by VIEW BY dimension
# ─────────────────────────────────────────────────────────────────────────────

_VALID_GROUP_BY = {
    "equipment_type", "make", "capacity", "make_model",
    "year_commissioned", "year_failure", "year_replaced",
}


def _capacity_bucket(mva_val) -> str:
    """Return a display-friendly MVA capacity label."""
    if mva_val is None:
        return "Unknown"
    try:
        v = float(mva_val)
    except (TypeError, ValueError):
        return str(mva_val)
    if v < 10:    return "< 10 MVA"
    if v < 50:    return "10–50 MVA"
    if v < 100:   return "50–100 MVA"
    if v < 200:   return "100–200 MVA"
    return "200+ MVA"


@router.get("/grouped", summary="Health distribution grouped by a VIEW BY dimension")
def get_grouped(
    department_id: Optional[uuid.UUID] = Query(None),
    group_by: str = Query("equipment_type", description=(
        "Dimension to group by: equipment_type | make | capacity | "
        "make_model | year_commissioned | year_failure | year_replaced"
    )),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns:
      group_by:  the active dimension
      groups:    [{label, count, avg_health, critical, poor, fair, good, excellent, avg_life_left}]
                 sorted by count desc
    """
    if group_by not in _VALID_GROUP_BY:
        group_by = "equipment_type"

    ea_list = _scoped_ea(department_id, db, organization_id=user.organization_id)
    eq_ids  = [ea.equipment_id for ea in ea_list]
    ea_map  = {ea.equipment_id: ea for ea in ea_list}
    eq_ids, ea_list, ea_map = _apply_test_date_scope(
        eq_ids, ea_list, ea_map, db, date_from, date_to)

    eq_list: list[Equipment] = db.query(Equipment).filter(
        Equipment.id.in_(eq_ids)
    ).all() if eq_ids else []

    # When a date range is active, use each equipment's most recent
    # TestAnalytics row *within that range* for health, instead of
    # EquipmentAnalytics' current/all-time snapshot — same reasoning as
    # get_overview's _eff_health.
    _date_active = bool(date_from or date_to)
    _ta_dated = _ta_with_dates(eq_ids, db) if eq_ids else []
    latest_ta_map: dict = {}
    if _date_active:
        best: dict = {}
        for ta, eff_date in _ta_dated:
            if not _dt_in_range(eff_date, date_from, date_to):
                continue
            cur = best.get(ta.equipment_id)
            if cur is None or eff_date > cur[1]:
                best[ta.equipment_id] = (ta, eff_date)
        latest_ta_map = {eq_id: pair[0] for eq_id, pair in best.items()}

    def _eff_health(eq_id, ea) -> float | None:
        if _date_active:
            ta = latest_ta_map.get(eq_id)
            return float(ta.health_score) if ta and ta.health_score is not None else None
        return float(ea.health_score) if ea and ea.health_score is not None else None

    # Test count per equipment_id — trimmed to the selected date range, not
    # just gated on "has any test in range" (that's what _apply_test_date_scope
    # already did above for equipment inclusion). Reuses _ta_dated's
    # TestResult-resolved dates rather than TestAnalytics.tested_at.
    from collections import Counter
    test_count_map: dict = Counter(
        str(ta.equipment_id) for ta, eff_date in _ta_dated
        if not _date_active or _dt_in_range(eff_date, date_from, date_to)
    )

    type_ids = list({e.equipment_type_id for e in eq_list if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    } if type_ids else {}

    eq_capacity_map = _eq_capacity_map(eq_ids, db) if group_by == "capacity" else {}

    def _group_label(eq: Equipment) -> str:
        if group_by == "equipment_type":
            return type_map.get(eq.equipment_type_id) or "Unknown"
        if group_by == "make":
            return eq.manufacturer or "Unknown"
        if group_by == "make_model":
            make  = eq.manufacturer or "Unknown"
            model = eq.model_number or ""
            return f"{make} {model}".strip() if model else make
        if group_by == "capacity":
            return _capacity_bucket(eq_capacity_map.get(eq.id))
        if group_by == "year_commissioned":
            if eq.commissioned_date:
                return str(eq.commissioned_date.year)
            if eq.year_of_manufacture:
                return str(eq.year_of_manufacture)
            return "Unknown"
        if group_by == "year_failure":
            # Use retired_date year as "year of failure / end of service"
            if eq.retired_date:
                return str(eq.retired_date.year)
            return "In Service"
        if group_by == "year_replaced":
            # Equipment has a replacement: use commissioned_date of the replacing unit
            if eq.replaced_by_id:
                rep = db.query(Equipment.commissioned_date).filter(
                    Equipment.id == eq.replaced_by_id
                ).first()
                if rep and rep[0]:
                    return str(rep[0].year)
                return "Replaced"
            return "Not Replaced"
        return "Unknown"

    # ── Accumulate per-group stats ────────────────────────────────────────────
    from collections import defaultdict
    group_scores:    dict[str, list[float]] = defaultdict(list)
    group_conditions:dict[str, dict]        = defaultdict(lambda: {
        "critical": 0, "poor": 0, "fair": 0, "good": 0, "excellent": 0
    })
    group_life:  dict[str, list[float]] = defaultdict(list)
    group_age:   dict[str, list[float]] = defaultdict(list)
    group_tests: dict[str, int]         = defaultdict(int)
    group_age_risk: dict[str, dict] = defaultdict(lambda: {
        "overdue": 0, "near_end": 0, "mid_life": 0, "early": 0
    })

    for eq in eq_list:
        ea        = ea_map.get(eq.id)
        label     = _group_label(eq)
        type_name = type_map.get(eq.equipment_type_id)
        score = _eff_health(eq.id, ea)
        if score is not None:
            group_scores[label].append(score)
            cond = _condition_from_score(score).lower()
            if cond in group_conditions[label]:
                group_conditions[label][cond] += 1

        ll  = _life_left(eq.commissioned_date, type_name)
        age = _age_years(eq.commissioned_date)
        exp = _expected_life(type_name)
        if ll is not None:
            group_life[label].append(ll)
        group_tests[label] += test_count_map.get(str(eq.id), 0)
        if age is not None:
            group_age[label].append(age)
            pct = age / exp if exp else 0
            if pct >= 1.0:
                group_age_risk[label]["overdue"] += 1
            elif pct >= 0.8:
                group_age_risk[label]["near_end"] += 1
            elif pct >= 0.5:
                group_age_risk[label]["mid_life"] += 1
            else:
                group_age_risk[label]["early"] += 1

    # Merge all labels
    all_labels = set(group_scores) | set(group_life) | set(group_age)

    groups = []
    for label in all_labels:
        scores = group_scores.get(label, [])
        conds  = group_conditions.get(label, {})
        lives  = group_life.get(label, [])
        ages   = group_age.get(label, [])
        ar     = group_age_risk.get(label, {})
        groups.append({
            "label":         label,
            "count":         len(scores) or len(lives) or len(ages),
            "avg_health":    round(mean(scores), 1) if scores else None,
            "avg_life_left": round(mean(lives),  1) if lives  else None,
            "avg_age_years": round(mean(ages),   1) if ages   else None,
            "critical":      conds.get("critical", 0),
            "poor":          conds.get("poor",     0),
            "fair":          conds.get("fair",     0),
            "good":          conds.get("good",     0),
            "excellent":     conds.get("excellent",0),
            "test_count":    group_tests.get(label, 0),
            "overdue":       ar.get("overdue",  0),
            "near_end":      ar.get("near_end", 0),
            "mid_life":      ar.get("mid_life", 0),
            "early":         ar.get("early",    0),
        })

    groups.sort(key=lambda x: -x["count"])

    return {
        "group_by": group_by,
        "groups":   groups,
    }
