-- ============================================================
-- RUN ALL MIGRATIONS IN ORDER
-- ============================================================
-- Executes all migration scripts in the correct sequence.
-- Run from the migrations/ directory:
--   psql -U <user> -d <db> -f run_all_migrations.sql
-- ============================================================

\echo '============================================================'
\echo 'Starting Full Database Migration'
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

-- Step 5: Repair Workflow Schema
\echo ''
\echo '5. Repair Workflow Schema...'
\i 005_repair_workflow_schema.sql

-- Step 6: Repair Workflow Source Failure
\echo ''
\echo '6. Repair Workflow Source Failure...'
\i 006_repair_workflow_source_failure.sql

-- Step 7: Repair Timeliness
\echo ''
\echo '7. Repair Timeliness...'
\i 007_repair_timeliness.sql

-- Step 8: Surveillance Workflow
\echo ''
\echo '8. Surveillance Workflow...'
\i 008_surveillance_workflow.sql

-- Step 9: Add Test Types to Recommendations
\echo ''
\echo '9. Add Test Types to Recommendations...'
\i 009_add_test_types_to_recommendations.sql

-- Step 10: Fix TAQC Annual Inspection Department
\echo ''
\echo '10. Fix TAQC Annual Inspection Department...'
\i 010_fix_taqc_annual_inspection_department.sql

-- Step 11: Repair Workflows Equipment Nullable
\echo ''
\echo '11. Repair Workflows Equipment Nullable...'
\i 011_repair_workflows_equipment_nullable.sql

-- Step 12: Repair Workflows Organization ID
\echo ''
\echo '12. Repair Workflows Organization ID...'
\i 012_repair_workflows_organization_id.sql

-- Step 13: Add Surveillance to Schedules
\echo ''
\echo '13. Add Surveillance to Schedules...'
\i 013_add_surveillance_to_schedules.sql

-- Step 14: Add Notification Events Table
\echo ''
\echo '14. Add Notification Events Table...'
\i 014_add_notification_events_table.sql

-- Step 15: Add Frequency to Schedule Rules
\echo ''
\echo '15. Add Frequency to Schedule Rules...'
\i 015_add_frequency_to_schedule_rules.sql

-- Step 16: Add Equipment Types to Schedule Rules
\echo ''
\echo '16. Add Equipment Types to Schedule Rules...'
\i 016_add_equipment_types_to_schedule_rules.sql

-- Step 17: Add CC/BCC to Notification Templates
\echo ''
\echo '17. Add CC/BCC to Notification Templates...'
\i 017_add_cc_bcc_to_notification_templates.sql

-- Step 18: Add Template Refs to Routing Rules
\echo ''
\echo '18. Add Template Refs to Routing Rules...'
\i 018_add_template_refs_to_routing_rules.sql

-- Step 19: Add Notification Log Recipient (CRITICAL — inapp + email tracking)
\echo ''
\echo '19. Add Notification Log Recipient table...'
\i 019_add_notification_log_recipient.sql

-- Step 20: Add Digest Columns to Schedule Rules
\echo ''
\echo '20. Add Digest Columns to Schedule Rules...'
\i 020_add_digest_columns_to_schedule_rules.sql

-- Step 21: Add Advanced Conditions to Routing Rules
\echo ''
\echo '21a. Add Advanced Conditions to Routing Rules...'
\i 021_add_advanced_conditions_to_routing_rules.sql

\echo '21b. Add Followup Action to Routing Rules...'
\i 021_add_followup_action_to_routing_rules.sql

-- Step 22: Eval Testname and Advanced Conditions
\echo ''
\echo '22. Eval Testname and Advanced Conditions...'
\i 022_eval_testname_and_advanced_conditions.sql

-- Step 23: Fix Scheduled Report Queries
\echo ''
\echo '23. Fix Scheduled Report Queries...'
\i 023_fix_scheduled_report_queries.sql

-- Step 24: Pre-commission Requests
\echo ''
\echo '24. Pre-commission Requests...'
\i 024_precommission_requests.sql

-- Step 25: Pre-commission Transformer Fields
\echo ''
\echo '25. Pre-commission Transformer Fields...'
\i 025_precommission_transformer_fields.sql

-- Step 26: Equipment Pre-commission Link
\echo ''
\echo '26. Equipment Pre-commission Link...'
\i 026_equipment_precommission_link.sql

\echo ''
\echo '============================================================'
\echo 'All Migrations Completed Successfully!'
\echo '============================================================'
