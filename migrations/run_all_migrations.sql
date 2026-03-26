-- ============================================================
-- RUN ALL MIGRATIONS IN ORDER
-- ============================================================
-- Executes all migration scripts in the correct sequence
-- ============================================================

\echo '============================================================'
\echo 'Starting Fresh Database Migration'
\echo '============================================================'

-- Step 0a: Enable Extensions
\echo ''
\echo '0a. Enabling PostgreSQL Extensions...'
\i 000_enable_extensions.sql

-- Step 0b: Create Base Tables
\echo ''
\echo '0b. Creating Base Tables...'
\i 000_create_base_tables.sql

-- Step 1: Organization Multi-Tenancy
\echo ''
\echo '1. Creating Organization Multi-Tenancy Tables...'
\i 001_add_organization_multi_tenancy.sql

-- Step 2: Testing Request Department Hierarchy
\echo ''
\echo '2. Adding Department Hierarchy to Testing Requests...'
\i 002_testing_request_department_hierarchy.sql

-- Step 3: Organization ID to Testing Tables
\echo ''
\echo '3. Adding Organization ID to Testing Tables...'
\i 003_add_org_id_to_testing_tables.sql

-- Step 4: Workflow Engine
\echo ''
\echo '4. Creating Workflow Engine Tables...'
\i 004_workflow_engine.sql

\echo ''
\echo '============================================================'
\echo 'All Migrations Completed Successfully!'
\echo '============================================================'
