-- Migration: Add gps_coordinates column to equipment table
-- Purpose: models.py's Equipment class maps this column (added alongside
-- the Data Quality Index feature, since a DQI rule was created against it
-- as a live-only raw column and then formalized into the ORM model) — any
-- environment deploying that models.py change needs this column to exist,
-- or every Equipment query will fail with an unknown-column error.

ALTER TABLE public.equipment
ADD COLUMN IF NOT EXISTS gps_coordinates VARCHAR(100);
