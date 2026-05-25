# Surveillance Workflow - Design Pattern Consistency

> **Principle:** Surveillance workflow reuses the EXACT SAME infrastructure as repair workflow  
> **No new tables for workflow management** - only surveillance-specific config and tracking

---

## Existing Repair Workflow Pattern

### Tables Used

| Table | Purpose | Example |
|-------|---------|---------|
| `repair_workflow_definitions` | Workflow types | REPAIR, CALIBRATION, OVERHAUL |
| `repair_stage_definitions` | Stage metadata | STAGE_1_FAILURE_REPORTING |
| `repair_stage_templates` | Stage → Form template mapping | STAGE_1 → failure_reporting_template |
| `repair_stage_roles` | RBAC per stage | Zone Engineer can edit STAGE_2 |
| `repair_stage_transitions` | Stage flow (approve/reject) | STAGE_1 --approve→ STAGE_2 |
| `repair_workflows` | Workflow instances | REP-2026-001, CAL-2026-015 |
| `repair_stage_instances` | Stage instances per workflow | REP-2026-001 / STAGE_1 instance |
| `repair_stage_data` | Form submissions | Officer's form data for STAGE_1 |
| `repair_assignment_queue` | Assignment management | STAGE_2 pending, needs assignment |
| `repair_stage_audit_log` | Audit trail | Officer approved STAGE_1 on date X |

### Service Pattern

**Single Service:** `RepairWorkflowService`

Handles all workflow types (REPAIR, CALIBRATION, OVERHAUL) using the same methods:
- `create_workflow()`
- `assign_stage()`
- `submit_stage()`
- `advance_stage()`
- `reject_stage()`

**No separate service per workflow type** - same service handles all via workflow_code differentiation.

---

## Surveillance Workflow Pattern (Follows Same Design)

### ✅ Use SAME Tables

| Table | Surveillance Usage | Records Created |
|-------|-------------------|-----------------|
| `repair_workflow_definitions` | Add SURVEILLANCE workflow type | 1 record: code=SURVEILLANCE |
| `repair_stage_definitions` | Add 5 surveillance stages | SURV_Q1, SURV_Q2, SURV_Q3, SURV_Q4, SURV_EVAL |
| `repair_stage_templates` | Link stages to templates | SURV_Q1 → surveillance_quarter_review |
| `repair_stage_roles` | Define who can edit/approve | Zone Engineer can approve SURV_Q1 |
| `repair_stage_transitions` | Define stage flow | SURV_Q1 --approve→ SURV_Q2 |
| `repair_workflows` | Create surveillance instances | REP-2026-001-SURV (workflow_code=SURVEILLANCE) |
| `repair_stage_instances` | Track stage progress | 5 instances per surveillance workflow |
| `repair_stage_data` | Store officer's form data | Q1 review form, final eval form |
| `repair_assignment_queue` | Manage stage assignments | SURV_Q2 pending assignment |
| `repair_stage_audit_log` | Audit all actions | Officer approved SURV_Q1, etc. |

### ✅ Use SAME Service

**Service:** `RepairWorkflowService` (no new service!)

Same methods work for surveillance:
```python
# Create surveillance workflow
RepairWorkflowService.create_workflow(
    workflow_definition_code="SURVEILLANCE",
    equipment_id=equipment_id,
    ...
)

# Officer submits Q1 stage
RepairWorkflowService.submit_stage(
    workflow_id=surv_workflow_id,
    stage_instance_id=q1_instance_id,
    form_data={...}
)

# Approver approves Q1
RepairWorkflowService.advance_stage(
    workflow_id=surv_workflow_id,
    remarks="Q1 surveillance satisfactory",
    user_id=approver_id
)
```

**Key Point:** No `SurveillanceWorkflowService` - just use the existing service!

### ✅ Use SAME UI Components

**Flutter Widgets:** Already built for repair workflow, work for surveillance too!

```dart
// Workflow detail page - shows any workflow type
WorkflowDetailPage(workflowId: survWorkflowId)

// Shows 5-stage stepper (same as 10-stage for repair)
WorkflowStageStepper(workflow: survWorkflow)

// Stage form - renders any template
StageFormPage(
  workflowId: survWorkflowId,
  stageInstanceId: q1InstanceId,
  templateKey: "surveillance_quarter_review"
)

// Approve/reject buttons - same component
StageApprovalButtons(
  onApprove: () => advanceStage(...),
  onReject: () => rejectStage(...)
)
```

