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
