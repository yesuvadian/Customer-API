"""
GET /testing/{id}/threshold-status (routers/testing.py) under the
"no thresholds -> the tester's verdict decides" rule, the seeded
no-threshold result, and the range / duplicate checks on health bands and
condition scores (routers/threshold_config.py).

DB-backed where needed, like the rest of this folder: every session is rolled
back, and a test skips when the data it needs isn't there.

    python -m pytest tests/test_threshold_status_and_bands.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import VendorSessionLocal  # noqa: E402
from models import (  # noqa: E402
    EquipmentHealthBandThreshold, RequestCategory, TestingRequest, TestResult, User,
)
from routers import testing as T  # noqa: E402
from routers import threshold_config as C  # noqa: E402
from services.evaluation_service import (  # noqa: E402
    CRITICAL, NO_THRESHOLD_VALUES, EvaluationService,
)


@pytest.fixture()
def db():
    s = VendorSessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


# ── threshold-status ────────────────────────────────────────────────────────

@pytest.fixture()
def test_request_with_result(db):
    row = (
        db.query(TestingRequest, TestResult.template_key)
        .join(TestResult, TestResult.testing_request_id == TestingRequest.id)
        .filter(TestingRequest.request_category == RequestCategory.test,
                TestResult.template_key != None)  # noqa: E711
        .first()
    )
    if not row:
        pytest.skip("no equipment test request with a result")
    return row


def test_threshold_status_answers(db, test_request_with_result):
    """Was a 500: it passed the request, not the template, to
    requires_thresholds."""
    req, key = test_request_with_result
    user = db.query(User).filter(User.organization_id == req.organization_id).first()
    body = T.get_threshold_status(request_id=req.id, template_key=key,
                                  db=db, current_user=user)
    tpl = EvaluationService.get_template_data(key, db, org_id=req.organization_id) or {}
    requires = EvaluationService.requires_thresholds(tpl, True)
    has = EvaluationService.has_threshold_values(tpl)
    assert body == {
        "requires_thresholds": requires,
        "has_threshold_values": has,
        "verdict_decides": requires and not has,
    }


def test_threshold_status_other_org_is_404(db, test_request_with_result):
    req, key = test_request_with_result
    other = db.query(User).filter(User.organization_id != None,  # noqa: E711
                                  User.organization_id != req.organization_id).first()
    if not other:
        pytest.skip("no user in another organization")
    with pytest.raises(HTTPException) as e:
        T.get_threshold_status(request_id=req.id, template_key=key,
                               db=db, current_user=other)
    assert e.value.status_code == 404


# ── Seeded no-threshold result ──────────────────────────────────────────────

def test_seed_builds_the_evaluated_result():
    """seed_no_threshold_cohort.py stores what submit's evaluation returns
    for its Fail results on a no-threshold equipment test (it called a
    removed helper)."""
    import seed_no_threshold_cohort  # noqa: F401 (imports cleanly)
    tpl = {"template_type": "test", "fields": [{"key": "x", "type": "text"}]}
    data = {"x": "ok", "overall_result": "Fail"}
    evaluated = EvaluationService.evaluate_test_data(tpl, data, is_equipment_test=True)
    seeded = EvaluationService._no_threshold_verdict_result(data)
    assert seeded["overall"] == evaluated["overall"] == CRITICAL
    assert seeded["unassessed_reason"] == NO_THRESHOLD_VALUES
    assert seeded.get("no_threshold_values") and evaluated.get("no_threshold_values")


# ── Health band / condition score ranges ────────────────────────────────────

@pytest.mark.parametrize("v", [-0.01, 100.01, 150])
def test_band_threshold_out_of_range_refused(v):
    with pytest.raises(ValidationError):
        C.HealthBandCreate(label="x", threshold=v)
    with pytest.raises(ValidationError):
        C.HealthBandUpdate(threshold=v)


@pytest.mark.parametrize("v", [0, 25, 100])
def test_band_threshold_in_range_ok(v):
    assert C.HealthBandCreate(label="x", threshold=v).threshold == v
    assert C.HealthBandUpdate(threshold=v).threshold == v


def test_band_update_without_threshold_ok():
    assert C.HealthBandUpdate(notes="n").threshold is None


@pytest.mark.parametrize("v", [-100.01, 100.01, 150])
def test_condition_score_out_of_range_refused(v):
    with pytest.raises(ValidationError):
        C.ConditionScoreCreate(condition="x", score=v)
    with pytest.raises(ValidationError):
        C.ConditionScoreUpdate(score=v)


@pytest.mark.parametrize("v", [-100, 0, 50, 100])
def test_condition_score_in_range_ok(v):
    assert C.ConditionScoreCreate(condition="x", score=v).score == v


# ── Duplicate band thresholds ───────────────────────────────────────────────

@pytest.fixture()
def active_band(db):
    band = (db.query(EquipmentHealthBandThreshold)
            .filter(EquipmentHealthBandThreshold.is_active == True).first())  # noqa: E712
    if not band:
        pytest.skip("no active health band")
    return band


def test_duplicate_active_threshold_refused(db, active_band):
    with pytest.raises(HTTPException) as e:
        C._reject_duplicate_band_threshold(db, active_band.threshold)
    assert e.value.status_code == 409
    # ... but not against itself (an update that keeps its threshold)
    C._reject_duplicate_band_threshold(db, active_band.threshold, exclude_id=active_band.id)


def test_free_threshold_ok(db):
    used = {float(t) for (t,) in db.query(EquipmentHealthBandThreshold.threshold)}
    free = next(v for v in (0.37, 1.23, 99.99) if v not in used)
    C._reject_duplicate_band_threshold(db, free)
