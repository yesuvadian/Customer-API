-- Migration 048: mandatory SLA window for each CAR follow-up action.
--
-- A follow-up created from a CRITICAL finding must always carry a due date
-- - an open-ended ticket defeats the purpose of a corrective action. So
-- due_in_days is NOT NULL with a default, never left blank.

BEGIN;

ALTER TABLE public.car_trigger_followups
    ADD COLUMN IF NOT EXISTS due_in_days INTEGER NOT NULL DEFAULT 7;

ALTER TABLE public.car_trigger_followups
    ADD CONSTRAINT chk_ctf_due_in_days_positive CHECK (due_in_days > 0);

COMMIT;
