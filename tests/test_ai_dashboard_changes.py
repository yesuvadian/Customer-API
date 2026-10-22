"""
"Change a value, every AI Analytics number follows" tests.

Each test changes something inside the test's own transaction (risk band
thresholds, a band's label, an equipment's type, retiring an equipment),
rescoring where the app would, then checks that the KPI tiles, department
cards, summary table and risk lists all moved together and still agree.
Every session is rolled back - nothing is written to the dev DB.

    python -m pytest tests/test_ai_dashboard_changes.py -v
"""
from collections import Counter

import pytest

from models import (
    OUT_OF_SERVICE_EQUIPMENT_STATUSES, Equipment, EquipmentAnalytics, EquipmentHealthBandThreshold,
)
from routers import analytics as A
from services.analytics_engine import AnalyticsEngine, risk_slot_mapper, RISK_SLOTS
from test_ai_dashboard_scope import call, db, top_org, org_admin  # noqa: F401 (fixtures)

BANDS = ("critical", "high", "medium", "low")


def snapshot(db, user):
    """Every AI Analytics risk number for the user's scope, after checking
    they agree with each other: tiles = department cards = summary table
    (by type, make, voltage) = risk lists."""
    d = call(A.get_analytics_dashboard, db=db, user=user)
    k = d["kpi_summary"]
    bd = call(A.get_asset_breakdown, db=db, user=user)
    tiles = {b: k[b] for b in BANDS}
    cards = {b: sum(c[f"equipment_{b}"] for c in d["department_scores"]) for b in BANDS}
    assert cards == tiles, f"department cards {cards} != tiles {tiles}"
    for view in ("by_type_health", "by_make_health", "by_voltage_class_health"):
        table = {b: sum(r[b] for r in bd[view].values()) for b in BANDS}
        assert table == tiles, f"{view} {table} != tiles {tiles}"
    for view in ("by_type", "by_make"):
        for g, h in bd[f"{view}_health"].items():
            parts = sum(h[b] for b in BANDS) + h["unknown"] + h["untested"]
            assert parts == bd[view][g], f"{view} row {g}: {parts} != {bd[view][g]}"
    for band, n in tiles.items():
        listed = call(A.get_dashboard_equipment, db=db, user=user,
                      risk_level=band.capitalize(), page_size=1000)["total"]
        assert listed == n, f"{band} risk list {listed} != tile {n}"
    return {"tiles": tiles, "k": k, "bd": bd}


def scope_ea(db, user):
    """EquipmentAnalytics rows the tiles count: the user's organization,
    active equipment."""
    retired = {e for (e,) in db.query(Equipment.id)
               .filter(Equipment.status.in_(OUT_OF_SERVICE_EQUIPMENT_STATUSES))}
    return [ea for ea in db.query(EquipmentAnalytics)
            .join(Equipment, Equipment.id == EquipmentAnalytics.equipment_id)
            .filter(Equipment.organization_id == user.organization_id).all()
            if ea.equipment_id not in retired]


def rescore(db, rows):
    engine = AnalyticsEngine(db)
    for ea in rows:
        engine.run_for_equipment(ea.equipment_id)
    db.flush()


def test_baseline_numbers_agree(db, org_admin):
    snap = snapshot(db, org_admin)
    assert sum(snap["tiles"].values()) > 0 or pytest.skip("no assessed equipment")


def test_band_threshold_change_moves_every_number(db, org_admin):
    """Raise the Critical cutoff: after rescoring, every number moves to the
    new classification together, matching an independent count."""
    bands = db.query(EquipmentHealthBandThreshold).filter(
        EquipmentHealthBandThreshold.is_active.is_(True)).all()
    if not bands:
        pytest.skip("risk bands not configured (defaults in use)")
    rows = scope_ea(db, org_admin)
    if not rows:
        pytest.skip("no equipment analytics in scope")
    before = snapshot(db, org_admin)["tiles"]

    # Turn High off: Critical now catches everything under the Medium cutoff.
    by_label = {b.label: b for b in bands}
    if "High" not in by_label or "Medium" not in by_label:
        pytest.skip("standard High/Medium bands not configured")
    by_label["High"].is_active = False
    db.flush()
    rescore(db, rows)

    after = snapshot(db, org_admin)["tiles"]
    slot = risk_slot_mapper(db)
    expected = Counter(slot(ea.risk_level) for ea in scope_ea(db, org_admin))
    assert after == {b: expected.get(b.capitalize(), 0) for b in BANDS}
    assert after["high"] == 0, "no score can fall in an empty High band"
    assert after["critical"] >= before["critical"]
    assert sum(after.values()) == sum(before.values()), "assessed total must not change"


