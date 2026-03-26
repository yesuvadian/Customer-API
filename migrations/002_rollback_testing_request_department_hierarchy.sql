-- Rollback Migration: Remove department hierarchy from testing requests
-- Date: 2026-03-22

-- ==========================================
-- STEP 1: Drop testing_requests columns and constraints
-- ==========================================

-- Drop indexes
DROP INDEX IF EXISTS public.idx_testing_requests_department_id;
DROP INDEX IF EXISTS public.idx_testing_requests_organization_id;

-- Drop foreign key constraints
ALTER TABLE public.testing_requests
DROP CONSTRAINT IF EXISTS fk_testing_request_department;

ALTER TABLE public.testing_requests
DROP CONSTRAINT IF EXISTS fk_testing_request_organization;

-- Drop columns
ALTER TABLE public.testing_requests
DROP COLUMN IF EXISTS department_id;

ALTER TABLE public.testing_requests
DROP COLUMN IF EXISTS organization_id;

-- ==========================================
-- STEP 2: Drop tester_locations columns and constraints
-- ==========================================

-- Drop index
DROP INDEX IF EXISTS public.idx_tester_locations_department_id;

-- Drop foreign key constraint
ALTER TABLE public.tester_locations
DROP CONSTRAINT IF EXISTS fk_tester_location_department;

-- Drop column
ALTER TABLE public.tester_locations
DROP COLUMN IF EXISTS department_id;

-- ==========================================
-- VERIFICATION
-- ==========================================
-- Verify columns are removed:
--
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'testing_requests'
-- ORDER BY ordinal_position;
