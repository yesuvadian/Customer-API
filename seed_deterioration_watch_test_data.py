"""
seed_deterioration_watch_test_data.py
-----------------------------------------------------------------------------
Seeds ONE isolated equipment (prefix DWL-TEST-) with two ParameterAnalytics
rows so the Deterioration Watch List (routers/analytics.py's
get_deterioration_watch_list) has something real to show — including the
recently-added "owner" and "reason" fields (TSMS-236).

Everything created here is new and self-contained (a dedicated department,
equipment, testing request, test result, and two ParameterAnalytics rows) —
no existing department/equipment/user row is modified. The department gets
its own manager_id pointing at an EXISTING user (referenced, not changed),
purely so the "owner" field has something to resolve — no real department's
manager assignment is touched. `python seed_deterioration_watch_test_data.py
--cleanup` removes everything this script created.

What it creates
----------------
1 OrgDepartment  "Deterioration Watch Test Dept" (code DWL-TEST), manager_id
                 set to an existing active user in the target org.
1 Equipment      DWL-TEST-01, voltage_class="220" (resolves to the oil-test
                 template's ">170kV" context band).
1 TestingRequest + 1 TestResult (template_key=transformer_oil_test), tested_at
                 5 days ago — the real-test-date anchor _real_breach_forecast
                 uses for breach_predicted_at/days_to_breach.
2 ParameterAnalytics rows, both status=NORMAL (not yet breached) so they
  surface as "trending toward a breach", not an active alert:
  - Acidity              current=0.085, Increasing  -> breach @ 0.10 (Fair)
    (increasing = bad; ~60 days out from the test date)
  - Interfacial Tension   current=27,    Decreasing  -> breach @ 25 (Fair)
    (decreasing = bad — the exact direction the docstring in
    routers/analytics.py's _real_breach_forecast calls out as the bug this
    feature fixed; ~90 days out from the test date)

Usage:
    python seed_deterioration_watch_test_data.py            # insert
    python seed_deterioration_watch_test_data.py --info      # show lookups only, no writes
    python seed_deterioration_watch_test_data.py --cleanup   # remove everything this script created
"""

import sys
import uuid
from datetime import datetime, timezone, timedelta

from database import VendorSessionLocal
from models import (
    Equipment,
    EquipmentStatus,
    OrgDepartment,
    Organization,
    ParameterAnalytics,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    User,
)

DEPT_CODE = "DWL-TEST"
EQUIPMENT_UEIC = "DWL-TEST-01"
REQUEST_NUMBER = "DWL-TEST-REQ-01"
ORG_NAME_HINT = "KPTCL"  # set to a substring (e.g. "KPTCL") to target a specific org; None = first active org with a department


def _get_org_and_seed_user(db):
    """Picks the org via whichever department already exists (any org with
    real departments works for this test), and an active user in that org to
    reference as the test department's manager."""
    dept_q = db.query(OrgDepartment)
    if ORG_NAME_HINT:
        dept_q = dept_q.join(Organization, Organization.id == OrgDepartment.organization_id).filter(
            Organization.display_name.ilike(f"%{ORG_NAME_HINT}%")
        )
    existing_dept = dept_q.first()
    if not existing_dept:
        raise RuntimeError("No existing OrgDepartment found to infer a target organization from.")
    org = db.query(Organization).filter(Organization.id == existing_dept.organization_id).first()
    if not org:
        raise RuntimeError(f"Organization {existing_dept.organization_id} not found.")

    manager = (
        db.query(User)
        .filter(User.organization_id == org.id, User.isactive == True)  # noqa: E712
        .first()
    )
    if not manager:
        raise RuntimeError(f"No active user found in org {org.display_name} to use as test department manager.")

    print(f"  org     : {org.display_name}  (id={org.id})")
    print(f"  manager : {manager.firstname or ''} {manager.lastname or ''} <{manager.email}>  (id={manager.id})")
    return org, manager


def _get_equipment_type(db):
    from models import CategoryMaster
    row = db.query(CategoryMaster).filter(CategoryMaster.name.ilike("%Power Transformer%")).first()
    if not row:
        raise RuntimeError("CategoryMaster 'Power Transformer' not found — ensure equipment types are seeded.")
    return row


