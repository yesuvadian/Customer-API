-- ============================================================
-- COMPLETE SYSTEM SEED SCRIPT
-- ============================================================
-- Seeds a complete working system with:
-- - Organization (KPTCL)
-- - Department Types
-- - Department Hierarchy
-- - Roles (Admin, Department Head, Tester, Engineer, etc.)
-- - Sample Users
-- - Testing Request Workflow
-- - Permission Matrix
-- ============================================================

\echo '============================================================'
\echo 'Starting Complete System Seed'
\echo '============================================================'

DO $$
DECLARE
    -- Organization
    v_org_id UUID;
    v_org_admin_user_id UUID;

    -- Department Types
    v_dept_type_zone UUID;
    v_dept_type_circle UUID;
    v_dept_type_division UUID;
    v_dept_type_subdivision UUID;
    v_dept_type_section UUID;
    v_dept_type_substation UUID;

    -- Departments
    v_dept_zone_bangalore UUID;
    v_dept_circle_transmission UUID;
    v_dept_division_north UUID;
    v_dept_subdivision_yelahanka UUID;
    v_dept_section_yelahanka UUID;
    v_dept_substation_220kv UUID;

    -- Roles
    v_role_org_admin UUID;
    v_role_dept_head UUID;
    v_role_tester UUID;
    v_role_engineer UUID;
    v_role_section_head UUID;

    -- Users
    v_user_dept_head UUID;
    v_user_tester1 UUID;
    v_user_tester2 UUID;
    v_user_engineer UUID;

    -- Workflow
    v_workflow_id UUID;
    v_state_draft UUID;
    v_state_submitted UUID;
    v_state_assigned UUID;
    v_state_accepted UUID;
    v_state_in_progress UUID;
    v_state_test_submitted UUID;
    v_state_approved UUID;
    v_state_rejected UUID;
    v_state_cancelled UUID;

    -- Transitions
    v_trans_submit UUID;
    v_trans_assign UUID;
    v_trans_accept UUID;
    v_trans_reject_from_assigned UUID;
    v_trans_start UUID;
    v_trans_submit_results UUID;
    v_trans_approve UUID;
    v_trans_reject_from_test_submitted UUID;
    v_trans_cancel UUID;

BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE '1. CREATING ORGANIZATION';
    RAISE NOTICE '============================================================';

    -- Create KPTCL Organization
    INSERT INTO organizations (
        id, name, code, display_name, is_active
    ) VALUES (
        uuid_generate_v4(),
        'Karnataka Power Transmission Corporation Limited',
        'KPTCL',
        'KPTCL',
        TRUE
    ) RETURNING id INTO v_org_id;

    RAISE NOTICE 'Created Organization: KPTCL (ID: %)', v_org_id;

    -- Create org admin user
    INSERT INTO users (
        id, firstname, lastname, email, password_hash, phone_number, isactive
    ) VALUES (
        uuid_generate_v4(),
        'Organization',
        'Admin',
        'orgadmin@kptcl.com',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5aq0XdTnX0QZm', -- password: admin123
        '9876543210',
        TRUE
    ) RETURNING id INTO v_org_admin_user_id;

    RAISE NOTICE 'Created Org Admin User: orgadmin@kptcl.com';

    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '2. CREATING DEPARTMENT TYPES';
    RAISE NOTICE '============================================================';

    -- Department Type: Zone
    INSERT INTO org_department_types (
        id, organization_id, type_name, type_code, description, icon, color, display_order
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Zone', 'ZONE',
        'Regional zone level', 'location_city', '#E91E63', 1
    ) RETURNING id INTO v_dept_type_zone;

    -- Department Type: Circle
    INSERT INTO org_department_types (
        id, organization_id, type_name, type_code, description, icon, color, display_order
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Circle', 'CIRCLE',
        'Transmission circle level', 'album', '#9C27B0', 2
    ) RETURNING id INTO v_dept_type_circle;

    -- Department Type: Division
    INSERT INTO org_department_types (
        id, organization_id, type_name, type_code, description, icon, color, display_order
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Division', 'DIVISION',
        'Divisional level', 'account_tree', '#3F51B5', 3
    ) RETURNING id INTO v_dept_type_division;

    -- Department Type: Subdivision
    INSERT INTO org_department_types (
        id, organization_id, type_name, type_code, description, icon, color, display_order
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Subdivision', 'SUBDIVISION',
        'Sub-divisional level', 'folder', '#2196F3', 4
    ) RETURNING id INTO v_dept_type_subdivision;

    -- Department Type: Section
    INSERT INTO org_department_types (
        id, organization_id, type_name, type_code, description, icon, color, display_order
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Section', 'SECTION',
        'Section level', 'folder_open', '#00BCD4', 5
    ) RETURNING id INTO v_dept_type_section;

    -- Department Type: Substation
    INSERT INTO org_department_types (
        id, organization_id, type_name, type_code, description, icon, color, display_order
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Substation', 'SUBSTATION',
        'Substation/facility level', 'electrical_services', '#4CAF50', 6
    ) RETURNING id INTO v_dept_type_substation;

    RAISE NOTICE 'Created 6 Department Types';

    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '3. CREATING DEPARTMENT HIERARCHY';
    RAISE NOTICE '============================================================';

    -- Zone: Bangalore
    INSERT INTO org_departments (
        id, organization_id, name, code, department_type_id, parent_department_id
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Bangalore Zone', 'BLR_ZONE',
        v_dept_type_zone, NULL
    ) RETURNING id INTO v_dept_zone_bangalore;

    -- Circle: Transmission Circle
    INSERT INTO org_departments (
        id, organization_id, name, code, department_type_id, parent_department_id
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Bangalore Transmission Circle', 'BLR_TRANS_CIRCLE',
        v_dept_type_circle, v_dept_zone_bangalore
    ) RETURNING id INTO v_dept_circle_transmission;

    -- Division: North Division
    INSERT INTO org_departments (
        id, organization_id, name, code, department_type_id, parent_department_id
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'RT North Division', 'RT_NORTH_DIV',
        v_dept_type_division, v_dept_circle_transmission
    ) RETURNING id INTO v_dept_division_north;

    -- Subdivision: Yelahanka
    INSERT INTO org_departments (
        id, organization_id, name, code, department_type_id, parent_department_id
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'RT North SD1 Yelahanka', 'RT_NORTH_SD1',
        v_dept_type_subdivision, v_dept_division_north
    ) RETURNING id INTO v_dept_subdivision_yelahanka;

    -- Section: Yelahanka Section
    INSERT INTO org_departments (
        id, organization_id, name, code, department_type_id, parent_department_id
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Yelahanka Section', 'YLK_SECTION',
        v_dept_type_section, v_dept_subdivision_yelahanka
    ) RETURNING id INTO v_dept_section_yelahanka;

    -- Substation: 220kV Yelahanka
    INSERT INTO org_departments (
        id, organization_id, name, code, department_type_id, parent_department_id
    ) VALUES (
        uuid_generate_v4(), v_org_id, '220kV Yelahanka Substation', '220KV_YLK',
        v_dept_type_substation, v_dept_section_yelahanka
    ) RETURNING id INTO v_dept_substation_220kv;

    RAISE NOTICE 'Created 6-level Department Hierarchy';

    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '4. CREATING ROLES';
    RAISE NOTICE '============================================================';

    -- Role: Organization Admin
    INSERT INTO org_roles (
        id, organization_id, name, description, is_org_admin, is_dept_admin
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Organization Admin',
        'Full administrative access to organization', TRUE, FALSE
    ) RETURNING id INTO v_role_org_admin;

    -- Role: Department Head
    INSERT INTO org_roles (
        id, organization_id, name, description, is_org_admin, is_dept_admin
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Department Head',
        'Head of department with management privileges', FALSE, TRUE
    ) RETURNING id INTO v_role_dept_head;

    -- Role: Tester
    INSERT INTO org_roles (
        id, organization_id, name, description, is_org_admin, is_dept_admin
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Tester',
        'Testing personnel who conduct equipment tests', FALSE, FALSE
    ) RETURNING id INTO v_role_tester;

    -- Role: Engineer
    INSERT INTO org_roles (
        id, organization_id, name, description, is_org_admin, is_dept_admin
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Engineer',
        'Engineering staff who request testing', FALSE, FALSE
    ) RETURNING id INTO v_role_engineer;

    -- Role: Section Head
    INSERT INTO org_roles (
        id, organization_id, name, description, is_org_admin, is_dept_admin
    ) VALUES (
        uuid_generate_v4(), v_org_id, 'Section Head',
        'Section level supervisor', FALSE, TRUE
    ) RETURNING id INTO v_role_section_head;

    RAISE NOTICE 'Created 5 Roles';

    -- Assign org admin role
    INSERT INTO org_user_roles (
        id, user_id, org_role_id, department_id, is_active
    ) VALUES (
        uuid_generate_v4(), v_org_admin_user_id, v_role_org_admin,
        NULL, TRUE
    );

    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '5. CREATING SAMPLE USERS';
    RAISE NOTICE '============================================================';

    -- User: Department Head
    INSERT INTO users (
        id, firstname, lastname, email, password_hash, phone_number, isactive, organization_id, department_id
    ) VALUES (
        uuid_generate_v4(), 'Ramesh', 'Kumar',
        'depthead@kptcl.com',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5aq0XdTnX0QZm', -- password: admin123
        '9876543211', TRUE, v_org_id, v_dept_division_north
    ) RETURNING id INTO v_user_dept_head;

    INSERT INTO org_user_roles (
        id, user_id, org_role_id, department_id, is_active
    ) VALUES (
        uuid_generate_v4(), v_user_dept_head, v_role_dept_head,
        v_dept_division_north, TRUE
    );

    -- User: Tester 1
    INSERT INTO users (
        id, firstname, lastname, email, password_hash, phone_number, isactive, organization_id, department_id
    ) VALUES (
        uuid_generate_v4(), 'Suresh', 'Reddy',
        'tester1@kptcl.com',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5aq0XdTnX0QZm', -- password: admin123
        '9876543212', TRUE, v_org_id, v_dept_section_yelahanka
    ) RETURNING id INTO v_user_tester1;

    INSERT INTO org_user_roles (
        id, user_id, org_role_id, department_id, is_active
    ) VALUES (
        uuid_generate_v4(), v_user_tester1, v_role_tester,
        v_dept_section_yelahanka, TRUE
    );

    -- User: Tester 2
    INSERT INTO users (
        id, firstname, lastname, email, password_hash, phone_number, isactive, organization_id, department_id
    ) VALUES (
        uuid_generate_v4(), 'Lakshmi', 'Narayanan',
        'tester2@kptcl.com',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5aq0XdTnX0QZm', -- password: admin123
        '9876543213', TRUE, v_org_id, v_dept_subdivision_yelahanka
    ) RETURNING id INTO v_user_tester2;

    INSERT INTO org_user_roles (
        id, user_id, org_role_id, department_id, is_active
    ) VALUES (
        uuid_generate_v4(), v_user_tester2, v_role_tester,
        v_dept_subdivision_yelahanka, TRUE
    );

    -- User: Engineer
    INSERT INTO users (
        id, firstname, lastname, email, password_hash, phone_number, isactive, organization_id, department_id
    ) VALUES (
        uuid_generate_v4(), 'Priya', 'Sharma',
        'engineer@kptcl.com',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5aq0XdTnX0QZm', -- password: admin123
        '9876543214', TRUE, v_org_id, v_dept_substation_220kv
    ) RETURNING id INTO v_user_engineer;

    INSERT INTO org_user_roles (
        id, user_id, org_role_id, department_id, is_active
    ) VALUES (
        uuid_generate_v4(), v_user_engineer, v_role_engineer,
        v_dept_substation_220kv, TRUE
    );

    RAISE NOTICE 'Created 5 Sample Users (password: admin123 for all)';
    RAISE NOTICE '  - orgadmin@kptcl.com (Org Admin)';
    RAISE NOTICE '  - depthead@kptcl.com (Department Head)';
    RAISE NOTICE '  - tester1@kptcl.com (Tester - Section Level)';
    RAISE NOTICE '  - tester2@kptcl.com (Tester - Subdivision Level)';
    RAISE NOTICE '  - engineer@kptcl.com (Engineer - Substation Level)';

END $$;

-- Seed testing request workflow
\i seed_testing_request_workflow.sql

\echo ''
\echo '============================================================'
\echo 'COMPLETE SYSTEM SEED FINISHED!'
\echo '============================================================'
\echo ''
\echo 'Login Credentials (password: admin123 for all):'
\echo '  Organization Admin: orgadmin@kptcl.com'
\echo '  Department Head:    depthead@kptcl.com'
\echo '  Tester 1:           tester1@kptcl.com'
\echo '  Tester 2:           tester2@kptcl.com'
\echo '  Engineer:           engineer@kptcl.com'
\echo ''
\echo 'Next Step: Configure permission matrix for workflow transitions'
\echo '============================================================'
