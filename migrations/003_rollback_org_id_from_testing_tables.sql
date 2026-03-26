-- Rollback Migration: Remove organization_id from testing tables
-- Date: 2026-03-22

-- ==========================================
-- Drop indexes
-- ==========================================
DROP INDEX IF EXISTS public.idx_tester_locations_organization_id;
DROP INDEX IF EXISTS public.idx_test_results_organization_id;
DROP INDEX IF EXISTS public.idx_recommendations_organization_id;
DROP INDEX IF EXISTS public.idx_procurement_requests_organization_id;

-- ==========================================
-- Drop foreign key constraints
-- ==========================================
ALTER TABLE public.tester_locations
DROP CONSTRAINT IF EXISTS fk_tester_location_organization;

ALTER TABLE public.test_results
DROP CONSTRAINT IF EXISTS fk_test_result_organization;

ALTER TABLE public.recommendations
DROP CONSTRAINT IF EXISTS fk_recommendation_organization;

ALTER TABLE public.procurement_requests
DROP CONSTRAINT IF EXISTS fk_procurement_request_organization;

-- ==========================================
-- Drop columns
-- ==========================================
ALTER TABLE public.tester_locations
DROP COLUMN IF EXISTS organization_id;

ALTER TABLE public.test_results
DROP COLUMN IF EXISTS organization_id;

ALTER TABLE public.recommendations
DROP COLUMN IF EXISTS organization_id;

ALTER TABLE public.procurement_requests
DROP COLUMN IF EXISTS organization_id;