**Zero new UI code needed** - existing components are generic!

---

## Complete Database Setup (Migration)

### Part 1: Workflow Definition

```sql
-- Create SURVEILLANCE workflow definition
INSERT INTO repair_workflow_definitions (id, workflow_code, name, is_active, created_at)
VALUES (
    gen_random_uuid(),
    'SURVEILLANCE',
    'Post-Repair Surveillance',
    true,
    CURRENT_TIMESTAMP
);
```

### Part 2: Stage Definitions

```sql
-- Get surveillance workflow definition ID
WITH surv_def AS (
    SELECT id FROM repair_workflow_definitions WHERE workflow_code = 'SURVEILLANCE'
)

-- Create 5 stage definitions
INSERT INTO repair_stage_definitions 
    (id, workflow_definition_id, code, name, sequence, weight, is_active, is_mandatory, created_at)
VALUES
    -- Q1
    (gen_random_uuid(), (SELECT id FROM surv_def), 'SURV_Q1', 'Q1 Surveillance Testing', 1, 20, true, true, CURRENT_TIMESTAMP),
    -- Q2
    (gen_random_uuid(), (SELECT id FROM surv_def), 'SURV_Q2', 'Q2 Surveillance Testing', 2, 20, true, true, CURRENT_TIMESTAMP),
    -- Q3
    (gen_random_uuid(), (SELECT id FROM surv_def), 'SURV_Q3', 'Q3 Surveillance Testing', 3, 20, true, true, CURRENT_TIMESTAMP),
    -- Q4
    (gen_random_uuid(), (SELECT id FROM surv_def), 'SURV_Q4', 'Q4 Surveillance Testing', 4, 20, true, true, CURRENT_TIMESTAMP),
    -- Final Evaluation
    (gen_random_uuid(), (SELECT id FROM surv_def), 'SURV_EVAL', 'Final Evaluation & Report', 5, 20, true, true, CURRENT_TIMESTAMP);
```

### Part 3: Stage Templates

**Option A: Store templates in org_test_templates**

```sql
-- Insert surveillance templates (if using org_test_templates table)
INSERT INTO org_test_templates (id, organization_id, template_key, name, template_data, created_at)
VALUES
    -- Quarter review template (used by Q1-Q4)
    (gen_random_uuid(), NULL, 'surveillance_quarter_review', 'Surveillance Quarter Review', 
     '{ ...JSON from SURVEILLANCE_STAGE_TEMPLATES.json... }'::jsonb, CURRENT_TIMESTAMP),
    
    -- Final evaluation template (used by Q5)
    (gen_random_uuid(), NULL, 'surveillance_final_evaluation', 'Final Post-Repair Evaluation',
     '{ ...JSON from SURVEILLANCE_STAGE_TEMPLATES.json... }'::jsonb, CURRENT_TIMESTAMP);
```

**Option B: Load from JSON file (like test_templates.py pattern)**

Just store template keys in `repair_stage_templates` and load from `SURVEILLANCE_STAGE_TEMPLATES.json` at runtime.

```sql
-- Link templates to stages
WITH 
    q1_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q1'),
    q2_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q2'),
    q3_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q3'),
    q4_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q4'),
    eval_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_EVAL')

INSERT INTO repair_stage_templates (id, stage_id, template_key, category_detail_id)
VALUES
    -- Q1-Q4 use same template
    (gen_random_uuid(), (SELECT id FROM q1_stage), 'surveillance_quarter_review', NULL),
    (gen_random_uuid(), (SELECT id FROM q2_stage), 'surveillance_quarter_review', NULL),
    (gen_random_uuid(), (SELECT id FROM q3_stage), 'surveillance_quarter_review', NULL),
    (gen_random_uuid(), (SELECT id FROM q4_stage), 'surveillance_quarter_review', NULL),
    
    -- Final eval uses different template
    (gen_random_uuid(), (SELECT id FROM eval_stage), 'surveillance_final_evaluation', NULL);
```

### Part 4: Stage Roles (RBAC)

