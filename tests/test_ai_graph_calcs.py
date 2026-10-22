"""
Calculation regression tests for the AI Graph dashboard (routers/ai_graph.py):
one overdue rule across cards, life numbers over never-tested equipment,
risk counted by slot (admin-renamed bands), local-date range boundaries.

Integration tests against the dev vendor DB, like the rest of this folder:
they read only (every session is rolled back) and skip when the data they
need isn't there.

    python -m pytest tests/test_ai_graph_calcs.py -q
"""
import inspect
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import ProgrammingError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import VendorSessionLocal  # noqa: E402
from models import CategoryMaster, Equipment, EquipmentAnalytics, User  # noqa: E402
from routers import ai_graph as G  # noqa: E402
from services import analytics_engine as AE  # noqa: E402
from auth_utils import has_org_admin_role  # noqa: E402


def call(fn, **kw):
    """Call a FastAPI endpoint function directly, filling Query() defaults."""
    args = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name in kw:
            args[name] = kw[name]
        elif p.default is not inspect.Parameter.empty:
            args[name] = getattr(p.default, "default", p.default)
    return fn(**args)


@pytest.fixture()
def db():
    s = VendorSessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def top_org(db):
    from sqlalchemy import func
    row = (db.query(EquipmentAnalytics.organization_id, func.count())
           .group_by(EquipmentAnalytics.organization_id)
           .order_by(func.count().desc()).first())
    if not row or not row[0]:
        pytest.skip("no equipment analytics in the DB")
    return row[0]


@pytest.fixture()
def org_admin(db, top_org):
    for u in db.query(User).filter(User.organization_id == top_org).limit(2000):
        if has_org_admin_role(u.id, db):
            return u
    pytest.skip("no org admin in the largest organization")


# ── One overdue definition ──────────────────────────────────────────────────

def test_overdue_same_on_every_card(db, org_admin):
    kpi = call(G.get_overview, db=db, user=org_admin)["kpis"]["overdue_count"]
    table = call(G.get_life_left, db=db, user=org_admin)["assets"]
    table_overdue = sum(1 for a in table
                        if a["life_left_years"] is not None and a["life_left_years"] < 0)
    grouped = call(G.get_grouped, db=db, user=org_admin, group_by="equipment_type")
    stage_overdue = sum(g["overdue"] for g in grouped["groups"])
    assert kpi == table_overdue == stage_overdue
    assert grouped["life_stage_cutoffs"]["overdue"] == 1.0


def test_is_overdue_rule():
    assert G._is_overdue(None, None, -0.2)
    assert not G._is_overdue(None, None, -0.04)   # shown as "0.0 yr"
    assert not G._is_overdue(None, None, 0.0)
    assert G._is_overdue(31.0, 30, None)
    assert not G._is_overdue(None, None, None)
    assert G._life_bucket(-0.2) == "Overdue"


def test_future_commissioned_date_clamped():
    future = datetime.now(timezone.utc) + timedelta(days=800)
    assert G._age_years(future) == 0.0
    assert G._life_left(future, "power transformer", None) == G._expected_life("power transformer", None)


# ── Life numbers include never-tested equipment ─────────────────────────────

def test_life_left_includes_untested_equipment(db, org_admin):
    in_scope = G._scoped_equipment(None, db, organization_id=org_admin.organization_id)
    assessed = {r[0] for r in db.query(EquipmentAnalytics.equipment_id).all()}
    untested = [e for e in in_scope
                if e.commissioned_date is not None and e.id not in assessed]
    if not untested:
        pytest.skip("no in-scope equipment with a commissioned date but no analytics row")
    rows = {a["equipment_id"]: a for a in
            call(G.get_life_left, db=db, user=org_admin)["assets"]}
    for e in untested:
        row = rows.get(str(e.id))
        assert row is not None, f"untested equipment {e.ueic} missing from life-left table"
        assert row["life_left_years"] is not None
        assert row["health_score"] is None
        assert row["risk_level"] is None
        assert row["condition"] == "Not assessed"
    # ...and the KPI averages over the same population as the table.
    kpis = call(G.get_overview, db=db, user=org_admin)["kpis"]
    lives = [a["life_left_years"] for a in rows.values() if a["life_left_years"] is not None]
    assert kpis["avg_life_left"] is not None
    assert abs(kpis["avg_life_left"] - sum(lives) / len(lives)) < 0.15


