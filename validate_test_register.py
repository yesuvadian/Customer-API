"""
validate_test_register.py
─────────────────────────
Validates old + new functionality after Test Register changes.
Run:  python validate_test_register.py
"""
import sys
import traceback
from database import SessionLocal
from models import (
    CategoryMaster, Equipment, Organization,
    ScheduleFrequency, TestingRequest, TestRequestSchedule,
)

db = SessionLocal()
results = []


def check(name, fn):
    try:
        fn()
        results.append(("PASS", name, None))
    except Exception as exc:
        results.append(("FAIL", name, str(exc)))
        traceback.print_exc()


# ── 1. Model column presence ──────────────────────────────────────────────────
def test_model_cols():
    req = TestingRequest()
    assert hasattr(req, "is_schedule_template"),  "is_schedule_template missing from TestingRequest"
    assert hasattr(req, "is_direct_submission"),   "is_direct_submission missing from TestingRequest"
    sched = TestRequestSchedule()
    for col in ("revised_periodicity_days", "oem_reference",
                "responsible_role_id", "reviewing_role_id"):
        assert hasattr(sched, col), f"{col} missing from TestRequestSchedule"


check("Model columns present on ORM classes", test_model_cols)


# ── 2. ScheduleFrequency enum ─────────────────────────────────────────────────
def test_enum():
    vals = {f.value for f in ScheduleFrequency}
    for v in ("daily", "weekly", "monthly", "quarterly",
              "semi_annual", "yearly", "triennial"):
        assert v in vals, f"ScheduleFrequency missing value: {v}"


check("ScheduleFrequency has all values including semi_annual + triennial", test_enum)


# ── 3. CategoryMaster — all equipment types ───────────────────────────────────
def test_category_master():
    required = (
        "Power Transformer", "Circuit Breaker", "Current Transformer",
        "Lightning Arrester", "Battery Bank",
    )
    for name in required:
        row = db.query(CategoryMaster).filter_by(name=name, is_active=True).first()
        assert row, f"CategoryMaster missing: {name}"


check("CategoryMaster has all 5 required equipment types", test_category_master)


# ── 4. Register templates seeded ─────────────────────────────────────────────
def test_templates_seeded():
    templates = (
        db.query(TestingRequest)
        .filter(TestingRequest.is_schedule_template.is_(True))
        .all()
    )
    assert len(templates) == 15, f"Expected 15 templates, got {len(templates)}"
    for t in templates:
        sched = db.query(TestRequestSchedule).filter_by(test_request_id=t.id).first()
        assert sched, f"No schedule for template: {t.title}"
        assert sched.responsible_role_id, f"responsible_role_id missing: {t.title}"
        assert sched.reviewing_role_id,   f"reviewing_role_id missing: {t.title}"


check("15 register templates seeded with roles", test_templates_seeded)


# ── 5. Template breakdown by equipment type ───────────────────────────────────
def test_template_breakdown():
    expected = {
        "Power Transformer": 4,
        "Circuit Breaker":   4,
        "Current Transformer": 2,
        "Lightning Arrester":  2,
        "Battery Bank":        3,
    }
    for eq_name, count in expected.items():
        eq_type = db.query(CategoryMaster).filter_by(name=eq_name).first()
        assert eq_type, f"Equipment type missing: {eq_name}"
        actual = (
            db.query(TestingRequest)
            .filter(
                TestingRequest.is_schedule_template.is_(True),
                TestingRequest.equipment_type_id == eq_type.id,
            )
            .count()
        )
        assert actual == count, (
            f"{eq_name}: expected {count} templates, got {actual}"
        )


check("Template count per equipment type correct", test_template_breakdown)


# ── 6. _advance_date with new frequencies ────────────────────────────────────
def test_advance_date():
    from services.test_request_schedule_service import _advance_date
    from datetime import datetime, timezone

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cases = [
        (ScheduleFrequency.monthly,     "2025-02-01"),
        (ScheduleFrequency.quarterly,   "2025-04-01"),
        (ScheduleFrequency.semi_annual, "2025-07-01"),
        (ScheduleFrequency.yearly,      "2026-01-01"),
        (ScheduleFrequency.triennial,   "2028-01-01"),
    ]
    for freq, expected in cases:
        result = _advance_date(base, freq).strftime("%Y-%m-%d")
        assert result == expected, (
            f"_advance_date({freq.value}): expected {expected}, got {result}"
        )


check("_advance_date handles semi_annual and triennial correctly", test_advance_date)


# ── 7. TestRegisterService.list_templates ─────────────────────────────────────
def test_svc_list():
    from services.test_register_service import TestRegisterService

    svc = TestRegisterService(db)
    kptcl = db.query(Organization).filter_by(code="KPTCL").first()
    assert kptcl, "KPTCL org not found"

    rows = svc.list_templates(organization_id=kptcl.id)
    assert len(rows) == 15, f"list_templates returned {len(rows)}, expected 15"

    # check serialization shape
    r = rows[0]
    for key in ("id", "title", "equipment_type_name", "schedule"):
        assert key in r, f"Missing key in template response: {key}"
    s = r["schedule"]
    assert s is not None, "schedule is None"
    for key in ("frequency", "responsible_role_name", "reviewing_role_name",
                "advance_days", "revised_periodicity_days", "oem_reference"):
        assert key in s, f"Missing key in schedule response: {key}"


check("TestRegisterService.list_templates — shape and count", test_svc_list)


# ── 8. TestRegisterService.get_template ──────────────────────────────────────
def test_svc_get():
    from services.test_register_service import TestRegisterService

    svc = TestRegisterService(db)
    tmpl = (
        db.query(TestingRequest)
        .filter(TestingRequest.is_schedule_template.is_(True))
        .first()
    )
    result = svc.get_template(tmpl.id)
    assert result["id"] == str(tmpl.id)
    assert result["schedule"] is not None


