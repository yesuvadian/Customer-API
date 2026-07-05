-- =============================================================================
-- Migration 029: Test Request Configurable Workflow Engine (tr_wf_*)
-- Creates a new parallel workflow engine for test request flows.
-- RepairStage* tables are NOT modified.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Workflow Definitions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_definitions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    request_type    VARCHAR(50),          -- normal | failure | special | NULL=all
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      UUID REFERENCES public.users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_by     UUID REFERENCES public.users(id) ON DELETE SET NULL,
    modified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_definitions_org ON tr_wf_definitions(org_id);

-- ---------------------------------------------------------------------------
-- 2. Configurable Statuses (per workflow definition)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_statuses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wf_definition_id    UUID NOT NULL REFERENCES tr_wf_definitions(id) ON DELETE CASCADE,
    status_code         VARCHAR(100) NOT NULL,   -- stable API identifier
    status_name         VARCHAR(200) NOT NULL,   -- editable display label
    sequence            INTEGER NOT NULL DEFAULT 0,
    color               VARCHAR(20),             -- hex badge color e.g. #3FA9F5
    approval_required   BOOLEAN NOT NULL DEFAULT FALSE,
    assignment_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_terminal         BOOLEAN NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_tr_wf_status_code UNIQUE (wf_definition_id, status_code)
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_statuses_def ON tr_wf_statuses(wf_definition_id);

-- ---------------------------------------------------------------------------
-- 3. Stage Definitions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_stages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wf_definition_id    UUID NOT NULL REFERENCES tr_wf_definitions(id) ON DELETE CASCADE,
    status_id           UUID REFERENCES tr_wf_statuses(id) ON DELETE SET NULL,
    name                VARCHAR(200) NOT NULL,
    code                VARCHAR(100) NOT NULL,
    sequence            INTEGER NOT NULL,
    weight              INTEGER NOT NULL DEFAULT 10,
    is_mandatory        BOOLEAN NOT NULL DEFAULT TRUE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    default_duration_days INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tr_wf_stage_code UNIQUE (wf_definition_id, code)
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_stages_def ON tr_wf_stages(wf_definition_id);

-- ---------------------------------------------------------------------------
-- 4. Stage Roles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_stage_roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage_id    UUID NOT NULL REFERENCES tr_wf_stages(id) ON DELETE CASCADE,
    role_id     UUID NOT NULL REFERENCES public.org_roles(id) ON DELETE CASCADE,
    can_approve BOOLEAN NOT NULL DEFAULT FALSE,
    can_assign  BOOLEAN NOT NULL DEFAULT FALSE,
    can_edit    BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_tr_wf_stage_role UNIQUE (stage_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_stage_roles_stage ON tr_wf_stage_roles(stage_id);
CREATE INDEX IF NOT EXISTS idx_tr_wf_stage_roles_role  ON tr_wf_stage_roles(role_id);

-- ---------------------------------------------------------------------------
-- 5. Stage Transitions
--    action_code: approve | reject | assign | return | cancel |
--                 complete | close | create_child | reassign
--    to_stage_id NULL = terminal.
--    Send-back rule: if target stage has 0 active roles → apply terminal_status_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_stage_transitions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_stage_id       UUID NOT NULL REFERENCES tr_wf_stages(id) ON DELETE CASCADE,
    to_stage_id         UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL,  -- NULL = terminal
    action_code         VARCHAR(50) NOT NULL,
    label               VARCHAR(100) NULL,  -- display label; falls back to action_code.title() if null
    requires_comment    BOOLEAN NOT NULL DEFAULT FALSE,
    is_rejection        BOOLEAN NOT NULL DEFAULT FALSE,
    terminal_status_id  UUID REFERENCES tr_wf_statuses(id) ON DELETE SET NULL,
    post_action         VARCHAR(100) NULL,  -- key into BaseWfAction registry, fired after transition
    CONSTRAINT uq_tr_wf_transition_action UNIQUE (from_stage_id, action_code)
);

-- Add label column if upgrading from an older schema (idempotent)
ALTER TABLE tr_wf_stage_transitions ADD COLUMN IF NOT EXISTS label VARCHAR(100) NULL;

CREATE INDEX IF NOT EXISTS idx_tr_wf_transitions_from ON tr_wf_stage_transitions(from_stage_id);

