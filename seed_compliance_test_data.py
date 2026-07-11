"""
seed_compliance_test_data.py
-----------------------------------------------------------------------------
Inserts controlled test data for validating CM Schedules and PM Schedules
dashboard behaviour -- status thresholds, Overdue filter, View By grouping,
and end_date expiry filtering.

Standalone usage:
    python seed_compliance_test_data.py            # insert test data
    python seed_compliance_test_data.py --cleanup  # remove test data
    python seed_compliance_test_data.py --info     # show DB lookup results only

What it creates
---------------
10 equipment rows (UEIC prefix: CM-TEST- and PM-TEST-)
17 TestRequestSchedule rows covering every status combination

CM Schedules (request_category = 'test') -- 6 equipment
  CM-TEST-001  Single test type, overdue by 10 days          -> OVERDUE
  CM-TEST-002  Three test types, mix of statuses             -> OVERDUE overall
  CM-TEST-003  All test types well in the future             -> OK
  CM-TEST-004  Due within 30-day window (20 days)            -> DUE  (amber)
  CM-TEST-005  Due within 15-day imminent window (7 days)    -> ALERT (orange)
  CM-TEST-006  Overdue 20 days, different dept               -> OVERDUE

PM Schedules (request_category = 'maintenance') -- 4 equipment
  PM-TEST-001  Single schedule, overdue by 5 days            -> OVERDUE
  PM-TEST-002  Two schedules: one overdue, one OK            -> OVERDUE overall
  PM-TEST-003  All OK                                        -> OK
  PM-TEST-004  Expired end_date -> must be INVISIBLE
"""

import sys
import uuid
from datetime import datetime, timezone, timedelta

from database import VendorSessionLocal
from models import (
    CategoryDetails,
    CategoryMaster,
    Equipment,
    EquipmentStatus,
    OrgDepartment,
    Organization,
    RequestCategory,
    ScheduleFrequency,
    TestRequestSchedule,
    TestingRequest,
    TestingRequestStatus,
    User,
)

CM_PREFIX = "CM-TEST-"
PM_PREFIX = "PM-TEST-"
TODAY = datetime.now(timezone.utc)


def _dt(delta_days: int) -> datetime:
    return TODAY + timedelta(days=delta_days)


# -----------------------------------------------------------------------------
# Lookups -- with verbose output so failures are obvious
# -----------------------------------------------------------------------------

ORG_NAME = "KPTCL"  # target organisation -- change if needed


def _get_org(db) -> Organization:
    org = (
        db.query(Organization)
        .filter(Organization.display_name.ilike(f"%{ORG_NAME}%"), Organization.is_active == True)
        .first()
    )
    if not org:
        # list available orgs to help diagnose
        all_orgs = db.query(Organization).filter(Organization.is_active == True).all()
        names = [o.display_name for o in all_orgs]
        raise RuntimeError(
            f"Organisation matching '{ORG_NAME}' not found. "
            f"Available orgs: {names}. Update ORG_NAME at top of script."
        )
    print(f"  org          : {org.display_name}  (id={org.id})")
    return org


def _get_equipment_type(db, name_hint: str, fallback: bool = True) -> CategoryMaster:
    row = (
        db.query(CategoryMaster)
        .filter(CategoryMaster.name.ilike(f"%{name_hint}%"), CategoryMaster.is_active == True)
        .first()
    )
    if row:
        return row
    if fallback:
        row = db.query(CategoryMaster).filter(CategoryMaster.is_active == True).first()
    if not row:
        raise RuntimeError(
            f"No equipment type found matching '{name_hint}' and no fallback available. "
            "Ensure CategoryMaster is seeded."
        )
    return row


def _get_test_type(db, name_hint: str, fallback_offset: int = 0) -> CategoryDetails:
    row = (
        db.query(CategoryDetails)
        .filter(CategoryDetails.name.ilike(f"%{name_hint}%"))
        .first()
    )
    if row:
        return row
    # fallback to nth available test type
    rows = db.query(CategoryDetails).offset(fallback_offset).limit(1).all()
    if not rows:
        raise RuntimeError(
            f"No test type found matching '{name_hint}' and no fallback available. "
            "Ensure CategoryDetails is seeded."
        )
    return rows[0]


def _get_departments(db, org_id) -> list:
    depts = (
        db.query(OrgDepartment)
        .filter(OrgDepartment.organization_id == org_id, OrgDepartment.is_active == True)
        .limit(3)
        .all()
    )
    if not depts:
        raise RuntimeError("No departments found for org. Cannot create equipment (department_id NOT NULL).")
    return depts


