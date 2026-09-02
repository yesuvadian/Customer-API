-- Migration 044: Detailed Project Report (DPR) projects table
-- A DprProject is the entity anchoring the DPR approval workflow (see
-- seed_dpr_workflow.py: RepairWorkflowDefinition workflow_code='DPR_APPROVAL').
-- On creation, a RepairWorkflow (entity_type='dpr_project', entity_id=this
-- row's id) is auto-created at the Initiation stage — same pattern as
-- precommission_requests / TAQCObservation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.dpr_projects (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_number           VARCHAR(50)  NOT NULL UNIQUE,

    title                    VARCHAR(255) NOT NULL,
    description              TEXT,
    project_category         VARCHAR(100),   -- free text for now, promote to a lookup table if a fixed taxonomy is wanted

    -- Organization / department / equipment
    organization_id          UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    proposing_department_id  UUID REFERENCES public.org_departments(id) ON DELETE SET NULL,
    equipment_id             UUID REFERENCES public.equipment(id) ON DELETE SET NULL,

    -- Denormalized headline cost figures (mirrored from Cost Estimation /
    -- Authority Approval stage form_data by DprProjectService) — the
    -- authoritative figures still live in repair_stage_data.form_data.
    estimated_cost           NUMERIC(14,2),
    approved_cost            NUMERIC(14,2),

    status                   VARCHAR(20)  NOT NULL DEFAULT 'active',  -- active | completed | cancelled

    -- Workflow link (set at creation) + denormalized current stage code
    workflow_id              UUID REFERENCES public.repair_workflows(id) ON DELETE SET NULL,
    current_stage_code       VARCHAR(50),

    -- Audit
    created_by               UUID REFERENCES public.users(id),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_by              UUID REFERENCES public.users(id),
    modified_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dpr_projects_org        ON public.dpr_projects(organization_id);
CREATE INDEX IF NOT EXISTS idx_dpr_projects_dept        ON public.dpr_projects(proposing_department_id);
CREATE INDEX IF NOT EXISTS idx_dpr_projects_equipment   ON public.dpr_projects(equipment_id);
CREATE INDEX IF NOT EXISTS idx_dpr_projects_workflow    ON public.dpr_projects(workflow_id);
CREATE INDEX IF NOT EXISTS idx_dpr_projects_stage_code  ON public.dpr_projects(current_stage_code);
CREATE INDEX IF NOT EXISTS idx_dpr_projects_number      ON public.dpr_projects(project_number);

COMMIT;
