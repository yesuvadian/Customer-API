# Annual Substation Inspection Observation System — Complete Updated Design

## 1. Design Principles

The Annual Substation Inspection Observation module shall:

- Reuse the existing workflow engine
- Reuse the existing transition graph model
- Reuse the existing assignment queue
- Reuse the existing RBAC framework
- Reuse the existing dynamic template engine
- Reuse the existing category framework
- Reuse the existing audit logging framework
- Avoid duplicate workflow infrastructure

The module shall be implemented as a business workflow using the existing configurable workflow framework.

---

# 2. Workflow Definition

Existing Model Reused:

- RepairWorkflowDefinition

## Existing Model

```python
class RepairWorkflowDefinition(Base):
    __tablename__ = "repair_workflow_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String, default="Transformer Repair Lifecycle")

    is_active = Column(Boolean, default=True)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    created_at = Column(
        DateTime,
        server_default=func.now()
    )

    modified_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    modified_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now()
    )
```

The Annual Audit workflow shall reuse the existing `repair_workflow_definitions` table.

No separate workflow definition table shall be created.

## Recommended Improvement

Add a workflow code column for unique workflow identification.

```python
workflow_code = Column(String(100), unique=True, nullable=False)
```

## Updated Recommended Model

```python
class RepairWorkflowDefinition(Base):
    __tablename__ = "repair_workflow_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workflow_code = Column(String(100), unique=True, nullable=False)

    name = Column(String, nullable=False)

    is_active = Column(Boolean, default=True)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    created_at = Column(
        DateTime,
        server_default=func.now()
    )

    modified_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    modified_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now()
    )
```

## Workflow Seed

```python
ANNUAL_AUDIT_WORKFLOW = {
    "workflow_code": "ANNUAL_AUDIT",
    "name": "Annual Audit Workflow"
}
```

---

# 2A. Existing System Roles

The current platform already supports the following organizational roles:

```text
Admin
Org Admin
Originator
Test Assigner
Field Tester
Lab Tester
Department Head
Dept Head
Purchaser
doc-viewer
AEE Maintenance
EE TLSS
SEE W&M
EE RT
SEE RT
CEE Transmission Zone
CEE RT&R&D
Workflow Coordinator
Tester
Technical Approver
Finance Approver
TA&QC Officer
Section Head
```

The Annual Audit workflow shall reuse the existing role framework.

No new workflow roles shall be introduced unless organizationally required.

---

# 2B. Roles Used in Annual Audit Workflow

The Annual Audit module shall use the following existing roles:

| Role | Responsibility |
|---|---|
| TA&QC Officer | Create observations, review compliance, close observations |
| Workflow Coordinator | Workflow assignment and routing |
| AEE Maintenance | Submit compliance and corrective actions |
| EE TLSS | Escalation monitoring |
| SEE W&M | Escalation monitoring |
| CEE Transmission Zone | Escalation monitoring |
| doc-viewer | Read-only dashboard/report access |
| Department Head / Dept Head | Monitoring and reporting access |

The following existing system roles are not part of the Annual Audit workflow execution lifecycle:

- Originator
- Test Assigner
- Field Tester
- Lab Tester
- Purchaser
- Technical Approver
- Finance Approver
- EE RT
- SEE RT
- Tester
- Section Head
- CEE RT&R&D

These roles may continue to be used by other workflow modules within the platform.

---

# 3. Workflow Stages

Existing Model Reused:

- RepairStageDefinition

The workflow shall follow the existing naming convention already used in the repair lifecycle workflow.

## Stage Definitions

```python
ANNUAL_AUDIT_STAGES = [

    {
        "stage_code": "OBSERVATION_REPORTING",
        "roles": [
            "TA&QC Officer"
        ],
        "assignment_role": "Workflow Coordinator"
    },

    {
        "stage_code": "OBSERVATION_ASSIGNMENT",
        "roles": [
            "Workflow Coordinator"
        ],
        "assignment_role": "Workflow Coordinator"
    },

    {
        "stage_code": "COMPLIANCE_SUBMISSION",
        "roles": [
            "AEE Maintenance"
        ],
        "assignment_role": "Workflow Coordinator"
    },

    {
        "stage_code": "COMPLIANCE_REVIEW",
        "roles": [
            "TA&QC Officer"
        ],
        "assignment_role": "Workflow Coordinator"
    },

    {
        "stage_code": "OBSERVATION_CLOSURE",
        "roles": [
            "TA&QC Officer"
        ],
        "assignment_role": "Workflow Coordinator"
    }
]
```

