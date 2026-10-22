"""
risk_by_finding on the equipment recommendations response
(services/condition_recommendation_service.evaluate_for_equipment), which
the app's recommendations popup shows as "Critical — by finding".

DB-backed like the rest of this folder: read only, the session is rolled
back, and a test skips when the data it needs isn't there.

    python -m pytest tests/test_recommendations_risk_by_finding.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import VendorSessionLocal  # noqa: E402
from models import EquipmentAnalytics  # noqa: E402
from services.analytics_engine import risk_by_finding_checker  # noqa: E402
from services.condition_recommendation_service import evaluate_for_equipment  # noqa: E402


@pytest.fixture()
def db():
    s = VendorSessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_matches_the_dashboards_rule(db):
    check = risk_by_finding_checker(db)
    rows = (db.query(EquipmentAnalytics)
            .filter(EquipmentAnalytics.health_score != None)  # noqa: E711
            .all())
    by_finding = [r for r in rows if check(r.health_score, r.risk_level)]
    by_score = [r for r in rows if not check(r.health_score, r.risk_level)]
    if not by_finding or not by_score:
        pytest.skip("need assets both with and without a by-finding risk")
    assert evaluate_for_equipment(db, by_finding[0].equipment_id)["risk_by_finding"] is True
    assert evaluate_for_equipment(db, by_score[0].equipment_id)["risk_by_finding"] is False


def test_unscored_equipment_is_false(db):
    ea = (db.query(EquipmentAnalytics)
          .filter(EquipmentAnalytics.health_score == None)  # noqa: E711
          .first())
    if not ea:
        pytest.skip("no unscored equipment analytics")
    assert evaluate_for_equipment(db, ea.equipment_id)["risk_by_finding"] is False
