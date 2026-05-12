from sqlalchemy import text
from database import engine

DDL = """
-- Stamp calibration flag on every testing request (like is_cumulative)
ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS is_calibration BOOLEAN NOT NULL DEFAULT FALSE;

-- Per-equipment calibration schedule config
CREATE TABLE IF NOT EXISTS public.equipment_calibration_configs (
    id UUID PRIMARY KEY,
    equipment_id UUID NOT NULL UNIQUE REFERENCES public.equipment(id) ON DELETE CASCADE,
    lead_days INTEGER NOT NULL DEFAULT 30,
    is_scheduled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    cts TIMESTAMPTZ DEFAULT now(),
    mts TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_equipment_calibration_configs_equipment_id
    ON public.equipment_calibration_configs(equipment_id);
"""


def run():
    with engine.begin() as conn:
        conn.execute(text(DDL))
    print("Calibration migration complete.")


if __name__ == "__main__":
    run()
