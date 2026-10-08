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
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from services.analytics_engine import accepted_test_result_ids

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
# Safety fallbacks only — the admin-configurable source of truth is
# EquipmentExpectedLife + AgeingConfig (Threshold Config page, seeded by
# alter_ageing_config.py); see _load_expected_life / _load_ageing_config.
# Used when no db session is available, or the tables are missing/unseeded.
_DEFAULT_LIFE = 30  # years — used when commissioned_date is known
_TYPE_LIFE: dict[str, int] = {
    "power transformer":   30,
    "current transformer": 25,
    "potential transformer": 25,
    "circuit breaker":     25,
    "capacitor":           20,
    "isolator":            30,
}
_DEFAULT_AGEING_CONFIG: dict = {
    "default_life": _DEFAULT_LIFE,
    # /grouped life-stage cutoffs on age / expected_life.
    "life_stage_cutoffs": {"mid": 0.5, "near_end": 0.8, "overdue": 1.0},
    # /ageing radar reference polygon.
    "benchmark": {
        "aging_rate": 30.0, "volatility": 25.0, "life_left_risk": 35.0,
        "thermal_stress": 25.0, "load_factor": 30.0,
    },
}


def _whole(v) -> int | float:
    """Numeric column -> int when whole (so e.g. /life-left's expected_life
    still serialises as 30, not 30.0, exactly as with the old constants)."""
    f = float(v)
    return int(f) if f.is_integer() else f


def _query_or_fallback(db: Session, fn, fallback, what: str):
    """Run fn() inside a SAVEPOINT so a missing table (alter_ageing_config.py
    not run yet -> UndefinedTable/ProgrammingError) only rolls back that one
    statement, leaving the request's session/transaction usable and the
    endpoint working on the hardcoded fallback."""
    try:
        with db.begin_nested():
            return fn()
    except ProgrammingError as exc:
        if what not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add(what)
            logger.warning("ai_graph: %s unavailable, using defaults (%s)",
                           what, str(exc).splitlines()[0])
        return fallback


_FALLBACK_LOGGED: set = set()


def _load_expected_life(db: Session | None) -> list[tuple[str, int | float]]:
    """Admin-configured (lowercased match_pattern, years) rules in match
    order (first substring match wins). Cached on the request session like
    _load_condition_bands - _expected_life runs once per equipment."""
    if db is None:
        return list(_TYPE_LIFE.items())
    cached = db.info.get("_ai_graph_expected_life")
    if cached is not None:
        return cached

    def _q():
        from models import EquipmentExpectedLife as EEL, AgeingConfig
        # Never set up (alter_ageing_config.py seeds both tables, so no
        # AgeingConfig row and no rules) -> hardcoded defaults. Set up, then
        # every rule deleted or disabled by an admin -> no rules: everything
        # gets the configured default life (not the old constants back).
        if (db.query(EEL.id).first() is None
                and db.query(AgeingConfig.id).first() is None):
            return list(_TYPE_LIFE.items())
        rows = (
            db.query(EEL)
            .filter(EEL.is_active.is_(True))
            .order_by(EEL.sort_order.asc(), EEL.id.asc())
            .all()
        )
        return [
            (r.match_pattern.strip().lower(), _whole(r.expected_life_years))
            for r in rows
            if r.match_pattern and r.match_pattern.strip()
        ]

    rules = _query_or_fallback(db, _q, list(_TYPE_LIFE.items()), "equipment_expected_life")
    db.info["_ai_graph_expected_life"] = rules
    return rules


