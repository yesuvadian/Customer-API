-- Migration: Add is_tester_assignable column to org_roles table
-- Purpose: Configure which roles can be assigned as testers in testing requests
-- This prevents admin roles from appearing in tester dropdown

-- Add the column
ALTER TABLE public.org_roles
ADD COLUMN IF NOT EXISTS is_tester_assignable BOOLEAN DEFAULT FALSE;

-- Update existing Tester roles to be assignable
-- Update roles with 'tester' in name (case-insensitive) but NOT admin roles
UPDATE public.org_roles
SET is_tester_assignable = TRUE
WHERE LOWER(name) LIKE '%tester%'
  AND NOT is_org_admin
  AND NOT is_dept_admin
  AND is_active = TRUE;

-- Create index for performance
CREATE INDEX IF NOT EXISTS idx_org_roles_tester_assignable
ON public.org_roles(is_tester_assignable)
WHERE is_tester_assignable = TRUE AND is_active = TRUE;

-- Verification query (run separately to check results)
-- SELECT id, name, is_tester_assignable, is_org_admin, is_dept_admin, is_active
-- FROM public.org_roles
-- WHERE organization_id = '<your-org-id>'
-- ORDER BY name;

COMMENT ON COLUMN public.org_roles.is_tester_assignable IS
'Indicates if this role can be assigned as a tester in testing request workflows.
Prevents admin roles from appearing in tester selection dropdown.';
