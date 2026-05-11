from sqlalchemy import text

from database import engine


DDL = """
ALTER TABLE repair_workflow_definitions
    ADD COLUMN IF NOT EXISTS workflow_code VARCHAR(100);

CREATE UNIQUE INDEX IF NOT EXISTS uq_repair_workflow_definitions_code
    ON repair_workflow_definitions(workflow_code)
    WHERE workflow_code IS NOT NULL;

ALTER TABLE repair_workflows
    ADD COLUMN IF NOT EXISTS workflow_code VARCHAR(100),
    ADD COLUMN IF NOT EXISTS entity_type VARCHAR(100),
    ADD COLUMN IF NOT EXISTS entity_id UUID;

CREATE INDEX IF NOT EXISTS ix_repair_workflows_workflow_code
    ON repair_workflows(workflow_code);
CREATE INDEX IF NOT EXISTS ix_repair_workflows_entity_type
    ON repair_workflows(entity_type);
CREATE INDEX IF NOT EXISTS ix_repair_workflows_entity_id
    ON repair_workflows(entity_id);

CREATE TABLE IF NOT EXISTS public.taqc_annual_inspections (
    id UUID PRIMARY KEY,
    inspection_number VARCHAR(50) UNIQUE NOT NULL,
    organization_id UUID NOT NULL REFERENCES public.organizations(id),
    substation_id UUID NOT NULL REFERENCES public.equipment(id),
    inspection_date DATE NOT NULL,
    inspected_by UUID REFERENCES public.users(id),
    remarks TEXT,
    created_by UUID REFERENCES public.users(id),
    cts TIMESTAMPTZ DEFAULT now(),
    mts TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_taqc_annual_inspections_number
    ON public.taqc_annual_inspections(inspection_number);

CREATE TABLE IF NOT EXISTS public.taqc_observations (
    id UUID PRIMARY KEY,
    inspection_id UUID NOT NULL REFERENCES public.taqc_annual_inspections(id) ON DELETE CASCADE,
    observation_number VARCHAR(50) UNIQUE NOT NULL,
    category_detail_id INTEGER NOT NULL REFERENCES public."CategoryDetails"(id),
    template_id UUID REFERENCES public.org_test_templates(id),
    workflow_id UUID REFERENCES repair_workflows(id),
    severity VARCHAR(20),
    target_compliance_date DATE,
    observation_description TEXT,
    current_stage_code VARCHAR(100),
    created_by UUID REFERENCES public.users(id),
    assigned_to UUID REFERENCES public.users(id),
    reviewer_id UUID REFERENCES public.users(id),
    is_overdue BOOLEAN DEFAULT false,
    cts TIMESTAMPTZ DEFAULT now(),
    mts TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_taqc_observations_inspection_id
    ON public.taqc_observations(inspection_id);
CREATE INDEX IF NOT EXISTS ix_taqc_observations_number
    ON public.taqc_observations(observation_number);
CREATE INDEX IF NOT EXISTS ix_taqc_observations_workflow_id
    ON public.taqc_observations(workflow_id);
CREATE INDEX IF NOT EXISTS ix_taqc_observations_stage
    ON public.taqc_observations(current_stage_code);
"""


def main():
    with engine.begin() as conn:
        conn.execute(text(DDL))
    print("Annual Audit migration applied.")


if __name__ == "__main__":
    main()
