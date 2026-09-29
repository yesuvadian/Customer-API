"""
SAMPLE DATA: one record for each scheduled report that is otherwise empty,
so every report on Reporting Center → Schedule produces a non-empty Excel.
For dev/demo databases only — not for production.

  Report                               Sample record added
  ───────────────────────────────────  ─────────────────────────────────────
  Equipment Failure Annual Report      failure-register request dated LAST
                                       year (the report defaults to last year)
  Repairer Performance Ranking Report  completed repair_lifecycle workflow,
  Transformer Repair Status Report     last year, on a power transformer,
                                       with a repairer (vendor) name
  TA&QC Observation Compliance Report  TA&QC inspection + one open
                                       observation this month
  Procurement Pipeline                 procurement request
  Open Corrective Actions (CAR)        two CARs on a CRITICAL test result —
                                       one OPEN (not due), one ASSIGNED and
                                       overdue

Every record is tagged SAMPLE (number/title), so it's easy to spot and to
remove again with --remove. Re-running never creates duplicates.

Usage:
    python seed_report_sample_data.py --check     # show what exists / would be added
    python seed_report_sample_data.py             # add the sample records
    python seed_report_sample_data.py --remove    # delete them again

Optional: --org <organization uuid> (default: the org with the most equipment)
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text

from database import SessionLocal

LAST_YEAR = date.today().year - 1
FR_NUMBER = f"FR-SAMPLE-{LAST_YEAR}-0001"
WF_NUMBER = f"RW-SAMPLE-{LAST_YEAR}-0001"
INSP_NUMBER = "TAQC-SAMPLE-0001"
OBS_NUMBER = "OBS-SAMPLE-0001"
PR_NUMBER = "PR-SAMPLE-0001"
CAR_NUMBERS = ("CAR-SAMPLE-0001", "CAR-SAMPLE-0002")


def _one(db, sql, **kw):
    return db.execute(text(sql), kw).first()


def _pick_org(db):
    if "--org" in sys.argv:
        return uuid.UUID(sys.argv[sys.argv.index("--org") + 1])
    return _one(db, "SELECT organization_id FROM public.equipment "
                    "GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1")[0]


def _existing(db):
    return {
        "failure":  _one(db, "SELECT id FROM public.testing_requests WHERE request_number=:n", n=FR_NUMBER),
        "workflow": _one(db, "SELECT id FROM public.repair_workflows WHERE workflow_number=:n", n=WF_NUMBER),
        "taqc":     _one(db, "SELECT id FROM public.taqc_annual_inspections WHERE inspection_number=:n", n=INSP_NUMBER),
        "procure":  _one(db, "SELECT id FROM public.procurement_requests WHERE procurement_number=:n", n=PR_NUMBER),
        "car":      _one(db, "SELECT id FROM public.corrective_action_requests WHERE car_number=:n",
                         n=CAR_NUMBERS[0]),
    }


def add(db, org):
    have = _existing(db)

    # A real power transformer + a real test request + a user in this org to hang the samples on.
    eq = _one(db, """
        SELECT e.id, e.ueic, e.department_id FROM public.equipment e
        JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        WHERE e.organization_id=:o AND e.status='active' AND cm.name ILIKE '%power transformer%'
          AND e.department_id IS NOT NULL
        ORDER BY e.ueic LIMIT 1""", o=org)
    tr = _one(db, """SELECT id, originator_id FROM public.testing_requests
                     WHERE organization_id=:o AND request_category='test' AND originator_id IS NOT NULL
                     ORDER BY cts DESC LIMIT 1""", o=org)
    cat = _one(db, """SELECT id FROM public."CategoryDetails"
                      WHERE category_type='inspection' ORDER BY id LIMIT 1""")
    if not (eq and tr and cat):
        print("[ERROR] need at least one active power transformer, one test request "
              "and one inspection category in this org."); sys.exit(1)
    eq_id, eq_ueic, dept_id = eq
    tr_id, user_id = tr
    now = datetime.now()

    if not have["failure"]:
        db.execute(text("""
            INSERT INTO public.testing_requests
              (id, request_number, title, request_category, status, originator_id,
               organization_id, department_id, equipment_id, form_data,
               is_cumulative, is_calibration, is_schedule_template, cts, mts)
            VALUES (:id, :n, :t, 'failure_registry', 'submitted', :u,
                    :o, :d, :e, CAST(:fd AS jsonb), false, false, false, :c, :c)"""),
            dict(id=uuid.uuid4(), n=FR_NUMBER, t=f"[SAMPLE] Winding failure - {eq_ueic}",
                 u=user_id, o=org, d=dept_id, e=eq_id,
                 fd='{"failure_category": "Winding / Insulation failure"}',
                 c=datetime(LAST_YEAR, 6, 15, 10, 0)))
        print(f"  [OK] failure record {FR_NUMBER} (dated {LAST_YEAR}-06-15)")

    if not have["workflow"]:
        db.execute(text("""
            INSERT INTO public.repair_workflows
              (id, workflow_number, workflow_type, status, vendor_name, progress,
               equipment_id, organization_id, entity_type, created_at, completed_at)
            VALUES (:id, :n, 'repair_lifecycle', 'completed', 'SAMPLE Transformer Repairs Pvt Ltd', 100,
                    :e, :o, 'equipment', :s, :f)"""),
            dict(id=uuid.uuid4(), n=WF_NUMBER, e=eq_id, o=org,
                 s=datetime(LAST_YEAR, 5, 10, 9, 0), f=datetime(LAST_YEAR, 6, 20, 17, 0)))
        print(f"  [OK] repair workflow {WF_NUMBER} on {eq_ueic} (completed, {LAST_YEAR})")

    if not have["taqc"]:
        insp_id = uuid.uuid4()
        db.execute(text("""
            INSERT INTO public.taqc_annual_inspections
              (id, inspection_number, organization_id, department_id, inspection_date,
               inspected_by, remarks, created_by, cts, mts)
            VALUES (:id, :n, :o, :d, :dt, :u, '[SAMPLE] Annual TA&QC inspection', :u, :c, :c)"""),
            dict(id=insp_id, n=INSP_NUMBER, o=org, d=dept_id, dt=date.today(), u=user_id, c=now))
        db.execute(text("""
            INSERT INTO public.taqc_observations
              (id, inspection_id, observation_number, category_detail_id, severity,
               target_compliance_date, observation_description, current_stage_code,
               created_by, is_overdue, cts, mts)
            VALUES (:id, :i, :n, :cat, 'medium', :tgt,
                    '[SAMPLE] Cable trench cover damaged near bay 2', 'open', :u, false, :c, :c)"""),
            dict(id=uuid.uuid4(), i=insp_id, n=OBS_NUMBER, cat=cat[0],
                 tgt=date.today() + timedelta(days=30), u=user_id, c=now))
        print(f"  [OK] TA&QC inspection {INSP_NUMBER} + observation {OBS_NUMBER} (this month)")

    if not have["procure"]:
        db.execute(text("""
            INSERT INTO public.procurement_requests
              (id, procurement_number, testing_request_id, organization_id, title, description,
               status, estimated_cost, quantity, raised_by, raised_at, created_by, cts, mts)
            VALUES (:id, :n, :tr, :o, '[SAMPLE] Replacement WTI/OTI sensor',
                    'Sample procurement request for report testing', 'pending', 45000, 1,
                    :u, :c, :u, :c, :c)"""),
            dict(id=uuid.uuid4(), n=PR_NUMBER, tr=tr_id, o=org, u=user_id, c=now))
        print(f"  [OK] procurement request {PR_NUMBER}")

    if not have["car"]:
        # Two most recent CRITICAL test results in this org — CARs are
        # auto-raised from CRITICAL results, so the samples mirror that.
        crit = db.execute(text("""
            SELECT res.id, res.template_key, e.id, e.ueic, e.department_id
            FROM   public.test_results res
            JOIN   public.testing_requests tr ON tr.id = res.testing_request_id
            JOIN   public.equipment        e  ON e.id  = tr.equipment_id
            WHERE  tr.organization_id = :o
              AND  res.evaluation_result->>'overall' = 'CRITICAL'
              AND  e.department_id IS NOT NULL
            ORDER  BY res.tested_at DESC NULLS LAST LIMIT 2"""), {"o": org}).all()
        # Assignee: an active user in the same department, else the sample user.
        samples = [
            ("OPEN", None, date.today() + timedelta(days=10),
             "[SAMPLE] Oil parameters CRITICAL — filtration and retest required",
             "Carry out oil filtration, then repeat BDV / moisture test within 10 days."),
            ("ASSIGNED", True, date.today() - timedelta(days=3),
             "[SAMPLE] SFRA deviation CRITICAL — winding inspection pending",
             "Internal inspection of windings and clamping; repeat SFRA after inspection."),
        ]
        for (status, assign, due, summary, action), car_no, src in zip(samples, CAR_NUMBERS, crit):
            res_id, tkey, c_eq, c_ueic, c_dept = src
            assignee = None
            if assign:
                row = _one(db, """SELECT our.user_id FROM public.org_user_roles our
                                  WHERE our.department_id = :d AND our.is_active LIMIT 1""", d=c_dept)
                assignee = row[0] if row else user_id
            db.execute(text("""
                INSERT INTO public.corrective_action_requests
                  (id, car_number, equipment_id, organization_id, department_id,
                   source_test_result_id, template_key, severity, summary, corrective_action,
                   status, assigned_to, due_date, created_by, created_at, modified_at)
                VALUES (:id, :n, :e, :o, :d, :r, :k, 'CRITICAL', :s, :a,
                        :st, :to, :due, :u, :c, :c)"""),
                dict(id=uuid.uuid4(), n=car_no, e=c_eq, o=org, d=c_dept, r=res_id, k=tkey,
                     s=summary, a=action, st=status, to=assignee, due=due, u=user_id,
                     c=now - timedelta(days=12)))
            print(f"  [OK] CAR {car_no} on {c_ueic} ({status}, due {due})")
        if not crit:
            print("  [SKIP] no CRITICAL test results in this org to raise sample CARs on")

    db.commit()


def remove(db):
    have = _existing(db)
    if have["taqc"]:
        db.execute(text("DELETE FROM public.taqc_observations WHERE inspection_id=:i"), {"i": have["taqc"][0]})
        db.execute(text("DELETE FROM public.taqc_annual_inspections WHERE id=:i"), {"i": have["taqc"][0]})
    db.execute(text("DELETE FROM public.corrective_action_requests WHERE car_number = ANY(:n)"),
               {"n": list(CAR_NUMBERS)})
    if have["procure"]:
        db.execute(text("DELETE FROM public.procurement_requests WHERE id=:i"), {"i": have["procure"][0]})
    if have["workflow"]:
        db.execute(text("DELETE FROM public.repair_workflows WHERE id=:i"), {"i": have["workflow"][0]})
    if have["failure"]:
        db.execute(text("DELETE FROM public.testing_requests WHERE id=:i"), {"i": have["failure"][0]})
    db.commit()
    print(f"  [OK] removed {sum(1 for v in have.values() if v)} sample record group(s)")


def main():
    db = SessionLocal()
    try:
        org = _pick_org(db)
        print("=" * 70)
        print(f"  Report sample data — org {org}")
        print("=" * 70)
        have = _existing(db)
        for k, v in have.items():
            print(f"  {k:9} {'present' if v else 'missing'}")
        if "--check" in sys.argv:
            print("\n  --check: nothing changed.")
        elif "--remove" in sys.argv:
            remove(db)
        else:
            add(db, org)
            print("\n  [SUCCESS] Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
