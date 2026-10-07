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
  Maintenance Effectiveness Index      two failure tickets with a completed PM
                                       Workflow, between two scored tests
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
# TA&QC Observation Compliance only covers the CURRENT month, so a fixed
# sample goes stale when the month changes — this set is keyed by month and
# re-running the script in a new month adds that month's observations.
MONTH_TAG = date.today().strftime("%Y%m")
INSP_MONTH_NUMBER = f"TAQC-SAMPLE-{MONTH_TAG}"
PR_NUMBER = "PR-SAMPLE-0001"
CAR_NUMBERS = ("CAR-SAMPLE-0001", "CAR-SAMPLE-0002")
PM_NUMBERS = ("FR-SAMPLE-PM-0001", "FR-SAMPLE-PM-0002")
PC_NUMBERS = ("PC-SAMPLE-0001", "PC-SAMPLE-0002", "PC-SAMPLE-0003")
POST_REPAIR_TR = "TR-SAMPLE-POSTREPAIR-0001"


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
        "taqc_month": _one(db, "SELECT id FROM public.taqc_annual_inspections WHERE inspection_number=:n",
                           n=INSP_MONTH_NUMBER),
        "procure":  _one(db, "SELECT id FROM public.procurement_requests WHERE procurement_number=:n", n=PR_NUMBER),
        "car":      _one(db, "SELECT id FROM public.corrective_action_requests WHERE car_number=:n",
                         n=CAR_NUMBERS[0]),
        "pm":       _one(db, "SELECT id FROM public.testing_requests WHERE request_number=:n",
                         n=PM_NUMBERS[0]),
        "vendor":   _one(db, "SELECT id FROM public.precommission_requests WHERE request_number=:n",
                         n=PC_NUMBERS[0]),
        "postrep":  _one(db, "SELECT id FROM public.testing_requests WHERE request_number=:n",
                         n=POST_REPAIR_TR),
        # result-review stages added to the sample PM tickets' workflows this month
        "review":   _one(db, """SELECT si.id FROM public.tr_wf_stage_instances si
                                JOIN public.tr_wf_instances wi ON wi.id = si.wf_instance_id
                                JOIN public.testing_requests tr ON tr.id = wi.testing_request_id
                                WHERE tr.request_number = ANY(:n)
                                  AND date_trunc('month', si.completed_at) = date_trunc('month', NOW())""",
                         n=list(PM_NUMBERS)),
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

    if not have["taqc_month"]:
        # Department of the most recent CRITICAL result's equipment (the same
        # substation the CAR samples use), else the sample transformer's.
        row = _one(db, """
            SELECT e.department_id FROM public.test_results res
            JOIN public.testing_requests tr ON tr.id = res.testing_request_id
            JOIN public.equipment e ON e.id = tr.equipment_id
            WHERE tr.organization_id = :o AND res.evaluation_result->>'overall' = 'CRITICAL'
              AND e.department_id IS NOT NULL
            ORDER BY res.tested_at DESC NULLS LAST LIMIT 1""", o=org)
        m_dept = row[0] if row else dept_id
        cats = {name: cid for cid, name in db.execute(text("""
            SELECT MIN(id), name FROM public."CategoryDetails"
            WHERE category_type = 'inspection' GROUP BY name""")).all()}
        insp_id = uuid.uuid4()
        db.execute(text("""
            INSERT INTO public.taqc_annual_inspections
              (id, inspection_number, organization_id, department_id, inspection_date,
               inspected_by, remarks, created_by, cts, mts)
            VALUES (:id, :n, :o, :d, :dt, :u, '[SAMPLE] Monthly TA&QC inspection', :u, :c, :c)"""),
            dict(id=insp_id, n=INSP_MONTH_NUMBER, o=org, d=m_dept, dt=date.today(), u=user_id, c=now))
        obs = [
            ("Electrical Safety", "open",   "high",
             "[SAMPLE] Earthing strip corroded at transformer bay — replace"),
            ("Electrical Safety", "closed", "medium",
             "[SAMPLE] Danger board missing on isolator — fixed"),
            ("Fire Safety",       "closed", "low",
             "[SAMPLE] Fire extinguisher refill overdue — refilled"),
        ]
        for i, (cat_name, stage, sev, desc) in enumerate(obs, 1):
            cat_id = cats.get(cat_name) or cat[0]
            db.execute(text("""
                INSERT INTO public.taqc_observations
                  (id, inspection_id, observation_number, category_detail_id, severity,
                   target_compliance_date, observation_description, current_stage_code,
                   created_by, is_overdue, cts, mts)
                VALUES (:id, :i, :n, :cat, :sev, :tgt, :desc, :st, :u, false, :c, :c)"""),
                dict(id=uuid.uuid4(), i=insp_id, n=f"OBS-SAMPLE-{MONTH_TAG}-{i}", cat=cat_id,
                     sev=sev, tgt=date.today() + timedelta(days=30), desc=desc, st=stage,
                     u=user_id, c=now))
        print(f"  [OK] TA&QC inspection {INSP_MONTH_NUMBER} + 3 observations (1 open, 2 closed) for {date.today():%B %Y}")

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

    if not have["pm"]:
        # Maintenance Effectiveness Index: failure tickets whose PM Workflow
        # reached pm_completed, on equipment with a scored test (test_analytics
        # .health_score) before AND after the completion time. The completion
        # time is placed between two real scored tests of that equipment.
        pm_def = _one(db, "SELECT id FROM public.tr_wf_definitions "
                          "WHERE name='PM Workflow' AND is_active ORDER BY created_at LIMIT 1")
        cands = db.execute(text("""
            SELECT e.id, e.ueic, e.department_id, ta.tested_at
            FROM   public.test_analytics ta
            JOIN   public.equipment e ON e.id = ta.equipment_id
            WHERE  e.organization_id = :o AND e.department_id IS NOT NULL
              AND  ta.health_score IS NOT NULL
            ORDER  BY e.id, ta.tested_at"""), {"o": org}).all()
        by_eq = {}
        for eq_id, ueic, dept, tested in cands:
            by_eq.setdefault(eq_id, (ueic, dept, []))[2].append(tested)
        # Equipment with at least two scored tests on different days; complete
        # the maintenance halfway between its last two distinct test days.
        picks = []
        for eq_id, (ueic, dept, times) in by_eq.items():
            days = sorted({t.date(): t for t in times}.values())
            if len(days) >= 2:
                before, after = days[-2], days[-1]
                picks.append((eq_id, ueic, dept, before + (after - before) / 2))
            if len(picks) == 2:
                break
        if not pm_def or not picks:
            print("  [SKIP] no PM Workflow / equipment with two scored tests for Maintenance Effectiveness")
        for (eq_id, ueic, dept, done_at), number in zip(picks, PM_NUMBERS):
            tr_new = uuid.uuid4()
            db.execute(text("""
                INSERT INTO public.testing_requests
                  (id, request_number, title, request_category, status, originator_id,
                   organization_id, department_id, equipment_id, form_data,
                   is_cumulative, is_calibration, is_schedule_template, cts, mts)
                VALUES (:id, :n, :t, 'failure_registry', 'closed', :u,
                        :o, :d, :e, CAST(:fd AS jsonb), false, false, false, :c, :done)"""),
                dict(id=tr_new, n=number, t=f"[SAMPLE] PM after failure - {ueic}", u=user_id,
                     o=org, d=dept, e=eq_id, fd='{"failure_category": "Performance deterioration"}',
                     c=done_at - timedelta(days=5), done=done_at))
            db.execute(text("""
                INSERT INTO public.tr_wf_instances
                  (id, wf_definition_id, testing_request_id, entity_type, entity_id, org_id,
                   current_status_code, status, started_at, completed_at, created_by,
                   created_at, modified_at)
                VALUES (:id, :wd, :tr, 'testing_request', :tr, :o,
                        'pm_completed', 'completed', :s, :done, :u, :s, :done)"""),
                dict(id=uuid.uuid4(), wd=pm_def[0], tr=tr_new, o=org,
                     s=done_at - timedelta(days=5), done=done_at, u=user_id))
            print(f"  [OK] PM-completed failure ticket {number} on {ueic} (maintenance done {done_at:%Y-%m-%d %H:%M})")
    db.flush()

    _add_report_extras(db, org, user_id, now, _existing(db))
    db.commit()


