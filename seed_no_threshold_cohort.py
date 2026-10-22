# Copyright (c) 2026 ReLU Technologies Private Limited. All rights reserved.
"""
seed_no_threshold_cohort.py
-----------------------------------------------------------------------------
Creates 5 equipment that form ONE fleet cohort (same type / make / voltage
class / age band) plus a test type + template whose fields define NO
threshold (no `evaluation` block), so results can never go ALERT/CRITICAL.

The cohort is what the "Equipment Failure Performance Analysis" report
(query_key=equipment_failure_performance_report) aggregates on, so after
seeding it must return a row with unit_count >= 5 for this make.

Usage:
    python seed_no_threshold_cohort.py            # insert
    python seed_no_threshold_cohort.py --cleanup  # remove
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone

from database import VendorSessionLocal
from services.analytics_engine import AnalyticsEngine
from services.evaluation_service import EvaluationService
from models import (
    CategoryDetails,
    CategoryMaster,
    Equipment,
    EquipmentStatus,
    OrgDepartment,
    Organization,
    OrgTestTemplate,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    User,
)

ORG_NAME = "KPTCL"
UEIC_PREFIX = "NOTH-TEST-"
REQ_PREFIX = "NOTH-REQ-"
COHORT_MAKE = "NoThreshold Cohort Make"
COHORT_VOLTAGE = "33kV"
COHORT_YEAR = 2018
EQUIPMENT_COUNT = 10
TEST_TYPE_NAME = "No Threshold Test"
TEMPLATE_KEY = "no_threshold_test"

# Plain numeric fields: deliberately no "evaluation" key anywhere.
TEMPLATE_DATA = {
    "key": TEMPLATE_KEY,
    "name": TEST_TYPE_NAME,
    "description": "Test with no threshold values; results are never evaluated.",
    "supports_multi_session": False,
    "sections": [
        {
            "title": "Measurements",
            "fields": [
                {"key": "reading_1", "label": "Reading 1", "type": "number", "unit": "A"},
                {"key": "reading_2", "label": "Reading 2", "type": "number", "unit": "V"},
                {"key": "overall_result", "label": "Overall Result", "type": "dropdown",
                 "options": ["Pass", "Fail"]},
                {"key": "remarks", "label": "Remarks", "type": "textarea"},
            ],
        }
    ],
}


def _lookup(db):
    org = (
        db.query(Organization)
        .filter(Organization.display_name.ilike(f"%{ORG_NAME}%"), Organization.is_active == True)
        .first()
    )
    if not org:
        raise RuntimeError(f"Organisation matching '{ORG_NAME}' not found.")
    eq_type = (
        db.query(CategoryMaster)
        .filter(CategoryMaster.name.ilike("%transformer%"), CategoryMaster.is_active == True)
        .first()
        or db.query(CategoryMaster).filter(CategoryMaster.is_active == True).first()
    )
    if not eq_type:
        raise RuntimeError("No active CategoryMaster rows; seed categories first.")
    dept = (
        db.query(OrgDepartment)
        .filter(OrgDepartment.organization_id == org.id, OrgDepartment.is_active == True)
        .first()
    )
    if not dept:
        raise RuntimeError("No department for org (department_id is NOT NULL).")
    return org, eq_type, dept


def seed(db):
    org, eq_type, dept = _lookup(db)
    print(f"  org={org.display_name}  type={eq_type.name}  dept={dept.name}")

    # Equipment: create only the missing ones (safe to re-run).
    have = {e.ueic for e in db.query(Equipment).filter(Equipment.ueic.like(f"{UEIC_PREFIX}%"))}
    for i in range(1, EQUIPMENT_COUNT + 1):
        ueic = f"{UEIC_PREFIX}{i:03d}"
        if ueic in have:
            continue
        db.add(Equipment(
            id=uuid.uuid4(),
            ueic=ueic,
            organization_id=org.id,
            equipment_type_id=eq_type.id,
            department_id=dept.id,
            voltage_class=COHORT_VOLTAGE,
            status=EquipmentStatus.active,
            manufacturer=COHORT_MAKE,
            year_of_manufacture=COHORT_YEAR,
            model_number="NOTH-MODEL",
        ))
    db.flush()
    print(f"[OK] Equipment ready ({EQUIPMENT_COUNT - len(have)} new, {len(have)} existing)")

    td = (
        db.query(CategoryDetails)
        .filter(CategoryDetails.name == TEST_TYPE_NAME,
                CategoryDetails.category_master_id == eq_type.id)
        .first()
    )
    if not td:
        td = CategoryDetails(name=TEST_TYPE_NAME, category_master_id=eq_type.id,
                             category_type="test", is_active=True,
                             description="Test type with no threshold values")
        db.add(td)
        db.flush()
    tpl = db.query(OrgTestTemplate).filter_by(org_id=org.id, template_key=TEMPLATE_KEY).first()
    if not tpl:
        db.add(OrgTestTemplate(org_id=org.id, template_key=TEMPLATE_KEY,
                               test_type_id=td.id, template_data=TEMPLATE_DATA,
                               is_system=False))
    else:
        tpl.template_data = TEMPLATE_DATA
    print(f"[OK] Test type '{TEST_TYPE_NAME}' (id={td.id}) + template '{TEMPLATE_KEY}' ready")

    originator = db.query(User).filter(User.organization_id == org.id).first()
    if not originator:
        raise RuntimeError("No user found in org to originate testing requests.")

    # One completed testing request + one FAILED test result per equipment.
    made = 0
    for eq in db.query(Equipment).filter(Equipment.ueic.like(f"{UEIC_PREFIX}%")).order_by(Equipment.ueic):
        req_no = eq.ueic.replace(UEIC_PREFIX, REQ_PREFIX)
        if db.query(TestingRequest).filter_by(request_number=req_no).first():
            continue
        now = datetime.now(timezone.utc)
        test_data = {"reading_1": 0, "reading_2": 0, "result": "Fail",
                     "overall_result": "Fail", "remarks": "Seeded failed result"}
        req = TestingRequest(
            id=uuid.uuid4(),
            request_number=req_no,
            title=f"[TEST] {TEST_TYPE_NAME} -- {eq.ueic}",
            organization_id=org.id,
            equipment_id=eq.id,
            equipment_type_id=eq.equipment_type_id,
            test_type_id=td.id,
            department_id=eq.department_id,
            request_category=RequestCategory.test,
            status=TestingRequestStatus.completed,
            priority="normal",
            originator_id=originator.id,
            requested_date=now - timedelta(days=7),
            completed_at=now,
        )
        db.add(req)
        db.flush()
        db.add(TestResult(
            id=uuid.uuid4(),
            testing_request_id=req.id,
            organization_id=org.id,
            test_name=TEST_TYPE_NAME,
            test_category="test",
            pass_fail="FAIL",
            remarks="Seeded failed result (no threshold defined).",
            test_data=test_data,
            overall_result="FAIL",
            template_key=TEMPLATE_KEY,
            # Same result the app builds for a template with no thresholds:
            # tester's Fail verdict -> overall CRITICAL.
            evaluation_result=EvaluationService._no_threshold_result(test_data),
            tested_by=originator.id,
            tested_at=now,
        ))
        made += 1
    db.commit()
    print(f"[OK] Created {made} failed test results")

    # Populate EquipmentAnalytics (what the Critical Equipment list reads).
    engine = AnalyticsEngine(db)
    for (rid,) in (
        db.query(TestResult.id)
        .filter(TestResult.template_key == TEMPLATE_KEY)
        .all()
    ):
        engine.run_for_test(rid)
    db.commit()
    print("[OK] Ran analytics for the failed results")


def cleanup(db):
    eq_ids = [e.id for e in db.query(Equipment.id).filter(Equipment.ueic.like(f"{UEIC_PREFIX}%"))]
    req_ids = [r.id for r in db.query(TestingRequest.id).filter(
        TestingRequest.request_number.like(f"{REQ_PREFIX}%"))]
    if req_ids:
        db.query(TestResult).filter(TestResult.testing_request_id.in_(req_ids)).delete(synchronize_session=False)
        db.query(TestingRequest).filter(TestingRequest.id.in_(req_ids)).delete(synchronize_session=False)
    n = db.query(Equipment).filter(Equipment.id.in_(eq_ids)).delete(synchronize_session=False) if eq_ids else 0
    db.query(OrgTestTemplate).filter_by(template_key=TEMPLATE_KEY).delete(synchronize_session=False)
    db.query(CategoryDetails).filter_by(name=TEST_TYPE_NAME).delete(synchronize_session=False)
    db.commit()
    print(f"[OK] Removed {n} equipment, {len(req_ids)} requests/results, template and test type")


if __name__ == "__main__":
    db = VendorSessionLocal()
    try:
        cleanup(db) if "--cleanup" in sys.argv else seed(db)
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        raise
    finally:
        db.close()
