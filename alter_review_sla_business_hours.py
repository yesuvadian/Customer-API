#!/usr/bin/env python3
"""
One-time setup: make the Monthly Result Review Compliance Report's SLA
computation skip weekends, matching utils.business_days.add_business_hours()
(used by main.py's _check_review_sla_breaches escalation job and
routers/dashboard_kpi.py's review_sla_pct tile / review-SLA breach list --
see that commit for the full change).

Creates a Postgres add_business_hours(timestamp, numeric) function with the
exact same "pause the clock on Sat/Sun, resume Monday 00:00" semantics as
the Python version, then updates the existing result_review_compliance_report
ReportQueryKey row's sql_template to call it instead of raw interval math.

Deliberately NOT edited: seed.py itself -- same reasoning as
alter_notification_wf_stage_overdue_roles.py: a future full seed.py rerun
would otherwise silently reset this report back to calendar-time SLA math.
Rerun this script afterward if that happens.

Idempotent: CREATE OR REPLACE FUNCTION and a plain UPDATE by query_key --
safe to re-run.

Usage:
    python alter_review_sla_business_hours.py
"""
from sqlalchemy import text
from database import VendorSessionLocal
from models import ReportQueryKey

QUERY_KEY = "result_review_compliance_report"

CREATE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION add_business_hours(start_ts timestamp, hrs numeric)
RETURNS timestamp AS $$
DECLARE
    remaining   interval := (hrs || ' hours')::interval;
    current_ts  timestamp := start_ts;
    next_midnight timestamp;
    today_remaining interval;
BEGIN
    IF hrs <= 0 THEN
        RETURN start_ts;
    END IF;

    WHILE remaining > interval '0' LOOP
        -- ISODOW: Monday=1 .. Sunday=7 -- Saturday=6, Sunday=7
        IF EXTRACT(ISODOW FROM current_ts) IN (6, 7) THEN
            current_ts := date_trunc('day', current_ts) + interval '1 day';
            CONTINUE;
        END IF;

        next_midnight := date_trunc('day', current_ts) + interval '1 day';
        today_remaining := next_midnight - current_ts;

        IF remaining <= today_remaining THEN
            RETURN current_ts + remaining;
        END IF;

        remaining := remaining - today_remaining;
        current_ts := next_midnight;
    END LOOP;

    RETURN current_ts;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""

NEW_SQL_TEMPLATE = """
SELECT
    d4.name                         AS zone,
    d3.name                         AS ce_circle,
    d2.name                         AS ee_subdivision,
    d.name                          AS substation,
    COUNT(tsi.id)                   AS reviews_closed,
    COUNT(CASE WHEN tsi.completed_at <= add_business_hours(
        tsi.started_at, COALESCE(ws.default_duration_hours, ws.default_duration_days * 24)
    ) THEN 1 END)                   AS reviews_within_sla,
    ROUND(
        COUNT(CASE WHEN tsi.completed_at <= add_business_hours(
            tsi.started_at, COALESCE(ws.default_duration_hours, ws.default_duration_days * 24)
        ) THEN 1 END)::numeric
        / NULLIF(COUNT(tsi.id), 0) * 100, 1
    )                                AS compliance_pct
FROM   public.tr_wf_stage_instances tsi
JOIN   public.tr_wf_stages          ws ON ws.id = tsi.stage_id
JOIN   public.tr_wf_instances       wi ON wi.id = tsi.wf_instance_id
JOIN   public.testing_requests      tr ON tr.id = wi.testing_request_id
LEFT JOIN public.equipment          e  ON e.id  = tr.equipment_id
LEFT JOIN public.org_departments    d  ON d.id  = e.department_id
LEFT JOIN public.org_departments    d2 ON d2.id = d.parent_department_id
LEFT JOIN public.org_departments    d3 ON d3.id = d2.parent_department_id
LEFT JOIN public.org_departments    d4 ON d4.id = d3.parent_department_id
WHERE  ws.is_result_stage IS TRUE
  AND  tsi.status IN ('completed', 'rejected')
  AND  tsi.started_at IS NOT NULL
  AND  tsi.completed_at IS NOT NULL
  AND  (ws.default_duration_hours IS NOT NULL OR ws.default_duration_days IS NOT NULL)
  AND  EXTRACT(MONTH FROM tsi.completed_at)
         = COALESCE(:month, EXTRACT(MONTH FROM NOW()))
  AND  EXTRACT(YEAR  FROM tsi.completed_at)
         = COALESCE(:year,  EXTRACT(YEAR  FROM NOW()))
  {org_clause}
  AND  (:department_id IS NULL OR d.id = :department_id::uuid)
GROUP  BY d4.name, d3.name, d2.name, d.name
ORDER  BY compliance_pct ASC NULLS LAST
"""


def main():
    db = VendorSessionLocal()
    try:
        db.execute(text(CREATE_FUNCTION_SQL))
        db.commit()
        print("[OK] add_business_hours(timestamp, numeric) function created/replaced.")

        qk = db.query(ReportQueryKey).filter_by(key=QUERY_KEY).first()
        if not qk:
            print(f"[WARN] No ReportQueryKey row found for key={QUERY_KEY!r} -- "
                  f"run seed.py's report query-key seeder first.")
            return
        qk.sql_template = NEW_SQL_TEMPLATE
        db.commit()
        print(f"[OK] ReportQueryKey({QUERY_KEY!r}).sql_template updated to use add_business_hours.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