# ── Risk counted by slot ────────────────────────────────────────────────────

def test_critical_count_matches_slot_count(db, org_admin):
    testkit = [c.id for c in db.query(CategoryMaster.id)
               .filter(CategoryMaster.name.ilike("%testing kit%")).all()]
    q = (db.query(EquipmentAnalytics.risk_level)
         .join(Equipment, Equipment.id == EquipmentAnalytics.equipment_id)
         .filter(Equipment.organization_id == org_admin.organization_id,
                 Equipment.status != "retired"))
    if testkit:
        q = q.filter((Equipment.equipment_type_id == None)  # noqa: E711
                     | ~Equipment.equipment_type_id.in_(testkit))
    slot = AE.risk_slot_mapper(db)
    levels = [r[0] for r in q.all()]
    kpis = call(G.get_overview, db=db, user=org_admin)["kpis"]
    assert kpis["critical_count"] == sum(1 for l in levels if slot(l) == "Critical")
    assert kpis["high_count"] == sum(1 for l in levels if slot(l) == "High")
    assert kpis["equipment_count"] == len(levels)


def test_risk_slot_mapper_renamed_label(monkeypatch):
    monkeypatch.setattr(AE, "_load_risk_bands",
                        lambda db: [(80, "Good"), (50, "Fair"), (25, "Poor"), (0, "Severe")])
    slot = AE.risk_slot_mapper(None)
    assert slot("Severe") == "Critical"
    assert slot("Fair") == "Medium"
    assert slot("High") == "High"
    assert slot(None) is None


def test_condition_override_uses_slot(monkeypatch):
    monkeypatch.setattr(AE, "_load_risk_bands",
                        lambda db: [(80, "Good"), (50, "Fair"), (25, "Poor"), (0, "Severe")])
    assert G._condition_from_score_and_risk(95.0, "Severe", None) == "Critical"


# ── Local-date range boundaries ─────────────────────────────────────────────

def test_dt_in_range_uses_local_date():
    dt = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)   # 2026-01-02 01:30 IST
    assert G._dt_in_range(dt, date(2026, 1, 2), None)
    assert not G._dt_in_range(dt, None, date(2026, 1, 1))
    # Naive datetimes are read as UTC.
    assert G._dt_in_range(dt.replace(tzinfo=None), date(2026, 1, 2), date(2026, 1, 2))
    assert G._trend_bucket(dt, 10)[0] == date(2026, 1, 2)


# ── Config fallbacks ────────────────────────────────────────────────────────

def test_condition_bands_missing_table_falls_back(db, monkeypatch):
    def boom(_db):
        raise ProgrammingError("SELECT 1", {}, Exception("relation does not exist"))
    monkeypatch.setattr(G, "_query_condition_bands", boom)
    db.info.pop("_ai_graph_condition_bands", None)
    assert G._load_condition_bands(db) == G._DEFAULT_CONDITION_BANDS
    db.info.pop("_ai_graph_condition_bands", None)


def test_param_risk_uses_configured_scores(db):
    risk = G._param_risk_map(db)
    scores = AE._load_condition_scores(db)
    if scores is AE._DEFAULT_SCORE:
        assert risk == G._DEFAULT_PARAM_RISK
    else:
        for cond, pts in scores.items():
            assert risk[cond] == round(100.0 - min(100.0, max(0.0, pts)), 1)
    assert G._param_risk_score("Good") == 10.0  # no session: old constants


# ── Radar axes: unclassified readings are "no data", not 50 ─────────────────

