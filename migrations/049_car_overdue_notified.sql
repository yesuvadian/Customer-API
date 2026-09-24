-- Migration 049: CAR overdue-notification marker.
--
-- The car_overdue check (main.py, every 15 min) needs a way to fire the
-- notification once per overdue CAR, not every single check cycle - same
-- "*_notified_at" marker pattern as the Result Review SLA breach check
-- (TrWfStageInstance.sla_notified_at).

BEGIN;

ALTER TABLE public.corrective_action_requests
    ADD COLUMN IF NOT EXISTS overdue_notified_at TIMESTAMPTZ;

COMMIT;
