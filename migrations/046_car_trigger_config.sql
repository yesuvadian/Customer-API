-- Migration 046: CAR trigger configuration (per Equipment Type + Test Type + Severity)
--
-- Replaces the hardcoded CAR_TRIGGER_SEVERITIES = {"CRITICAL"} constant in
-- services/car_service.py with an admin-editable rule, same pattern as
-- ConditionMonitoringRecommendation (score -> recommended test/frequency):
-- here it's (equipment_type, test_type, severity) -> does this trigger a
-- CAR, and if so what test type should the follow-up/retest be against.
--
-- Absence of a matching row falls back to the pre-existing hardcoded
-- default (CRITICAL triggers, ALERT doesn't) - so equipment types with no
-- config yet keep working exactly as before, and nothing breaks on rollout.

BEGIN;

CREATE TABLE IF NOT EXISTS public.car_trigger_configs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- NULL organization_id = global default (same convention as
    -- ConditionMonitoringRecommendation) — an org-specific row overrides it.
    organization_id         UUID REFERENCES public.organizations(id) ON DELETE CASCADE,

    equipment_type_id       INTEGER NOT NULL REFERENCES public."CategoryMaster"(id) ON DELETE CASCADE,

    -- NULL test_type_id = applies to every test type under this equipment
    -- type (a wildcard default), overridden by a more specific row when
    -- both exist for the same equipment_type + severity.
    test_type_id            INTEGER REFERENCES public."CategoryDetails"(id) ON DELETE CASCADE,

    severity                VARCHAR(20) NOT NULL,   -- ALERT | CRITICAL

    car_trigger             BOOLEAN NOT NULL DEFAULT TRUE,

    -- Which test type the follow-up/retest should be raised against.
    -- NULL = same test type as the one that triggered (today's default
    -- behaviour via equipment+test_type sibling matching in car_service.py).
    follow_up_test_type_id  INTEGER REFERENCES public."CategoryDetails"(id) ON DELETE SET NULL,

    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    display_order           INTEGER NOT NULL DEFAULT 0,

    created_by              UUID REFERENCES public.users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (organization_id, equipment_type_id, test_type_id, severity)
);

CREATE INDEX IF NOT EXISTS ix_ctc_equipment_type ON public.car_trigger_configs (equipment_type_id);
CREATE INDEX IF NOT EXISTS ix_ctc_org             ON public.car_trigger_configs (organization_id);

-- corrective_action_requests: record the recommended follow-up test type at
-- the moment the CAR was created, for display in the CAR detail view — the
-- config could change later, but the CAR should keep showing what applied
-- when it was raised.
ALTER TABLE public.corrective_action_requests
    ADD COLUMN IF NOT EXISTS follow_up_test_type_id INTEGER REFERENCES public."CategoryDetails"(id) ON DELETE SET NULL;

COMMIT;
