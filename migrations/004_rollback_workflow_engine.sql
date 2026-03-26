-- ============================================================
-- ROLLBACK MIGRATION 004: Workflow Engine & Permission Matrix
-- ============================================================
-- Description: Removes workflow engine tables
-- Date: 2026-03-22
-- ============================================================

-- Drop triggers first
DROP TRIGGER IF EXISTS trigger_permission_matrix_mts ON permission_matrix;
DROP TRIGGER IF EXISTS trigger_workflow_transitions_mts ON workflow_transitions;
DROP TRIGGER IF EXISTS trigger_workflow_states_mts ON workflow_states;
DROP TRIGGER IF EXISTS trigger_workflows_mts ON workflows;

-- Drop functions
DROP FUNCTION IF EXISTS update_workflow_mts();
DROP FUNCTION IF EXISTS get_available_transitions(UUID, UUID, UUID, UUID);

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS workflow_audit_log CASCADE;
DROP TABLE IF EXISTS permission_matrix CASCADE;
DROP TABLE IF EXISTS workflow_transitions CASCADE;
DROP TABLE IF EXISTS workflow_states CASCADE;
DROP TABLE IF EXISTS workflows CASCADE;

-- ============================================================
-- END OF ROLLBACK
-- ============================================================