---

# 4. Workflow Transitions

Existing Model Reused:

- RepairStageTransition

The workflow engine is action-driven and transition-based.

## Transition Definitions

```python
ANNUAL_AUDIT_TRANSITIONS = [

    {
        "from": "OBSERVATION_REPORTING",
        "action": "assign",
        "to": "OBSERVATION_ASSIGNMENT"
    },

    {
        "from": "OBSERVATION_ASSIGNMENT",
        "action": "submit",
        "to": "COMPLIANCE_SUBMISSION"
    },

    {
        "from": "COMPLIANCE_SUBMISSION",
        "action": "review",
        "to": "COMPLIANCE_REVIEW"
    },

    {
        "from": "COMPLIANCE_REVIEW",
        "action": "approve",
        "to": "OBSERVATION_CLOSURE"
    },

    {
        "from": "COMPLIANCE_REVIEW",
        "action": "reject",
        "to": "COMPLIANCE_SUBMISSION"
    }
]
```

---

# 4A. Workflow Stage Status Mapping

The workflow engine uses business-oriented stage names.

For dashboards, SLA tracking, escalation handling, reporting, and filtering, each stage shall also correspond to a derived workflow status.

## Stage to Status Mapping

| Stage Code | Derived Workflow Status | Description |
|---|---|---|
| OBSERVATION_REPORTING | OPEN | Observation created by TA&QC Officer |
| OBSERVATION_ASSIGNMENT | ASSIGNED | Observation assigned to responsible user/role |
| COMPLIANCE_SUBMISSION | PENDING_COMPLIANCE | Corrective action pending/submitted by maintenance |
| COMPLIANCE_REVIEW | UNDER_REVIEW | Compliance under verification by TA&QC Officer |
| OBSERVATION_CLOSURE | CLOSED | Observation verified and closed |

---

# 4B. Rejection Workflow Behavior

The workflow engine is transition-driven.

Rejected observations shall NOT move to a separate REOPENED stage.

Instead:

```text
COMPLIANCE_REVIEW
    ↓ reject
COMPLIANCE_SUBMISSION
```

The rejection action shall:

- create workflow audit logs,
- store reviewer remarks,
- notify assigned users,
- and return the ticket to the compliance stage.

## Runtime Status During Rejection

When a rejection transition occurs:

| Action | Resulting Status |
|---|---|
| reject | PENDING_COMPLIANCE |

---

# 5. Workflow Runtime Flow

```text
OBSERVATION_REPORTING
        ↓ assign
OBSERVATION_ASSIGNMENT
        ↓ submit
COMPLIANCE_SUBMISSION
        ↓ review
COMPLIANCE_REVIEW
    ├── approve → OBSERVATION_CLOSURE
    └── reject  → COMPLIANCE_SUBMISSION
```

---

# 6. Category Framework

Existing Models Reused:

- CategoryMaster
- CategoryDetails

The Annual Audit module shall reuse the existing generic category framework.

## Category Master Seed

```python
{
    "name": "Annual Audit Categories",
    "description": "Annual Substation Audit Observation Categories"
}
```

## Category Detail Seed

```python
[
    {
        "name": "Electrical Safety",
        "category_type": "annual_audit"
    },

    {
        "name": "Civil",
        "category_type": "annual_audit"
    },

    {
        "name": "Fire Safety",
        "category_type": "annual_audit"
    },

    {
        "name": "Documentation",
        "category_type": "annual_audit"
    },

    {
        "name": "Environmental",
        "category_type": "annual_audit"
    },

    {
        "name": "General Maintenance",
        "category_type": "annual_audit"
    }
]
```