-- ---------------------------------------------------------------------------
-- 6. Workflow Instances (one per testing_request)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_instances (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wf_definition_id    UUID REFERENCES tr_wf_definitions(id) ON DELETE SET NULL,
    testing_request_id  UUID NOT NULL UNIQUE REFERENCES public.testing_requests(id) ON DELETE CASCADE,
    org_id              UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    current_stage_id    UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL,
    current_status_code VARCHAR(100),    -- denormalized for fast querying
    status              VARCHAR(20) NOT NULL DEFAULT 'active',  -- active | completed | terminated | cancelled
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    created_by          UUID REFERENCES public.users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_instances_request ON tr_wf_instances(testing_request_id);
CREATE INDEX IF NOT EXISTS idx_tr_wf_instances_status  ON tr_wf_instances(current_status_code);

-- ---------------------------------------------------------------------------
-- 7. Stage Instances (one per stage per workflow instance)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_stage_instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wf_instance_id  UUID NOT NULL REFERENCES tr_wf_instances(id) ON DELETE CASCADE,
    stage_id        UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL,
    status          VARCHAR(30) NOT NULL DEFAULT 'not_started',  -- not_started | in_progress | completed | rejected | returned
    action_taken    VARCHAR(50),         -- action_code that closed this instance
    assigned_user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    assigned_role_id UUID REFERENCES public.org_roles(id) ON DELETE SET NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    completed_by    UUID REFERENCES public.users(id) ON DELETE SET NULL,
    comment         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_stage_instances_wf    ON tr_wf_stage_instances(wf_instance_id);
CREATE INDEX IF NOT EXISTS idx_tr_wf_stage_instances_stage ON tr_wf_stage_instances(stage_id);

-- ---------------------------------------------------------------------------
-- 8. Audit Log (immutable, one row per transition)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_audit_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wf_instance_id      UUID NOT NULL REFERENCES tr_wf_instances(id) ON DELETE CASCADE,
    testing_request_id  UUID NOT NULL REFERENCES public.testing_requests(id) ON DELETE CASCADE,
    from_stage_id       UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL,
    to_stage_id         UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL,
    action_code         VARCHAR(50) NOT NULL,
    performed_by        UUID REFERENCES public.users(id) ON DELETE SET NULL,
    role_id             UUID REFERENCES public.org_roles(id) ON DELETE SET NULL,
    from_status_code    VARCHAR(100),
    to_status_code      VARCHAR(100),
    comment             TEXT,
    is_send_back        BOOLEAN NOT NULL DEFAULT FALSE,
    is_terminal         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_audit_wf      ON tr_wf_audit_logs(wf_instance_id);
CREATE INDEX IF NOT EXISTS idx_tr_wf_audit_request ON tr_wf_audit_logs(testing_request_id);

-- ---------------------------------------------------------------------------
-- 9. Alter testing_requests — add workflow engine fields
-- ---------------------------------------------------------------------------
ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS wf_instance_id      UUID REFERENCES tr_wf_instances(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS current_wf_stage_id UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS current_status_code VARCHAR(100),
    ADD COLUMN IF NOT EXISTS parent_request_id   UUID REFERENCES public.testing_requests(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS request_type        VARCHAR(50) DEFAULT 'normal';  -- normal | failure | special

CREATE INDEX IF NOT EXISTS idx_tr_requests_wf_instance ON public.testing_requests(wf_instance_id);
CREATE INDEX IF NOT EXISTS idx_tr_requests_status_code ON public.testing_requests(current_status_code);
CREATE INDEX IF NOT EXISTS idx_tr_requests_parent      ON public.testing_requests(parent_request_id);

-- ---------------------------------------------------------------------------
-- 10. Extend TesterRoleModuleRequirement — stage-scoped tester pool
-- ---------------------------------------------------------------------------
ALTER TABLE public.tester_role_module_requirements
    ADD COLUMN IF NOT EXISTS wf_stage_id UUID REFERENCES tr_wf_stages(id) ON DELETE SET NULL;

-- NULL wf_stage_id = global default (existing behavior preserved)

-- ---------------------------------------------------------------------------
-- 11. Routing Rules
--     Lookup order by specificity:
--     (request_type + equipment_type + test_type) > (equipment_type + test_type)
--     > (request_type only) > all-NULL catch-all.
--     Priority breaks ties at equal specificity.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_routing_rules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    wf_definition_id    UUID NOT NULL REFERENCES tr_wf_definitions(id) ON DELETE CASCADE,
    request_type        VARCHAR(50),          -- normal | failure | special | NULL=any
    equipment_type_id   INTEGER REFERENCES public."CategoryMaster"(id) ON DELETE SET NULL,
    test_type_id        INTEGER REFERENCES public."CategoryDetails"(id) ON DELETE SET NULL,
    priority            INTEGER NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          UUID REFERENCES public.users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tr_wf_routing_rules_org  ON tr_wf_routing_rules(org_id);
CREATE INDEX IF NOT EXISTS idx_tr_wf_routing_rules_type ON tr_wf_routing_rules(org_id, request_type, equipment_type_id, test_type_id);

-- ---------------------------------------------------------------------------
-- 12. Routing Defaults
--     One row per org — explicit placeholder, never a NULL catch-all in rules.
--     Engine raises WorkflowConfigError if neither table has a match.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tr_wf_routing_defaults (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL UNIQUE REFERENCES public.organizations(id) ON DELETE CASCADE,
    wf_definition_id    UUID REFERENCES tr_wf_definitions(id) ON DELETE SET NULL,
    updated_by          UUID REFERENCES public.users(id) ON DELETE SET NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
