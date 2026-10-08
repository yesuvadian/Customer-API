-- Migration 047: CAR trigger config supports MULTIPLE follow-up actions per
-- rule (not just one), matching the "New Testing Request" form's own
-- pattern of letting a user multi-select several test types under one
-- Request Type (Test/Maintenance/Inspection/Repair) and creating one
-- independent TestingRequest per selection.
--
-- Replaces the single follow_up_test_type_id column added in migration 046
-- with a child table so one (equipment_type, test_type, severity) rule can
-- fan out to N follow-ups spanning different categories.

BEGIN;

CREATE TABLE IF NOT EXISTS public.car_trigger_followups (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    car_trigger_config_id   UUID NOT NULL REFERENCES public.car_trigger_configs(id) ON DELETE CASCADE,

    -- The follow-up's own test/maintenance/inspection type. Its
    -- CategoryDetails.category_type tells the hook whether to create a
    -- TestingRequest (test/maintenance/inspection) or start a repair
    -- workflow instead (repair_lifecycle) - same branch the create-request
    -- form itself takes.
    follow_up_test_type_id  INTEGER NOT NULL REFERENCES public."CategoryDetails"(id) ON DELETE CASCADE,

    display_order           INTEGER NOT NULL DEFAULT 0,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (car_trigger_config_id, follow_up_test_type_id)
);

CREATE INDEX IF NOT EXISTS ix_ctf_config ON public.car_trigger_followups (car_trigger_config_id);

-- The singular column from migration 046 is superseded by the child table
-- above on both tables it was added to.
ALTER TABLE public.car_trigger_configs DROP COLUMN IF EXISTS follow_up_test_type_id;
ALTER TABLE public.corrective_action_requests DROP COLUMN IF EXISTS follow_up_test_type_id;

COMMIT;