---

# 7. Important Architectural Principle

Observation Categories are NOT workflow stages.

Correct:

```text
Observation:
    Category = Electrical Safety

Workflow:
    OBSERVATION_REPORTING
        ↓
    COMPLIANCE_REVIEW
        ↓
    OBSERVATION_CLOSURE
```

Incorrect:

```text
Electrical Safety → Fire Safety → Civil
```

Categories classify observations.
Workflow stages manage lifecycle.

---

# 8. Annual Inspection Entity

## New Model

```python
class TAQCAnnualInspection(Base):
    __tablename__ = "taqc_annual_inspections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    inspection_number = Column(
        String(50),
        unique=True,
        nullable=False
    )

    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.organizations.id"),
        nullable=False
    )

    substation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.equipment.id"),
        nullable=False
    )

    inspection_date = Column(Date, nullable=False)

    inspected_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    remarks = Column(Text)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    cts = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    mts = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    observations = relationship(
        "TAQCObservation",
        back_populates="inspection",
        cascade="all, delete-orphan"
    )
```

---

# 8A. Observation Numbering Pattern

The Annual Audit observation tickets shall use a structured running ticket number format similar to the existing platform numbering convention.

## Existing Platform Pattern Example

```text
TR-REG-20260509-0001
TR-REG-20260509-0002
TR-REG-20260509-0003
```

Where:

| Segment | Meaning |
|---|---|
| TR | Testing Request |
| REG | Request Category / Module |
| 20260509 | Date (YYYYMMDD) |
| 0001 | Running Sequence |

---

# Recommended Annual Audit Observation Number Pattern

The Annual Audit module shall follow the same numbering convention already used by testing requests.

## Recommended Observation Number Format

```text
TR-ANU-20260509-0001
TR-ANU-20260509-0002
TR-ANU-20260509-0003
```

---

# Recommended Segment Meaning

| Segment | Meaning |
|---|---|
| TR | Transmission / Testing Platform Prefix |
| ANU | Annual Audit Module |
| 20260509 | Observation Creation Date |
| 0001 | Daily Running Sequence |

---

# Recommended Annual Inspection Number Pattern

The parent annual inspection entity may use:

```text
TR-ANU-INSP-20260509-0001
```

or simplified:

```text
TR-ANU-20260509-0001
```

based on organizational preference.

---

# Recommended Runtime Generation Logic

```text
TR-ANU-YYYYMMDD-####
```

Example:

```text
TR-ANU-20260509-0015
```

represents:

- 15th annual audit observation created on 09-May-2026.

---

# Recommended Database Constraints

| Segment | Meaning |
|---|---|
| AA | Annual Audit |
| OBS | Observation |
| 20260509 | Observation Creation Date |
| 0001 | Daily Running Sequence |

---

# Recommended Annual Inspection Number Pattern

The parent annual inspection entity may use:

```text
AA-INSP-20260509-0001
```

---

# Recommended Number Generation Rules

The numbering engine shall:

- generate numbers automatically,
- maintain uniqueness,
- reset running sequence daily,
- support concurrent request creation,
- and prevent duplicate numbers.

---

# Recommended Runtime Generation Logic

```text
PREFIX + DATE + DAILY_SEQUENCE
```

Example:

```text
AA-OBS-20260509-0015
```

represents:

- 15th observation created on 09-May-2026.

---

# Recommended Database Constraints

The following fields shall remain unique:

| Entity | Field |
|---|---|
| taqc_annual_inspections | inspection_number |
| taqc_observations | observation_number |

---

# 9. Observation Entity

Each observation shall behave as an independent workflow ticket.

## New Model