def _show_info(db):
    """Print what the script would use -- run with --info to verify before seeding."""
    print("\n-- DB Lookup Info --------------------------------------------------")

    org = db.query(Organization).filter(Organization.display_name.ilike(f"%{ORG_NAME}%"), Organization.is_active == True).first()
    print(f"  Organisation   : {org.display_name if org else 'NOT FOUND'}  (searching for: {ORG_NAME})")

    eq_types = db.query(CategoryMaster).filter(CategoryMaster.is_active == True).limit(5).all()
    print(f"  Equipment types ({len(eq_types)} shown):")
    for t in eq_types:
        print(f"    id={t.id}  name={t.name}")

    test_types = db.query(CategoryDetails).limit(8).all()
    print(f"  Test types ({len(test_types)} shown):")
    for t in test_types:
        print(f"    id={t.id}  name={t.name}")

    if org:
        depts = db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == org.id, OrgDepartment.is_active == True
        ).limit(5).all()
        print(f"  Departments ({len(depts)} shown):")
        for d in depts:
            print(f"    id={d.id}  name={d.name}")

    existing_cm = db.query(Equipment).filter(Equipment.ueic.like(f"{CM_PREFIX}%")).count()
    existing_pm = db.query(Equipment).filter(Equipment.ueic.like(f"{PM_PREFIX}%")).count()
    print(f"\n  Existing test equipment: {existing_cm} CM rows, {existing_pm} PM rows")
    print("--------------------------------------------------------------------\n")


# -----------------------------------------------------------------------------
# Row builders
# -----------------------------------------------------------------------------

def _make_equipment(ueic, org_id, equipment_type_id, department_id, voltage_class="33kV"):
    return Equipment(
        id=uuid.uuid4(),
        ueic=ueic,
        organization_id=org_id,
        equipment_type_id=equipment_type_id,
        department_id=department_id,          # NOT NULL -- always provided
        voltage_class=voltage_class,
        status=EquipmentStatus.active,        # enum value, not string
        manufacturer="Test Manufacturer",
        year_of_manufacture=2018,
        model_number="TEST-MODEL",
    )


def _make_completed_request(org_id, equipment, test_type, request_category,
                            originator_id, completed_days_ago: int,
                            req_number: str, title: str = None):
    """Create a completed TestingRequest. completed_days_ago=0 means today."""
    completed_at = _dt(-completed_days_ago)
    return TestingRequest(
        id=uuid.uuid4(),
        request_number=req_number,
        title=title or f"[TEST] {test_type.name} -- {equipment.ueic}",
        organization_id=org_id,
        equipment_id=equipment.id,
        equipment_type_id=equipment.equipment_type_id,
        test_type_id=test_type.id,
        department_id=equipment.department_id,
        request_category=RequestCategory(request_category),
        status=TestingRequestStatus.completed,
        priority="normal",
        originator_id=originator_id,
        completed_at=completed_at,
        requested_date=_dt(-(completed_days_ago + 7)),
    )


def _make_schedule(org_id, equipment, test_type, request_category,
                   next_run_days, frequency=ScheduleFrequency.yearly,
                   end_date_days=None, title=None):
    return TestRequestSchedule(
        id=uuid.uuid4(),
        organization_id=org_id,
        equipment_id=equipment.id,
        test_type_id=test_type.id,
        title=title or f"[TEST] {test_type.name} -- {equipment.ueic}",
        request_category=RequestCategory(request_category),
        frequency=frequency,
        start_date=_dt(-365),
        end_date=_dt(end_date_days) if end_date_days is not None else None,
        next_run_date=_dt(next_run_days),
        is_active=True,
        is_deleted=False,
        advance_days=7,
        consecutive_failures=0,
    )


# -----------------------------------------------------------------------------
# Seed
# -----------------------------------------------------------------------------