def test_renamed_band_label_still_counted(db, org_admin):
    """An admin renames "Critical" to "Severe": the equipment stays on the
    Critical tile, card and column instead of vanishing."""
    band = db.query(EquipmentHealthBandThreshold).filter(
        EquipmentHealthBandThreshold.label == "Critical",
        EquipmentHealthBandThreshold.is_active.is_(True)).first()
    if band is None:
        pytest.skip("no active Critical band")
    rows = scope_ea(db, org_admin)
    before = snapshot(db, org_admin)["tiles"]
    # Includes equipment that is Critical only through a CRITICAL finding:
    # that override must follow the renamed band too.
    band.label = "Severe"
    db.flush()
    rescore(db, rows)
    assert any(ea.risk_level == "Severe" for ea in scope_ea(db, org_admin)) or before["critical"] == 0
    assert snapshot(db, org_admin)["tiles"] == before


def test_equipment_type_change_moves_its_row(db, org_admin):
    """Re-typing an assessed equipment moves it between summary-table rows;
    the tiles don't change."""
    before = snapshot(db, org_admin)
    rows = [ea for ea in scope_ea(db, org_admin) if ea.risk_level]
    if not rows:
        pytest.skip("no assessed equipment")
    eq = db.get(Equipment, rows[0].equipment_id)
    other = (db.query(Equipment.equipment_type_id)
             .filter(Equipment.organization_id == org_admin.organization_id,
                     Equipment.equipment_type_id.isnot(None),
                     Equipment.equipment_type_id != eq.equipment_type_id)
             .first())
    if other is None:
        pytest.skip("only one equipment type in scope")
    eq.equipment_type_id = other[0]
    db.flush()
    after = snapshot(db, org_admin)
    assert after["tiles"] == before["tiles"]
    assert sum(after["bd"]["by_type"].values()) == sum(before["bd"]["by_type"].values())
    assert after["bd"]["by_type"] != before["bd"]["by_type"], "a row should have moved"


def test_retiring_equipment_drops_it_everywhere(db, org_admin):
    """Retire one Critical (or any assessed) equipment: its band drops by
    one on the tile, card, table and risk list; total assets by one."""
    slot = risk_slot_mapper(db)
    rows = [ea for ea in scope_ea(db, org_admin) if slot(ea.risk_level)]
    if not rows:
        pytest.skip("no assessed equipment")
    target = next((ea for ea in rows if slot(ea.risk_level) == "Critical"), rows[0])
    band = slot(target.risk_level).lower()
    before = snapshot(db, org_admin)
    db.get(Equipment, target.equipment_id).status = "retired"
    db.flush()
    after = snapshot(db, org_admin)
    assert after["tiles"][band] == before["tiles"][band] - 1
    assert after["k"]["total_equipment"] == before["k"]["total_equipment"] - 1


def test_disabling_worst_band_turns_off_findings_override(db, org_admin):
    """Disabling the Critical band (unlike renaming it) stops anything being
    labelled Critical - findings-only equipment included."""
    band = db.query(EquipmentHealthBandThreshold).filter(
        EquipmentHealthBandThreshold.label == "Critical").first()
    if band is None:
        pytest.skip("no Critical band")
    band.is_active = False
    db.flush()
    rescore(db, scope_ea(db, org_admin))
    snap = snapshot(db, org_admin)
    assert all(ea.risk_level != "Critical" for ea in scope_ea(db, org_admin))
    # The bottom active band (High) now catches everything below it.
    assert snap["tiles"]["critical"] == 0 or snap["tiles"]["critical"] == sum(
        1 for ea in scope_ea(db, org_admin) if risk_slot_mapper(db)(ea.risk_level) == "Critical")


