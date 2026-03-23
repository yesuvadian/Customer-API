# Test and Utility Scripts

This directory contains test scripts, diagnostic tools, and utility scripts for the Customer API project.

## Test Scripts

### End-to-End Testing
- **test_full_cycle.py** - Complete testing workflow from request creation to completion
- **test_kptcl_complete.py** - Full cycle testing for KPTCL organization
- **test_end_to_end_tester_config.py** - Tester role configuration end-to-end test
- **test_tester_role_config_complete.py** - Complete tester role configuration testing

### Approval Workflow Testing
- **test_approval_workflow.py** - Test approval workflow with tester selection
- **test_approval_only.py** - Isolated approval workflow testing

### Authentication & Authorization Testing
- **test_depthead_login.py** - Department head login and permissions testing
- **test_endpoints.py** - API endpoint testing
- **test_templates.py** - Test template functionality

## Diagnostic Scripts

### User Verification
- **check_users.py** - List and verify all users in the database
- **check_user_ids.py** - Check user ID assignments and conflicts
- **check_user_password.py** - Verify user password hashes
- **check_depthead.py** - Verify department head user setup
- **check_kptcl_user.py** - Check KPTCL organization users
- **check_kptcl_user_custom_db.py** - Custom database check for KPTCL users
- **check_sample_org_user.py** - Verify sample organization users

### Database Verification
- **check_tables.py** - Verify database table structure
- **check_modules.py** - Check module configuration
- **check_query.py** - Generic database query utility
- **check_all_requests.py** - List all testing requests
- **check_request.py** - Check specific testing request details

### Debugging
- **debug_approval.py** - Debug approval workflow issues

## Utility Scripts

### Database Setup
- **clean_and_seed.py** - Clean database and run seed data
- **create_sample_tester_roles.py** - Create sample tester roles for testing

### Migrations
- **run_migration_001.py** - Run migration 001 (tester role configuration)
- **run_approval_migration.py** - Run approval workflow migration

### Data Fixes
- **fix_request_org.py** - Fix organization assignments for testing requests
- **update_request_status.py** - Update testing request statuses
- **add_enum_value.py** - Add enum values to database

### Verification
- **verify_tester_config_table.py** - Verify tester configuration table structure

## Usage

Most scripts can be run directly:
```bash
python tests/test_full_cycle.py
python tests/check_users.py
```

Make sure your `.env` file is configured with the correct database credentials before running any scripts.

## Notes

- These scripts are for development and testing only
- Some scripts may modify the database - use with caution
- Check script source code for specific requirements and parameters