def _load_ageing_config(db: Session | None) -> dict:
    """Admin-configured default life, life-stage cutoffs and radar
    benchmark (AgeingConfig's single row). Falls back to
    _DEFAULT_AGEING_CONFIG when there's no session, no row or no table."""
    if db is None:
        return _DEFAULT_AGEING_CONFIG
    cached = db.info.get("_ai_graph_ageing_config")
    if cached is not None:
        return cached

    def _q():
        from models import AgeingConfig
        r = db.query(AgeingConfig).order_by(AgeingConfig.id.asc()).first()
        if r is None:
            return _DEFAULT_AGEING_CONFIG
        return {
            "default_life": _whole(r.default_expected_life_years),
            "life_stage_cutoffs": {
                "mid":      float(r.life_stage_mid),
                "near_end": float(r.life_stage_near_end),
                "overdue":  float(r.life_stage_overdue),
            },
            "benchmark": {
                "aging_rate":     float(r.benchmark_aging_rate),
                "volatility":     float(r.benchmark_volatility),
                "life_left_risk": float(r.benchmark_life_left_risk),
                "thermal_stress": float(r.benchmark_thermal_stress),
                "load_factor":    float(r.benchmark_load_factor),
            },
        }

    cfg = _query_or_fallback(db, _q, _DEFAULT_AGEING_CONFIG, "ageing_config")
    db.info["_ai_graph_ageing_config"] = cfg
    return cfg


def _expected_life(type_name: str | None, db: Session | None = None) -> int | float:
    default_life = _load_ageing_config(db)["default_life"]
    if not type_name:
        return default_life
    n = type_name.lower()
    for key, yrs in _load_expected_life(db):
        if key in n:
            return yrs
    return default_life


def _age_years(commissioned: datetime | None) -> float | None:
    if not commissioned:
        return None
    now = datetime.now(timezone.utc)
    if commissioned.tzinfo is None:
        commissioned = commissioned.replace(tzinfo=timezone.utc)
    return (now - commissioned).days / 365.25


def _life_left(
    commissioned: datetime | None, type_name: str | None, db: Session | None = None,
) -> float | None:
    age = _age_years(commissioned)
    if age is None:
        return None
    return max(0.0, _expected_life(type_name, db) - age)


# ── Ageing index ──────────────────────────────────────────────────────────────

def _ageing_index(pct_changes) -> float | None:
    """0-100 ageing velocity: mean of |annual % change| with each parameter
    capped at 100%. The old min(100, mean(|pct|) x 2) was pinned at 100 -
    annual % changes are extremely heavy-tailed (a near-zero baseline gives
    thousands of %), so a handful of readings saturated the whole fleet."""
    vals = [min(100.0, abs(float(v))) for v in pct_changes if v is not None]
    return round(mean(vals), 1) if vals else None


# ── Parameter keyword matching ────────────────────────────────────────────────

_KW_CACHE: dict = {}


def _kw_match(label: str | None, keys) -> bool:
    """True if any key occurs in label as a whole word/phrase (underscores
    read as spaces, case-insensitive). Plain substring matching over-matched:
    "co" hit "Water COntent" / "COlour", "h2" hit "C2H2", "td" hit any word
    containing it - so readings landed in the wrong trend/radar axis, and in
    two groups at once."""
    text = (label or "").lower().replace("_", " ")
    for k in keys:
        pat = _KW_CACHE.get(k)
        if pat is None:
            pat = re.compile(r"(?<![a-z0-9])" + re.escape(k.lower().replace("_", " ")) + r"(?![a-z0-9])")
            _KW_CACHE[k] = pat
        if pat.search(text):
            return True
    return False


# ── Department scope helper ───────────────────────────────────────────────────

def _enforced_department(db: Session, user, department_id: uuid.UUID | None) -> set | None:
    """Department ids this request may read (None = the whole organization):
    404 for another organization's department, 403 outside a
    department-scoped user's departments - the exact rule (and active-only
    subtree) the AI Analytics dashboard uses, see
    routers.analytics._resolve_dashboard_scope."""
    from routers.analytics import _resolve_dashboard_scope
    _org, dept_ids = _resolve_dashboard_scope(db, user, department_id)
    return dept_ids


