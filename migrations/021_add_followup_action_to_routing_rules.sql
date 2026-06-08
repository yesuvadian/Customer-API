-- Migration 021: Add followup_action to notification_routing_rules
-- Stores auto follow-up ticket config for eval_alert / eval_critical events.
-- NULL = no auto follow-up (default).
--
-- Format:
-- {
--   "create_request": true,
--   "next_action": "maintenance",        -- test/maintenance/inspection/repair_cycle
--   "schedule_frequency": "yearly",
--   "schedule_start_date": "2026-01-01",
--   "schedule_end_date": "2026-12-31",
--   "test_types": [{"id": "uuid", "name": "BDV Test"}],
--   "summary": "Follow-up after CRITICAL alert"
-- }

ALTER TABLE public.notification_routing_rules
    ADD COLUMN IF NOT EXISTS followup_action JSONB NULL;

COMMENT ON COLUMN public.notification_routing_rules.followup_action IS
'Auto follow-up ticket config for eval_alert/eval_critical events.
Only applicable when org-specific override with specific equipment + test types.
NULL = no auto follow-up.';
