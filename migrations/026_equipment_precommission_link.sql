-- Migration 026: Add precommission_request_id FK to equipment table
-- Allows direct lookup of which PCR a transformer was commissioned from.

BEGIN;

ALTER TABLE public.equipment
    ADD COLUMN IF NOT EXISTS precommission_request_id UUID
        REFERENCES public.precommission_requests(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_equipment_pcr
    ON public.equipment(precommission_request_id);

COMMIT;
