-- =============================================
-- Rollback Migration: Remove Organization Multi-Tenancy
-- Description: Drop organization tables and columns from users table
-- Author: System
-- Date: 2026-03-21
-- =============================================

-- WARNING: This will delete all organization data!
-- Make sure to backup your database before running this rollback.

-- =============================================
-- 1. DROP TRIGGERS
-- =============================================
DROP TRIGGER IF EXISTS trigger_update_organizations_mts ON public.organizations;
DROP TRIGGER IF EXISTS trigger_update_org_departments_mts ON public.org_departments;
DROP TRIGGER IF EXISTS trigger_update_org_roles_mts ON public.org_roles;
DROP TRIGGER IF EXISTS trigger_update_org_role_permissions_mts ON public.org_role_permissions;
DROP TRIGGER IF EXISTS trigger_update_role_templates_mts ON public.role_templates;

-- =============================================
-- 2. REMOVE COLUMNS FROM USERS TABLE
-- =============================================
ALTER TABLE public.users
    DROP COLUMN IF EXISTS department_id,
    DROP COLUMN IF EXISTS employee_id,
    DROP COLUMN IF EXISTS organization_id;

-- =============================================
-- 3. DROP TABLES (in reverse dependency order)
-- =============================================
DROP TABLE IF EXISTS public.org_invitations CASCADE;
DROP TABLE IF EXISTS public.org_role_permissions CASCADE;
DROP TABLE IF EXISTS public.org_user_roles CASCADE;
DROP TABLE IF EXISTS public.org_roles CASCADE;
DROP TABLE IF EXISTS public.org_departments CASCADE;
DROP TABLE IF EXISTS public.role_templates CASCADE;
DROP TABLE IF EXISTS public.organizations CASCADE;

-- =============================================
-- ROLLBACK COMPLETE
-- =============================================