def _scoped_ea(
    dept_ids: set | None,
    db: Session,
    organization_id=None,
    equipment_id: uuid.UUID | None = None,
    retired_only: bool = False,
) -> list[EquipmentAnalytics]:
    """EquipmentAnalytics rows of the real assets in scope: same asset set as
    the AI Analytics dashboard - no Testing Kits, no retired equipment, and
    scoped by the equipment's CURRENT department (EquipmentAnalytics'
    denormalized department_id lags behind a move until the next recompute)."""
    testkit_ids = [
        c.id for c in db.query(CategoryMaster.id)
        .filter(CategoryMaster.name.ilike("%testing kit%")).all() if c.id
    ]
    q = (
        db.query(EquipmentAnalytics)
        .join(Equipment, Equipment.id == EquipmentAnalytics.equipment_id)
        .filter((Equipment.status == "retired") if retired_only
                else (Equipment.status != "retired"))
    )
    if testkit_ids:
        q = q.filter((Equipment.equipment_type_id == None)  # noqa: E711
                     | ~Equipment.equipment_type_id.in_(testkit_ids))
    if organization_id:
        q = q.filter(Equipment.organization_id == organization_id)
    if dept_ids is not None:
        q = q.filter(Equipment.department_id.in_(dept_ids))
    if equipment_id:
        q = q.filter(EquipmentAnalytics.equipment_id == equipment_id)
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
    cache = db.info.setdefault("_ai_graph_ta_dates", {})
    key = frozenset(eq_ids)
    if key in cache:
        return cache[key]
    rows = db.query(TestAnalytics, TestResult.tested_at, TestResult.cts).join(
        TestResult, TestResult.id == TestAnalytics.test_result_id
    ).filter(TestAnalytics.equipment_id.in_(eq_ids),
             TestAnalytics.test_result_id.in_(accepted_test_result_ids(db))).all()
    result = []
    for ta, tr_tested_at, tr_cts in rows:
        eff_date = tr_tested_at or tr_cts
        if eff_date:
            result.append((ta, eff_date))
    cache[key] = result
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


# Safety fallback only — used when no db session is available. The
# admin-configurable source of truth is EquipmentConditionBandThreshold;
# see _load_condition_bands.
_DEFAULT_CONDITION_BANDS = [
    (88, "Excellent"),
    (75, "Good"),
    (65, "Fair"),
    (50, "Poor"),
    (0,  "Critical"),
]


def _load_condition_bands(db: Session | None) -> list[tuple[float, str]]:
    """Admin-configured (threshold, label) pairs for the 5-tier condition
    scale, highest threshold first. Falls back to _DEFAULT_CONDITION_BANDS
    if no db session was given or the table has no active rows yet.
    """
    if db is None:
        return _DEFAULT_CONDITION_BANDS
    # Called once per score (thousands of times per request) - cache on the
    # request's session instead of re-querying the band table every call.
    cached = db.info.get("_ai_graph_condition_bands")
    if cached is not None:
        return cached
    bands = _query_condition_bands(db)
    db.info["_ai_graph_condition_bands"] = bands
    return bands


def _query_condition_bands(db: Session) -> list:
    from models import EquipmentConditionBandThreshold
    # Table-never-seeded vs admin-disabled-everything must not be conflated
    # (same reasoning as analytics_engine.py's _load_risk_bands) - otherwise
    # disabling every condition band silently resurrects the hardcoded
    # defaults instead of leaving the band list empty.
    if db.query(EquipmentConditionBandThreshold).first() is None:
        return _DEFAULT_CONDITION_BANDS
    rows = (
        db.query(EquipmentConditionBandThreshold)
        .filter(EquipmentConditionBandThreshold.is_active.is_(True))
        .order_by(EquipmentConditionBandThreshold.threshold.desc())
        .all()
    )
    return [(float(r.threshold), r.label) for r in rows]


def _condition_from_score(score: float | None, db: Session | None = None) -> str:
    if score is None:
        return "Unknown"
    bands = _load_condition_bands(db)
    for threshold, label in bands:
        if score >= threshold:
            return label
    # Score cleared none of the active bands - typically because the
    # lowest-threshold band (normally "Critical") was deactivated. The
    # lowest-threshold *active* band is the catch-all for everything below
    # it (same reasoning as analytics_engine.py's _risk_from_score). No
    # bands active at all means nothing can be classified - "Unknown", not
    # a hardcoded "Critical" that would misrepresent an admin's deliberate
    # choice to disable every band.
    return bands[-1][1] if bands else "Unknown"


