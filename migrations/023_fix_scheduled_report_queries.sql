-- ============================================================================
-- Migration 023 — Fix scheduled report query templates against real schema
-- ============================================================================
-- Several report_query_keys SQL templates referenced tables/columns that do
-- not exist in the live schema, causing the scheduler to error every run:
--   • failure_registry        → FR lives in testing_requests (request_category)
--   • workflow_sessions        → repair_workflows / repair_stage_instances
--   • taqc_inspections         → taqc_observations + taqc_annual_inspections
--   • tr.category              → tr.request_category (handled in migration prior)
--   • procurement vendor cols  → not captured → Vendor Performance deactivated
--
-- Uses dollar-quoting ($sql$ … $sql$) so single quotes inside the SQL need no
-- escaping. Idempotent — safe to run multiple times.
-- ============================================================================

BEGIN;

-- ── 1. Equipment Failure Annual — FR is testing_requests(request_category) ──
UPDATE public.report_query_keys
SET org_alias = 'tr',
    sql_template = $sql$
SELECT
    cm.name                                              AS equipment_type,
    e.manufacturer                                       AS make,
    e.voltage_class,
    COUNT(tr.id)                                         AS failure_count,
    COUNT(DISTINCT e.id)                                 AS units_affected,
    STRING_AGG(DISTINCT tr.form_data->>'failure_category', ', ') AS failure_categories
FROM   public.testing_requests tr
JOIN   public.equipment        e   ON e.id   = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
WHERE  tr.request_category = 'failure_registry'
  AND  EXTRACT(YEAR FROM tr.cts)
         = COALESCE(:year, EXTRACT(YEAR FROM NOW())::int - 1)
  {org_clause}
GROUP  BY cm.name, e.manufacturer, e.voltage_class
ORDER  BY failure_count DESC
$sql$
WHERE key = 'equipment_failure_annual_report';

-- ── 2. Transformer Repair Status — repair_workflows + stage instances ──────
UPDATE public.report_query_keys
SET org_alias = 'wf',
    sql_template = $sql$
SELECT
    e.ueic,
    e.manufacturer,
    e.voltage_class,
    d.name                                  AS department,
    wf.id                                   AS workflow_id,
    wf.status                               AS workflow_status,
    wf.created_at::date                     AS started_date,
    sd.name                                 AS current_stage,
    COUNT(si.id) FILTER (WHERE si.status = 'completed') AS stages_done,
    COUNT(si.id)                            AS stages_total,
    ROUND(COALESCE(wf.progress, 0)::numeric, 1) AS pct_complete,
    EXTRACT(DAY FROM NOW() - wf.created_at)::int AS days_elapsed
FROM   public.repair_workflows wf
JOIN   public.equipment        e  ON e.id  = wf.equipment_id
LEFT JOIN public.org_departments d ON d.id = e.department_id
LEFT JOIN public.repair_stage_definitions sd ON sd.id = wf.current_stage_id
LEFT JOIN public.repair_stage_instances   si ON si.workflow_id = wf.id
WHERE  wf.workflow_type = 'repair_lifecycle'
  AND  e.equipment_type_id IN (
           SELECT id FROM public."CategoryMaster" WHERE name ILIKE '%transformer%')
  {org_clause}
  AND  (:date_from::date IS NULL OR wf.created_at >= :date_from::date)
  AND  (:date_to::date   IS NULL OR wf.created_at <= :date_to::date)
  AND  (:department_id   IS NULL OR e.department_id = :department_id::uuid)
GROUP  BY e.ueic, e.manufacturer, e.voltage_class, d.name, wf.id,
          wf.status, wf.created_at, sd.name, wf.progress
ORDER  BY wf.created_at DESC
$sql$
WHERE key = 'transformer_repair_status_report';

-- ── 3. Repairer Performance — repair_workflows.vendor_name ─────────────────
UPDATE public.report_query_keys
SET org_alias = 'wf',
    sql_template = $sql$
SELECT
    wf.vendor_name                          AS repairer_name,
    COUNT(wf.id)                            AS total_workflows,
    COUNT(CASE WHEN wf.status = 'completed' THEN 1 END) AS completed,
    ROUND(
        AVG(EXTRACT(DAY FROM wf.completed_at - wf.created_at))
            FILTER (WHERE wf.completed_at IS NOT NULL), 1
    )                                       AS avg_turnaround_days
FROM   public.repair_workflows wf
WHERE  wf.workflow_type = 'repair_lifecycle'
  AND  EXTRACT(YEAR FROM wf.created_at)
         = COALESCE(:year, EXTRACT(YEAR FROM NOW())::int - 1)
  AND  wf.vendor_name IS NOT NULL
  {org_clause}