def test_slot_mapper_maps_renamed_bands_by_rank(monkeypatch):
    import services.analytics_engine as E
    monkeypatch.setattr(E, "_load_risk_bands",
                        lambda db: [(80, "Good"), (50, "Fair"), (25, "Poor"), (0, "Severe")])
    slot = E.risk_slot_mapper(None)
    assert [slot(x) for x in ("Severe", "Poor", "Fair", "Good")] == list(RISK_SLOTS)
    assert slot("High") == "High" and slot(None) is None and slot("Nope") is None


def test_settings_save_starts_one_coalesced_rescore(db, monkeypatch):
    """Saving a risk band starts the background rescore; a second save while
    it runs flags one more run instead of starting a parallel job."""
    started = []

    class FakeThread:
        def __init__(self, target, args, **_):
            started.append(args)

        def start(self):
            pass

    monkeypatch.setattr(A.threading, "Thread", FakeThread)
    monkeypatch.setattr(A, "_RECOMPUTE_JOBS", {})
    monkeypatch.setattr(A, "_JOB_STORE_ENABLED", False)  # its own sessions commit
    monkeypatch.setattr(db, "commit", db.flush)  # never commit to the dev DB

    from routers import threshold_config as TC
    band = db.query(EquipmentHealthBandThreshold).first()
    if band is None:
        pytest.skip("risk bands not configured")
    payload = TC.HealthBandUpdate(notes=(band.notes or "") + " ")
    TC.update_health_band(band.id, payload, db=db, current_user=type("U", (), {"id": None})())
    TC.update_health_band(band.id, payload, db=db, current_user=type("U", (), {"id": None})())
    assert len(started) == 1, "second save must not start a parallel job"
    (job,) = A._RECOMPUTE_JOBS.values()
    assert job["org_id"] is None and job["rerun"] is True


# ── Background rescore: never two overlapping jobs, no lost save ────────────

@pytest.fixture()
def fake_jobs(monkeypatch):
    """No real threads; returns the org scope of every job started."""
    started = []

    class FakeThread:
        def __init__(self, target, args, **_):
            started.append(args[1])

        def start(self):
            pass

    monkeypatch.setattr(A.threading, "Thread", FakeThread)
    monkeypatch.setattr(A, "_RECOMPUTE_JOBS", {})
    monkeypatch.setattr(A, "_JOB_STORE_ENABLED", False)
    return started


ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


def test_all_org_save_coalesces_with_running_org_job(fake_jobs):
    """A Threshold Config save (all orgs) while an org's own recompute runs
    widens that job's follow-up run to every org instead of starting a
    second, overlapping all-org job."""
    A.start_recompute_job(ORG_A)
    job = A.start_recompute_job(None)
    assert fake_jobs == [ORG_A], "all-org request must not start a parallel job"
    assert job["org_id"] == ORG_A
    (j,) = A._RECOMPUTE_JOBS.values()
    assert j["rerun"] is True and j["rerun_org_id"] is None


def test_rerun_scope_widens_across_requests(fake_jobs):
    A.start_recompute_job(None)
    A.start_recompute_job(ORG_A)
    (j,) = A._RECOMPUTE_JOBS.values()
    assert j["rerun_org_id"] == ORG_A          # only what was asked
    A.start_recompute_job(ORG_A)
    assert j["rerun_org_id"] == ORG_A
    A.start_recompute_job(ORG_B)               # two orgs -> every org
    assert j["rerun_org_id"] is None and fake_jobs == [None]


def test_different_orgs_may_run_side_by_side(fake_jobs):
    A.start_recompute_job(ORG_A)
    A.start_recompute_job(ORG_B)
    assert fake_jobs == [ORG_A, ORG_B]


def test_finish_and_rerun_check_are_atomic(fake_jobs, monkeypatch):
    """The job stays "running" until the locked finish step, so a save that
    lands at the very end is either coalesced (and rerun) or starts its own
    job - never set on a job that already read its rerun flag."""
    import uuid
    import database

    first = A.start_recompute_job(ORG_A)["job_id"]
    job = A._RECOMPUTE_JOBS[first]
    seen = {}

    class FakeSession:
        def query(self, *a, **k):
            raise RuntimeError("boom")

        def rollback(self):
            pass

        def close(self):
            # A save arriving after the work, before the finish.
            seen["status"] = job["status"]
            A.start_recompute_job(None)

    monkeypatch.setattr(database, "BackgroundSessionLocal", FakeSession)
    A._run_recompute_job(first, uuid.UUID(ORG_A))
    assert seen["status"] == "running", "job left 'running' before the locked finish"
    assert job["status"] == "error" and job["error"] == "boom" and job["finished_at"]
    # The save landed on the running job and was rerun over its scope.
    assert fake_jobs[1:] == [None]