```python
class TAQCObservation(Base):
    __tablename__ = "taqc_observations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    inspection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.taqc_annual_inspections.id"),
        nullable=False
    )

    observation_number = Column(
        String(50),
        unique=True,
        nullable=False
    )

    category_detail_id = Column(
        Integer,
        ForeignKey("public.CategoryDetails.id"),
        nullable=False
    )

    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.org_test_templates.id")
    )

    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.repair_workflows.id")
    )

    severity = Column(String(20))

    target_compliance_date = Column(Date)

    observation_description = Column(Text)

    current_stage_code = Column(String(100))

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    assigned_to = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    reviewer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    is_overdue = Column(Boolean, default=False)

    cts = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    mts = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    inspection = relationship(
        "TAQCAnnualInspection",
        back_populates="observations"
    )

    category = relationship(
        "CategoryDetails",
        foreign_keys=[category_detail_id]
    )
```

---

# 10. Dynamic Template Design

Existing Component Reused:

- OrgTestTemplate

## Existing Model

```python
class OrgTestTemplate(Base):
    __tablename__ = "org_test_templates"

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "template_key",
            name="uq_org_template_key"
        ),
        {"schema": "public"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    org_id = Column(
        UUID(as_uuid=True),
        nullable=True
    )

    # NULL = global default

    template_key = Column(
        String(100),
        nullable=False
    )

    test_type_id = Column(
        Integer,
        nullable=True
    )

    # soft ref to CategoryDetails.id

    template_data = Column(
        JSONB,
        nullable=False
    )

    # full template JSON

    is_system = Column(Boolean, default=True)

    version = Column(Integer, default=1)
```

The Annual Audit module shall fully reuse the existing `org_test_templates` architecture.

No separate audit template tables shall be created.

The existing `test_type_id` field shall reference:

```text
CategoryDetails.id
```

for annual audit observation categories.

---

# Recommended Annual Audit Template Strategy

Instead of introducing separate category-template mapping tables, the Annual Audit module shall directly use:

```text
CategoryDetails
        ↓
OrgTestTemplate.test_type_id
```

This keeps the architecture fully aligned with the current platform template framework.

---

# Recommended Template Keys

| Category | Template Key |
|---|---|
| Electrical Safety | audit_electrical_safety |
| Civil | audit_civil |
| Fire Safety | audit_fire_safety |
| Documentation | audit_documentation |
| Environmental | audit_environmental |
| General Maintenance | audit_general_maintenance |

---

# Recommended test_type_id Usage

| CategoryDetails.name | CategoryDetails.category_type | Used As |
|---|---|---|
| Electrical Safety | annual_audit | OrgTestTemplate.test_type_id |
| Fire Safety | annual_audit | OrgTestTemplate.test_type_id |
| Civil | annual_audit | OrgTestTemplate.test_type_id |

---

# Runtime Template Resolution

```text
TAQCObservation.category_detail_id
        ↓
OrgTestTemplate.test_type_id
        ↓
Dynamic Template Loaded
```

---

# Annual Audit Template Seed Example

```python
ANNUAL_AUDIT_TEMPLATES = {

    "audit_electrical_safety": {

        "template_key": "audit_electrical_safety",

        "template_type": "annual_audit",

        "sections": [

            {
                "title": "Electrical Safety Checks",

                "fields": [

                    {
                        "key": "earthing_condition",
                        "label": "Earthing Condition",
                        "type": "dropdown",
                        "required": True,
                        "options": [
                            "Good",
                            "Damaged",
                            "Corroded"
                        ]
                    },

                    {
                        "key": "danger_board_available",
                        "label": "Danger Board Available",
                        "type": "boolean"
                    },

                    {
                        "key": "shock_hazard_observed",
                        "label": "Shock Hazard Observed",
                        "type": "boolean"
                    },

                    {
                        "key": "observation_photo",
                        "label": "Observation Photograph",
                        "type": "file"
                    },

                    {
                        "key": "remarks",
                        "label": "Remarks",
                        "type": "textarea"
                    }
                ]
            }
        ]
    }
}
```

---

# 11. Category Template Mapping

## New Model

```python
class TAQCCategoryTemplate(Base):
    __tablename__ = "taqc_category_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    category_detail_id = Column(
        Integer,
        ForeignKey("public.CategoryDetails.id"),
        nullable=False
    )

    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.org_test_templates.id"),
        nullable=False
    )

    is_active = Column(Boolean, default=True)

    cts = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
```

---

# 12. Dynamic Template Structure Standard

