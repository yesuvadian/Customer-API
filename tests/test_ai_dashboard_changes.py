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

from models import Equipment, EquipmentAnalytics, EquipmentHealthBandThreshold
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
    retired = {e for (e,) in db.query(Equipment.id).filter(Equipment.status == "retired")}
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
