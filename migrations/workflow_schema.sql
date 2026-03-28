-- ============================================================
-- WORKFLOW ENGINE & PERMISSION MATRIX SCHEMA
-- ============================================================
-- Description: Complete workflow system with role-based permissions
-- and department-scoped access control
-- ============================================================

-- ============================================================
-- 1. WORKFLOWS TABLE
-- ============================================================
-- Stores workflow definitions (e.g., "Testing Request Workflow")
CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Basic Info
    name VARCHAR(200) NOT NULL,
    description TEXT,
    workflow_type VARCHAR(100) NOT NULL, -- 'testing_request', 'approval', 'procurement', etc.

    -- Multi-tenancy
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    version INT DEFAULT 1,

    -- Audit
    created_by UUID REFERENCES users(id),
    cts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    UNIQUE(organization_id, workflow_type, version)
);

CREATE INDEX idx_workflows_org ON workflows(organization_id);
CREATE INDEX idx_workflows_type ON workflows(workflow_type);
CREATE INDEX idx_workflows_active ON workflows(is_active);

-- ============================================================
-- 2. WORKFLOW STATES TABLE
-- ============================================================
-- Stores individual states within a workflow
CREATE TABLE IF NOT EXISTS workflow_states (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Relationship
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,

    -- State Info
    state_code VARCHAR(50) NOT NULL, -- 'draft', 'submitted', 'approved', etc.
    state_name VARCHAR(200) NOT NULL,
    description TEXT,

    -- State Type
    state_type VARCHAR(50) DEFAULT 'intermediate', -- 'initial', 'intermediate', 'final', 'cancelled'

    -- Display
    color VARCHAR(20) DEFAULT '#3FA9F5',
    icon VARCHAR(50) DEFAULT 'circle',
    display_order INT DEFAULT 0,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Audit
    created_by UUID REFERENCES users(id),
    cts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    UNIQUE(workflow_id, state_code)
);

CREATE INDEX idx_workflow_states_workflow ON workflow_states(workflow_id);
CREATE INDEX idx_workflow_states_code ON workflow_states(state_code);
CREATE INDEX idx_workflow_states_type ON workflow_states(state_type);

-- ============================================================
-- 3. WORKFLOW TRANSITIONS TABLE
-- ============================================================
-- Defines allowed transitions between states
CREATE TABLE IF NOT EXISTS workflow_transitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Relationship
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    from_state_id UUID NOT NULL REFERENCES workflow_states(id) ON DELETE CASCADE,
    to_state_id UUID NOT NULL REFERENCES workflow_states(id) ON DELETE CASCADE,

    -- Transition Info
    transition_name VARCHAR(200) NOT NULL, -- 'Submit', 'Approve', 'Reject', 'Cancel'
    action_code VARCHAR(50) NOT NULL, -- 'submit', 'approve', 'reject', 'cancel'
    description TEXT,

    -- Conditions (stored as JSONB for flexibility)
    conditions JSONB, -- e.g., {"requires_comment": true, "min_days_in_state": 1}

    -- Display
    button_label VARCHAR(100), -- Label for UI button
    button_color VARCHAR(20) DEFAULT '#3FA9F5',
    icon VARCHAR(50) DEFAULT 'arrow_forward',
    requires_comment BOOLEAN DEFAULT FALSE,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Audit
    created_by UUID REFERENCES users(id),
    cts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    UNIQUE(workflow_id, from_state_id, to_state_id, action_code),
    CHECK (from_state_id != to_state_id)
);

CREATE INDEX idx_workflow_transitions_workflow ON workflow_transitions(workflow_id);
CREATE INDEX idx_workflow_transitions_from ON workflow_transitions(from_state_id);
CREATE INDEX idx_workflow_transitions_to ON workflow_transitions(to_state_id);
CREATE INDEX idx_workflow_transitions_action ON workflow_transitions(action_code);

-- ============================================================
-- 4. PERMISSION MATRIX TABLE
-- ============================================================
-- Role-based permissions for workflow transitions with department scope
CREATE TABLE IF NOT EXISTS permission_matrix (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Relationship
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    transition_id UUID NOT NULL REFERENCES workflow_transitions(id) ON DELETE CASCADE,

    -- Role-Based Access
    role_id UUID NOT NULL REFERENCES org_roles(id) ON DELETE CASCADE,

    -- Department Scope (hierarchical permission)
    scope_type VARCHAR(50) NOT NULL DEFAULT 'exact', -- 'exact', 'department_tree', 'organization', 'any'
    department_type_id UUID REFERENCES org_department_types(id) ON DELETE SET NULL, -- Optional: restrict to specific dept type

    -- Permission Level
    can_execute BOOLEAN DEFAULT TRUE, -- Can perform the transition
    can_view BOOLEAN DEFAULT TRUE, -- Can see the transition button
    requires_approval BOOLEAN DEFAULT FALSE, -- Needs approval from another role

    -- Additional Conditions (stored as JSONB)
    conditions JSONB, -- e.g., {"max_amount": 10000, "requires_2fa": true}

    -- Priority (for conflict resolution)
    priority INT DEFAULT 0, -- Higher priority rules override lower ones

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Audit
    created_by UUID REFERENCES users(id),
    cts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    UNIQUE(transition_id, role_id, scope_type),
    CHECK (scope_type IN ('exact', 'department_tree', 'organization', 'any'))
);

