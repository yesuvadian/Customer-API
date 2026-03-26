-- Migration: Add organization_id to all testing-related tables
-- Date: 2026-03-22
-- Description: Add organization_id to tester_locations, test_results, recommendations, and procurement_requests

-- ==========================================
-- STEP 1: Add organization_id to tester_locations
-- ==========================================

ALTER TABLE public.tester_locations
ADD COLUMN IF NOT EXISTS organization_id UUID;

-- Add foreign key constraint
ALTER TABLE public.tester_locations
DROP CONSTRAINT IF EXISTS fk_tester_location_organization;

ALTER TABLE public.tester_locations
ADD CONSTRAINT fk_tester_location_organization
FOREIGN KEY (organization_id)
REFERENCES public.organizations(id)
ON DELETE CASCADE;

-- Add index
CREATE INDEX IF NOT EXISTS idx_tester_locations_organization_id
ON public.tester_locations(organization_id);

-- ==========================================
-- STEP 2: Add organization_id to test_results
-- ==========================================

ALTER TABLE public.test_results
ADD COLUMN IF NOT EXISTS organization_id UUID;

-- Add foreign key constraint
ALTER TABLE public.test_results
DROP CONSTRAINT IF EXISTS fk_test_result_organization;

ALTER TABLE public.test_results
ADD CONSTRAINT fk_test_result_organization
FOREIGN KEY (organization_id)
REFERENCES public.organizations(id)
ON DELETE CASCADE;

-- Add index
CREATE INDEX IF NOT EXISTS idx_test_results_organization_id
ON public.test_results(organization_id);

-- ==========================================
-- STEP 3: Add organization_id to recommendations
-- ==========================================

ALTER TABLE public.recommendations
ADD COLUMN IF NOT EXISTS organization_id UUID;

-- Add foreign key constraint
ALTER TABLE public.recommendations
DROP CONSTRAINT IF EXISTS fk_recommendation_organization;

ALTER TABLE public.recommendations
ADD CONSTRAINT fk_recommendation_organization
FOREIGN KEY (organization_id)
REFERENCES public.organizations(id)
ON DELETE CASCADE;

-- Add index
CREATE INDEX IF NOT EXISTS idx_recommendations_organization_id
ON public.recommendations(organization_id);

-- ==========================================
-- STEP 4: Add organization_id to procurement_requests
-- ==========================================

ALTER TABLE public.procurement_requests
ADD COLUMN IF NOT EXISTS organization_id UUID;

-- Add foreign key constraint
ALTER TABLE public.procurement_requests
DROP CONSTRAINT IF EXISTS fk_procurement_request_organization;

ALTER TABLE public.procurement_requests
ADD CONSTRAINT fk_procurement_request_organization
FOREIGN KEY (organization_id)
REFERENCES public.organizations(id)
ON DELETE CASCADE;

-- Add index
CREATE INDEX IF NOT EXISTS idx_procurement_requests_organization_id
ON public.procurement_requests(organization_id);

-- ==========================================
-- STEP 5: Optional - Populate organization_id from testing_requests
-- ==========================================
-- This helps migrate existing data by copying organization_id from parent testing_request

-- Update test_results.organization_id from testing_requests
UPDATE public.test_results tr
SET organization_id = req.organization_id
FROM public.testing_requests req
WHERE tr.testing_request_id = req.id
AND tr.organization_id IS NULL
AND req.organization_id IS NOT NULL;

-- Update recommendations.organization_id from testing_requests
UPDATE public.recommendations r
SET organization_id = req.organization_id
FROM public.testing_requests req
WHERE r.testing_request_id = req.id
AND r.organization_id IS NULL
AND req.organization_id IS NOT NULL;

-- Update procurement_requests.organization_id from testing_requests
UPDATE public.procurement_requests pr
SET organization_id = req.organization_id
FROM public.testing_requests req
WHERE pr.testing_request_id = req.id
AND pr.organization_id IS NULL
AND req.organization_id IS NOT NULL;

-- ==========================================
-- VERIFICATION QUERIES
-- ==========================================
-- Run these to verify the migration:
--
-- SELECT table_name, column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
-- AND table_name IN ('tester_locations', 'test_results', 'recommendations', 'procurement_requests')
-- AND column_name = 'organization_id'
-- ORDER BY table_name;
--
-- SELECT constraint_name, table_name
-- FROM information_schema.table_constraints
-- WHERE table_schema = 'public'
-- AND constraint_name LIKE '%organization%'
-- AND table_name IN ('tester_locations', 'test_results', 'recommendations', 'procurement_requests');
