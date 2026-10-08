-- Migration 045: Corrective Action Request (CAR) tables
--
-- Implements the CAR layer from the CM Recommendation -> Test Request ->
-- Evaluation -> CAR design: a CAR is the persistent corrective-action issue
-- that can span multiple Test Requests (original + follow-up + retests),
-- auto-created by the evaluation engine (see services/car_service.py) when
-- a test result evaluates CRITICAL - never created manually by a user.
--
-- car_test_requests is a separate many-to-many table (not a single FK on
-- either side) specifically so a failed retest attaches to the SAME CAR
-- instead of spawning a new one each time - see design doc section 6.

BEGIN;

CREATE TABLE IF NOT EXISTS public.corrective_action_requests (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    car_number            VARCHAR(50)  NOT NULL UNIQUE,

    -- What equipment/issue this CAR is about (denormalized from the
    -- originating test result for fast listing/filtering)
    equipment_id          UUID REFERENCES public.equipment(id) ON DELETE SET NULL,
    organization_id       UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    department_id         UUID REFERENCES public.org_departments(id) ON DELETE SET NULL,

    -- Origin: the test result whose evaluation triggered this CAR
    source_test_result_id UUID REFERENCES public.test_results(id) ON DELETE SET NULL,
    template_key          VARCHAR(100),
    severity              VARCHAR(20)  NOT NULL,   -- ALERT | CRITICAL (evaluation.overall at trigger time)

    summary               TEXT,                     -- auto-built from remedial_action_text
    corrective_action     TEXT,                     -- filled in as work progresses (previously a bare textarea, now tracked here per-CAR)

    status                VARCHAR(25)  NOT NULL DEFAULT 'OPEN',
        -- OPEN | ASSIGNED | IN_PROGRESS | PENDING_VERIFICATION | CLOSED | FAILED | REOPENED
    assigned_to           UUID REFERENCES public.users(id) ON DELETE SET NULL,
    due_date              DATE,

    -- Audit
    created_by            UUID REFERENCES public.users(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_by           UUID REFERENCES public.users(id),
    modified_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_car_equipment      ON public.corrective_action_requests (equipment_id);
CREATE INDEX IF NOT EXISTS ix_car_status         ON public.corrective_action_requests (status);
CREATE INDEX IF NOT EXISTS ix_car_organization   ON public.corrective_action_requests (organization_id);

CREATE TABLE IF NOT EXISTS public.car_test_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    car_id            UUID NOT NULL REFERENCES public.corrective_action_requests(id) ON DELETE CASCADE,
    test_request_id   UUID NOT NULL REFERENCES public.testing_requests(id) ON DELETE CASCADE,
    relationship_type VARCHAR(20) NOT NULL,  -- ORIGINATING | FOLLOW_UP | RETEST | VERIFICATION
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (car_id, test_request_id)
);

CREATE INDEX IF NOT EXISTS ix_car_tr_car     ON public.car_test_requests (car_id);
CREATE INDEX IF NOT EXISTS ix_car_tr_request ON public.car_test_requests (test_request_id);

COMMIT;