```sql
-- Define who can edit and approve each surveillance stage

WITH 
    zone_engineer_role AS (
        SELECT id FROM org_roles WHERE code = 'ZONE_ENGINEER' LIMIT 1
    ),
    quality_officer_role AS (
        SELECT id FROM org_roles WHERE code = 'QUALITY_OFFICER' LIMIT 1
    ),
    q1_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q1'),
    q2_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q2'),
    q3_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q3'),
    q4_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q4'),
    eval_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_EVAL')

INSERT INTO repair_stage_roles (id, stage_id, role_id, can_edit, can_approve)
VALUES
    -- Q1: Zone Engineer can edit and approve
    (gen_random_uuid(), (SELECT id FROM q1_stage), (SELECT id FROM zone_engineer_role), true, true),
    
    -- Q2: Zone Engineer can edit and approve
    (gen_random_uuid(), (SELECT id FROM q2_stage), (SELECT id FROM zone_engineer_role), true, true),
    
    -- Q3: Zone Engineer can edit and approve
    (gen_random_uuid(), (SELECT id FROM q3_stage), (SELECT id FROM zone_engineer_role), true, true),
    
    -- Q4: Zone Engineer can edit and approve
    (gen_random_uuid(), (SELECT id FROM q4_stage), (SELECT id FROM zone_engineer_role), true, true),
    
    -- Final Eval: Zone Engineer can edit, Quality Officer can approve
    (gen_random_uuid(), (SELECT id FROM eval_stage), (SELECT id FROM zone_engineer_role), true, false),
    (gen_random_uuid(), (SELECT id FROM eval_stage), (SELECT id FROM quality_officer_role), false, true);
```

**Note:** Adjust role codes based on your actual org_roles table.

### Part 5: Stage Transitions

```sql
-- Define stage flow (approve/reject transitions)

WITH
    q1_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q1'),
    q2_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q2'),
    q3_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q3'),
    q4_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_Q4'),
    eval_stage AS (SELECT id FROM repair_stage_definitions WHERE code = 'SURV_EVAL')

INSERT INTO repair_stage_transitions (id, from_stage_id, to_stage_id, action)
VALUES
    -- Q1 approve → Q2
    (gen_random_uuid(), (SELECT id FROM q1_stage), (SELECT id FROM q2_stage), 'approve'),
    
    -- Q2 approve → Q3
    (gen_random_uuid(), (SELECT id FROM q2_stage), (SELECT id FROM q3_stage), 'approve'),
    
    -- Q3 approve → Q4
    (gen_random_uuid(), (SELECT id FROM q3_stage), (SELECT id FROM q4_stage), 'approve'),
    
    -- Q4 approve → Final Eval
    (gen_random_uuid(), (SELECT id FROM q4_stage), (SELECT id FROM eval_stage), 'approve'),
    
    -- Final Eval approve → NULL (workflow completes)
    (gen_random_uuid(), (SELECT id FROM eval_stage), NULL, 'approve'),
    
    -- Reject transitions: all stages reject → stay at same stage (standard pattern)
    (gen_random_uuid(), (SELECT id FROM q1_stage), (SELECT id FROM q1_stage), 'reject'),
    (gen_random_uuid(), (SELECT id FROM q2_stage), (SELECT id FROM q2_stage), 'reject'),
    (gen_random_uuid(), (SELECT id FROM q3_stage), (SELECT id FROM q3_stage), 'reject'),
    (gen_random_uuid(), (SELECT id FROM q4_stage), (SELECT id FROM q4_stage), 'reject'),
    (gen_random_uuid(), (SELECT id FROM eval_stage), (SELECT id FROM eval_stage), 'reject');
```

### Part 6: Surveillance-Specific Tables (NEW)

**These are the ONLY new tables:**

