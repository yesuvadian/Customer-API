"""
Scope / access regression tests for the AI Analytics and AI Graph dashboards
(routers/analytics.py _resolve_dashboard_scope, _user_allowed_dept_ids,
_assert_equipment_access and the endpoints built on them).

Integration tests against the dev vendor DB, like the rest of this folder:
they read only (every session is rolled back) and skip when the data they
need (an org admin, a department-scoped user, a second organization) isn't
there.

    python -m pytest tests/test_ai_dashboard_scope.py -v
"""
import inspect
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import VendorSessionLocal  # noqa: E402
from models import Equipment, EquipmentAnalytics, OrgDepartment, User  # noqa: E402
from routers import analytics as A  # noqa: E402
from routers import ai_graph as G  # noqa: E402
from routers.car import has_module_permission  # noqa: E402
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


@pytest.fixture()
def dept_user(db):
    for u in db.query(User).filter(User.organization_id.isnot(None)).limit(3000):
        if A._user_allowed_dept_ids(db, u):
            return u
    pytest.skip("no department-scoped user in the DB")


# ── _resolve_dashboard_scope ────────────────────────────────────────────────

def test_org_admin_scope_is_whole_org(db, org_admin):
    org_id, dept_ids = A._resolve_dashboard_scope(db, org_admin, None)
    assert org_id == org_admin.organization_id
    assert dept_ids is None


def test_dept_user_default_scope_is_their_departments(db, dept_user):
    org_id, dept_ids = A._resolve_dashboard_scope(db, dept_user, None)
    assert dept_ids, "a department-scoped user must never get an empty (= whole org) scope"
    if dept_user.department_id:
        assert dept_user.department_id in dept_ids, \
            "the profile department (what /me sends) must be allowed"


def test_dept_user_outside_department_is_403(db, dept_user):
    allowed = A._user_allowed_dept_ids(db, dept_user)
    other = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == dept_user.organization_id,
        ~OrgDepartment.id.in_(allowed)).first()
    if not other:
        pytest.skip("no department outside the user's scope")
    with pytest.raises(HTTPException) as e:
        A._resolve_dashboard_scope(db, dept_user, other.id)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        call(G.get_overview, db=db, user=dept_user, department_id=other.id)
    assert e.value.status_code == 403


def test_other_org_department_is_404(db, org_admin):
    foreign = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id != org_admin.organization_id).first()
    if not foreign:
        pytest.skip("only one organization in the DB")
    with pytest.raises(HTTPException) as e:
        call(A.get_dashboard_equipment, db=db, user=org_admin, department_id=foreign.id)
    assert e.value.status_code == 404


def test_inactive_root_still_scopes(db, dept_user, monkeypatch):
    """An inactive own department makes the subtree CTE return nothing - the
    scope must still be the department itself, never "no restriction"."""
    monkeypatch.setattr(A, "_collect_department_ids", lambda root, _db: set())
    db.info.pop("_dashboard_allowed_depts", None)
    allowed = A._user_allowed_dept_ids(db, dept_user)
    assert allowed, "empty allowed set would read as whole-organization access"


# ── equipment access ────────────────────────────────────────────────────────

def test_other_org_equipment_is_404(db, org_admin):
    foreign = db.query(Equipment.id).filter(
        Equipment.organization_id != org_admin.organization_id).first()
    if not foreign:
        pytest.skip("only one organization in the DB")
    with pytest.raises(HTTPException) as e:
        A._assert_equipment_access(db, org_admin, foreign[0])
    assert e.value.status_code == 404


def test_own_org_equipment_is_readable(db, org_admin):
    own = db.query(Equipment.id).filter(
        Equipment.organization_id == org_admin.organization_id).first()
    if not own:
        pytest.skip("organization has no equipment")
    A._assert_equipment_access(db, org_admin, own[0])  # no exception


def test_unknown_equipment_is_404(db, org_admin):
    with pytest.raises(HTTPException) as e:
        A._assert_equipment_access(db, org_admin, uuid.uuid4())
    assert e.value.status_code == 404


def test_equipment_list_is_org_only(db, org_admin):
    r = call(A.get_dashboard_equipment, db=db, user=org_admin, page_size=1000)
    ids = [uuid.UUID(i["equipment_id"]) for i in r["items"]]
    if not ids:
        pytest.skip("no equipment in scope")
    orgs = {o for (o,) in db.query(Equipment.organization_id).filter(Equipment.id.in_(ids))}
    assert orgs == {org_admin.organization_id}


