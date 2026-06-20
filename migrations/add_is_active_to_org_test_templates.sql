-- Migration: add is_active column to org_test_templates
-- Run once against the target database.

ALTER TABLE public.org_test_templates
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- Back-fill existing rows (already defaulted above, but explicit for clarity)
UPDATE public.org_test_templates SET is_active = TRUE WHERE is_active IS NULL;
