-- Migration 050: per-rule CAR due date, admin-configurable from the
-- existing CAR Trigger Config screen instead of the flat global
-- CAR_DUE_DAYS_CRITICAL/CAR_DUE_DAYS_ALERT .env constants (config.py).
--
-- NULL = inherit the global .env default for this severity (same
-- "override falls back to platform default" shape used by
-- CarTriggerFollowup.due_in_days and every other org-override table in
-- this codebase) -- so existing rows are unaffected until an admin sets
-- one explicitly.

BEGIN;

ALTER TABLE public.car_trigger_configs
    ADD COLUMN IF NOT EXISTS car_due_in_days INTEGER;

COMMIT;
