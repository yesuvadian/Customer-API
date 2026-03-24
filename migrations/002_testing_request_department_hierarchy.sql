-- Migration: Replace location string fields with department hierarchy
-- Date: 2026-03-22
-- Description: Replace zone, ce_circle, se_division, ee_subdivision, aee_section, ae_je
--              with department_id FK to org_departments table

-- ==========================================
-- STEP 1: Add new department_id column to testing_requests
-- ==========================================

ALTER TABLE public.testing_requests
ADD COLUMN department_id UUID;

-- Add foreign key constraint
ALTER TABLE public.testing_requests
ADD CONSTRAINT fk_testing_request_department
FOREIGN KEY (department_id)
REFERENCES public.org_departments(id)
ON DELETE SET NULL;

-- Add index for performance
CREATE INDEX idx_testing_requests_department_id
ON public.testing_requests(department_id);

-- ==========================================
-- STEP 2: Add department_id to tester_locations
-- ==========================================

ALTER TABLE public.tester_locations
ADD COLUMN department_id UUID;

-- Add foreign key constraint
ALTER TABLE public.tester_locations
ADD CONSTRAINT fk_tester_location_department
FOREIGN KEY (department_id)
REFERENCES public.org_departments(id)
ON DELETE SET NULL;

-- Add index for performance
CREATE INDEX idx_tester_locations_department_id
ON public.tester_locations(department_id);

-- ==========================================
-- STEP 3: Optional - Keep old columns for backward compatibility
-- ==========================================
-- Note: The old columns (zone, ce_circle, etc.) are NOT dropped
-- to maintain backward compatibility and data history.
-- New code should use department_id exclusively.
-- You can manually drop them later after full migration if needed:
--
-- ALTER TABLE public.testing_requests DROP COLUMN zone;
-- ALTER TABLE public.testing_requests DROP COLUMN ce_circle;
-- ALTER TABLE public.testing_requests DROP COLUMN se_division;
-- ALTER TABLE public.testing_requests DROP COLUMN ee_subdivision;
-- ALTER TABLE public.testing_requests DROP COLUMN aee_section;
-- ALTER TABLE public.testing_requests DROP COLUMN ae_je;
--
-- ALTER TABLE public.tester_locations DROP COLUMN zone;
-- ALTER TABLE public.tester_locations DROP COLUMN ce_circle;
-- ALTER TABLE public.tester_locations DROP COLUMN se_division;
-- ALTER TABLE public.tester_locations DROP COLUMN ee_subdivision;

-- ==========================================
-- STEP 4: Add organization_id to testing_requests
-- ==========================================
-- This links testing requests to organizations for multi-tenancy

ALTER TABLE public.testing_requests
ADD COLUMN organization_id UUID;

-- Add foreign key constraint
ALTER TABLE public.testing_requests
ADD CONSTRAINT fk_testing_request_organization
FOREIGN KEY (organization_id)
REFERENCES public.organizations(id)
ON DELETE CASCADE;

-- Add index
CREATE INDEX idx_testing_requests_organization_id
ON public.testing_requests(organization_id);

-- ==========================================
-- VERIFICATION QUERIES
-- ==========================================
-- Run these to verify the migration:
--
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'testing_requests'
-- ORDER BY ordinal_position;
--
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'tester_locations'
-- ORDER BY ordinal_position;