The Annual Audit module shall follow the same JSON template structure already used in the existing platform dynamic forms.

Existing platform templates already support:

- sections
- fields
- dropdowns
- booleans
- numbers
- units
- validation
- placeholders
- textarea
- file uploads
- result evaluation

The Annual Audit templates shall use the exact same structure.

---

# Existing Dynamic Template Pattern Example

```json
{
  "key": "relay_testing_report",
  "name": "Relay Testing Report",
  "sections": [
    {
      "title": "Relay Information",
      "fields": [
        {
          "key": "relay_make",
          "type": "text",
          "label": "Relay Make",
          "required": true
        }
      ]
    }
  ]
}
```

---

# Annual Audit Template Design Standard

Annual Audit templates shall follow the same structure:

```json
{
  "key": "audit_electrical_safety",
  "name": "Electrical Safety Audit",
  "sections": [
    {
      "title": "Electrical Safety Checks",
      "fields": [
        {
          "key": "earthing_condition",
          "type": "dropdown",
          "label": "Earthing Condition",
          "options": [
            "Good",
            "Damaged",
            "Corroded"
          ],
          "required": true
        }
      ]
    }
  ]
}
```

---

# Recommended Annual Audit Template Seed

```python
ANNUAL_AUDIT_TEMPLATES = {

    "audit_electrical_safety": {

        "key": "audit_electrical_safety",

        "name": "Electrical Safety Audit",

        "description": "Electrical safety inspection observations",

        "sections": [

            {
                "title": "Earthing System",

                "fields": [

                    {
                        "key": "earthing_condition",
                        "type": "dropdown",
                        "label": "Earthing Condition",
                        "options": [
                            "Good",
                            "Damaged",
                            "Corroded"
                        ],
                        "required": true
                    },

                    {
                        "key": "earthing_resistance",
                        "type": "number",
                        "label": "Earthing Resistance",
                        "unit": "ohms"
                    },

                    {
                        "key": "earthing_photo",
                        "type": "file",
                        "label": "Earthing Photograph"
                    }
                ]
            },

            {
                "title": "Safety Protection",

                "fields": [

                    {
                        "key": "danger_board_available",
                        "type": "boolean",
                        "label": "Danger Board Available"
                    },

                    {
                        "key": "shock_hazard_observed",
                        "type": "boolean",
                        "label": "Shock Hazard Observed"
                    },

                    {
                        "key": "safety_remarks",
                        "type": "textarea",
                        "label": "Safety Remarks"
                    }
                ]
            },

            {
                "title": "Observation Assessment",

                "fields": [

                    {
                        "key": "severity",
                        "type": "dropdown",
                        "label": "Severity",
                        "options": [
                            "Major",
                            "Minor",
                            "Advisory"
                        ],
                        "required": true
                    },

                    {
                        "key": "overall_result",
                        "type": "dropdown",
                        "label": "Overall Result",
                        "options": [
                            "Compliant",
                            "Non-Compliant",
                            "Conditional"
                        ],
                        "required": true
                    }
                ]
            }
        ]
    },

    "audit_fire_safety": {

        "key": "audit_fire_safety",

        "name": "Fire Safety Audit",

        "description": "Fire safety inspection observations",

        "sections": [

            {
                "title": "Fire Safety Equipment",

                "fields": [

                    {
                        "key": "fire_extinguisher_available",
                        "type": "boolean",
                        "label": "Fire Extinguisher Available"
                    },

                    {
                        "key": "fire_extinguisher_expiry",
                        "type": "date",
                        "label": "Fire Extinguisher Expiry"
                    },

                    {
                        "key": "fire_alarm_operational",
                        "type": "boolean",
                        "label": "Fire Alarm Operational"
                    },

                    {
                        "key": "oil_leakage_present",
                        "type": "boolean",
                        "label": "Oil Leakage Present"
                    },

                    {
                        "key": "fire_safety_photo",
                        "type": "file",
                        "label": "Fire Safety Photograph"
                    }
                ]
            }
        ]
    }
}
```

---

# 13. Assignment Logic