def seed(db):
    print("\n-- Resolving DB references -----------------------------------------")
    org = _get_org(db)
    org_id = org.id

    # Equipment types
    transformer = _get_equipment_type(db, "transformer")
    breaker     = _get_equipment_type(db, "breaker", fallback=True)
    print(f"  transformer  : id={transformer.id}  name={transformer.name}")
    print(f"  breaker      : id={breaker.id}  name={breaker.name}")

    # CM test types -- pick 3 distinct ones
    cm_t1 = _get_test_type(db, "insulation",   fallback_offset=0)
    cm_t2 = _get_test_type(db, "dissolved",    fallback_offset=1)
    cm_t3 = _get_test_type(db, "transformer",  fallback_offset=2)
    # If cm_t1 == cm_t2 (fallback collision), warn
    used = {cm_t1.id, cm_t2.id, cm_t3.id}
    if len(used) < 3:
        # Grab enough distinct types
        all_types = db.query(CategoryDetails).limit(10).all()
        if len(all_types) < 3:
            raise RuntimeError("Need at least 3 CategoryDetails rows to seed multi-column test.")
        cm_t1, cm_t2, cm_t3 = all_types[0], all_types[1], all_types[2]

    # PM test types -- pick 2 distinct ones
    pm_t1 = _get_test_type(db, "oil",       fallback_offset=3)
    pm_t2 = _get_test_type(db, "inspection", fallback_offset=4)
    if pm_t1.id == pm_t2.id:
        all_types = db.query(CategoryDetails).limit(10).all()
        pm_t1, pm_t2 = all_types[0], all_types[1]

    print(f"  cm_t1        : id={cm_t1.id}  name={cm_t1.name}")
    print(f"  cm_t2        : id={cm_t2.id}  name={cm_t2.name}")
    print(f"  cm_t3        : id={cm_t3.id}  name={cm_t3.name}")
    print(f"  pm_t1        : id={pm_t1.id}  name={pm_t1.name}")
    print(f"  pm_t2        : id={pm_t2.id}  name={pm_t2.name}")

    # Departments -- need at least 1, prefer 3 for View By grouping coverage
    depts = _get_departments(db, org_id)
    dept_a = depts[0]
    dept_b = depts[1] if len(depts) > 1 else depts[0]
    dept_c = depts[2] if len(depts) > 2 else depts[0]
    print(f"  dept_a       : {dept_a.name}")
    print(f"  dept_b       : {dept_b.name}")
    print(f"  dept_c       : {dept_c.name}")
    print("--------------------------------------------------------------------\n")

    # -- CM Equipment ---------------------------------------------------------
    cm1 = _make_equipment(f"{CM_PREFIX}001", org_id, transformer.id, dept_a.id, "33kV")
    cm2 = _make_equipment(f"{CM_PREFIX}002", org_id, transformer.id, dept_a.id, "33kV")
    cm3 = _make_equipment(f"{CM_PREFIX}003", org_id, transformer.id, dept_b.id, "11kV")
    cm4 = _make_equipment(f"{CM_PREFIX}004", org_id, breaker.id,     dept_b.id, "11kV")
    cm5 = _make_equipment(f"{CM_PREFIX}005", org_id, breaker.id,     dept_b.id, "33kV")
    cm6 = _make_equipment(f"{CM_PREFIX}006", org_id, transformer.id, dept_c.id, "110kV")

    # -- PM Equipment ---------------------------------------------------------
    pm1 = _make_equipment(f"{PM_PREFIX}001", org_id, transformer.id, dept_a.id, "33kV")
    pm2 = _make_equipment(f"{PM_PREFIX}002", org_id, transformer.id, dept_b.id, "11kV")
    pm3 = _make_equipment(f"{PM_PREFIX}003", org_id, transformer.id, dept_c.id, "33kV")
    pm4 = _make_equipment(f"{PM_PREFIX}004", org_id, transformer.id, dept_a.id, "11kV")

    all_eq = [cm1, cm2, cm3, cm4, cm5, cm6, pm1, pm2, pm3, pm4]
    for eq in all_eq:
        db.add(eq)
    db.flush()
    print(f"[OK] Inserted {len(all_eq)} equipment rows")

    # -- CM Schedules ---------------------------------------------------------

    # CM-001: single test type, 10 days overdue -> OVERDUE
    s_cm1 = _make_schedule(org_id, cm1, cm_t1, "test",
                           next_run_days=-10,
                           title="[TEST] CM-001 overdue single")

    # CM-002: 3 test types mixed -- col1 overdue(-3d), col2 alert(+10d), col3 due(+25d)
    # Overall -> OVERDUE
    s_cm2a = _make_schedule(org_id, cm2, cm_t1, "test",
                            next_run_days=-3,
                            title="[TEST] CM-002 col1 overdue")
    s_cm2b = _make_schedule(org_id, cm2, cm_t2, "test",
                            next_run_days=10,
                            frequency=ScheduleFrequency.monthly,
                            title="[TEST] CM-002 col2 alert")
    s_cm2c = _make_schedule(org_id, cm2, cm_t3, "test",
                            next_run_days=25,
                            frequency=ScheduleFrequency.quarterly,
                            title="[TEST] CM-002 col3 due")

    # CM-003: all future -> OK
    s_cm3a = _make_schedule(org_id, cm3, cm_t1, "test",
                            next_run_days=60,
                            title="[TEST] CM-003 ok col1")
    s_cm3b = _make_schedule(org_id, cm3, cm_t2, "test",
                            next_run_days=90,
                            title="[TEST] CM-003 ok col2")

    # CM-004: due in 20 days -> DUE (16-30d amber window)
    s_cm4 = _make_schedule(org_id, cm4, cm_t1, "test",
                           next_run_days=20,
                           frequency=ScheduleFrequency.monthly,
                           title="[TEST] CM-004 due 20d")

    # CM-005: due in 7 days -> ALERT (1-15d orange window)
    s_cm5 = _make_schedule(org_id, cm5, cm_t1, "test",
                           next_run_days=7,
                           frequency=ScheduleFrequency.monthly,
                           title="[TEST] CM-005 alert 7d")

    # CM-006: overdue 20 days, different dept -> OVERDUE
    s_cm6 = _make_schedule(org_id, cm6, cm_t1, "test",
                           next_run_days=-20,
                           title="[TEST] CM-006 overdue diff dept")

    # -- PM Schedules ---------------------------------------------------------

    # PM-001: overdue 5 days -> OVERDUE
    s_pm1 = _make_schedule(org_id, pm1, pm_t1, "maintenance",
                           next_run_days=-5,
                           title="[TEST] PM-001 overdue 5d")

    # PM-002: two types -- oil overdue(-2d), inspection ok(+45d) -> OVERDUE overall
    s_pm2a = _make_schedule(org_id, pm2, pm_t1, "maintenance",
                            next_run_days=-2,
                            title="[TEST] PM-002 oil overdue")
    s_pm2b = _make_schedule(org_id, pm2, pm_t2, "maintenance",
                            next_run_days=45,
                            frequency=ScheduleFrequency.semi_annual,
                            title="[TEST] PM-002 inspection ok")

    # PM-003: all OK -> OK
    s_pm3a = _make_schedule(org_id, pm3, pm_t1, "maintenance",
                            next_run_days=90,
                            frequency=ScheduleFrequency.quarterly,
                            title="[TEST] PM-003 ok col1")
    s_pm3b = _make_schedule(org_id, pm3, pm_t2, "maintenance",
                            next_run_days=120,
                            frequency=ScheduleFrequency.semi_annual,
                            title="[TEST] PM-003 ok col2")

    # PM-004: expired end_date yesterday -> must NOT appear in dashboard
    s_pm4 = _make_schedule(org_id, pm4, pm_t1, "maintenance",
                           next_run_days=-5,
                           end_date_days=-1,   # end_date = yesterday -> service filters it out
                           title="[TEST] PM-004 EXPIRED invisible")

    cm_scheds = [s_cm1, s_cm2a, s_cm2b, s_cm2c, s_cm3a, s_cm3b, s_cm4, s_cm5, s_cm6]
    pm_scheds = [s_pm1, s_pm2a, s_pm2b, s_pm3a, s_pm3b, s_pm4]

    for s in cm_scheds + pm_scheds:
        db.add(s)
    db.flush()
    print(f"[OK] Inserted {len(cm_scheds)} CM schedules + {len(pm_scheds)} PM schedules")

    db.commit()

    # -- Completed TestingRequests (for Completed(mo) KPI) --------------------
    originator = db.query(User).filter(User.organization_id == org_id).first()
    if not originator:
        print("[WARN] No user found for org -- skipping completed requests")
    else:
        originator_id = originator.id
        completed_reqs = [
            # CM equipment -- 3 completed this month, 1 last month
            _make_completed_request(org_id, cm1, cm_t1, "test", originator_id,
                                    completed_days_ago=2,
                                    req_number="TR-CM-TEST-001-A",
                                    title="[TEST] CM-001 completed 2d ago"),
            _make_completed_request(org_id, cm2, cm_t2, "test", originator_id,
                                    completed_days_ago=5,
                                    req_number="TR-CM-TEST-002-A",
                                    title="[TEST] CM-002 completed 5d ago"),
            _make_completed_request(org_id, cm3, cm_t1, "test", originator_id,
                                    completed_days_ago=0,
                                    req_number="TR-CM-TEST-003-A",
                                    title="[TEST] CM-003 completed today"),
            # Last month -- should NOT count in Completed(mo)
            _make_completed_request(org_id, cm4, cm_t1, "test", originator_id,
                                    completed_days_ago=35,
                                    req_number="TR-CM-TEST-004-OLD",
                                    title="[TEST] CM-004 completed last month"),
            # PM equipment -- 2 completed this month
            _make_completed_request(org_id, pm1, pm_t1, "maintenance", originator_id,
                                    completed_days_ago=1,
                                    req_number="TR-PM-TEST-001-A",
                                    title="[TEST] PM-001 completed 1d ago"),
            _make_completed_request(org_id, pm3, pm_t2, "maintenance", originator_id,
                                    completed_days_ago=10,
                                    req_number="TR-PM-TEST-003-A",
                                    title="[TEST] PM-003 completed 10d ago"),
        ]
        for r in completed_reqs:
            db.add(r)
        db.commit()
        this_month = sum(1 for r in completed_reqs
                         if r.completed_at >= TODAY.replace(day=1))
        print(f"[OK] Inserted {len(completed_reqs)} completed requests "
              f"({this_month} this month, {len(completed_reqs)-this_month} last month)")

    print("\n[DONE] Test data seeded successfully.")

    # -- Expected state --------------------------------------------------------
    print("\n" + "=" * 70)
    print("EXPECTED DASHBOARD STATE")
    print("=" * 70)
    print(f"\nCM Schedules  (request_category = test)")
    print(f"  Total equipment visible : 6  (CM-TEST-001 through 006)")
    print(f"  OVERDUE  : CM-001 (10d past), CM-002 (3d past), CM-006 (20d past)  -> KPI = 3")
    print(f"  ALERT    : CM-005 (7d ahead)")
    print(f"  DUE      : CM-002 col3 (25d), CM-004 (20d)")
    print(f"  OK       : CM-003")
    print(f"  Overdue chip count : 3")
    print(f"  Click Overdue chip : only CM-001, CM-002, CM-006 shown in matrix")
    print(f"  View By Equipment type : transformer group vs breaker group")
    print(f"  View By Voltage class  : 33kV / 11kV / 110kV")
    print(f"  View By Dept : CM-001/002 in '{dept_a.name}', CM-006 in '{dept_c.name}'")
    print(f"\nPM Schedules  (request_category = maintenance)")
    print(f"  Total equipment visible : 3  (PM-TEST-001, 002, 003)")
    print(f"  PM-TEST-004 must NOT appear  (end_date expired)")
    print(f"  OVERDUE  : PM-001 (5d past), PM-002 (2d past)  -> KPI = 2")
    print(f"  OK       : PM-003")
    print(f"  Overdue chip count : 2")
    print("=" * 70)
    print("\nRun with --cleanup to remove all test rows.\n")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------