```sql
-- Configuration table (org/dept level settings)
CREATE TABLE surveillance_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    department_id UUID REFERENCES org_departments(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT true,
    default_period_months INTEGER,
    period_mode VARCHAR(50),  -- use_warranty, use_default, use_max
    abnormal_statuses JSONB,  -- ["FAIL", "MARGINAL", "CRITICAL", "ALERT"]
    quality_thresholds JSONB,  -- {"good": 0, "fair": 0.2}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Ensure unique config per org/dept combo
    CONSTRAINT uq_surveillance_config UNIQUE (organization_id, department_id),
    
    -- Either org or dept, not both NULL (system-wide config can have both NULL)
    CONSTRAINT chk_config_scope CHECK (
        (organization_id IS NOT NULL AND department_id IS NULL) OR
        (organization_id IS NULL AND department_id IS NOT NULL) OR
        (organization_id IS NULL AND department_id IS NULL)
    )
);

-- Test type configuration (links to CategoryDetails)
CREATE TABLE surveillance_test_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    surveillance_config_id UUID NOT NULL REFERENCES surveillance_config(id) ON DELETE CASCADE,
    test_type_id INTEGER NOT NULL REFERENCES "CategoryDetails"(id) ON DELETE CASCADE,
    normal_frequency_months INTEGER NOT NULL,
    surveillance_frequency_months INTEGER NOT NULL,
    enabled BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- No duplicate test types per config
    CONSTRAINT uq_test_per_config UNIQUE (surveillance_config_id, test_type_id)
);

-- Surveillance test tracking (junction table)
CREATE TABLE repair_surveillance_tests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repair_workflow_id UUID NOT NULL REFERENCES repair_workflows(id) ON DELETE CASCADE,
    testing_request_id UUID NOT NULL REFERENCES testing_requests(id) ON DELETE CASCADE,
    test_result_id UUID REFERENCES test_results(id) ON DELETE SET NULL,
    test_type VARCHAR(100) NOT NULL,
    result_status VARCHAR(50),
    is_abnormal BOOLEAN DEFAULT false,
    abnormal_reason TEXT,
    tested_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- No duplicate testing requests
    CONSTRAINT uq_surveillance_test_request UNIQUE (testing_request_id)
);

CREATE INDEX idx_surveillance_tests_workflow ON repair_surveillance_tests(repair_workflow_id);
CREATE INDEX idx_surveillance_tests_abnormal ON repair_surveillance_tests(is_abnormal) WHERE is_abnormal = true;
```

### Part 7: Modify Existing Tables (Minimal Changes)

```sql
-- Add surveillance linkage to repair_workflows
ALTER TABLE repair_workflows 
    ADD COLUMN linked_repair_workflow_id UUID REFERENCES repair_workflows(id) ON DELETE SET NULL,
    ADD COLUMN surveillance_period_months INTEGER,
    ADD COLUMN warranty_period_months INTEGER;

CREATE INDEX idx_repair_workflows_linked ON repair_workflows(linked_repair_workflow_id);

-- Add surveillance linkage to testing_requests
ALTER TABLE testing_requests
    ADD COLUMN surveillance_workflow_id UUID REFERENCES repair_workflows(id) ON DELETE SET NULL,
    ADD COLUMN surveillance_quarter INTEGER CHECK (surveillance_quarter BETWEEN 1 AND 4);

CREATE INDEX idx_testing_requests_surveillance ON testing_requests(surveillance_workflow_id, surveillance_quarter);

-- Add metadata to test_request_schedules (if column doesn't exist)
-- ALTER TABLE test_request_schedules ADD COLUMN metadata JSONB;
-- (Check if metadata column already exists first)
```

---

## Workflow Lifecycle (Using Existing Service)

### 1. Create Surveillance Workflow (Same as Repair)

**Trigger:** Stage 10 of parent repair completes

**Hook:**

```python
# repair_hooks.py

def _on_stage_10_approved(db, workflow, user_id, stage_code=None, **_kwargs):
    if stage_code != "STAGE_10_COMMISSIONING":
        return
    
    # Use existing RepairWorkflowService
    from services.repair_workflow_service import RepairWorkflowService
    from services.surveillance_config_service import SurveillanceConfigService
    
    wf_service = RepairWorkflowService(db)
    config_service = SurveillanceConfigService(db)
    
    # Get surveillance config
    config = config_service.get_config(workflow.organization_id, workflow.department_id)
    
    if not config.enabled:
        return
    
    # Get SURVEILLANCE workflow definition
    surv_def = db.query(RepairWorkflowDefinition).filter(
        RepairWorkflowDefinition.workflow_code == "SURVEILLANCE"
    ).first()
    
    # Calculate surveillance period
    months = config.get_surveillance_period(workflow.warranty_period_months)
    
    # Create surveillance workflow using existing service
    surv_workflow = wf_service.create_workflow(
        workflow_definition_id=surv_def.id,
        equipment_id=workflow.equipment_id,
        organization_id=workflow.organization_id,
        department_id=workflow.department_id,
        workflow_number=f"{workflow.workflow_number}-SURV",
        workflow_code="SURVEILLANCE",
        linked_repair_workflow_id=workflow.id,
        surveillance_period_months=months,
        warranty_period_months=workflow.warranty_period_months,
        created_by=user_id
    )
    
    # Service automatically creates stage instances for all 5 stages
    # (This is standard RepairWorkflowService behavior)
    
    # Update test schedules to surveillance mode
    _activate_enhanced_testing(db, workflow.equipment_id, surv_workflow.id, config, user_id)
```

