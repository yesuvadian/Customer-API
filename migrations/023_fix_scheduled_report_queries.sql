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

COMMIT;
