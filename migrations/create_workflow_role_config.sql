-- Migration: Create workflow_role_configs table
-- Purpose: Configure which roles can be assigned in workflows based on module permissions
-- This makes role assignment dynamic and permission-based

CREATE TABLE IF NOT EXISTS public.workflow_role_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Workflow type (e.g., "testing_request", "inspection_request")
    workflow_type VARCHAR(100) NOT NULL,

    -- Role assignment type (e.g., "tester", "inspector", "reviewer")
    assignment_type VARCHAR(100) NOT NULL,

    -- Module that must have permissions
    module_id INTEGER NOT NULL REFERENCES public.modules(id) ON DELETE CASCADE,

    -- Required permissions on the module
    requires_can_view BOOLEAN DEFAULT FALSE,
    requires_can_add BOOLEAN DEFAULT FALSE,
    requires_can_edit BOOLEAN DEFAULT FALSE,
    requires_can_delete BOOLEAN DEFAULT FALSE,
    requires_can_approve BOOLEAN DEFAULT FALSE,
    requires_can_assign BOOLEAN DEFAULT FALSE,

    -- Description
    description TEXT,

    -- Active flag
    is_active BOOLEAN DEFAULT TRUE,

    -- Audit fields
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_workflow_role_configs_workflow_type
ON public.workflow_role_configs(workflow_type) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_workflow_role_configs_assignment_type
ON public.workflow_role_configs(workflow_type, assignment_type) WHERE is_active = TRUE;

-- Add comments
COMMENT ON TABLE public.workflow_role_configs IS
'Configuration for role assignment in workflows based on module permissions.
Makes role selection dynamic - only roles with specific module permissions appear in dropdowns.';

COMMENT ON COLUMN public.workflow_role_configs.workflow_type IS
'Type of workflow (e.g., testing_request, inspection_request)';

COMMENT ON COLUMN public.workflow_role_configs.assignment_type IS
'Type of assignment in workflow (e.g., tester, inspector, approver)';

-- Seed default configuration for testing requests
-- Testing Request: Tester Assignment
-- Require roles to have FULL permissions (all flags TRUE) on "Testing Requests" module (ID: 45)
INSERT INTO public.workflow_role_configs (
    workflow_type,
    assignment_type,
    module_id,
    requires_can_view,
    requires_can_add,
    requires_can_edit,
    requires_can_delete,
    requires_can_approve,
    requires_can_assign,
    description,
    is_active
) VALUES (
    'testing_request',
    'tester',
    45,  -- Testing Requests module
    TRUE,
    TRUE,
    TRUE,
    TRUE,
    TRUE,
    TRUE,
    'Roles must have FULL permissions (all permissions) on Testing Requests module to be assigned as testers. This prevents admin roles that have broader access from appearing in the tester dropdown.',
    TRUE
) ON CONFLICT DO NOTHING;

-- Verification query (run separately)
-- SELECT wrc.*, m.name as module_name
-- FROM workflow_role_configs wrc
-- JOIN modules m ON m.id = wrc.module_id
-- WHERE wrc.workflow_type = 'testing_request';