def _condition_from_score_and_risk(
    score: float | None, risk_level: str | None, db: Session | None = None,
) -> str:
    """Same score bands as _condition_from_score, but honors a stored
    risk_level of "Critical" the way _risk_from_score's critical-findings
    override does - otherwise an equipment/test with a critical finding but
    a score >=50 lands in "Poor" here while kpis.critical_count (which reads
    risk_level directly) still counts it as critical, so the two disagree."""
    if risk_level == "Critical":
        return "Critical"
    return _condition_from_score(score, db)


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
    equipment_id: Optional[uuid.UUID] = Query(None),
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
    dept_scope = _enforced_department(db, user, department_id)

    # ── Equipment analytics in scope ─────────────────────────────────────────
    ea_list: list[EquipmentAnalytics] = _scoped_ea(
        dept_scope, db, organization_id=user.organization_id, equipment_id=equipment_id)
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
        ll = _life_left(eq.commissioned_date, type_map.get(eq.equipment_type_id), db)
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
        # Same accepted-results rule as /ageing's aging_rate.
        ParameterAnalytics.test_result_id.in_(accepted_test_result_ids(db)),
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
    ageing_risk_index = _ageing_index(pct_changes)

    # ── KPI 4: Dielectric Index ──────────────────────────────────────────────
    # Avg health score from test_type_scores where template_key is dielectric-related
    _DIEL_KEYS = {"oil_bdv", "dissolved_gas", "tan_delta", "insulation_resistance",
                  "oil_quality", "dga", "oil_test", "dielectric"}
    diel_scores: list[float] = []
    if _date_active:
        # Latest in-range dielectric test per (equipment, template) - the
        # EquipmentAnalytics snapshot is all-time, so the index used to
        # ignore the date range while the other KPIs followed it.
        _diel_best: dict = {}
        for ta, eff_date in _ta_dated:
            tkey = (ta.template_key or "").lower()
            if not any(k in tkey for k in _DIEL_KEYS):
                continue
            if not _dt_in_range(eff_date, date_from, date_to):
                continue
            key = (ta.equipment_id, tkey)
            cur = _diel_best.get(key)
            if cur is None or eff_date > cur[1]:
                _diel_best[key] = (ta, eff_date)
        diel_scores = [float(ta.health_score) for ta, _d in _diel_best.values()
                       if ta.health_score is not None]
    else:
        for ea in ea_list:
            for tkey, tval in (ea.test_type_scores or {}).items():
                if any(k in tkey.lower() for k in _DIEL_KEYS):
                    s = tval.get("score")
                    if s is not None:
                        diel_scores.append(float(s))
    dielectric_index = round(mean(diel_scores), 1) if diel_scores else None

    # ── Health distribution: condition × life-left bucket ────────────────────
    BUCKETS = ["0–5 yrs", "5–10 yrs", "10–15 yrs", "15–20 yrs", "20–25 yrs", "25+ yrs", "Unknown"]
    CONDITIONS = ["critical", "poor", "fair", "good", "excellent"]
    dist: dict[str, dict] = {b: {c: 0 for c in CONDITIONS} | {"unknown": 0, "total": 0} for b in BUCKETS}

    eq_by_id = {e.id: e for e in eq_list}
    for ea in ea_list:
        eq = eq_by_id.get(ea.equipment_id)
        ll = _life_left(eq.commissioned_date if eq else None,
                        type_map.get(eq.equipment_type_id) if eq else None, db)
        # No commissioned date = life unknown, not "25+ yrs" (which read as
        # the healthiest bucket).
        bucket = _life_bucket(ll) if ll is not None else "Unknown"
        cond = _condition_from_score_and_risk(
            _eff_health(ea.equipment_id, ea), _eff_risk(ea.equipment_id, ea), db
        )
        # An admin-renamed/custom Condition Band (anything other than the
        # 5 built-in words) doesn't match CONDITIONS - it used to be
        # silently dropped from every count including "total". Bucket it
        # as "unknown" instead so it's still counted and visible, rather
        # than vanishing (and, on the frontend, being visually mistaken
        # for "Critical" wherever a chart inferred that bucket by
        # subtracting the 4 known buckets from a separately-fetched total).
        key = cond.lower()
        dist[bucket][key if key in CONDITIONS else "unknown"] += 1
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
        cond = _condition_from_score_and_risk(float(ta.health_score), ta.risk_level, db)
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
    dept_scope = _enforced_department(db, user, department_id)
    ea_list = _scoped_ea(dept_scope, db, organization_id=user.organization_id)
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

    # With a date range, health/condition/risk come from each equipment's
    # latest test IN the range (same as /overview and /grouped) - the
    # all-time EquipmentAnalytics snapshot made this table contradict the
    # date-scoped charts next to it.
    _date_active = bool(date_from or date_to)
    latest_ta_map: dict = {}
    if _date_active:
        best: dict = {}
        for ta, eff_date in _ta_with_dates(eq_ids, db):
            if not _dt_in_range(eff_date, date_from, date_to):
                continue
            cur = best.get(ta.equipment_id)
            if cur is None or eff_date > cur[1]:
                best[ta.equipment_id] = (ta, eff_date)
        latest_ta_map = {k: v[0] for k, v in best.items()}

    assets = []
    for eq in eq_list:
        ea = ea_map.get(eq.id)
        src = latest_ta_map.get(eq.id) if _date_active else ea
        score = float(src.health_score) if src is not None and src.health_score is not None else None
        risk = (src.risk_level if src is not None else None) or "Unknown"
        type_name = type_map.get(eq.equipment_type_id)
        age = _age_years(eq.commissioned_date)
        exp_life = _expected_life(type_name, db)
        ll = _life_left(eq.commissioned_date, type_name, db)
        assets.append({
            "equipment_id":       str(eq.id),
            "ueic":               eq.ueic,
            "equipment_type":     type_name,
            "manufacturer":       eq.manufacturer or None,
            "commissioned_year":  eq.commissioned_date.year if eq.commissioned_date else None,
            "age_years":          round(age, 1) if age is not None else None,
            "expected_life":      exp_life,
            "life_left_years":    round(ll, 1) if ll is not None else None,
            "health_score":       score,
            "condition":          _condition_from_score_and_risk(score, risk, db),
            "risk_level":         risk,
            # For the row's actions menu ("Why Critical?" / "Why At Risk?").
            "critical_findings":  (src.critical_findings or []) if src is not None else [],
        })

    # Shortest life first; unknown life (no commissioned date) last. `or 999`
    # also sent a genuine 0.0 (past expected life) to the end.
    assets.sort(key=lambda x: (x["life_left_years"] is None,
                               x["life_left_years"] if x["life_left_years"] is not None else 0))

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
        ll_at = max(0.0, _expected_life(tname, db) - age_at)
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
    # Whole-word keys (see _kw_match); "current"/"load" alone matched
    # e.g. "leakage current" and "no load loss".
    "thermal_stress":  ["oti", "wti", "oil temperature", "winding temperature",
                        "hot spot", "top oil"],
    "load_factor":     ["load current", "load factor", "loading", "lc"],
}