### 2. Officer Submits Stage (Same Method)

```python
# No new code needed - existing service handles this

from services.repair_workflow_service import RepairWorkflowService

service = RepairWorkflowService(db)

# Officer submits Q1 review
service.submit_stage(
    workflow_id=surveillance_workflow_id,
    stage_instance_id=q1_stage_instance_id,
    form_data={
        "quarter_number": "Q1",
        "test_summary_table": [...],
        "officer_observations": "All tests satisfactory...",
        ...
    },
    user_id=officer_id
)

# This saves to repair_stage_data table (same as repair workflow)
# Stage status: pending → submitted
```

### 3. Approver Approves Stage (Same Method)

```python
# Existing service method - no changes needed

service.advance_stage(
    workflow_id=surveillance_workflow_id,
    remarks="Q1 surveillance approved",
    user_id=approver_id,
    action_label="approve"
)

# Service automatically:
# - Updates stage instance status: submitted → completed
# - Advances to next stage (Q2)
# - Updates workflow progress: 0% → 20%
# - Creates audit log entry
# - Fires workflow hook: fire("SURVEILLANCE", "stage_approved", stage_code="SURV_Q1")
```

### 4. Workflow Completes (Same Pattern)

```python
# When Final Evaluation approved:

service.advance_stage(
    workflow_id=surveillance_workflow_id,
    remarks="Final evaluation approved",
    user_id=approver_id
)

# Service detects no next stage (transition to NULL)
# Automatically:
# - Sets workflow status: active → completed
# - Sets progress: 100%
# - Fires hook: fire("SURVEILLANCE", "completed", db, workflow, user_id)

# Hook handler generates report and reverts schedules:
def _on_surveillance_completed(db, workflow, user_id, **_kwargs):
    # Generate final report
    PostRepairEvaluationService(db).generate_report(workflow.linked_repair_workflow_id)
    
    # Revert test schedules
    _deactivate_enhanced_testing(db, workflow.equipment_id)
```

---

## Template Loading (Same Pattern as Test Templates)

**Current System:** Test templates loaded from `test_templates.py` dict

**Surveillance Templates:** Same pattern using `SURVEILLANCE_STAGE_TEMPLATES.json`

```python
# services/template_loader_service.py (or wherever templates are loaded)

import json

# Load surveillance templates
with open('SURVEILLANCE_STAGE_TEMPLATES.json') as f:
    SURVEILLANCE_TEMPLATES = json.load(f)

# When rendering stage form:
def get_stage_template(stage_id):
    # Get template key from repair_stage_templates table
    template_link = db.query(RepairStageTemplate).filter(
        RepairStageTemplate.stage_id == stage_id
    ).first()
    
    template_key = template_link.template_key
    
    # Load from appropriate source
    if template_key.startswith('surveillance_'):
        return SURVEILLANCE_TEMPLATES[template_key]
    else:
        return TEST_TEMPLATES[template_key]  # Existing test templates
```

---

## UI Integration (Zero New Components)

### Workflow List Page

**Existing Component:** Shows all workflows (repair, calibration, overhaul)

**No Change Needed:** Surveillance workflows appear automatically