def test_unknown_or_vanished_job_status(fake_jobs, org_admin):
    """After a server restart _RECOMPUTE_JOBS is empty: a status poll for the
    old job id is a clear 404, and "current job" is {}."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        A.get_recompute_job("0" * 32, user=org_admin)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Recompute job not found"
    assert A.get_current_recompute_job(user=org_admin) == {}


# ── Shared job copy: a poll reaching another process (DR, other worker) ─────

def _shared_job(org_id=None, **kw):
    return {"status": "running", "org_id": org_id, "total": 10, "processed": 4,
            "recomputed": 4, "failed": 0, "error": None, "started_at": None,
            "finished_at": None, "rerun": False, "rerun_org_id": None, **kw}


ORG_A_ADMIN = {"id": None, "organization_id": ORG_A, "usertype": None}


def test_poll_falls_back_to_shared_copy(fake_jobs, monkeypatch):
    """A job another process runs is answered from recompute_jobs, not 404."""
    jid = "a" * 32
    monkeypatch.setattr(A, "_db_get_job", lambda j: _shared_job() if j == jid else None)
    monkeypatch.setattr(A, "_db_current_job", lambda mine, any_scope: (jid, _shared_job()))
    assert A.get_recompute_job(jid, user=ORG_A_ADMIN)["processed"] == 4
    assert A.get_current_recompute_job(user=ORG_A_ADMIN)["job_id"] == jid


def test_shared_copy_keeps_org_scope(fake_jobs, monkeypatch):
    """Another organization's job stays invisible, wherever it runs."""
    from fastapi import HTTPException
    monkeypatch.setattr(A, "_db_get_job", lambda j: _shared_job(org_id=ORG_B))
    with pytest.raises(HTTPException) as exc:
        A.get_recompute_job("b" * 32, user=ORG_A_ADMIN)
    assert exc.value.status_code == 404