_DP_KEYS = ["dp", "degree of polymerization", "degree of polymerisation",
            "polymerization", "polymerisation"]


@router.get("/ageing", summary="Ageing risk radar axes + DP degree of polymerisation trend")
def get_ageing(
    department_id: Optional[uuid.UUID] = Query(None),
    equipment_id: Optional[uuid.UUID] = Query(None),
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
    dept_scope = _enforced_department(db, user, department_id)
    ea_list = _scoped_ea(
        dept_scope, db, organization_id=user.organization_id, equipment_id=equipment_id)
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
        ParameterAnalytics.test_result_id.in_(accepted_test_result_ids(db)),
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
    _match = _kw_match

    # Aging rate: avg abs pct_change_annual across all params
    all_pct = [min(100.0, abs(float(r.pct_change_annual))) for r in pa_rows
               if r.pct_change_annual is not None]
    aging_rate = _ageing_index(all_pct)  # same formula as the KPI tile

    # Volatility: spread of the (capped) annual % changes, 0-100
    volatility = round(min(100.0, stdev(all_pct)), 1) if len(all_pct) >= 2 else None

    # Life left risk: 100 = no life left, 0 = full life remaining
    life_vals = []
    for eq in eq_list:
        ll = _life_left(eq.commissioned_date, type_map.get(eq.equipment_type_id), db)
        exp = _expected_life(type_map.get(eq.equipment_type_id), db)
        if ll is not None:
            life_vals.append(max(0.0, 100.0 * (1 - ll / exp)))
    life_left_risk = round(mean(life_vals), 1) if life_vals else None

    # Thermal stress: avg condition risk score for thermal params
    thermal_pa = [r for r in pa_rows if _match(r.parameter_label or r.parameter_key, _AGEING_AXES["thermal_stress"])]
    thermal_stress = round(mean([_param_risk_score(r.condition) for r in thermal_pa]), 1) if thermal_pa else None

    # Load factor: avg condition risk score for load params
    load_pa = [r for r in pa_rows if _match(r.parameter_label or r.parameter_key, _AGEING_AXES["load_factor"])]
    load_factor = round(mean([_param_risk_score(r.condition) for r in load_pa]), 1) if load_pa else None

    fleet_radar = {
        "aging_rate":     aging_rate,
        "volatility":     volatility,
        "life_left_risk": life_left_risk,
        "thermal_stress": thermal_stress,
        "load_factor":    load_factor,
    }
    # Admin-configured reference polygon (AgeingConfig.benchmark_*).
    benchmark_radar = dict(_load_ageing_config(db)["benchmark"])

    # ── Per-asset ageing index ────────────────────────────────────────────────
    eq_label_map = {e.id: e.ueic for e in eq_list}
    asset_pct: dict = {}
    for r in pa_rows:
        if r.pct_change_annual is not None:
            asset_pct.setdefault(r.equipment_id, []).append(abs(float(r.pct_change_annual)))

    asset_scores = []
    for eq_id, pcts in asset_pct.items():
        score = _ageing_index(pcts)
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

# Whole-word keys (see _kw_match).
_DIEL_AXIS_KEYS = {
    "c2h2":      ["c2h2", "acetylene"],
    "h2":        ["h2", "hydrogen"],
    "acidity":   ["acidity", "neutralisation value", "neutralization value"],
    "wco":       ["wco", "water content", "moisture"],
    "dp_risk":   ["dp", "degree of polymerization", "degree of polymerisation"],
    "tan_delta": ["tan delta", "td", "dissipation factor", "d.f"],
}

_TREND_GROUPS = {
    "tan_delta": ["tan delta", "td", "dissipation factor", "d.f"],
    "dga":       ["c2h2", "h2", "ch4", "co", "co2", "c2h4", "c2h6", "tgc",
                  "acetylene", "hydrogen", "methane", "ethylene", "ethane",
                  "carbon monoxide", "carbon dioxide"],
    "bdv":       ["bdv", "oil breakdown", "breakdown voltage"],
}


@router.get("/dielectric", summary="Dielectric risk radar + DGA / Tan Delta / BDV parameter trends")
def get_dielectric(
    department_id: Optional[uuid.UUID] = Query(None),
    equipment_id: Optional[uuid.UUID] = Query(None),
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
    dept_scope = _enforced_department(db, user, department_id)
    ea_list = _scoped_ea(
        dept_scope, db, organization_id=user.organization_id, equipment_id=equipment_id)
    eq_ids = [ea.equipment_id for ea in ea_list]
    eq_ids, ea_list, _ = _apply_test_date_scope(
        eq_ids, ea_list, None, db, date_from, date_to)

    eq_list = db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all() if eq_ids else []
    eq_label_map = {e.id: e.ueic for e in eq_list}

    pa_rows: list[ParameterAnalytics] = db.query(ParameterAnalytics).filter(
        ParameterAnalytics.equipment_id.in_(eq_ids),
        ParameterAnalytics.test_result_id.in_(accepted_test_result_ids(db)),
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

    _match = _kw_match

    # ── Radar: one risk score per axis ────────────────────────────────────────
    radar_fleet: dict[str, float] = {}
    for axis, keys in _DIEL_AXIS_KEYS.items():
        matched = [r for r in pa_rows
                   if _match(r.parameter_label or r.parameter_key, keys)]
        if matched:
            radar_fleet[axis] = round(mean([_param_risk_score(r.condition) for r in matched]), 1)
        else:
            # No readings for this axis: null ("no data"), not 0 - a 0 read
            # as "no risk" on the radar.
            radar_fleet[axis] = None

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
    equipment_id: Optional[uuid.UUID] = Query(None),
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
    dept_scope = _enforced_department(db, user, department_id)
    if group_by not in _VALID_GROUP_BY:
        group_by = "equipment_type"

    # Year of failure is about retired equipment only (same as the AI
    # Analytics dashboard's by_failure_year); every other view is in-service.
    ea_list = _scoped_ea(
        dept_scope, db, organization_id=user.organization_id, equipment_id=equipment_id,
        retired_only=(group_by == "year_failure"))
    eq_ids  = [ea.equipment_id for ea in ea_list]
    ea_map  = {ea.equipment_id: ea for ea in ea_list}
    # Year of failure counts every retired unit whatever the date range (as
    # AI Analytics' by_failure_year does); the range only decides which of
    # them have an in-range health snapshot (see _eff_health below).
    if group_by != "year_failure":
        eq_ids, ea_list, ea_map = _apply_test_date_scope(
            eq_ids, ea_list, ea_map, db, date_from, date_to)
    if group_by == "year_failure" and not equipment_id:
        # Every retired unit counts toward its failure year, assessed or not
        # (AI Analytics' by_failure_year counts them all) - _scoped_ea only
        # returns equipment with an analytics row, so add the rest here
        # (they land in the group's count as unscored).
        _have = set(eq_ids)
        _testkit_ids = [c.id for c in db.query(CategoryMaster.id)
                        .filter(CategoryMaster.name.ilike("%testing kit%")).all() if c.id]
        _rq = db.query(Equipment.id).filter(Equipment.status == "retired")
        if user.organization_id:
            _rq = _rq.filter(Equipment.organization_id == user.organization_id)
        if dept_scope is not None:
            _rq = _rq.filter(Equipment.department_id.in_(dept_scope))
        if _testkit_ids:
            _rq = _rq.filter((Equipment.equipment_type_id == None)  # noqa: E711
                             | ~Equipment.equipment_type_id.in_(_testkit_ids))
        eq_ids = eq_ids + [r[0] for r in _rq.all() if r[0] not in _have]

    eq_list: list[Equipment] = db.query(Equipment).filter(
        Equipment.id.in_(eq_ids)
    ).all() if eq_ids else []
    if group_by == "year_replaced":
        # Same definition as the AI Analytics dashboard's by_replacement_year:
        # the REPLACEMENT unit (replaces_equipment_id set), bucketed by its
        # own commissioned year. Previously the opposite (the old unit, via a
        # per-equipment query on replaced_by_id), so the dashboards disagreed.
        eq_list = [e for e in eq_list if e.replaces_equipment_id is not None]
        eq_ids = [e.id for e in eq_list]

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

    def _eff_risk(eq_id, ea) -> str | None:
        if _date_active:
            ta = latest_ta_map.get(eq_id)
            return ta.risk_level if ta else None
        return ea.risk_level if ea else None

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
            # retired_date year = "year of failure / end of service"
            return str(eq.retired_date.year) if eq.retired_date else "Unknown"
        if group_by == "year_replaced":
            # eq is the replacement unit (filtered above): its commissioned year
            return str(eq.commissioned_date.year) if eq.commissioned_date else "Unknown"
        return "Unknown"

    # ── Accumulate per-group stats ────────────────────────────────────────────
    from collections import defaultdict
    group_scores:    dict[str, list[float]] = defaultdict(list)
    group_conditions:dict[str, dict]        = defaultdict(lambda: {
        "critical": 0, "poor": 0, "fair": 0, "good": 0, "excellent": 0, "unknown": 0
    })
    group_life:  dict[str, list[float]] = defaultdict(list)
    group_age:   dict[str, list[float]] = defaultdict(list)
    group_tests: dict[str, int]         = defaultdict(int)
    group_age_risk: dict[str, dict] = defaultdict(lambda: {
        "overdue": 0, "near_end": 0, "mid_life": 0, "early": 0
    })
    # Admin-configured age/expected_life cutoffs (AgeingConfig.life_stage_*).
    life_stage_cutoffs = dict(_load_ageing_config(db)["life_stage_cutoffs"])
    _ls_mid = life_stage_cutoffs["mid"]
    _ls_near_end = life_stage_cutoffs["near_end"]
    _ls_overdue = life_stage_cutoffs["overdue"]

    # Every in-scope equipment of the group, scored or not - "count" must
    # include unscored units (previously len(scores) or len(lives) or
    # len(ages), which undercounted mixed groups and dropped equipment with
    # neither a score nor a commissioned date entirely).
    group_members: dict[str, int] = defaultdict(int)

    for eq in eq_list:
        ea        = ea_map.get(eq.id)
        label     = _group_label(eq)
        type_name = type_map.get(eq.equipment_type_id)
        group_members[label] += 1
        score = _eff_health(eq.id, ea)
        if score is not None:
            group_scores[label].append(score)
            # _and_risk, same as /overview - a Critical-risk equipment must
            # land in the Critical segment here too, not Poor.
            cond = _condition_from_score_and_risk(score, _eff_risk(eq.id, ea), db).lower()
            # Same "unknown" handling as /overview's health_distribution -
            # an admin-renamed Condition Band must not silently disappear
            # (previously dropped here, then implicitly rendered as
            # Critical/red on the frontend, which inferred that segment as
            # "count minus the 4 known buckets" instead of reading an
            # actual field).
            key = cond if cond in ("critical", "poor", "fair", "good", "excellent") else "unknown"
            group_conditions[label][key] += 1

        ll  = _life_left(eq.commissioned_date, type_name, db)
        age = _age_years(eq.commissioned_date)
        exp = _expected_life(type_name, db)
        if ll is not None:
            group_life[label].append(ll)
        group_tests[label] += test_count_map.get(str(eq.id), 0)
        if age is not None:
            group_age[label].append(age)
            pct = age / exp if exp else 0
            if pct >= _ls_overdue:
                group_age_risk[label]["overdue"] += 1
            elif pct >= _ls_near_end:
                group_age_risk[label]["near_end"] += 1
            elif pct >= _ls_mid:
                group_age_risk[label]["mid_life"] += 1
            else:
                group_age_risk[label]["early"] += 1

    # Merge all labels
    all_labels = set(group_members)

    groups = []
    for label in all_labels:
        scores = group_scores.get(label, [])
        conds  = group_conditions.get(label, {})
        lives  = group_life.get(label, [])
        ages   = group_age.get(label, [])
        ar     = group_age_risk.get(label, {})
        groups.append({
            "label":         label,
            "count":         group_members[label],
            "avg_health":    round(mean(scores), 1) if scores else None,
            "avg_life_left": round(mean(lives),  1) if lives  else None,
            "avg_age_years": round(mean(ages),   1) if ages   else None,
            "critical":      conds.get("critical", 0),
            "poor":          conds.get("poor",     0),
            "fair":          conds.get("fair",     0),
            "good":          conds.get("good",     0),
            "excellent":     conds.get("excellent",0),
            "unknown":       conds.get("unknown",  0),
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
        # Active condition bands (highest threshold first) so the client
        # colours avg-health bars by the same admin-configured cutoffs the
        # condition counts above were classified with.
        "condition_bands": [
            {"threshold": t, "label": l} for t, l in _load_condition_bands(db)
        ],
        # Admin-configured age/expected_life cutoffs the overdue/near_end/
        # mid_life/early counts above were bucketed with.
        "life_stage_cutoffs": life_stage_cutoffs,
    }