check("TestRegisterService.get_template", test_svc_get)


# ── 9. TestRegisterService.list_templates filter by equipment_type_id ─────────
def test_svc_filter():
    from services.test_register_service import TestRegisterService

    svc = TestRegisterService(db)
    ct = db.query(CategoryMaster).filter_by(name="Current Transformer").first()
    rows = svc.list_templates(equipment_type_id=ct.id)
    assert len(rows) == 2, f"Expected 2 CT templates, got {len(rows)}"


check("TestRegisterService.list_templates filter by equipment_type_id", test_svc_filter)


# ── 10. TestRegisterService.apply_alert_reschedule ────────────────────────────
def test_alert_reschedule():
    from services.test_register_service import TestRegisterService

    svc = TestRegisterService(db)
    sched = (
        db.query(TestRequestSchedule)
        .filter(TestRequestSchedule.revised_periodicity_days.isnot(None))
        .first()
    )
    assert sched, "No schedule with revised_periodicity_days"

    before = sched.next_run_date
    result = svc.apply_alert_reschedule(sched.id)
    assert result["rescheduled"] is True
    assert result["next_run_date"] is not None
    assert result["revised_periodicity_days"] is not None
    print(f"        revised by {result['revised_periodicity_days']} days "
          f"-> new next_run_date: {result['next_run_date'][:10]}")


check("TestRegisterService.apply_alert_reschedule", test_alert_reschedule)


# ── 11. Equipment schedule list ───────────────────────────────────────────────
def test_equipment_schedules():
    from services.test_register_service import TestRegisterService

    svc = TestRegisterService(db)
    kptcl = db.query(Organization).filter_by(code="KPTCL").first()
    eq = (
        db.query(Equipment)
        .join(CategoryMaster, Equipment.equipment_type_id == CategoryMaster.id)
        .filter(
            Equipment.organization_id == kptcl.id,
            CategoryMaster.name == "Power Transformer",
        )
        .first()
    )
    if eq:
        schedules = svc.list_equipment_schedules(eq.id)
        assert isinstance(schedules, list)
        print(f"        {eq.ueic}: {len(schedules)} live schedule(s)")
    else:
        print("        [INFO] No Power Transformer equipment — skipped schedule count check")


check("TestRegisterService.list_equipment_schedules returns list", test_equipment_schedules)


# ── 12. Direct submission service still works ─────────────────────────────────
def test_direct_submission():
    from services.direct_submission_service import DirectSubmissionService

    svc = DirectSubmissionService(db)
    rows = svc.list_submissions("failure_registry", user=None, skip=0, limit=10)
    assert isinstance(rows, list)
    rows2 = svc.list_submissions("taqc_inspection", user=None, skip=0, limit=10)
    assert isinstance(rows2, list)


check("DirectSubmissionService — both categories list OK", test_direct_submission)


# ── 13. is_schedule_template partitions all rows ──────────────────────────────
def test_partition():
    live      = db.query(TestingRequest).filter(TestingRequest.is_schedule_template.is_(False)).count()
    templates = db.query(TestingRequest).filter(TestingRequest.is_schedule_template.is_(True)).count()
    total     = db.query(TestingRequest).count()
    assert live + templates == total, (
        f"Partition mismatch: live={live} + templates={templates} != total={total}"
    )
    assert templates == 15
    print(f"        live={live}  templates={templates}  total={total}")


check("is_schedule_template partitions TestingRequest cleanly", test_partition)


# ── 14. Routes registered ─────────────────────────────────────────────────────
def test_routes():
    import main
    paths = {r.path for r in main.app.routes}
    required = [
        "/test-register/",
        "/test-register/{template_id}",
        "/test-register/commission/{equipment_id}",
        "/test-register/alert-reschedule/{schedule_id}",
        "/test-register/equipment/{equipment_id}/schedules",
        "/direct-submissions/",
        "/direct-submissions/{submission_id}",
        "/equipment/",
    ]
    for ep in required:
        assert ep in paths, f"Route not registered: {ep}"


check("All required routes registered in main.py", test_routes)


# ── 15. KPTCL equipment seeded ────────────────────────────────────────────────
def test_kptcl_equipment():
    kptcl = db.query(Organization).filter_by(code="KPTCL").first()
    assert kptcl
    count = db.query(Equipment).filter_by(organization_id=kptcl.id).count()
    assert count >= 1, f"No equipment seeded for KPTCL (got {count})"
    print(f"        KPTCL equipment units: {count}")


check("KPTCL equipment seeded", test_kptcl_equipment)


# ── 16. OEM references present on templates with standards ───────────────────
def test_oem_refs():
    schedules_with_oem = (
        db.query(TestRequestSchedule)
        .filter(TestRequestSchedule.oem_reference.isnot(None))
        .count()
    )
    assert schedules_with_oem >= 10, (
        f"Expected >= 10 schedules with OEM reference, got {schedules_with_oem}"
    )
    print(f"        schedules with OEM reference: {schedules_with_oem}")


check("OEM references present on register schedules", test_oem_refs)


db.close()

# ── REPORT ─────────────────────────────────────────────────────────────────────
print()
print("=" * 65)
print("  VALIDATION REPORT")
print("=" * 65)
passed = failed = 0
for r in results:
    if r[0] == "PASS":
        print(f"  PASS  {r[1]}")
        passed += 1
    else:
        print(f"  FAIL  {r[1]}")
        print(f"          {r[2]}")
        failed += 1

print("=" * 65)
print(f"  PASSED: {passed}   FAILED: {failed}   TOTAL: {passed + failed}")
print("=" * 65)
sys.exit(0 if failed == 0 else 1)