Existing Component Reused:

- RepairAssignmentQueue

Workflow assignment shall remain:

- stage-driven
- role-driven
- user-assigned

A role may contain multiple users.
Actual workflow accountability shall remain at user level.

---

# 14. Dashboard, SLA Tracking, and Escalation Logic

The system shall continuously maintain workflow analytics and SLA monitoring for Annual Audit observations.

The functionality shall be implemented using:

- workflow runtime data,
- workflow stage status,
- target compliance dates,
- scheduler jobs,
- dashboard aggregation queries,
- and notification services.

---

# 14A. Open Observation Tracking

The system shall maintain and display:

- total open observations for each substation,
- pending duration for each observation,
- overdue observations,
- and overall compliance percentage.

These values shall be dynamically derived from:

```text
TAQCObservation
        ↓
current_stage_code
```

---

# 14B. Definition of Open Observation

An observation shall be treated as OPEN when:

```text
current_stage_code != OBSERVATION_CLOSURE
```

Closed observations:

```text
current_stage_code = OBSERVATION_CLOSURE
```

shall not be counted in pending totals.

---

# 14C. Pending Duration Calculation

Pending duration shall be calculated as:

```text
Current Date - Observation Creation Date
```

Recommended Runtime Calculation:

```sql
CURRENT_DATE - DATE(cts)
```

or

```sql
AGE(NOW(), cts)
```

This value shall be displayed in:

- substation dashboards,
- workflow inbox,
- escalation reports,
- management dashboards.

---

# 14D. Compliance Percentage Calculation

Compliance percentage shall be dynamically calculated for each substation.

## Formula

```text
(
    Closed Observations
    /
    Total Observations
) × 100
```

---

# Example

| Total Observations | Closed | Compliance % |
|---|---|---|
| 20 | 15 | 75% |

---

# Recommended SQL Logic

```sql
SELECT
    substation_id,

    COUNT(*) AS total_observations,

    SUM(
        CASE
            WHEN current_stage_code = 'OBSERVATION_CLOSURE'
            THEN 1
            ELSE 0
        END
    ) AS closed_observations,

    ROUND(
        (
            SUM(
                CASE
                    WHEN current_stage_code = 'OBSERVATION_CLOSURE'
                    THEN 1
                    ELSE 0
                END
            )::numeric
            /
            COUNT(*)
        ) * 100,
        2
    ) AS compliance_percentage

FROM taqc_observations
GROUP BY substation_id;
```

---

# 14E. Auto Escalation Logic

Auto escalation shall NOT be implemented as workflow stages.

Escalation shall be implemented using:

- scheduler jobs,
- SLA validation logic,
- notification engine,
- escalation hierarchy.

---

# Escalation Trigger Condition

An observation shall be escalated when:

```text
today > target_compliance_date
AND current_stage_code != OBSERVATION_CLOSURE
```

---

# Recommended Overdue Flag Update

```python
observation.is_overdue = (
    today > observation.target_compliance_date
    and observation.current_stage_code != "OBSERVATION_CLOSURE"
)
```

---

# 14F. Escalation Hierarchy

The following existing roles shall receive escalation alerts:

| Escalation Level | Role |
|---|---|
| Level 1 | EE TLSS |
| Level 2 | SEE W&M |
| Level 3 | CEE Transmission Zone |

---

# 14G. Escalation Notification Flow

```text
Observation overdue
        ↓
Scheduler detects SLA breach
        ↓
is_overdue = true
        ↓
Notification created
        ↓
Alerts sent to:
    - EE TLSS
    - SEE W&M
    - CEE Transmission Zone
```

---

# 14H. Recommended Scheduler Frequency

Recommended scheduler execution:

```text
Every day at 09:00 AM
```

The scheduler shall:

- identify overdue observations,
- update overdue flags,
- generate escalation notifications,
- generate dashboard metrics.

---

# 14I. Recommended Dashboard Metrics

The dashboard shall support:

