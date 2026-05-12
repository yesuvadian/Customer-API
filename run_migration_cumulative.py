from sqlalchemy import text
from database import engine

DDL = """
ALTER TABLE repair_workflows
    ADD COLUMN IF NOT EXISTS workflow_type VARCHAR(50) DEFAULT 'BREAKDOWN',
    ADD COLUMN IF NOT EXISTS source VARCHAR(50);

ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS is_cumulative BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS public.equipment_overhaul_configs (
    id UUID PRIMARY KEY,
    equipment_id UUID NOT NULL UNIQUE REFERENCES public.equipment(id) ON DELETE CASCADE,
    threshold_value DOUBLE PRECISION NOT NULL,
    created_by UUID REFERENCES public.users(id),
    cts TIMESTAMPTZ DEFAULT now(),
    mts TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_equipment_overhaul_configs_equipment_id
    ON public.equipment_overhaul_configs(equipment_id);

CREATE TABLE IF NOT EXISTS public.overhaul_recommendations (
    id UUID PRIMARY KEY,
    equipment_id UUID NOT NULL REFERENCES public.equipment(id) ON DELETE CASCADE,
    workflow_id UUID REFERENCES repair_workflows(id) ON DELETE SET NULL,
    cumulative_value DOUBLE PRECISION NOT NULL,
    threshold_value DOUBLE PRECISION NOT NULL,
    status VARCHAR(20) DEFAULT 'OPEN',
    triggered_at TIMESTAMPTZ DEFAULT now(),
    closed_at TIMESTAMPTZ,
    created_by UUID REFERENCES public.users(id)
);

CREATE INDEX IF NOT EXISTS ix_overhaul_recommendations_equipment_id
    ON public.overhaul_recommendations(equipment_id);
CREATE INDEX IF NOT EXISTS ix_overhaul_recommendations_status
    ON public.overhaul_recommendations(status);
"""


def run():
    with engine.begin() as conn:
        conn.execute(text(DDL))
    print("Cumulative migration complete.")


if __name__ == "__main__":
    run()