def _add_report_extras(db, org, user_id, now, have):
    """Vendor Ranking, Result Review Compliance (this month), Post-Repair
    Evaluation, Transformer Repair Status and Failure Resolution samples."""
    # Power transformer with real test history from before LAST_YEAR-06-01,
    # to hang the repair / post-repair samples on.
    tr_eq = _one(db, """
        SELECT e.id, e.ueic, e.department_id, e.equipment_type_id
        FROM   public.equipment e
        JOIN   public."CategoryMaster" cm ON cm.id = e.equipment_type_id
        JOIN   public.testing_requests tr ON tr.equipment_id = e.id
        JOIN   public.test_results res ON res.testing_request_id = tr.id
        WHERE  e.organization_id = :o AND cm.name ILIKE '%power transformer%'
          AND  res.tested_at < :cut
        GROUP  BY e.id ORDER BY COUNT(res.id) DESC LIMIT 1""",
        o=org, cut=datetime(LAST_YEAR, 6, 1))

    # Vendor Performance Ranking: pre-commission requests this quarter
    if not have["vendor"] and tr_eq:
        start = now.replace(hour=0, minute=5, second=0, microsecond=0)
        vendors = [
            ("ABB India Ltd",      "approved", 2),
            ("ABB India Ltd",      "approved", 1),
            ("Siemens Energy Ltd", "rejected", 1),
        ]
        for (vendor, st, qty), number in zip(vendors, PC_NUMBERS):
            ok = st == "approved"
            db.execute(text("""
                INSERT INTO public.precommission_requests
                  (id, request_number, organization_id, equipment_type_id, vendor_name,
                   purchase_order_number, po_date, rated_mva, voltage_class, quantity,
                   approval_status, approved_by, approved_at, rejected_by, rejected_at,
                   dept_id, created_by, cts, mts)
                VALUES (:id, :n, :o, :t, :v, :po, :pod, '100', '220', :q, :st,
                        :ab, :aa, :rb, :ra, :d, :u, :c, :c)"""),
                dict(id=uuid.uuid4(), n=number, o=org, t=tr_eq[3], v=vendor,
                     po="PO-SAMPLE-" + number[-4:], pod=start.date(), q=qty, st=st,
                     ab=user_id if ok else None, aa=now if ok else None,
                     rb=None if ok else user_id, ra=None if ok else now,
                     d=tr_eq[2], u=user_id, c=start))
        print("  [OK] 3 sample pre-commission requests (ABB approved x2, Siemens rejected) this quarter")

    # Result Review Compliance: two closed result reviews this month
    if not have["review"]:
        stage = _one(db, """SELECT id, COALESCE(default_duration_hours, default_duration_days * 24)
                            FROM public.tr_wf_stages
                            WHERE is_result_stage AND name ILIKE '%result review%'
                              AND COALESCE(default_duration_hours, default_duration_days * 24) IS NOT NULL
                            LIMIT 1""")
        insts = db.execute(text("""SELECT wi.id FROM public.tr_wf_instances wi
                                   JOIN public.testing_requests tr ON tr.id = wi.testing_request_id
                                   WHERE tr.request_number = ANY(:n) ORDER BY tr.request_number"""),
                           {"n": list(PM_NUMBERS)}).scalars().all()
        if stage and insts:
            sla_h = float(stage[1])
            done = now - timedelta(minutes=30)
            # one reviewed within the SLA, one that overran it
            for inst, hours in zip(insts, (sla_h * 0.5, sla_h * 1.5)):
                db.execute(text("""
                    INSERT INTO public.tr_wf_stage_instances
                      (id, wf_instance_id, stage_id, status, started_at, completed_at)
                    VALUES (:id, :wi, :st, 'completed', :s, :c)"""),
                    dict(id=uuid.uuid4(), wi=inst, st=stage[0],
                         s=done - timedelta(hours=hours), c=done))
            print(f"  [OK] 2 closed result reviews this month (1 within the {sla_h:g}h SLA, 1 breached)")

    # Post-Repair Evaluation / Transformer Repair Status / Failure Resolution
    wf = _one(db, "SELECT id FROM public.repair_workflows WHERE workflow_number=:n", n=WF_NUMBER)
    if wf and tr_eq and not have["postrep"]:
        wf_id = wf[0]
        started = datetime(LAST_YEAR, 6, 1, 9, 0)
        finished = datetime(LAST_YEAR, 6, 20, 17, 0)
        stages = db.execute(text("""
            SELECT sd.id FROM public.repair_stage_definitions sd
            WHERE  sd.workflow_definition_id = (
                     SELECT workflow_definition_id FROM public.repair_stage_definitions
                     WHERE name = 'Failure Reporting' LIMIT 1)
            ORDER  BY sd.sequence""")).scalars().all()
        fr = _one(db, "SELECT id FROM public.testing_requests WHERE request_number=:n", n=FR_NUMBER)
        db.execute(text("""
            UPDATE public.repair_workflows
            SET    equipment_id = :e, created_at = :s, completed_at = :f,
                   current_stage_id = :cs, source_failure_id = :fr
            WHERE  id = :id"""),
            dict(e=tr_eq[0], s=started, f=finished, cs=stages[-1] if stages else None,
                 fr=fr[0] if fr else None, id=wf_id))
        step = (finished - started) / max(len(stages), 1)
        for i, sid in enumerate(stages):
            db.execute(text("""
                INSERT INTO public.repair_stage_instances
                  (id, workflow_id, stage_id, status, started_at, completed_at, created_at)
                VALUES (:id, :w, :s, 'completed', :a, :b, :a)"""),
                dict(id=uuid.uuid4(), w=wf_id, s=sid, a=started + step * i, b=started + step * (i + 1)))
        post_tr = uuid.uuid4()
        tested = finished + timedelta(days=10)
        db.execute(text("""
            INSERT INTO public.testing_requests
              (id, request_number, title, request_category, status, current_status_code,
               originator_id, organization_id, department_id, equipment_id, equipment_type_id,
               surveillance_workflow_id, is_cumulative, is_calibration, is_schedule_template,
               completed_at, cts, mts)
            VALUES (:id, :n, '[SAMPLE] Post-repair surveillance test', 'test', 'closed',
                    'wf_completed', :u, :o, :d, :e, :t, :w, false, false, false, :c, :c, :c)"""),
            dict(id=post_tr, n=POST_REPAIR_TR, u=user_id, o=org, d=tr_eq[2], e=tr_eq[0],
                 t=tr_eq[3], w=wf_id, c=tested))
        db.execute(text("""
            INSERT INTO public.test_results
              (id, testing_request_id, test_name, template_key, organization_id,
               evaluation_result, tested_at, tested_by)
            VALUES (:id, :tr, 'Post-repair SFRA', 'sfra_routine', :o,
                    CAST(:ev AS jsonb), :c, :u)"""),
            dict(id=uuid.uuid4(), tr=post_tr, o=org, c=tested, u=user_id,
                 ev='{"overall": "NORMAL", "fields": []}'))
        print(f"  [OK] sample repair moved to {tr_eq[1]} with {len(stages)} completed stages, "
              f"linked to {FR_NUMBER}, plus post-repair surveillance test {POST_REPAIR_TR}")