GROUP  BY wf.vendor_name
ORDER  BY avg_turnaround_days ASC NULLS LAST
$sql$
WHERE key = 'repairer_performance_report';

-- ── 4. TA&QC Observation Compliance — taqc_observations + annual_inspections ─
UPDATE public.report_query_keys
SET org_alias = 'tai',
    sql_template = $sql$
SELECT
    d.name                                  AS department,
    cd.name                                 AS observation_category,
    COUNT(ti.id)                            AS total_observations,
    COUNT(CASE WHEN ti.current_stage_code ILIKE '%clos%' THEN 1 END) AS closed,
    COUNT(CASE WHEN ti.current_stage_code NOT ILIKE '%clos%'
                 OR ti.current_stage_code IS NULL THEN 1 END)        AS open,
    ROUND(
        COUNT(CASE WHEN ti.current_stage_code ILIKE '%clos%' THEN 1 END)::numeric
        / NULLIF(COUNT(ti.id), 0) * 100, 1
    )                                       AS compliance_pct,
    MAX(EXTRACT(DAY FROM NOW() - ti.cts))::int AS max_age_days
FROM   public.taqc_observations ti
JOIN   public.taqc_annual_inspections tai ON tai.id = ti.inspection_id
LEFT JOIN public.org_departments d  ON d.id  = tai.department_id
LEFT JOIN public."CategoryDetails" cd ON cd.id = ti.category_detail_id
WHERE  EXTRACT(MONTH FROM ti.cts) = COALESCE(:month, EXTRACT(MONTH FROM NOW()))
  AND  EXTRACT(YEAR  FROM ti.cts) = COALESCE(:year,  EXTRACT(YEAR  FROM NOW()))
  {org_clause}
  AND  (:department_id IS NULL OR tai.department_id = :department_id::uuid)
GROUP  BY d.name, cd.name
ORDER  BY compliance_pct ASC NULLS LAST
$sql$
WHERE key = 'taqc_compliance_report';

-- ── 5. Vendor Performance — schema has no vendor/decision/delivery data ─────
--      Deactivate scheduling until procurement vendor tracking exists.
UPDATE public.report_definitions
SET is_active = FALSE, mts = now()
WHERE query_key = 'vendor_performance_report';

-- ── 6. Equipment Lifecycle — failure_registry join → testing_requests ──────
UPDATE public.report_query_keys
SET sql_template = $sql$
SELECT
    e.ueic,
    cm.name                             AS equipment_type,
    e.voltage_class,
    e.manufacturer,
    e.status,
    d.name                              AS department,
    e.commissioned_date,
    COUNT(DISTINCT tr.id)               AS total_tests,
    COUNT(DISTINCT fr.id)               AS total_failures,
    MAX(res.tested_at)                  AS last_tested_at,
    (SELECT res2.evaluation_result->>'overall'
     FROM   public.test_results res2
     JOIN   public.testing_requests req2 ON req2.id = res2.testing_request_id
     WHERE  req2.equipment_id = e.id
     ORDER  BY res2.tested_at DESC LIMIT 1) AS last_result
FROM   public.equipment e
LEFT JOIN public.org_departments  d   ON d.id  = e.department_id
LEFT JOIN public."CategoryMaster" cm  ON cm.id = e.equipment_type_id
LEFT JOIN public.testing_requests tr  ON tr.equipment_id = e.id
LEFT JOIN public.testing_requests fr  ON fr.equipment_id = e.id
                                     AND fr.request_category = 'failure_registry'
LEFT JOIN public.test_results     res ON res.testing_request_id = tr.id
WHERE  1=1
  {org_clause}
  AND  (:status        IS NULL OR e.status        = :status)
  AND  (:voltage_class IS NULL OR e.voltage_class = :voltage_class)
  AND  (:department_id IS NULL OR e.department_id = :department_id::uuid)
  AND  (:date_from::date IS NULL OR e.commissioned_date >= :date_from::date)
  AND  (:date_to::date   IS NULL OR e.commissioned_date <= :date_to::date)
GROUP  BY e.id, e.ueic, cm.name, e.voltage_class, e.manufacturer,
          e.status, d.name, e.commissioned_date
ORDER  BY e.ueic
$sql$
WHERE key = 'equipment_lifecycle_report';

-- ── 7. Equipment Failure Performance — failure_registry → testing_requests ──
UPDATE public.report_query_keys
SET org_alias = 'fr',
    sql_template = $sql$
