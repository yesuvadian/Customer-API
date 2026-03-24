-- ================================================
-- Migration: Tester Role Module Requirements
-- Purpose: Configure exact module match for tester role selection
-- Date: 2026-03-23
-- ================================================

-- Create configuration table
CREATE TABLE IF NOT EXISTS public.tester_role_module_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Organization (NULL = global default for all orgs)
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,

    -- Required module IDs (role must have EXACTLY these)
    required_module_ids INTEGER[] NOT NULL,

    -- Metadata
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,

    -- Audit fields
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,

    -- Ensure one config per org
    CONSTRAINT uq_tester_role_config_org UNIQUE(organization_id)
);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_tester_role_requirements_org_active
ON public.tester_role_module_requirements(organization_id)
WHERE is_active = TRUE;

-- Add comments for documentation
COMMENT ON TABLE public.tester_role_module_requirements IS
'Configuration for tester role selection. Defines which modules a role must have (with full permissions) to appear in tester assignment dropdown.';

COMMENT ON COLUMN public.tester_role_module_requirements.required_module_ids IS
'Array of module IDs. Role must have FULL permissions (all 6 flags) on EXACTLY these modules to be selectable as tester.';

COMMENT ON COLUMN public.tester_role_module_requirements.organization_id IS
'Organization-specific config. NULL = global default for all organizations.';

-- Seed global default configuration
-- Modules: 45=Testing Requests, 46=Testing, 49=Testing Request Approvals, 51=Tester Mapping
INSERT INTO public.tester_role_module_requirements (
    organization_id,
    required_module_ids,
    description,
    is_active
) VALUES (
    NULL,  -- Global default
    ARRAY[45, 46, 49, 51],
    'Global default: Roles must have full permissions on Testing Requests, Testing, Testing Request Approvals, and Tester Mapping modules',
    TRUE
) ON CONFLICT (organization_id) DO NOTHING;

-- Verification query
SELECT
    id,
    organization_id,
    required_module_ids,
    array_length(required_module_ids, 1) as module_count,
    description,
    is_active
FROM public.tester_role_module_requirements;
