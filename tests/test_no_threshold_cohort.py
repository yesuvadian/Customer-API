# Copyright (c) 2026 ReLU Technologies Private Limited. All rights reserved.
"""
Checks that (1) the no-threshold test template carries no threshold/evaluation
config, and (2) the 5 seeded equipment appear as one fleet cohort in the
Equipment Failure Performance Analysis report.

Needs a DB seeded via `python seed_no_threshold_cohort.py` and
`python run_report_query_keys_reseed.py`. Skips if the DB is unreachable.
Run from Customer-API/:  pytest tests/test_no_threshold_cohort.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from database import VendorSessionLocal
    from models import Equipment, OrgTestTemplate
    from seed_no_threshold_cohort import (
        COHORT_MAKE, EQUIPMENT_COUNT, TEMPLATE_KEY, UEIC_PREFIX,
    )
    from services.reporting_service import ReportingService
    from sqlalchemy import text
    with VendorSessionLocal() as _s:
        _s.execute(text("select 1"))
except Exception as exc:  # pragma: no cover
    pytest.skip(f"DB not available: {exc}", allow_module_level=True)


@pytest.fixture()
def db():
    with VendorSessionLocal() as s:
        yield s


def _walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_template_has_no_threshold(db):
    tpl = db.query(OrgTestTemplate).filter_by(template_key=TEMPLATE_KEY).first()
    assert tpl is not None, "run seed_no_threshold_cohort.py first"
    keys = {k for k, _ in _walk(tpl.template_data)}
    forbidden = {"evaluation", "table_evaluation", "dropdown_evaluation",
                 "date_evaluation", "thresholds", "threshold_value"}
    assert not (keys & forbidden)


def test_five_equipment_exist(db):
    assert db.query(Equipment).filter(Equipment.ueic.like(f"{UEIC_PREFIX}%")).count() == EQUIPMENT_COUNT


def test_all_five_equipment_have_failed_test(db):
    from models import TestingRequest, TestResult
    rows = (
        db.query(Equipment.ueic, TestResult.pass_fail, TestResult.evaluation_result)
        .join(TestingRequest, TestingRequest.equipment_id == Equipment.id)
        .join(TestResult, TestResult.testing_request_id == TestingRequest.id)
        .filter(Equipment.ueic.like(f"{UEIC_PREFIX}%"), TestResult.template_key == TEMPLATE_KEY)
        .all()
    )
    assert {r[0] for r in rows} == {
        e.ueic for e in db.query(Equipment).filter(Equipment.ueic.like(f"{UEIC_PREFIX}%"))
    }
    assert all(r[1] == "FAIL" for r in rows)


def test_five_equipment_shown_in_cohort(db):
    org_id = db.query(Equipment.organization_id).filter(
        Equipment.ueic.like(f"{UEIC_PREFIX}%")).first()[0]
    rows = ReportingService(db, org_id)._run_query(
        "equipment_failure_performance_report",
        {"make": COHORT_MAKE},
    )
    cohort = [r for r in rows if r["make"] == COHORT_MAKE]
    assert cohort, "cohort missing from report"
    assert sum(int(r["unit_count"]) for r in cohort) == EQUIPMENT_COUNT