def seed(db):
    org, manager = _get_org_and_seed_user(db)
    equipment_type = _get_equipment_type(db)

    dept = db.query(OrgDepartment).filter(OrgDepartment.code == DEPT_CODE).first()
    if not dept:
        dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Deterioration Watch Test Dept",
            code=DEPT_CODE,
            manager_id=manager.id,
            is_active=True,
        )
        db.add(dept)
        db.flush()
    print(f"  dept    : {dept.name}  (id={dept.id})")

    equipment = db.query(Equipment).filter(Equipment.ueic == EQUIPMENT_UEIC).first()
    if not equipment:
        equipment = Equipment(
            id=uuid.uuid4(),
            ueic=EQUIPMENT_UEIC,
            organization_id=org.id,
            department_id=dept.id,
            equipment_type_id=equipment_type.id,
            voltage_class="220",
            status=EquipmentStatus.active,
            manufacturer="Seed Data",
            commissioned_date=datetime.now(timezone.utc) - timedelta(days=365 * 5),
            created_by=manager.id,
        )
        db.add(equipment)
        db.flush()
    print(f"  equip   : {equipment.ueic}  (id={equipment.id})")

    testing_request = db.query(TestingRequest).filter(TestingRequest.request_number == REQUEST_NUMBER).first()
    if not testing_request:
        testing_request = TestingRequest(
            id=uuid.uuid4(),
            request_number=REQUEST_NUMBER,
            title="Deterioration Watch List seed — transformer oil test",
            equipment_id=equipment.id,
            equipment_type_id=equipment_type.id,
            organization_id=org.id,
            department_id=dept.id,
            request_category=RequestCategory.test,
            status=TestingRequestStatus.completed,
            originator_id=manager.id,
        )
        db.add(testing_request)
        db.flush()
    print(f"  request : {testing_request.request_number}  (id={testing_request.id})")

    tested_at = datetime.now(timezone.utc) - timedelta(days=5)
    test_result = (
        db.query(TestResult)
        .filter(TestResult.testing_request_id == testing_request.id, TestResult.template_key == "transformer_oil_test")
        .first()
    )
    if not test_result:
        test_result = TestResult(
            id=uuid.uuid4(),
            testing_request_id=testing_request.id,
            organization_id=org.id,
            test_name="Transformer Oil Test",
            template_key="transformer_oil_test",
            overall_result="NORMAL",
            tested_at=tested_at,
            tested_by=manager.id,
        )
        db.add(test_result)
        db.flush()
    print(f"  result  : {test_result.id}  tested_at={test_result.tested_at}")

    # (parameter_key, label, unit, current_value, trend, slope_per_day, r_sq, history_count)
    param_rows = [
        ("oil_test_results.Acidity.measured_value", "Acidity", "mg KOH/g",
         0.085, "Increasing", 0.00025, 0.87, 6),
        ("oil_test_results.Interfacial Tension.measured_value", "Interfacial Tension", "mN/m",
         27.0, "Decreasing", -0.0222, 0.81, 6),
    ]
    for parameter_key, label, unit, current_value, trend, slope, r_sq, history_count in param_rows:
        existing = (
            db.query(ParameterAnalytics)
            .filter(ParameterAnalytics.test_result_id == test_result.id, ParameterAnalytics.parameter_key == parameter_key)
            .first()
        )
        if existing:
            pa = existing
        else:
            pa = ParameterAnalytics(id=uuid.uuid4(), test_result_id=test_result.id, parameter_key=parameter_key)
            db.add(pa)
        pa.organization_id = org.id
        pa.equipment_id = equipment.id
        pa.template_key = "transformer_oil_test"
        pa.parameter_label = label
        pa.parameter_type = "table"
        pa.unit = unit
        pa.current_value = current_value
        pa.condition = "Good"
        pa.status = "NORMAL"
        pa.trend = trend
        pa.trend_slope = slope
        pa.trend_r_squared = r_sq
        pa.history_count = history_count
        print(f"  param   : {label} = {current_value} {trend} (slope={slope}/day, r2={r_sq})")

    db.commit()
    print("\nDone. Log in and check the Deterioration Watch List / Overview Dashboard "
          f"for department '{dept.name}' — equipment {equipment.ueic} should show 2 flagged "
          "parameters, with an Owner and Reason on each.")


def cleanup(db):
    test_result_ids = [
        r.id for r in db.query(TestResult.id)
        .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
        .filter(TestingRequest.request_number == REQUEST_NUMBER)
        .all()
    ]
    n_pa = db.query(ParameterAnalytics).filter(ParameterAnalytics.test_result_id.in_(test_result_ids)).delete(synchronize_session=False) if test_result_ids else 0
    n_tr = db.query(TestResult).filter(TestResult.id.in_(test_result_ids)).delete(synchronize_session=False) if test_result_ids else 0
    n_req = db.query(TestingRequest).filter(TestingRequest.request_number == REQUEST_NUMBER).delete(synchronize_session=False)
    n_eq = db.query(Equipment).filter(Equipment.ueic == EQUIPMENT_UEIC).delete(synchronize_session=False)
    n_dept = db.query(OrgDepartment).filter(OrgDepartment.code == DEPT_CODE).delete(synchronize_session=False)
    db.commit()
    print(f"Removed: {n_pa} ParameterAnalytics, {n_tr} TestResult, {n_req} TestingRequest, "
          f"{n_eq} Equipment, {n_dept} OrgDepartment.")


if __name__ == "__main__":
    db = VendorSessionLocal()
    try:
        if "--cleanup" in sys.argv:
            cleanup(db)
        elif "--info" in sys.argv:
            _get_org_and_seed_user(db)
        else:
            seed(db)
    finally:
        db.close()