```dart
// Existing query fetches ALL workflow types
final workflows = await api.getWorkflows(
  organizationId: orgId,
  status: 'active'
);

// Returns:
// - REP-2026-001 (REPAIR workflow)
// - CAL-2026-015 (CALIBRATION workflow)
// - REP-2026-001-SURV (SURVEILLANCE workflow) ← Shows up here!

// Filter in UI if needed:
final surveillanceWorkflows = workflows.where(
  (w) => w.workflowCode == 'SURVEILLANCE'
).toList();
```

### Workflow Detail Page

**Existing Component:** `WorkflowDetailPage(workflowId)`

**No Change Needed:** Renders any workflow type

```dart
// Same component for all workflows
WorkflowDetailPage(workflowId: 'uuid-of-surv-workflow')

// Automatically shows:
// - 5-stage progress stepper (instead of 10 for repair)
// - Current stage: "Q1 Surveillance Testing"
// - Progress: 20%
// - Stage history
// - Audit log
```

### Stage Form Page

**Existing Component:** `StageFormPage(workflowId, stageInstanceId)`

**No Change Needed:** Renders any template

```dart
// Same component renders surveillance templates
StageFormPage(
  workflowId: survWorkflowId,
  stageInstanceId: q1InstanceId
)

// Fetches template key from backend: "surveillance_quarter_review"
// Loads template JSON
// Renders form sections
// Pre-fills readonly fields
// Shows editable fields for officer
```

### Approval Page

**Existing Component:** Stage approval buttons

**No Change Needed:** Same approve/reject logic

```dart
// Same buttons for all workflow types
StageApprovalButtons(
  onApprove: () {
    await api.advanceStage(workflowId, remarks);
  },
  onReject: () {
    await api.rejectStage(workflowId, remarks);
  }
)
```

---

## API Endpoints (Minimal New Endpoints)

### Existing Endpoints Work for Surveillance

| Endpoint | Usage for Surveillance | Changes Needed |
|----------|------------------------|----------------|
| `GET /api/repair-workflows` | List surveillances | ✅ None (filter by workflow_code) |
| `GET /api/repair-workflows/{id}` | Get surveillance detail | ✅ None |
| `POST /api/repair-workflows` | Create surveillance | ✅ None (called by hook) |
| `GET /api/repair-workflows/{id}/stages` | Get stage list | ✅ None |
| `POST /api/repair-workflows/{id}/stages/{stage_id}/submit` | Submit Q1 review | ✅ None |
| `POST /api/repair-workflows/{id}/stages/{stage_id}/approve` | Approve Q1 | ✅ None |
| `POST /api/repair-workflows/{id}/stages/{stage_id}/reject` | Reject Q1 | ✅ None |
| `GET /api/repair-workflows/{id}/audit-log` | Get audit trail | ✅ None |

### New Endpoints Needed (Surveillance-Specific)

**Only for template data population and config:**

```python
# routers/surveillance.py (NEW - but minimal)

@router.get("/api/surveillance-workflows/{workflow_id}/stage/{stage_id}/template-data")
def get_surveillance_stage_template_data(...):
    """
    Pre-populate template with test data.
    This is surveillance-specific logic (not generic to all workflows).
    """
    from services.surveillance_template_service import SurveillanceTemplateService
    
    svc = SurveillanceTemplateService(db)
    
    # Determine which template based on stage code
    stage = db.query(RepairStageDefinition).join(...).filter(...).first()
    
    if stage.code in ['SURV_Q1', 'SURV_Q2', 'SURV_Q3', 'SURV_Q4']:
        template_data = svc.populate_quarter_review_template(workflow_id, stage_id)
    elif stage.code == 'SURV_EVAL':
        template_data = svc.populate_final_evaluation_template(workflow_id, stage_id)
    
    return template_data

@router.get("/api/surveillance-config")
def get_surveillance_config(...):
    """Get surveillance configuration for org/dept"""
    # Config management endpoints

@router.put("/api/surveillance-config")
def update_surveillance_config(...):
    """Update surveillance configuration"""
    # Admin only
```

---

## Summary: Pattern Consistency

### ✅ What Surveillance Reuses (No Duplication)