def cleanup(db):
    # Delete schedules first (FK -> equipment)
    test_eq_ids = [
        row.id for row in db.query(Equipment.id).filter(
            Equipment.ueic.like(f"{CM_PREFIX}%") | Equipment.ueic.like(f"{PM_PREFIX}%")
        ).all()
    ]
    if not test_eq_ids:
        print("[INFO] No test equipment found -- nothing to clean up.")
        return

    # Testing requests
    tr_del = (
        db.query(TestingRequest)
        .filter(TestingRequest.equipment_id.in_(test_eq_ids))
        .all()
    )
    for r in tr_del:
        db.delete(r)
    db.flush()
    print(f"[OK] Deleted {len(tr_del)} testing requests")

    sched_del = (
        db.query(TestRequestSchedule)
        .filter(TestRequestSchedule.equipment_id.in_(test_eq_ids))
        .all()
    )
    for s in sched_del:
        db.delete(s)
    db.flush()
    print(f"[OK] Deleted {len(sched_del)} schedules")

    eq_del = db.query(Equipment).filter(Equipment.id.in_(test_eq_ids)).all()
    for e in eq_del:
        db.delete(e)
    db.flush()
    db.commit()
    print(f"[OK] Deleted {len(eq_del)} equipment rows")
    print("[DONE] Cleanup complete.\n")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    db = VendorSessionLocal()
    try:
        if "--info" in sys.argv:
            _show_info(db)
        elif "--cleanup" in sys.argv:
            print("[MODE] Cleanup\n")
            cleanup(db)
        else:
            print("[MODE] Seed\n")
            seed(db)
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
