-- ============================================================
-- DROP ALL TABLES - COMPLETE DATABASE RESET
-- ============================================================
-- WARNING: This will delete ALL data!
-- Use only for development/testing
-- ============================================================

-- Drop workflow tables
DROP TABLE IF EXISTS workflow_audit_log CASCADE;
DROP TABLE IF EXISTS permission_matrix CASCADE;
DROP TABLE IF EXISTS workflow_transitions CASCADE;
DROP TABLE IF EXISTS workflow_states CASCADE;
DROP TABLE IF EXISTS workflows CASCADE;

-- Drop workflow functions
DROP FUNCTION IF EXISTS update_workflow_mts() CASCADE;
DROP FUNCTION IF EXISTS get_available_transitions(UUID, UUID, UUID, UUID) CASCADE;

-- Drop testing request system tables
DROP TABLE IF EXISTS procurement_requests CASCADE;
DROP TABLE IF EXISTS recommendations CASCADE;
DROP TABLE IF EXISTS test_result_images CASCADE;
DROP TABLE IF EXISTS test_results_structured CASCADE;
DROP TABLE IF EXISTS testing_requests CASCADE;
DROP TABLE IF EXISTS test_templates CASCADE;
DROP TABLE IF EXISTS test_types CASCADE;
DROP TABLE IF EXISTS equipment_types CASCADE;
DROP TABLE IF EXISTS tester_locations CASCADE;

-- Drop organization multi-tenancy tables
DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS org_roles CASCADE;
DROP TABLE IF EXISTS org_department_types CASCADE;
DROP TABLE IF EXISTS org_departments CASCADE;
DROP TABLE IF EXISTS org_users CASCADE;
DROP TABLE IF EXISTS organizations CASCADE;

-- Drop department hierarchy function and trigger
DROP FUNCTION IF EXISTS calculate_department_hierarchy() CASCADE;
DROP TRIGGER IF EXISTS trigger_department_hierarchy ON org_departments CASCADE;

-- Drop user/auth related tables (if you want to reset users too)
-- Uncomment these if you want to reset users as well
-- DROP TABLE IF EXISTS user_addresses CASCADE;
-- DROP TABLE IF EXISTS user_documents CASCADE;
-- DROP TABLE IF EXISTS users CASCADE;

-- Drop category/master data tables (if needed)
-- DROP TABLE IF EXISTS category_details CASCADE;
-- DROP TABLE IF EXISTS category_master CASCADE;

\echo 'All tables dropped successfully. Ready for fresh migration.'
