-- Migration 053: corrective_action_requests.has_closed_once
--
-- car_service.py sets status = REOPENED whenever a follow-up/retest fails
-- again while the CAR is still OPEN (see _apply_test_result), even if the
-- CAR has never actually been CLOSED once. That is correct for the internal
-- "needs another retest" state machine (OPEN_STATUSES, unresolved_test_types,
-- etc. all rely on REOPENED meaning "still needs work"), but it produces a
-- misleading "REOPENED" label in the UI for a CAR that was never closed.
--
-- has_closed_once is set exactly once, inside services/car_service.py's
-- _close() (the single CLOSE transition point), and never cleared. The API
-- and frontend use it to compute a display status: show "OPEN" instead of
-- "REOPENED" when has_closed_once is false, without touching the underlying
-- status column or any of the business logic that reads it.

BEGIN;

ALTER TABLE public.corrective_action_requests
    ADD COLUMN IF NOT EXISTS has_closed_once BOOLEAN NOT NULL DEFAULT false;

-- Backfill: any CAR that is currently CLOSED, VOIDED (voids only happen from
-- OPEN_STATUSES per void_car, so a VOIDED car was never closed - leave those
-- false), or has a non-null closed_at has closed at least once.
UPDATE public.corrective_action_requests
   SET has_closed_once = true
 WHERE status = 'CLOSED' OR closed_at IS NOT NULL;

COMMIT;