| Metric | Description |
|---|---|
| Total Observations | Total created observations |
| Open Observations | Pending observations |
| Closed Observations | Completed observations |
| Overdue Observations | SLA breached observations |
| Compliance Percentage | Closed vs total percentage |
| Pending Days | Observation aging |
| Category-wise Pending | Pending by audit category |
| Severity-wise Pending | Major / Minor / Advisory |

---

# 15. Runtime Lifecycle

```text
TA&QC Officer
    ↓
Creates Annual Inspection
    ↓
Creates Observation
    ↓
Selects Category
    ↓
Dynamic Template Loaded
    ↓
Workflow Created
    ↓
OBSERVATION_REPORTING
    ↓ assign
OBSERVATION_ASSIGNMENT
    ↓ submit
COMPLIANCE_SUBMISSION
    ↓ review
COMPLIANCE_REVIEW
    ├── approve → OBSERVATION_CLOSURE
    └── reject  → COMPLIANCE_SUBMISSION
```

---

# 16. Generic Workflow Architecture Alignment

The existing platform architecture already follows a reusable business entity + workflow runtime model.

## Existing Testing Module Architecture

```text
testing_requests
        ↓
repair_workflows
        ↓
repair_stage_instances
        ↓
repair_stage_data
```

The Annual Audit module shall follow the same architectural pattern.

## Annual Audit Module Architecture

```text
taqc_observations
        ↓
repair_workflows
        ↓
repair_stage_instances
        ↓
repair_stage_data
```

This ensures:

- workflow engine reuse,
- assignment reuse,
- stage runtime reuse,
- audit log reuse,
- notification reuse,
- template reuse,
- and dashboard reuse.

---

# 16A. Separation of Business Entities

The Annual Audit module shall NOT reuse:

```text
testing_requests
```

because:

- testing lifecycle differs from audit lifecycle,
- audit observations are not testing requests,
- assignment semantics differ,
- SLA logic differs,
- escalation logic differs,
- workflow stages differ,
- and dashboard metrics differ.

The module shall instead introduce dedicated business entities while reusing the generic workflow infrastructure.

---

# 16B. Shared Generic Infrastructure

The following existing platform infrastructure shall be reused:

| Shared Component | Reused |
|---|---|
| repair_workflows | Yes |
| repair_stage_instances | Yes |
| repair_stage_data | Yes |
| repair_stage_audit_logs | Yes |
| repair_assignment_queue | Yes |
| org_test_templates | Yes |
| CategoryMaster | Yes |
| CategoryDetails | Yes |
| Notification Framework | Yes |
| RBAC Framework | Yes |

---

# 16C. Dedicated Annual Audit Business Entities

The following new entities shall be introduced:

| Entity | Purpose |
|---|---|
| taqc_annual_inspections | Parent annual inspection event |
| taqc_observations | Individual workflow observation ticket |

---

# 16D. Recommended Workflow Engine Enhancement

Since multiple business modules now reuse the same workflow runtime engine, the workflow engine should support generic entity references.

## Recommended Enhancement in repair_workflows

```python
entity_type = Column(String(100))
entity_id = Column(UUID(as_uuid=True))
```

---

# Example Runtime References

| entity_type | entity_id |
|---|---|
| testing_request | testing_requests.id |
| taqc_observation | taqc_observations.id |

This makes the workflow engine fully generic and reusable across future modules.

---

# 16E. Final Runtime Architecture

```text
CategoryMaster
    ↓
CategoryDetails
    ↓
OrgTestTemplate
    ↓
TAQCObservation
    ↓
RepairWorkflow
    ↓
RepairStageInstance
    ↓
RepairStageData(JSONB)
    ↓
Assignment Queue
    ↓
Audit Logs
```

---

# 17. Final Design Outcome

This design:

- fully aligns with existing naming conventions,
- fully reuses existing workflow runtime infrastructure,
- fully reuses existing category framework,
- fully reuses existing template engine,
- fully reuses existing assignment framework,
- avoids duplicate workflow systems,
- avoids duplicate category masters,
- keeps categories configurable,
- keeps workflows configurable,
- supports future inspection modules,
- supports future audit modules,
- and remains scalable for enterprise workflow expansion.

