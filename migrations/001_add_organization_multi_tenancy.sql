-- =============================================
-- Migration: Add Organization Multi-Tenancy
-- Description: Create organization tables and update users table
-- Author: System
-- Date: 2026-03-21
-- =============================================

-- =============================================
-- 1. CREATE ORGANIZATIONS TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(255),

    organization_type VARCHAR(50),
    industry VARCHAR(100),
    website VARCHAR(255),

    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,

    plan_id UUID REFERENCES public.plans(id),
    subscription_start_date TIMESTAMP WITH TIME ZONE,
    subscription_end_date TIMESTAMP WITH TIME ZONE,

    primary_email VARCHAR(255),
    primary_phone VARCHAR(50),

    settings JSONB DEFAULT '{}',

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    erp_sync_status VARCHAR(10) DEFAULT 'pending',
    erp_last_sync_at TIMESTAMP WITH TIME ZONE,
    erp_error_message TEXT,
    erp_external_id VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_organizations_code ON public.organizations(code);
CREATE INDEX IF NOT EXISTS idx_organizations_plan_id ON public.organizations(plan_id);

COMMENT ON TABLE public.organizations IS 'Multi-tenant organizations table';

-- =============================================
-- 2. CREATE ORG_DEPARTMENTS TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.org_departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    code VARCHAR(100),
    description TEXT,

    parent_department_id UUID REFERENCES public.org_departments(id) ON DELETE SET NULL,
    manager_id UUID REFERENCES public.users(id) ON DELETE SET NULL,

    is_active BOOLEAN DEFAULT TRUE,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    erp_sync_status VARCHAR(10) DEFAULT 'pending',
    erp_last_sync_at TIMESTAMP WITH TIME ZONE,
    erp_error_message TEXT,
    erp_external_id VARCHAR(255),

    CONSTRAINT uq_org_dept_name UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_org_departments_organization_id ON public.org_departments(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_departments_parent_id ON public.org_departments(parent_department_id);
CREATE INDEX IF NOT EXISTS idx_org_departments_manager_id ON public.org_departments(manager_id);

COMMENT ON TABLE public.org_departments IS 'Organization departments/divisions';

-- =============================================
-- 3. CREATE ORG_ROLES TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.org_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,

    name VARCHAR(100) NOT NULL,
    description TEXT,
    role_type VARCHAR(50) DEFAULT 'custom',

    is_org_admin BOOLEAN DEFAULT FALSE,
    is_dept_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_org_role_name UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_org_roles_organization_id ON public.org_roles(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_roles_is_org_admin ON public.org_roles(is_org_admin) WHERE is_org_admin = TRUE;

COMMENT ON TABLE public.org_roles IS 'Organization-scoped roles';

-- =============================================
-- 4. CREATE ORG_USER_ROLES TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.org_user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    org_role_id UUID NOT NULL REFERENCES public.org_roles(id) ON DELETE CASCADE,
    department_id UUID REFERENCES public.org_departments(id) ON DELETE CASCADE,

    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    assigned_by UUID REFERENCES public.users(id),
    is_active BOOLEAN DEFAULT TRUE,

    CONSTRAINT uq_user_org_role UNIQUE (user_id, org_role_id, department_id)
);

CREATE INDEX IF NOT EXISTS idx_org_user_roles_user_id ON public.org_user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_org_user_roles_org_role_id ON public.org_user_roles(org_role_id);
CREATE INDEX IF NOT EXISTS idx_org_user_roles_department_id ON public.org_user_roles(department_id);

COMMENT ON TABLE public.org_user_roles IS 'User role assignments within organizations';

-- =============================================
-- 5. CREATE ORG_ROLE_PERMISSIONS TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.org_role_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_role_id UUID NOT NULL REFERENCES public.org_roles(id) ON DELETE CASCADE,
    module_id INTEGER NOT NULL REFERENCES public.modules(id) ON DELETE CASCADE,

    can_view BOOLEAN DEFAULT FALSE,
    can_add BOOLEAN DEFAULT FALSE,
    can_edit BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    can_approve BOOLEAN DEFAULT FALSE,
    can_assign BOOLEAN DEFAULT FALSE,
    can_export BOOLEAN DEFAULT FALSE,
    can_import BOOLEAN DEFAULT FALSE,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_org_role_module UNIQUE (org_role_id, module_id)
);