# ── consistency the scope work guarantees ───────────────────────────────────

@pytest.mark.parametrize("dated", [False, True])
def test_tiles_cards_and_risk_list_agree(db, org_admin, dated):
    from datetime import date
    kw = dict(date_from=date(2024, 1, 1), date_to=date.today()) if dated else {}
    d = call(A.get_analytics_dashboard, db=db, user=org_admin, **kw)
    k, cards = d["kpi_summary"], d["department_scores"]
    for band, key in (("Critical", "equipment_critical"), ("High", "equipment_high"),
                      ("Medium", "equipment_medium"), ("Low", "equipment_low")):
        assert sum(c[key] for c in cards) == k[band.lower()], band
        listed = call(A.get_dashboard_equipment, db=db, user=org_admin,
                      risk_level=band, page_size=1000, **kw)["total"]
        assert listed == k[band.lower()], f"{band} list vs tile"
    assert sum(c["test_count"] for c in cards) == k["total_tests"]


@pytest.mark.parametrize("dated", [False, True])
def test_tiles_and_summary_table_agree(db, org_admin, dated):
    """The summary table's Critical/High/Medium/Low columns (/asset-breakdown,
    any view) add up to the KPI tiles, and a group's tested drill rows carry
    the same risk split as its row."""
    from collections import Counter
    from datetime import date
    kw = dict(date_from=date(2024, 1, 1), date_to=date.today()) if dated else {}
    k = call(A.get_analytics_dashboard, db=db, user=org_admin, **kw)["kpi_summary"]
    bd = call(A.get_asset_breakdown, db=db, user=org_admin, **kw)
    for view in ("by_type_health", "by_voltage_class_health", "by_make_health"):
        rows = bd[view]
        for band in ("critical", "high", "medium", "low"):
            assert sum(r[band] for r in rows.values()) == k[band], f"{view} {band}"
    rows = bd["by_type_health"]
    if not rows:
        pytest.skip("no equipment types in scope")
    group = max(rows, key=lambda g: sum(rows[g][b] for b in ("critical", "high", "medium", "low")))
    if group in ("Unknown", "Not Specified"):
        pytest.skip("largest group is the unknown bucket")
    items = call(A.get_dashboard_equipment, db=db, user=org_admin,
                 equipment_type=group, tested_only=True, page_size=1000, **kw)["items"]
    got = Counter(i["risk_level"] for i in items)
    for band in ("Critical", "High", "Medium", "Low"):
        assert got[band] == rows[group][band.lower()], f"{group} {band} drill vs row"


@pytest.mark.parametrize("view,param", [
    ("by_type", "equipment_type"), ("by_make", "manufacturer"),
    ("by_voltage_class", "voltage_class"),
])
def test_group_drill_lists_every_asset_in_the_row(db, org_admin, view, param):
    """The drill-down (tested_only off, as the app now sends it) lists as many
    assets as the row's Total Assets - placeholder groups ("N/A", "-", blank,
    ...) included, which the app merges into "Not Specified" and drills with
    the "unknown" sentinel."""
    bd = call(A.get_asset_breakdown, db=db, user=org_admin)
    rows = bd[view]
    if not rows:
        pytest.skip(f"no {view} groups")
    unknown_total = sum(n for g, n in rows.items() if A._is_placeholder_group(g))
    if unknown_total:
        got = call(A.get_dashboard_equipment, db=db, user=org_admin,
                   tested_only=False, page_size=1, **{param: "unknown"})["total"]
        assert got == unknown_total, "Not Specified drill vs row"
    real = [g for g in rows if not A._is_placeholder_group(g)]
    if real:
        g = max(real, key=rows.get)
        got = call(A.get_dashboard_equipment, db=db, user=org_admin,
                   tested_only=False, page_size=1, **{param: g})["total"]
        assert got == rows[g], f"{g} drill vs row"


def test_search_wildcards_are_literal(db, org_admin):
    r = call(A.get_dashboard_equipment, db=db, user=org_admin, search="%_%")
    assert all("%_%" in (i["ueic"] or "") for i in r["items"])


def test_recompute_requires_permission(db, dept_user):
    if has_org_admin_role(dept_user.id, db) or \
            has_module_permission(db, dept_user, "threshold_config", "can_edit"):
        pytest.skip("user is allowed to recompute - not starting a real job")
    with pytest.raises(HTTPException) as e:
        call(A.recompute_all_analytics, db=db, user=dept_user)
    assert e.value.status_code == 403