def remove(db):
    have = _existing(db)
    # Every TA&QC sample (the fixed one and each month's set).
    db.execute(text("""DELETE FROM public.taqc_observations WHERE inspection_id IN
                       (SELECT id FROM public.taqc_annual_inspections
                        WHERE inspection_number LIKE 'TAQC-SAMPLE-%')"""))
    db.execute(text("DELETE FROM public.taqc_annual_inspections WHERE inspection_number LIKE 'TAQC-SAMPLE-%'"))
    db.execute(text("DELETE FROM public.corrective_action_requests WHERE car_number = ANY(:n)"),
               {"n": list(CAR_NUMBERS)})
    db.execute(text("DELETE FROM public.precommission_requests WHERE request_number = ANY(:n)"),
               {"n": list(PC_NUMBERS)})
    db.execute(text("""DELETE FROM public.test_results WHERE testing_request_id IN
                       (SELECT id FROM public.testing_requests WHERE request_number = :n)"""),
               {"n": POST_REPAIR_TR})
    db.execute(text("DELETE FROM public.testing_requests WHERE request_number = :n"), {"n": POST_REPAIR_TR})
    db.execute(text("""DELETE FROM public.repair_stage_instances WHERE workflow_id IN
                       (SELECT id FROM public.repair_workflows WHERE workflow_number = :n)"""),
               {"n": WF_NUMBER})
    db.execute(text("""DELETE FROM public.tr_wf_stage_instances WHERE wf_instance_id IN
                       (SELECT wi.id FROM public.tr_wf_instances wi
                        JOIN public.testing_requests tr ON tr.id = wi.testing_request_id
                        WHERE tr.request_number = ANY(:n))"""),
               {"n": list(PM_NUMBERS)})
    db.execute(text("""DELETE FROM public.tr_wf_instances WHERE testing_request_id IN
                       (SELECT id FROM public.testing_requests WHERE request_number = ANY(:n))"""),
               {"n": list(PM_NUMBERS)})
    db.execute(text("DELETE FROM public.testing_requests WHERE request_number = ANY(:n)"),
               {"n": list(PM_NUMBERS)})
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