CREATE INDEX IF NOT EXISTS idx_org_role_permissions_org_role_id ON public.org_role_permissions(org_role_id);
CREATE INDEX IF NOT EXISTS idx_org_role_permissions_module_id ON public.org_role_permissions(module_id);

COMMENT ON TABLE public.org_role_permissions IS 'Module permissions for organization roles';

-- =============================================
-- 6. CREATE ROLE_TEMPLATES TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.role_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,

    is_org_admin BOOLEAN DEFAULT FALSE,
    is_dept_admin BOOLEAN DEFAULT FALSE,
    auto_provision BOOLEAN DEFAULT FALSE,

    permissions_template JSONB DEFAULT '[]',

    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE public.role_templates IS 'System-level role templates for auto-provisioning';

-- =============================================
-- 7. CREATE ORG_INVITATIONS TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.org_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,

    email VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),

    org_role_id UUID REFERENCES public.org_roles(id),
    department_id UUID REFERENCES public.org_departments(id),

    invitation_token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    status VARCHAR(20) DEFAULT 'pending',
    accepted_at TIMESTAMP WITH TIME ZONE,
    accepted_by_user_id UUID REFERENCES public.users(id),

    invited_by UUID NOT NULL REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_org_invitation_email UNIQUE (organization_id, email, status)
);

CREATE INDEX IF NOT EXISTS idx_org_invitations_organization_id ON public.org_invitations(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_invitations_email ON public.org_invitations(email);
CREATE INDEX IF NOT EXISTS idx_org_invitations_token ON public.org_invitations(invitation_token);

COMMENT ON TABLE public.org_invitations IS 'Organization user invitations';

-- =============================================
-- 8. ALTER USERS TABLE - ADD ORGANIZATION COLUMNS
-- =============================================
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES public.org_departments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_users_organization_id ON public.users(organization_id);
CREATE INDEX IF NOT EXISTS idx_users_department_id ON public.users(department_id);
CREATE INDEX IF NOT EXISTS idx_users_employee_id ON public.users(employee_id);

COMMENT ON COLUMN public.users.organization_id IS 'Organization the user belongs to';
COMMENT ON COLUMN public.users.employee_id IS 'Employee/Vendor ID within organization';
COMMENT ON COLUMN public.users.department_id IS 'Department the user belongs to';

-- =============================================
-- 9. CREATE FUNCTION TO AUTO-UPDATE TIMESTAMPS
-- =============================================
CREATE OR REPLACE FUNCTION update_modified_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.mts = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- 10. CREATE TRIGGERS FOR AUTO-UPDATE TIMESTAMPS
-- =============================================
DO $$
BEGIN
    -- Organizations
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_update_organizations_mts') THEN
        CREATE TRIGGER trigger_update_organizations_mts
            BEFORE UPDATE ON public.organizations
            FOR EACH ROW
            EXECUTE FUNCTION update_modified_timestamp();
    END IF;

    -- Org Departments
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_update_org_departments_mts') THEN
        CREATE TRIGGER trigger_update_org_departments_mts
            BEFORE UPDATE ON public.org_departments
            FOR EACH ROW
            EXECUTE FUNCTION update_modified_timestamp();
    END IF;

    -- Org Roles
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_update_org_roles_mts') THEN
        CREATE TRIGGER trigger_update_org_roles_mts
            BEFORE UPDATE ON public.org_roles
            FOR EACH ROW
            EXECUTE FUNCTION update_modified_timestamp();
    END IF;

    -- Org Role Permissions
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_update_org_role_permissions_mts') THEN
        CREATE TRIGGER trigger_update_org_role_permissions_mts
            BEFORE UPDATE ON public.org_role_permissions
            FOR EACH ROW
            EXECUTE FUNCTION update_modified_timestamp();
    END IF;

    -- Role Templates
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_update_role_templates_mts') THEN
        CREATE TRIGGER trigger_update_role_templates_mts
            BEFORE UPDATE ON public.role_templates
            FOR EACH ROW
            EXECUTE FUNCTION update_modified_timestamp();
    END IF;
END $$;

-- =============================================
-- MIGRATION COMPLETE
-- =============================================
-- To apply this migration, run:
-- psql -U [username] -d [database] -f 001_add_organization_multi_tenancy.sql
