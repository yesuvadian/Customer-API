-- Migration 051: drop the CAR overdue notification feature
--
-- Removes what migrations 049/050 added. The CAR-level overdue check
-- (car_due_in_days, overdue_notified_at, the car_overdue notification
-- event) turned out to duplicate the existing generic "Test Overdue" /
-- "Test Overdue Escalation" alerts (overdue_alert/overdue_escalation),
-- which already fire for the auto-created follow-up TestingRequest once
-- it passes its own due_date -- the common case for every CAR that has an
-- active follow-up configured. Keeping both meant two alarms for the same
-- delay, plus a save-time consistency check (routers/car_trigger_config.py)
-- that existed only to stop the two independently-configured due-day
-- numbers from drifting apart. car.due_date itself is untouched -- it's a
-- pre-existing, informational field (creation default / manual reassign)
-- unrelated to this notification job.

ALTER TABLE public.corrective_action_requests DROP COLUMN IF EXISTS overdue_notified_at;
ALTER TABLE public.car_trigger_configs DROP COLUMN IF EXISTS car_due_in_days;

DELETE FROM public.notification_templates WHERE event_type = 'car_overdue';
DELETE FROM public.notification_event_catalogue WHERE event_type = 'car_overdue';