SELECT
    cm.name                     AS equipment_type,
    e.manufacturer              AS make,
    e.voltage_class,
    CASE
        WHEN (DATE_PART('year', NOW()) - e.year_of_manufacture::int)
             BETWEEN 0  AND 10 THEN '0-10 years'
        WHEN (DATE_PART('year', NOW()) - e.year_of_manufacture::int)
             BETWEEN 11 AND 20 THEN '11-20 years'
        ELSE '>20 years'
    END                         AS age_band,
    COUNT(fr.id)                AS failure_count,
    COUNT(DISTINCT e.id)        AS unit_count,
    ROUND(COUNT(fr.id)::numeric / NULLIF(COUNT(DISTINCT e.id), 0), 2)
                                AS failure_rate_per_unit
FROM   public.testing_requests fr
JOIN   public.equipment        e   ON e.id   = fr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
WHERE  fr.request_category = 'failure_registry'
  {org_clause}
  AND  (:date_from::date IS NULL OR fr.cts >= :date_from::date)
  AND  (:date_to::date   IS NULL OR fr.cts <= :date_to::date)
  AND  (:equipment_type  IS NULL OR cm.name ILIKE '%' || :equipment_type || '%')
  AND  (:make            IS NULL OR e.manufacturer ILIKE '%' || :make || '%')
  AND  (:voltage_class   IS NULL OR e.voltage_class = :voltage_class)
GROUP  BY cm.name, e.manufacturer, e.voltage_class, age_band
ORDER  BY failure_rate_per_unit DESC NULLS LAST
$sql$
WHERE key = 'equipment_failure_performance_report';

-- ── 8. Failure Resolution — failure_registry + workflow_sessions ───────────
UPDATE public.report_query_keys
SET org_alias = 'fr',
    sql_template = $sql$
SELECT
    fr.request_number           AS fr_number,
    e.ueic                      AS equipment_ueic,
    cm.name                     AS equipment_type,
    fr.form_data->>'failure_category' AS failure_category,
    fr.form_data->>'next_action'      AS resolution_outcome,
    fr.status                   AS approval_status,
    fr.cts::date                AS failure_date,
    wf.status                   AS linked_workflow_status,
    wf.id                       AS linked_workflow_id
FROM   public.testing_requests fr
JOIN   public.equipment        e   ON e.id   = fr.equipment_id
LEFT JOIN public."CategoryMaster"   cm ON cm.id = e.equipment_type_id
LEFT JOIN public.repair_workflows   wf ON wf.source_failure_id = fr.id
WHERE  fr.request_category = 'failure_registry'
  {org_clause}
  AND  (:date_from::date IS NULL OR fr.cts >= :date_from::date)
  AND  (:date_to::date   IS NULL OR fr.cts <= :date_to::date)
  AND  (:outcome IS NULL OR :outcome = 'all'
        OR fr.form_data->>'next_action' = :outcome)
ORDER  BY fr.cts DESC
$sql$
WHERE key = 'failure_resolution_report';

-- ── 9. Post-Repair Evaluation — workflow_sessions → repair_workflows ───────
UPDATE public.report_query_keys
SET org_alias = 'wf',
    sql_template = $sql$
SELECT
    e.ueic,
    e.manufacturer,
    e.voltage_class,
    d.name                              AS department,
    wf.id                               AS workflow_id,
    wf.completed_at::date               AS completion_date,
    pre.evaluation_result ->>'overall'  AS pre_repair_result,
    post.evaluation_result->>'overall'  AS post_repair_result,
    pre.tested_at                       AS pre_repair_tested_at,
    post.tested_at                      AS post_repair_tested_at
FROM   public.repair_workflows wf
JOIN   public.equipment          e  ON e.id  = wf.equipment_id
LEFT JOIN public.org_departments d  ON d.id  = e.department_id
LEFT JOIN LATERAL (
    SELECT res.evaluation_result, res.tested_at
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id AND res.tested_at < wf.created_at
    ORDER  BY res.tested_at DESC LIMIT 1
) pre  ON true
LEFT JOIN LATERAL (
    SELECT res.evaluation_result, res.tested_at
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id
      AND  req.surveillance_workflow_id IS NOT NULL
      AND  res.tested_at    > wf.completed_at
    ORDER  BY res.tested_at ASC LIMIT 1
) post ON true
WHERE  wf.workflow_type  = 'repair_lifecycle'
  AND  wf.completed_at IS NOT NULL
  {org_clause}
  AND  (:workflow_id IS NULL OR wf.id = :workflow_id::uuid)
  AND  (:date_from::date IS NULL OR wf.completed_at >= :date_from::date)
  AND  (:date_to::date   IS NULL OR wf.completed_at <= :date_to::date)
ORDER  BY wf.completed_at DESC
$sql$
WHERE key = 'post_repair_evaluation_report';

COMMIT;
