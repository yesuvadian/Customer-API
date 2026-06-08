-- ============================================================================
-- Migration 022 — Threshold-alert notification enhancements
-- ============================================================================
-- Bundles the schema + data changes for:
--   1. advanced_conditions column on notification_routing_rules
--      (per-rule test-type scoping for threshold alerts)
--   2. {{eval.testname}} system notification variable (user-friendly test name)
--   3. Global eval_alert / eval_critical EMAIL templates updated to use
--      {{eval.testname}} instead of {{eval.test_type}}
--
-- Idempotent — safe to run multiple times.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. advanced_conditions column on notification_routing_rules
--    JSONB, e.g. {"activity_types": ["Short Circuit Test HV-IV"]}
--    NULL / absent = rule applies to all tests for the equipment.
-- ----------------------------------------------------------------------------
ALTER TABLE public.notification_routing_rules
    ADD COLUMN IF NOT EXISTS advanced_conditions JSONB;

-- ----------------------------------------------------------------------------
-- 2. {{eval.testname}} system notification variable
--    Resolves the user-friendly test name. Falls back through
--    test_name -> eval.test_type so existing fire() contexts populate it.
-- ----------------------------------------------------------------------------
INSERT INTO public.notification_variables
    (id, organization_id, var_key, label, group_name, description,
     sample_value, resolver_key, role_template_ids, fallback_keys,
     is_system, is_active, cts, mts)
SELECT gen_random_uuid(), NULL, 'eval.testname', 'Test Name', 'Evaluation',
       'User-friendly test name (e.g. Short Circuit Test HV-IV).',
       'Short Circuit Test HV-IV', 'test_name', '[]'::jsonb,
       '["test_name", "eval.test_type"]'::jsonb,
       TRUE, TRUE, now(), now()
WHERE NOT EXISTS (
    SELECT 1 FROM public.notification_variables
    WHERE var_key = 'eval.testname' AND organization_id IS NULL
);

-- Keep the row correct whether it was just inserted or already existed.
UPDATE public.notification_variables
SET    label         = 'Test Name',
       group_name    = 'Evaluation',
       description   = 'User-friendly test name (e.g. Short Circuit Test HV-IV).',
       sample_value  = 'Short Circuit Test HV-IV',
       resolver_key  = 'test_name',
       fallback_keys = '["test_name", "eval.test_type"]'::jsonb,
       is_system     = TRUE,
       is_active     = TRUE,
       mts           = now()
WHERE  var_key = 'eval.testname'
  AND  organization_id IS NULL;

-- ----------------------------------------------------------------------------
-- 3. Global eval_alert / eval_critical EMAIL templates → use {{eval.testname}}
--    Only touches GLOBAL rows where organization_id IS NULL. Org overrides untouched.
-- ----------------------------------------------------------------------------
UPDATE public.notification_templates
SET    subject_template = REPLACE(subject_template, '{{eval.test_type}}', '{{eval.testname}}'),
       body_template    = REPLACE(body_template,    '{{eval.test_type}}', '{{eval.testname}}'),
       mts              = now()
WHERE  organization_id IS NULL
  AND  channel = 'email'
  AND  event_type IN ('eval_alert', 'eval_critical')
  AND  (subject_template LIKE '%{{eval.test_type}}%'
        OR body_template LIKE '%{{eval.test_type}}%');

-- ----------------------------------------------------------------------------
-- 4. Global eval_alert EMAIL: the inline {{report.retriepdf}} link is broken
--    (test-result reports have no public URL — they are emailed as attachments).
--    Replace the broken link with the threshold-config table + "attached" note,
--    and attach the PDF the same way eval_critical does.
-- ----------------------------------------------------------------------------
UPDATE public.notification_templates
SET    body_template = REPLACE(
           body_template,
           '<p><a href=''{{report.retriepdf}}''>Download PDF Report</a></p>',
           '<h4 style=''margin-top:14px''>Threshold Configuration</h4>{{alert.thresholdconfig}}<p>The evaluation report is attached to this email.</p>'
       ),
       attachment_vars = '[{"var_key": "report.retriepdf", "type": "pdf"}]'::jsonb,
       mts             = now()
WHERE  organization_id IS NULL
  AND  channel = 'email'
  AND  event_type = 'eval_alert'
  AND  body_template LIKE '%<a href=''{{report.retriepdf}}''>%';

COMMIT;