def test_stale_running_row_reports_interrupted():
    """A process that died mid-job stops its heartbeat: the row reads as an
    error with a reason, so the page stops polling."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(status="running", org_id=None, total=5, processed=2, recomputed=2,
                          failed=0, error=None, started_at=now, finished_at=None,
                          rerun=False, rerun_org_id=None,
                          heartbeat_at=now - timedelta(seconds=A._JOB_STALE_SECONDS + 1))
    job = A._job_from_row(row)
    assert job["status"] == "error" and "interrupted" in job["error"]
    row.heartbeat_at = now
    assert A._job_from_row(row)["status"] == "running"


def test_start_joins_job_running_on_another_process(fake_jobs, monkeypatch):
    """No parallel job when another process already runs an overlapping one."""
    other = "c" * 32
    monkeypatch.setattr(A, "_db_claim_or_insert_job",
                        lambda key, jid, job: (other, _shared_job(rerun=True)))
    assert A.start_recompute_job(ORG_A)["job_id"] == other
    assert fake_jobs == [] and A._RECOMPUTE_JOBS == {}


def test_finish_runs_rerun_flagged_by_another_process(fake_jobs, monkeypatch):
    """A save on another process flags the row; the finishing process reads
    it in its locked finish step and reruns over that scope."""
    import uuid
    import database

    first = A.start_recompute_job(ORG_A)["job_id"]

    class FakeSession:
        def query(self, *a, **k):
            raise RuntimeError("boom")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(database, "BackgroundSessionLocal", FakeSession)
    monkeypatch.setattr(A, "_db_job_finish", lambda jid, job: (True, None))
    A._run_recompute_job(first, uuid.UUID(ORG_A))
    assert fake_jobs[1:] == [None]


# ── Global scoring config: org admin, Threshold Config edit, or super admin ─

def test_global_scoring_config_writes_need_admin_or_edit(db, org_admin):
    import inspect
    from fastapi import HTTPException
    from auth_utils import has_org_admin_role
    from models import User
    from routers import threshold_config as TC
    from routers.car import has_module_permission
    assert TC._require_scoring_admin(org_admin, db) is org_admin
    su = type("U", (), {"id": None, "usertype": "super_admin"})()
    assert TC._require_scoring_admin(su, db) is su
    with pytest.raises(HTTPException) as exc:
        TC._require_scoring_admin({"id": None, "usertype": "user"}, db)
    assert exc.value.status_code == 403
    # Non-admins of the org: allowed exactly when a role gives them edit on
    # the Threshold Config module (the same rule as Recompute All).
    users = [u for u in db.query(User)
             .filter(User.organization_id == org_admin.organization_id,
                     User.usertype.is_(None)).limit(200)
             if not has_org_admin_role(u.id, db)]
    for u in users:
        if has_module_permission(db, u, "threshold_config", "can_edit"):
            assert TC._require_scoring_admin(u, db) is u
        else:
            with pytest.raises(HTTPException):
                TC._require_scoring_admin(u, db)
    # Every write route of the rescoring tables and Table scoring is guarded.
    for fn in (TC.create_health_band, TC.update_health_band, TC.delete_health_band,
               TC.create_condition_score, TC.update_condition_score, TC.delete_condition_score,
               TC.create_status_condition, TC.update_status_condition, TC.delete_status_condition,
               TC.update_health_scoring_config):
        dep = inspect.signature(fn).parameters["current_user"].default
        assert dep.dependency is TC._require_scoring_admin, fn.__name__


def test_threshold_config_edit_grants_scoring_saves(db, org_admin):
    """A non-admin whose role is given edit on Threshold Config passes;
    view alone doesn't (rolled back)."""
    from fastapi import HTTPException
    from auth_utils import has_org_admin_role
    from models import Module, OrgRolePermission, OrgUserRole, User
    from routers import threshold_config as TC
    module = db.query(Module).filter(Module.path == "threshold_config").first()
    if not module:
        pytest.skip("no Threshold Config module")
    pick = next(((u, ur) for u, ur in db.query(User, OrgUserRole)
                 .join(OrgUserRole, OrgUserRole.user_id == User.id)
                 .filter(User.organization_id == org_admin.organization_id,
                         User.usertype.is_(None), OrgUserRole.is_active == True)  # noqa: E712
                 .limit(200)
                 if not has_org_admin_role(u.id, db)), None)
    if not pick:
        pytest.skip("no non-admin user with a role")
    user, ur = pick
    db.query(OrgRolePermission).filter(
        OrgRolePermission.org_role_id == ur.org_role_id,
        OrgRolePermission.module_id == module.id).delete()
    perm = OrgRolePermission(org_role_id=ur.org_role_id, module_id=module.id, can_view=True)
    db.add(perm)
    db.flush()
    with pytest.raises(HTTPException):
        TC._require_scoring_admin(user, db)
    perm.can_edit = True
    db.flush()
    assert TC._require_scoring_admin(user, db) is user


# ── Summary-table row drill lists every asset the row counts ────────────────

_DRILLS = {
    "by_type":          "equipment_type",
    "by_make":          "manufacturer",
    "by_voltage_class": "voltage_class",
    "by_make_model":    "make_model",
    "by_capacity_mva":  "capacity_mva",
}


@pytest.mark.parametrize("ranged", [False, True])
def test_row_drill_count_equals_row_total(db, org_admin, ranged):
    from datetime import date, timedelta
    rng = {"date_from": date.today() - timedelta(days=365), "date_to": date.today()} if ranged else {}
    bd = call(A.get_asset_breakdown, db=db, user=org_admin, **rng)
    checked = 0
    for view, param in _DRILLS.items():
        rows: dict = {}
        for key, n in bd[view].items():
            drill_key = "unknown" if A._is_placeholder_group(key) else key
            rows[drill_key] = rows.get(drill_key, 0) + n   # one "Not Specified" row
        for drill_key, total in rows.items():
            listed = call(A.get_dashboard_equipment, db=db, user=org_admin, page_size=1,
                          tested_only=False, **{param: drill_key}, **rng)["total"]
            assert listed == total, f"{view} row {drill_key!r}: drill {listed} != total {total}"
            checked += 1
    assert checked
