UPDATE org_user_roles
SET department_id = 'bb804f63-f392-4d42-b599-2271fdf3dce3'
WHERE department_id = 'a8fb50c7-e5f4-47d3-a8de-32526278ed21';



DELETE FROM org_departments
WHERE id = 'a8fb50c7-e5f4-47d3-a8de-32526278ed21';





SELECT COUNT(*)
FROM org_user_roles
WHERE department_id = 'a8fb50c7-e5f4-47d3-a8de-32526278ed21';


-- =========================================
-- FAILURE REPORT
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '157b5489-2afd-45c8-9497-afaf79856918',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- COMMITTEE REVIEW
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '268f44bd-60ba-4579-9b57-56c37fdcb85e',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- VENDOR ASSIGNMENT
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    'ed605ffe-ed4b-4c6a-9bf0-41c215a34306',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- LIFTING
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    'ea7f077c-4010-459f-a091-5877040b8013',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- JOINT INSPECTION
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    'ecaa5af1-cc5e-4bd5-b5ba-c5b2f23f3098',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- ESTIMATE
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '8b16a56d-aa4f-4fac-ad93-d45c5e2c1d5a',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- REPAIR QA
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '522882fe-e359-4ba0-9522-119289944050',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- FINAL INSPECTION
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '0b91f97f-13b0-4c21-8e80-5b398687e64e',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- DISPATCH
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '19a92dea-410e-460b-abe0-d29ab17ed76f',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
    true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;


-- =========================================
-- COMMISSIONING
-- =========================================

INSERT INTO repair_stage_roles (
    id,
    stage_id,
    role_id,
    can_edit,
    can_approve,
    can_assign
)
VALUES (
    gen_random_uuid(),
    '21c9c737-140d-47cb-a8bd-34f786e2aa86',
    '935e2824-aee3-4b70-906a-cf5d9a57dd60',
    true,
    true,
   true
)
ON CONFLICT (stage_id, role_id) DO NOTHING;



UPDATE repair_stage_roles
SET can_approve = false
WHERE role_id =
'08b1b136-dc69-4f5b-ab87-63ddad4f7ca2'
AND stage_id =
'157b5489-2afd-45c8-9497-afaf79856918';


UPDATE repair_stage_roles
SET can_approve = false
WHERE role_id IN (
    '2263df6f-d1e1-49d9-a71f-82ddb8c57784',
    'e78ddee7-2aac-4d06-a474-81048e0369fd'
)
AND stage_id =
'157b5489-2afd-45c8-9497-afaf79856918';


UPDATE org_role_permissions
SET can_assign = true
WHERE org_role_id = (
    SELECT id
    FROM org_roles
    WHERE name = 'Workflow Coordinator'
    LIMIT 1
)
AND module_id = (
    SELECT id
    FROM modules
    WHERE name = 'Repair Workflows'
);


UPDATE org_role_permissions
SET
    can_view = true,
    can_assign = true,
    can_edit = false,
    can_approve = false
WHERE org_role_id =
'3db408eb-d1e6-4a37-8a34-19a5a0ab9af2'
AND module_id = 71;