CREATE INDEX idx_permission_matrix_workflow ON permission_matrix(workflow_id);
CREATE INDEX idx_permission_matrix_transition ON permission_matrix(transition_id);
CREATE INDEX idx_permission_matrix_role ON permission_matrix(role_id);
CREATE INDEX idx_permission_matrix_scope ON permission_matrix(scope_type);
CREATE INDEX idx_permission_matrix_dept_type ON permission_matrix(department_type_id);

-- ============================================================
-- 5. WORKFLOW AUDIT LOG TABLE
-- ============================================================
-- Tracks all state transitions and who performed them
CREATE TABLE IF NOT EXISTS workflow_audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Relationship
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    entity_type VARCHAR(100) NOT NULL, -- 'testing_request', 'purchase_order', etc.
    entity_id UUID NOT NULL, -- ID of the entity (e.g., testing_request.id)

    -- Transition Details
    transition_id UUID REFERENCES workflow_transitions(id) ON DELETE SET NULL,
    from_state_id UUID REFERENCES workflow_states(id) ON DELETE SET NULL,
    to_state_id UUID REFERENCES workflow_states(id) ON DELETE SET NULL,
    action_code VARCHAR(50),

    -- User & Context
    performed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_role_id UUID REFERENCES org_roles(id) ON DELETE SET NULL,
    user_department_id UUID REFERENCES org_departments(id) ON DELETE SET NULL,

    -- Additional Data
    comment TEXT,
    metadata JSONB, -- Additional context (IP, device, etc.)

    -- Result
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);

CREATE INDEX idx_workflow_audit_workflow ON workflow_audit_log(workflow_id);
CREATE INDEX idx_workflow_audit_entity ON workflow_audit_log(entity_type, entity_id);
CREATE INDEX idx_workflow_audit_transition ON workflow_audit_log(transition_id);
CREATE INDEX idx_workflow_audit_user ON workflow_audit_log(performed_by);
CREATE INDEX idx_workflow_audit_timestamp ON workflow_audit_log(performed_at);

-- ============================================================
-- 6. HELPER FUNCTIONS
-- ============================================================

-- Function to get available transitions for a user
CREATE OR REPLACE FUNCTION get_available_transitions(
    p_workflow_id UUID,
    p_current_state_id UUID,
    p_user_id UUID,
    p_entity_department_id UUID
) RETURNS TABLE (
    transition_id UUID,
    transition_name VARCHAR,
    action_code VARCHAR,
    to_state_code VARCHAR,
    button_label VARCHAR,
    button_color VARCHAR,
    requires_comment BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        wt.id,
        wt.transition_name,
        wt.action_code,
        ws.state_code,
        wt.button_label,
        wt.button_color,
        wt.requires_comment
    FROM workflow_transitions wt
    INNER JOIN workflow_states ws ON wt.to_state_id = ws.id
    INNER JOIN permission_matrix pm ON wt.id = pm.transition_id
    INNER JOIN user_roles ur ON pm.role_id = ur.role_id
    WHERE wt.workflow_id = p_workflow_id
      AND wt.from_state_id = p_current_state_id
      AND wt.is_active = TRUE
      AND pm.is_active = TRUE
      AND pm.can_execute = TRUE
      AND ur.user_id = p_user_id
      AND ur.is_active = TRUE
      AND (
          -- Check department scope
          pm.scope_type = 'any'
          OR pm.scope_type = 'organization'
          OR (pm.scope_type = 'exact' AND ur.department_id = p_entity_department_id)
          OR (pm.scope_type = 'department_tree' AND EXISTS (
              SELECT 1 FROM org_departments
              WHERE id = p_entity_department_id
                AND hierarchy_path LIKE (
                    SELECT hierarchy_path || '%'
                    FROM org_departments
                    WHERE id = ur.department_id
                )
          ))
      )
    ORDER BY wt.display_order, wt.transition_name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 7. TRIGGER TO UPDATE TIMESTAMP
-- ============================================================

CREATE OR REPLACE FUNCTION update_workflow_mts()
RETURNS TRIGGER AS $$
BEGIN
    NEW.mts = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_workflows_mts
    BEFORE UPDATE ON workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_workflow_mts();

CREATE TRIGGER trigger_workflow_states_mts
    BEFORE UPDATE ON workflow_states
    FOR EACH ROW
    EXECUTE FUNCTION update_workflow_mts();

CREATE TRIGGER trigger_workflow_transitions_mts
    BEFORE UPDATE ON workflow_transitions
    FOR EACH ROW
    EXECUTE FUNCTION update_workflow_mts();

CREATE TRIGGER trigger_permission_matrix_mts
    BEFORE UPDATE ON permission_matrix
    FOR EACH ROW
    EXECUTE FUNCTION update_workflow_mts();

-- ============================================================
-- END OF SCHEMA
-- ============================================================
