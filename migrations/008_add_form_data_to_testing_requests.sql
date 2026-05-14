-- Migration 008: add form_data JSONB to testing_requests
-- Stores FR dynamic template fields + recommendation snapshot in one column.
-- Safe to run multiple times (IF NOT EXISTS guard).

ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS form_data JSONB;