def _rows(*conds):
    return [type("R", (), {"condition": c})() for c in conds]


def test_condition_axis_ignores_unclassified_readings():
    assert G._condition_risk_axis(_rows(None, None)) is None
    assert G._condition_risk_axis([]) is None
    assert G._condition_risk_axis(_rows("Poor", None, "")) == G._param_risk_score("Poor")
    assert G._condition_risk_axis(_rows("Good", "Poor")) == round(
        (G._param_risk_score("Good") + G._param_risk_score("Poor")) / 2, 1)


def test_life_left_never_negative_zero():
    import json
    assert json.dumps(G._life_left_out(-0.04)) == "0.0"
    assert G._life_left_out(-0.06) == -0.1
    assert G._life_left_out(None) is None


# ── /overview assessed_count, /ageing life_left_risk population ─────────────

def test_assessed_count_is_four_risk_slots(db, org_admin):
    k = call(G.get_overview, db=db, user=org_admin)["kpis"]
    assert isinstance(k["assessed_count"], int)
    slot = G._risk_slot(db)
    ea = G._scoped_ea(None, db, organization_id=org_admin.organization_id)
    assert k["assessed_count"] == sum(1 for r in ea if slot(r.risk_level) in AE.RISK_SLOTS)
    assert k["critical_count"] + k["high_count"] <= k["assessed_count"] <= k["equipment_count"]


def test_life_left_risk_over_life_kpi_population(db, org_admin):
    radar = call(G.get_ageing, db=db, user=org_admin)["radar"]["fleet"]
    eqs = G._scoped_equipment(None, db, organization_id=org_admin.organization_id)
    types = {c.id: c.name for c in db.query(CategoryMaster).all()}
    vals = []
    for e in eqs:
        ll = G._life_left(e.commissioned_date, types.get(e.equipment_type_id), db)
        exp = G._expected_life(types.get(e.equipment_type_id), db)
        if ll is not None and exp:
            vals.append(min(100.0, max(0.0, 100.0 * (1 - ll / exp))))
    if not vals:
        pytest.skip("no in-scope equipment with a commissioned date")
    assert radar["life_left_risk"] == round(sum(vals) / len(vals), 1)


# ── EquipmentAnalytics.last_test_date is the test's date ────────────────────

def test_last_test_date_prefers_tested_at():
    def row(tested, calc):
        return type("R", (), {"tested_at": tested, "calculated_at": calc})()
    rescored = datetime(2026, 10, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    t2 = datetime(2025, 5, 1, 6, 0)                          # naive = UTC
    assert AE._last_test_date([row(t1, rescored), row(t2, rescored)]) == t2.replace(tzinfo=timezone.utc)
    assert AE._last_test_date([row(None, t1)]) == t1          # no test date: calculated_at
    assert AE._last_test_date([]) is None


# ── AI Analytics date bounds / whitespace / paging ──────────────────────────

def test_analytics_date_bounds_are_local_midnight():
    from routers import analytics as A
    b = A._local_day_start(date(2026, 1, 2))
    assert b.utcoffset() == timedelta(hours=5, minutes=30)
    assert b.astimezone(timezone.utc) == datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc)


def test_drill_strip_matches_python_strip(db):
    """The drill's SQL trims like str.strip() (tabs, newlines, NBSP, ...) -
    Postgres trim() strips spaces only."""
    from sqlalchemy import func, literal
    from routers import analytics as A
    for raw in ("  Make\t", " Make ", "\nN/A \r", "Ma ke", "　x "):
        got = db.query(func.regexp_replace(literal(raw), A._SQL_EDGE_WS, "", "g")).scalar()
        assert got == raw.strip(), repr(raw)


def test_testing_request_lists_have_id_tiebreak():
    from services import testing_request_service as S
    src = inspect.getsource(S)
    assert "order_by(TestingRequest.cts.desc())" not in src
    assert src.count("TestingRequest.cts.desc(), TestingRequest.id.desc()") >= 2
