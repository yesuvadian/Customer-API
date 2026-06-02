-- Migration 020: Add digest_columns to notification_schedule_rules
-- Allows per-rule configuration of which columns appear in digest email tables.
-- NULL = use system DEFAULT_DIGEST_COLUMNS defined in NotificationService.

ALTER TABLE public.notification_schedule_rules
    ADD COLUMN IF NOT EXISTS digest_columns JSONB NULL;

COMMENT ON COLUMN public.notification_schedule_rules.digest_columns IS
'Optional JSON array of column definitions for the {{digest_table}} HTML table.
NULL = use NotificationService.DEFAULT_DIGEST_COLUMNS.
Format: [{"field": "equipment", "header": "Equipment", "style": "width:20%"}, ...]
Supported fields: equipment, department, due_date, days, request, status, priority, category, assigned_to';
