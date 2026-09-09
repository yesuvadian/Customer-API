"""
seed_areva_p443_calibration_test_data.py
-----------------------------------------------------------------------------
Seeds 5 new Protection Relay equipment (manufacturer "Areva", model "P443")
at Devanahalli (400kV Devanahalli Hardware Park), each with one PASSED
calibration cycle recorded at validity_months=18 — a brand-new cohort for
the Calibration Interval Advisories panel (routers/dashboard_kpi.py's
export_calibration_interval_advisories / services/calibration_service.py's
compute_interval_advisories), distinct from the existing ABB REF615 and
Siemens 7SJ82 cohorts already at this department.

Expected advisory once seeded: 5 cycles, 0 fails (0.0%) -> direction=extend
-> current_validity=18 (the only value recorded) -> suggested =
18 + CALIBRATION_INTERVAL_EXTEND_MONTHS(6) = 24, capped at
CALIBRATION_INTERVAL_MAX_MONTHS(60) -> unaffected. Displayed as "18 -> 24mo".

Follows the same real-data conventions already in this department (UEIC
pattern "BN-DEVA-<bay>-400-RL-<Manufacturer>-<Model>", test_type_id=102
"Protection Relay Calibration and History", is_calibration=True,
request_category=maintenance) rather than a separate isolated test
department, since the whole point is for this to show up in the SAME
Calibration Interval Advisories panel the real Devanahalli data already
populates.

Usage:
    python seed_areva_p443_calibration_test_data.py            # insert
    python seed_areva_p443_calibration_test_data.py --cleanup   # remove everything this script created
"""

import sys
import uuid
from datetime import datetime, timezone, timedelta

from database import VendorSessionLocal
from models import (
    Equipment,
    EquipmentStatus,
    RequestCategory,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    User,
)

ORG_ID = uuid.UUID("f58a4b2c-c3c2-4ab7-9fde-a82506ae8992")   # KPTCL
DEPT_ID = uuid.UUID("a85a7d75-6909-4ea2-bd8b-a641fc119313")  # 400kV Devanahalli Hardware Park
EQUIPMENT_TYPE_ID = 14   # Protection Relay (CategoryMaster)
TEST_TYPE_ID = 102       # Protection Relay Calibration and History (CategoryDetails)
MANUFACTURER = "Areva"
MODEL_NUMBER = "P443"
VALIDITY_MONTHS = 18
BAYS = ["06", "07", "08", "09", "10"]
REQUEST_PREFIX = "TR-KP-2026-00"   # continues the real request_number sequence already in use
STARTING_SEQ = 44                  # first free number (0041-0043 already taken by other real requests)


def seed(db):
    user = db.query(User).filter(User.id == uuid.UUID("f57c21cd-290b-4f62-9f0e-90101904f487")).first()
    if not user:
        raise RuntimeError("Expected AE_JE Devanahalli user (ae.devanahallihp400@kptcl.org) not found.")

    tested_at = datetime.now(timezone.utc) - timedelta(days=1)
    for i, bay in enumerate(BAYS):
        ueic = f"BN-DEVA-{bay}-400-RL-{MANUFACTURER}-{MODEL_NUMBER}"
        equipment = db.query(Equipment).filter(Equipment.ueic == ueic).first()
        if not equipment:
            equipment = Equipment(
                id=uuid.uuid4(),
                ueic=ueic,
                organization_id=ORG_ID,
                department_id=DEPT_ID,
                equipment_type_id=EQUIPMENT_TYPE_ID,
                voltage_class="400",
                manufacturer=MANUFACTURER,
                model_number=MODEL_NUMBER,
                status=EquipmentStatus.active,
                commissioned_date=datetime.now(timezone.utc) - timedelta(days=365 * 3),
                created_by=user.id,
            )
            db.add(equipment)
            db.flush()
        print(f"  equip   : {equipment.ueic}  (id={equipment.id})")

        request_number = f"{REQUEST_PREFIX}{STARTING_SEQ + i}"
        testing_request = db.query(TestingRequest).filter(TestingRequest.request_number == request_number).first()
        if not testing_request:
            testing_request = TestingRequest(
                id=uuid.uuid4(),
                request_number=request_number,
                title=f"Protection relay calibration — {ueic}",
                equipment_id=equipment.id,
                equipment_type_id=EQUIPMENT_TYPE_ID,
                test_type_id=TEST_TYPE_ID,
                organization_id=ORG_ID,
                department_id=DEPT_ID,
                request_category=RequestCategory.maintenance,
                status=TestingRequestStatus.closed,
                originator_id=user.id,
                is_calibration=True,
            )
            db.add(testing_request)
            db.flush()
        print(f"  request : {testing_request.request_number}  (id={testing_request.id})")

        test_result = (
            db.query(TestResult)
            .filter(TestResult.testing_request_id == testing_request.id)
            .first()
        )
        if not test_result:
            test_result = TestResult(
                id=uuid.uuid4(),
                testing_request_id=testing_request.id,
                organization_id=ORG_ID,
                test_name="Protection Relay Calibration and History",
                template_key="protection_relay_calibration",
                overall_result="pass",
                test_data={"validity_months": str(VALIDITY_MONTHS), "overall_result": "pass"},
                tested_at=tested_at,
                tested_by=user.id,
            )
            db.add(test_result)
        print(f"  result  : validity_months={VALIDITY_MONTHS}, overall_result=pass")

    db.commit()
    print("\nDone. Expect a new 'Protection Relay Calibration and History — Areva P443' advisory "
          "reading '18 -> 24mo' (extend) once refreshed.")


def cleanup(db):
    ueics = [f"BN-DEVA-{bay}-400-RL-{MANUFACTURER}-{MODEL_NUMBER}" for bay in BAYS]
    request_numbers = [f"{REQUEST_PREFIX}{STARTING_SEQ + i}" for i in range(len(BAYS))]

    trs = db.query(TestingRequest).filter(TestingRequest.request_number.in_(request_numbers)).all()
    tr_ids = [tr.id for tr in trs]
    n_res = db.query(TestResult).filter(TestResult.testing_request_id.in_(tr_ids)).delete(synchronize_session=False) if tr_ids else 0
    n_req = db.query(TestingRequest).filter(TestingRequest.request_number.in_(request_numbers)).delete(synchronize_session=False)
    n_eq = db.query(Equipment).filter(Equipment.ueic.in_(ueics)).delete(synchronize_session=False)
    db.commit()
    print(f"Removed: {n_res} TestResult, {n_req} TestingRequest, {n_eq} Equipment.")


if __name__ == "__main__":
    db = VendorSessionLocal()
    try:
        if "--cleanup" in sys.argv:
            cleanup(db)
        else:
            seed(db)
    finally:
        db.close()
