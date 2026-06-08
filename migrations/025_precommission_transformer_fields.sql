-- Migration 025: Add transformer-specific fields to precommission_requests
-- transformer_type, cooling_class, vector_group, quantity (already in table, just ensuring)

BEGIN;

ALTER TABLE public.precommission_requests
    ADD COLUMN IF NOT EXISTS transformer_type  VARCHAR(50),   -- Two-winding / Three-winding / Auto Transformer
    ADD COLUMN IF NOT EXISTS cooling_class     VARCHAR(20),   -- ONAN / ONAF / OFAF / ODAF
    ADD COLUMN IF NOT EXISTS vector_group      VARCHAR(30);   -- e.g. YNyn0d11

COMMIT;