| Component | Existing Infrastructure | Surveillance Usage |
|-----------|------------------------|-------------------|
| **Tables** | repair_workflow_definitions | Add 1 row: SURVEILLANCE |
| | repair_stage_definitions | Add 5 rows: Q1-Q4, Eval |
| | repair_stage_templates | Add 5 rows: stage→template links |
| | repair_stage_roles | Add 6-10 rows: RBAC |
| | repair_stage_transitions | Add 10 rows: approve/reject |
| | repair_workflows | Create instances with workflow_code=SURVEILLANCE |
| | repair_stage_instances | 5 instances per surveillance |
| | repair_stage_data | Store officer's form submissions |
| | repair_assignment_queue | Manage pending stages |
| | repair_stage_audit_log | Track all actions |
| **Service** | RepairWorkflowService | ✅ Same service, zero changes |
| **UI Components** | Workflow list, detail, forms | ✅ Same components, zero changes |
| **API Endpoints** | GET/POST /repair-workflows/... | ✅ Same endpoints |

### ✅ What's New (Surveillance-Specific Only)

| Component | Purpose | Justification |
|-----------|---------|---------------|
| `surveillance_config` table | Org/dept settings | Surveillance-specific config (not needed by repair) |
| `surveillance_test_config` table | Test type frequencies | Surveillance-specific (repair doesn't auto-create tests) |
| `repair_surveillance_tests` table | Test tracking/junction | Links tests to parent repair workflow |
| Template population service | Pre-fill template data | Surveillance-specific logic (queries testing_requests) |
| 2-3 new API endpoints | Template data, config | Surveillance-specific features |

### ✅ Design Principles Followed

1. **Single Service Pattern** ✅  
   RepairWorkflowService handles all workflow types

2. **Generic Workflow Infrastructure** ✅  
   Same tables for all workflow types

3. **Template-Based Forms** ✅  
   Surveillance templates like test templates

4. **RBAC via Roles** ✅  
   repair_stage_roles defines permissions

5. **Audit Trail** ✅  
   repair_stage_audit_log tracks everything

6. **UI Component Reuse** ✅  
   Zero new UI components needed

7. **Hook-Based Extensions** ✅  
   Hooks handle surveillance-specific logic

---

## Migration Script Structure

```python
# alembic/versions/xxx_add_surveillance_workflow.py

def upgrade():
    # Part 1: Workflow Definition (1 INSERT)
    # INSERT INTO repair_workflow_definitions ...
    
    # Part 2: Stage Definitions (5 INSERTs)
    # INSERT INTO repair_stage_definitions ...
    
    # Part 3: Stage Templates (5 INSERTs)
    # INSERT INTO repair_stage_templates ...
    
    # Part 4: Stage Roles (6-10 INSERTs)
    # INSERT INTO repair_stage_roles ...
    
    # Part 5: Stage Transitions (10 INSERTs)
    # INSERT INTO repair_stage_transitions ...
    
    # Part 6: Surveillance-Specific Tables (3 CREATEs)
    # CREATE TABLE surveillance_config ...
    # CREATE TABLE surveillance_test_config ...
    # CREATE TABLE repair_surveillance_tests ...
    
    # Part 7: Modify Existing Tables (2 ALTERs)
    # ALTER TABLE repair_workflows ADD COLUMN linked_repair_workflow_id ...
    # ALTER TABLE testing_requests ADD COLUMN surveillance_workflow_id ...
    
    # Part 8: Seed Data (System-wide default config)
    # INSERT INTO surveillance_config (organization_id=NULL, ...) ...
    # INSERT INTO surveillance_test_config (test_type_id from CategoryDetails) ...

def downgrade():
    # Reverse all changes
    pass
```

---

## Verification Checklist

Before implementation, verify:

- [ ] Surveillance uses repair_workflow_definitions (not new table)
- [ ] Surveillance uses repair_stage_definitions (not new table)
- [ ] Surveillance uses repair_stage_instances (not new table)
- [ ] Surveillance uses repair_stage_data (not new table)
- [ ] Surveillance uses repair_stage_audit_log (not new table)
- [ ] RepairWorkflowService methods work for surveillance (no new service)
- [ ] Existing UI components render surveillance (no new components)
- [ ] Existing API endpoints handle surveillance (no new CRUD endpoints)
- [ ] Only 3 new tables: config, test_config, surveillance_tests (justified)
- [ ] Only surveillance-specific endpoints: template-data, config (justified)

✅ **Pattern consistency maintained - surveillance is just another workflow type!**

---

**Document End**
