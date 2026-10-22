"""
DEMO (dev/local only): an equipment test on a template with NO threshold
values is decided by the tester's verdict (services/evaluation_service.py,
EvaluationService._no_threshold_result):

    tester marks Pass -> NORMAL   (no CAR, equipment not Critical)
    tester marks Fail -> CRITICAL (CAR, critical alert, equipment Critical)

Creates, in the KPTCL org, two Protection Relays (copies of an existing one,
same department), each with a Relay Testing request ('relay_testing' has no
thresholds):

    DEMO-NOTHRESH-RELAY-01  TR-DEMO-NOTHRESH-0001  tester verdict: Pass
    DEMO-NOTHRESH-RELAY-02  TR-DEMO-NOTHRESH-0002  tester verdict: Fail

Each result is saved through TestingService.create_structured_result
(finalize=True) — the same path the UI's Submit uses — so the real
auto-evaluation, CAR hook and notifications run. The request is then closed
(as an approval would) so the result counts for equipment health.

Usage:
    python seed_no_threshold_demo.py            # create (idempotent)
    python seed_no_threshold_demo.py --remove   # delete everything it made
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy import text

from database import SessionLocal

ORG_NAME = "Karnataka Power Transmission Corporation Limited"
TEMPLATE_KEY = "relay_testing"
CASES = [  # (ueic, request number, tester verdict)
    ("DEMO-NOTHRESH-RELAY-01", "TR-DEMO-NOTHRESH-0001", "pass"),
    ("DEMO-NOTHRESH-RELAY-02", "TR-DEMO-NOTHRESH-0002", "fail"),
]


def _clone_row(db, table: str, src_id, overrides: dict) -> uuid.UUID:
    """INSERT a copy of one row with `overrides` applied (new id included)."""
    cols = db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
        {"t": table}).scalars().all()
    new_id = uuid.uuid4()
    overrides = {"id": new_id, **overrides}
    select_parts = [f":ov_{c}" if c in overrides else f'"{c}"' for c in cols]
    params = {f"ov_{c}": v for c, v in overrides.items()}
    params["src"] = src_id
    db.execute(text(
        f'INSERT INTO public.{table} ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
        f'SELECT {", ".join(select_parts)} FROM public.{table} WHERE id = :src'), params)
    return new_id


def remove(db) -> None:
    """Delete the demo equipment and everything hanging off it: its requests
    (incl. a CAR's auto-created retest), results, CARs and analytics."""
    depts = set()
    for ueic, _, _ in CASES:
        eq = db.execute(text("SELECT id FROM public.equipment WHERE ueic=:u"), {"u": ueic}).scalar()
        if not eq:
            continue
        p = {"e": eq}
        depts.add(db.execute(text("SELECT department_id FROM public.equipment WHERE id = :e"), p).scalar())
        trs = "(SELECT id FROM public.testing_requests WHERE equipment_id = :e)"
        db.execute(text("DELETE FROM public.corrective_action_requests WHERE equipment_id = :e"), p)
        db.execute(text("DELETE FROM public.test_analytics WHERE equipment_id = :e"), p)
        db.execute(text("DELETE FROM public.equipment_analytics WHERE equipment_id = :e"), p)
        db.execute(text(f"UPDATE public.testing_requests SET parent_request_id = NULL "
                        f"WHERE parent_request_id IN {trs}"), p)
        db.execute(text(f"DELETE FROM public.test_results WHERE testing_request_id IN {trs}"), p)
        db.execute(text("DELETE FROM public.testing_requests WHERE equipment_id = :e"), p)
        db.execute(text("DELETE FROM public.equipment WHERE id = :e"), p)
    from services.analytics_engine import AnalyticsEngine
    for dept in filter(None, depts):  # department / zone health rolls up from equipment
        AnalyticsEngine(db).run_for_department(dept)
    db.commit()
    print("[OK] demo equipment / requests / results / CARs removed")


def _create_case(db, org, src_eq, tester, test_type, ueic, tr_number, verdict) -> None:
    eq_id = db.execute(text("SELECT id FROM public.equipment WHERE ueic=:u"), {"u": ueic}).scalar()
    if not eq_id:
        eq_id = _clone_row(db, "equipment", src_eq, {
            "ueic": ueic, "factory_serial_number": "SN-" + ueic,
            "status": "active", "cts": None, "mts": None,
        })
        db.execute(text("UPDATE public.equipment SET cts=NOW(), mts=NOW() WHERE id=:i"), {"i": eq_id})
    eq = db.execute(text("""SELECT department_id, equipment_type_id FROM public.equipment
                            WHERE id=:i"""), {"i": eq_id}).one()

    tr_id = db.execute(text("SELECT id FROM public.testing_requests WHERE request_number=:n"),
                       {"n": tr_number}).scalar()
    if not tr_id:
        tr_id = uuid.uuid4()
        db.execute(text("""
            INSERT INTO public.testing_requests
              (id, request_number, title, request_category, status, originator_id,
               organization_id, department_id, equipment_id, equipment_type_id, test_type_id,
               assigned_tester_id, requested_date, is_cumulative, is_calibration,
               is_schedule_template, cts, mts)
            VALUES (:id, :n, :t, 'test', 'in_progress', :u, :o, :d, :e, :et, :tt,
                    :u, NOW(), false, false, false, NOW(), NOW())"""),
            dict(id=tr_id, n=tr_number,
                 t=f"[DEMO] Relay Testing (no thresholds, tester {verdict.title()}) - {ueic}",
                 u=tester, o=org, d=eq.department_id, e=eq_id, et=eq.equipment_type_id,
                 tt=test_type))
    db.commit()

    # Real save + auto-evaluation path (what the UI's Submit calls). The form
    # writes the tester's verdict into test_data['overall_result'] as well.
    from services.testing_service import TestingService
    result = TestingService(db).create_structured_result(
        request_id=tr_id, template_key=TEMPLATE_KEY,
        test_data={"overall_result": verdict,
                   "overall_remarks": f"[DEMO] tester checked the relay and marked it {verdict.title()}"},
        overall_result=verdict, remarks=f"[DEMO] tester verdict: {verdict.title()}",
        tester_id=tester, finalize=True,
    )

    # Equipment health only counts ACCEPTED results (accepted_test_result_ids:
    # closed/approved requests) - close the request as an approval would.
    db.execute(text("""UPDATE public.testing_requests
                       SET status='closed', completed_at=NOW(), mts=NOW() WHERE id=:i"""),
               {"i": tr_id})
    db.flush()
    from services.analytics_engine import AnalyticsEngine
    AnalyticsEngine(db).run_for_test(result.id)
    db.commit()

    ev = result.evaluation_result or {}
    ea = db.execute(text("""SELECT risk_level, health_score FROM public.equipment_analytics
                            WHERE equipment_id=:e"""), {"e": eq_id}).first()
    cars = db.execute(text("""SELECT count(*) FROM public.corrective_action_requests
                              WHERE equipment_id=:e"""), {"e": eq_id}).scalar()
    print(f"[OK] {ueic} / {tr_number}: tester={verdict.upper():4} -> evaluation={ev.get('overall')}, "
          f"result={result.overall_result}, CARs={cars}, "
          f"equipment risk={ea[0] if ea else None} (health {ea[1] if ea else None})")


def create(db) -> None:
    org = db.execute(text('SELECT id FROM public.organizations WHERE name=:n'),
                     {"n": ORG_NAME}).scalar()
    if not org:
        sys.exit(f"org '{ORG_NAME}' not found")
    src_eq = db.execute(text("""
        SELECT e.id FROM public.equipment e
        JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        WHERE e.organization_id = :o AND cm.name = 'Protection Relay'
          AND e.department_id IS NOT NULL AND e.ueic NOT LIKE 'DEMO-%'
        ORDER BY e.cts LIMIT 1"""), {"o": org}).scalar()
    tester = db.execute(text("""SELECT id FROM public.users WHERE organization_id=:o
                                ORDER BY cts LIMIT 1"""), {"o": org}).scalar()
    test_type = db.execute(text("""SELECT id FROM public."CategoryDetails"
                                   WHERE name='Relay Testing' ORDER BY id LIMIT 1""")).scalar()
    for ueic, tr_number, verdict in CASES:
        _create_case(db, org, src_eq, tester, test_type, ueic, tr_number, verdict)


if __name__ == "__main__":
    s = SessionLocal()
    try:
        remove(s) if "--remove" in sys.argv else create(s)
    finally:
        s.close()
