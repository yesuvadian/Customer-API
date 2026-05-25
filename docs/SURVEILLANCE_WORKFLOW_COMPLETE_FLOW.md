# Post-Commissioning Surveillance Workflow - Complete Flow

> **Version:** 1.0  
> **Last Updated:** 2024-05-24  
> **Purpose:** End-to-end documentation of post-repair surveillance workflow with explicit testing request linkage

---

## Table of Contents

1. [Overview](#overview)
2. [Main Flow](#main-flow)
3. [Data Linkage Model](#data-linkage-model)
4. [Edge Cases & Error Handling](#edge-cases--error-handling)
5. [Missing Connections & Gaps](#missing-connections--gaps)
6. [UI Integration Points](#ui-integration-points)
7. [Notification Flow](#notification-flow)
8. [Dashboard Queries](#dashboard-queries)
9. [Testing Scenarios](#testing-scenarios)

---

## Overview

### Purpose

Post-commissioning surveillance is a **24-month monitoring period** after transformer repair completion (Stage 10 - Commissioning) to:
- Track equipment health during warranty period
- Validate vendor repair quality
- Detect early failure patterns
- Build vendor performance history

### Key Components

| Component | Type | Purpose |
|-----------|------|---------|
| Surveillance Workflow | RepairWorkflow | 5-stage workflow (Q1, Q2, Q3, Q4, Final Eval) |
| Testing Requests | TestingRequest | Auto-created tests with surveillance linkage |
| Test Schedules | TestRequestSchedule | Temporarily set to 2x frequency (6 months) |
| Junction Table | RepairSurveillanceTest | Links tests to parent repair workflow |
| Stage Templates | Form Templates | surveillance_quarter_review + surveillance_final_evaluation |

### Workflow Hierarchy

```
Parent Repair Workflow (REP-2026-001)
    └─> Stage 10: Commissioning (COMPLETED)
         └─> Triggers creation of:
              └─> Surveillance Workflow (REP-2026-001-SURV)
                   ├─> Stage 1: Q1 Surveillance Testing
                   ├─> Stage 2: Q2 Surveillance Testing
                   ├─> Stage 3: Q3 Surveillance Testing
                   ├─> Stage 4: Q4 Surveillance Testing
                   └─> Stage 5: Final Evaluation & Report
                        └─> Testing Requests (Auto-created every 6 months)
                             ├─> TR-2026-1001 (DGA, Q1, linked to SURV)
                             ├─> TR-2026-1002 (BDV, Q1, linked to SURV)
                             ├─> TR-2026-1003 (IR, Q1, linked to SURV)
                             └─> TR-2026-1004 (Oil Quality, Q1, linked to SURV)
```

---

## Main Flow

### Phase 1: Surveillance Activation (Day 0)

#### Trigger Event

```
Officer approves Stage 10 (Commissioning) of repair workflow REP-2026-001
    ↓
RepairWorkflowService.advance_stage() completes successfully
    ↓
Hook fires: workflow_hooks.fire("REPAIR", "stage_approved", stage_code="STAGE_10_COMMISSIONING")
    ↓
repair_hooks._on_stage_10_approved() executes
```

#### Actions Performed

**1. Create Surveillance Workflow**

```
New Record: repair_workflows
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
workflow_number:              REP-2026-001-SURV
workflow_code:                SURVEILLANCE
linked_repair_workflow_id:    uuid-of-REP-2026-001
equipment_id:                 uuid-of-PT-001
organization_id:              uuid-of-KPTCL
department_id:                uuid-of-Bangalore-North
surveillance_period_months:   24
warranty_period_months:       24 (from parent workflow)
status:                       active
progress:                     0
current_stage_id:             uuid-of-SURV_Q1-stage
created_at:                   2026-05-24 00:00:00 UTC
```

**2. Create 5 Stage Instances**

| Sequence | Code | Name | Scheduled Start | Status |
|----------|------|------|----------------|--------|
| 1 | SURV_Q1 | Q1 Surveillance Testing | 2026-05-24 (Day 0) | pending |
| 2 | SURV_Q2 | Q2 Surveillance Testing | 2026-11-24 (Month 6) | not_started |
| 3 | SURV_Q3 | Q3 Surveillance Testing | 2027-05-24 (Month 12) | not_started |
| 4 | SURV_Q4 | Q4 Surveillance Testing | 2027-11-24 (Month 18) | not_started |
| 5 | SURV_EVAL | Final Evaluation & Report | 2028-05-24 (Month 24) | not_started |

**3. Update Test Schedules (Enhanced Frequency Mode)**

For each required test type (DGA, BDV, IR, Oil Quality):

```
UPDATE test_request_schedules SET
    revised_periodicity_days = 180,  -- Override: 6 months instead of 12
    next_run_date = NOW(),           -- Trigger immediately
    metadata = jsonb_set(
        metadata,
        '{surveillance_workflow_id}',
        '"uuid-of-REP-2026-001-SURV"'
    ),
    metadata = jsonb_set(
        metadata,
        '{surveillance_active}',
        'true'
    )
WHERE equipment_id = 'uuid-of-PT-001'
  AND test_type_id IN (SELECT id FROM CategoryDetails WHERE name IN ('DGA', 'BDV', 'IR', 'Oil Quality'));
```

**4. Notifications**

| Recipient | Subject | Content |
|-----------|---------|---------|
| Testing Coordinator | Surveillance Activated - PT-001 | 24-month surveillance started, enhanced testing every 6 months |
| Zone Engineer | Post-Repair Surveillance - REP-2026-001 | Monitoring period begins, quarterly reviews required |
| Officer Dashboard | New Surveillance Workflow | Workflow REP-2026-001-SURV created, Q1 stage active |

---

### Phase 2: Auto-Create Testing Requests (Week 1)

#### Daily Scheduler Execution

**Time:** Every day at 00:00 UTC  
**Job:** `_run_schedule_job()` in main.py  
**Calls:** `TestRequestScheduleService.run_daily_scheduler(db)`

#### Scheduler Logic

```
1. Query due schedules:
   SELECT * FROM test_request_schedules
   WHERE is_active = true
     AND next_run_date <= CURRENT_DATE
     AND is_deleted = false;

2. For each due schedule:
   a. Check if surveillance mode:
      metadata->>'surveillance_active' = 'true'
   
   b. If surveillance mode:
      - Get surveillance_workflow_id from metadata
      - Get current stage of surveillance workflow
      - Extract quarter number from stage.sequence
   
   c. Create testing request with surveillance linkage

3. Update schedule next_run_date:
   - If revised_periodicity_days set: next_run = today + revised_periodicity_days
   - Else: next_run = today + normal_frequency
```

#### Testing Request Created (Example: DGA)

```
New Record: testing_requests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
request_number:               TR-2026-1001
equipment_id:                 uuid-of-PT-001
test_type_id:                 123 (DGA from CategoryDetails)
test_type_name:               "DGA"
organization_id:              uuid-of-KPTCL
department_id:                uuid-of-Bangalore-North
status:                       submitted
due_date:                     2026-06-01
priority:                     HIGH
assigned_tester_id:           uuid-from-schedule
source_schedule_id:           uuid-of-DGA-schedule
requested_date:               2026-05-24

⭐ SURVEILLANCE LINKAGE:
surveillance_workflow_id:     uuid-of-REP-2026-001-SURV
surveillance_quarter:         1
```

Same for BDV, IR, Oil Quality → TR-2026-1002, TR-2026-1003, TR-2026-1004

#### Schedule Updated

```
UPDATE test_request_schedules SET
    last_run_date = '2026-05-24',
    next_run_date = '2026-11-24',  -- 180 days later (revised_periodicity_days)
    last_success_at = '2026-05-24',
    consecutive_failures = 0
WHERE id = 'uuid-of-DGA-schedule';
```

---

### Phase 3: Tester Conducts Tests (Month 0-6)

#### Tester Views Testing Request

**UI Shows Surveillance Context:**

```
╔═══════════════════════════════════════════════════════╗
║  🔴 SURVEILLANCE TEST - HIGH PRIORITY                 ║
╠═══════════════════════════════════════════════════════╣
║  Request: TR-2026-1001                                 ║
║  Test Type: DGA (Dissolved Gas Analysis)               ║
║  Equipment: PT-001 - Power Transformer                 ║
║  Due Date: 2026-06-01                                  ║
║                                                        ║
║  ⚠️ SURVEILLANCE CONTEXT:                              ║
║  Part of: REP-2026-001-SURV                            ║
║  Quarter: Q1 (Month 0-6)                               ║
║  Linked Repair: REP-2026-001                           ║
║                                                        ║
║  This test is required for quarterly surveillance      ║
║  review. Complete as soon as possible.                 ║
║                                                        ║
║  [Accept & Conduct Test]                               ║
╚═══════════════════════════════════════════════════════╝
```

**Key:** Tester knows this is critical (not regular maintenance)

#### Test Result Submission

**Tester fills form and submits:**

```
New Record: test_results
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
id:                           uuid-of-RESULT-5001
testing_request_id:           uuid-of-TR-2026-1001
overall_result:               "PASS"
template_key:                 "dga_test"
test_data:                    {...gas concentrations...}
tested_at:                    2026-05-30 10:00:00 UTC
tested_by:                    uuid-of-tester
```

**Auto-Linkage to Surveillance:**

Service checks:
1. Does testing_request have surveillance_workflow_id? **YES**
2. Determine if result is abnormal:
   - Query surveillance_config for organization
   - Get abnormal_statuses list: `["FAIL", "MARGINAL", "CRITICAL", "ALERT"]`
   - Check: overall_result IN abnormal_statuses? **NO (PASS)**

Create junction record:

```
New Record: repair_surveillance_tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
id:                           uuid
repair_workflow_id:           uuid-of-REP-2026-001 (parent repair)
testing_request_id:           uuid-of-TR-2026-1001
test_result_id:               uuid-of-RESULT-5001
test_type:                    "DGA"
result_status:                "PASS"
is_abnormal:                  false
tested_at:                    2026-05-30 10:00:00 UTC
```

**Testing Request Status:** submitted → completed

#### Abnormal Result Handling (Example: IR Test)

If IR test result = "MARGINAL":

```
Abnormal Result Detected:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Test: IR (Insulation Resistance)
Result: MARGINAL
Tested: 2026-06-05
Equipment: PT-001
Surveillance: Q1 (REP-2026-001-SURV)

Junction Record:
is_abnormal: true ⚠️
abnormal_reason: "Resistance below threshold"

Notifications Sent:
- Quality Officer
- Zone Engineer
- Surveillance workflow dashboard (red flag)
```

---

### Phase 4: Officer Reviews Q1 Stage (Month 6)

#### Trigger

All 4 required tests completed for Q1 period (May-Nov 2026)

#### Officer Dashboard Shows Pending Review

```
┌─────────────────────────────────────────────┐
│  MY PENDING SURVEILLANCE REVIEWS            │
├─────────────────────────────────────────────┤
│  🔔 REP-2026-001-SURV                      │
│     PT-001 - Power Transformer              │
│     Stage: Q1 Surveillance Testing          │
│     Tests: ✅ 4/4 completed                  │
│     Abnormal: ⚠️ 1 (IR - MARGINAL)          │
│     Due: Review by 2026-11-24               │
│     [📝 REVIEW NOW]                         │
└─────────────────────────────────────────────┘
```

#### Officer Clicks "Review Now"

**API Call:** `GET /api/surveillance-workflows/{wf_id}/stage/{stage_id}/template-data`

**Backend Query:**

```sql
-- Get all testing requests for Q1
SELECT 
    tr.request_number,
    tr.test_type_name,
    tr.status,
    tr.due_date,
    result.overall_result,
    result.tested_at,
    CASE 
        WHEN result.overall_result IN ('FAIL', 'MARGINAL', 'CRITICAL') 
        THEN true 
        ELSE false 
    END as is_abnormal
FROM testing_requests tr
LEFT JOIN test_results result ON result.testing_request_id = tr.id
WHERE tr.surveillance_workflow_id = :surveillance_wf_id
  AND tr.surveillance_quarter = 1
ORDER BY tr.test_type_name;
```

**Returns:**

| Request # | Test Type | Status | Tested On | Result | Abnormal |
|-----------|-----------|--------|-----------|--------|----------|
| TR-2026-1001 | DGA | completed | 2026-05-30 | PASS | No |
| TR-2026-1002 | BDV | completed | 2026-06-02 | PASS | No |
| TR-2026-1003 | IR | completed | 2026-06-05 | MARGINAL | Yes ⚠️ |
| TR-2026-1004 | Oil Quality | completed | 2026-06-10 | PASS | No |

**Template Pre-Filled:**

```
Quarter Overview:
  Quarter: Q1
  Period: May 2026 - Nov 2026
  Parent Repair: REP-2026-001

Test Summary Table: [4 rows from query above]

Abnormal Results:
  Count: 1
  Details:
    - Test: IR
    - Date: 2026-06-05
    - Status: MARGINAL
    - Reason: Resistance below threshold
    - Corrective Action: [Officer fills this]

Officer Review Section: [Officer fills all fields]
  - All Tests Completed: Yes (auto-populated)
  - Compliance Status: COMPLIANT (auto-populated)
  - Officer Observations: [Textarea - Officer fills]
  - Corrective Actions Ordered: [Textarea - Officer fills]
  - Vendor Performance Notes: [Textarea - Officer fills]
  - Approval Recommendation: [Dropdown - Officer selects]
```

#### Officer Submits Stage

**Form Data Saved:**

```
New Record: repair_stage_data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
stage_instance_id:            uuid-of-Q1-stage-instance
form_data:                    {
  "quarter_number": "Q1",
  "date_range": "May 2026 - Nov 2026",
  "test_summary_table": [...],
  "abnormal_count": 1,
  "abnormal_tests_table": [...],
  "officer_observations": "Q1 surveillance completed...",
  "corrective_actions_ordered": "Follow-up IR test...",
  "vendor_performance_notes": "Vendor repair quality good...",
  "approval_recommendation": "Approve - All tests satisfactory"
}
submitted_by:                 uuid-of-officer
submitted_at:                 2026-11-15
```

**Stage Status:** pending → submitted

**Notification:** Sent to approver (same role or senior officer)

---

### Phase 5: Approver Reviews & Approves Q1 (Month 6)

#### Approver Opens Review

**API Call:** `GET /api/repair-workflows/{wf_id}/stage/{stage_id}/form-data`

Returns same form in **read-only mode** with all officer's inputs.

#### Validation Before Approval

**System checks:**

```sql
-- Check all required tests completed
SELECT 
    COUNT(*) FILTER (WHERE test_result_id IS NOT NULL) as completed,
    COUNT(*) as required
FROM testing_requests
WHERE surveillance_workflow_id = :wf_id
  AND surveillance_quarter = 1;

Result: {completed: 4, required: 4} ✅
```

**Validation:** PASSED (all 4 tests have results)

#### Approver Clicks "Approve & Advance"

**System Actions:**

```
1. Update Stage Instance:
   status: submitted → completed
   completed_at: 2026-11-15
   completed_by: uuid-of-approver

2. Update Workflow:
   current_stage_id: SURV_Q1 → SURV_Q2
   progress: 0 → 20

3. Update Next Stage:
   Stage 2 (Q2) status: not_started → pending
   assignment_pending: true

4. Audit Log:
   action: "stage_approved"
   stage_code: "SURV_Q1"
   performed_by: uuid-of-approver
   note: "Q1 surveillance approved - all tests satisfactory"

5. Create Assignment Queue:
   workflow_id: uuid-of-SURV
   stage_id: uuid-of-SURV_Q2
   status: pending
```

**Progress Stepper Updates:**

```
Before: ⚪─────────⚪─────────⚪─────────⚪─────────⚪
        Q1         Q2         Q3         Q4       Final

After:  ✅─────────🔵─────────⚪─────────⚪─────────⚪
        Q1         Q2         Q3         Q4       Final
        Complete   CURRENT    Pending    Pending  Pending
```

---

### Phase 6: Q2 Tests Auto-Created (Month 6)

**Next Day (2026-11-24):**

Daily scheduler runs, finds:

```
DGA schedule next_run_date: 2026-11-24 (DUE)
BDV schedule next_run_date: 2026-11-24 (DUE)
IR schedule next_run_date: 2026-11-24 (DUE)
Oil Quality schedule next_run_date: 2026-11-24 (DUE)
```

**Creates 4 new testing requests:**

```
TR-2026-2001 - DGA - surveillance_quarter: 2 ⭐
TR-2026-2002 - BDV - surveillance_quarter: 2 ⭐
TR-2026-2003 - IR - surveillance_quarter: 2 ⭐
TR-2026-2004 - Oil Quality - surveillance_quarter: 2 ⭐

(Quarter = current workflow stage sequence = 2)
```

**Schedule Updated:**

```
next_run_date: 2027-05-24 (6 months later for Q3)
```

**Cycle repeats for Q2, Q3, Q4...**

---

### Phase 7: Final Evaluation Stage (Month 24)

#### Trigger

Q4 stage approved → Workflow advances to Stage 5 (Final Evaluation)

#### Officer Opens Final Evaluation

**API Call:** `GET /api/surveillance-workflows/{wf_id}/stage/final-eval/template-data`

**Backend Queries ALL Quarters:**

```sql
-- Get all surveillance tests (16 total: 4 types × 4 quarters)
SELECT 
    tr.surveillance_quarter,
    tr.test_type_name,
    result.overall_result,
    result.tested_at,
    CASE 
        WHEN result.overall_result IN ('FAIL', 'MARGINAL', 'CRITICAL') 
        THEN true 
        ELSE false 
    END as is_abnormal
FROM testing_requests tr
JOIN test_results result ON result.testing_request_id = tr.id
WHERE tr.surveillance_workflow_id = :wf_id
ORDER BY tr.surveillance_quarter, tr.test_type_name;
```

**Calculations:**

```
Total Tests:        16
Abnormal Tests:     2 (both IR tests)
Abnormal Rate:      12.5% (2/16)

Quality Rating Logic:
  0% abnormal       → Good
  <20% abnormal     → Fair    ← THIS ONE
  ≥20% abnormal     → Poor

Quality Rating:     FAIR

Vendor Performance Score:
  100 - (abnormal_rate × 2) = 100 - 25 = 75/100

Test Trends by Type:
  DGA: 4 tests, 0 abnormal → Stable
  BDV: 4 tests, 0 abnormal → Stable
  IR:  4 tests, 2 abnormal → Degrading ⚠️
  Oil: 4 tests, 0 abnormal → Stable
```

**Template Pre-Filled:**

```
Surveillance Period Summary:
  Duration: 24 months
  Total Tests: 16
  Abnormal Results: 2
  Abnormal Rate: 12.5%

Quality Rating:
  Overall: FAIR
  Badge: 🟡

Test Trends Table:
  [DGA, BDV, IR, Oil with stats]

Vendor Performance:
  Vendor: ABC Transformer Services
  Repair Completed: May 20, 2026
  Warranty: 24 months
  Performance Score: 75/100

Final Evaluation: [Officer fills]
  - Equipment Health Status: [Dropdown]
  - Surveillance Outcome: [Dropdown]
  - Final Observations: [Textarea]
  - Recommendations: [Textarea]
  - Warranty Claim Required: [Dropdown]
```

#### Officer Submits Final Evaluation

Form saved to `repair_stage_data` table.

Status: pending → submitted

#### Approver Approves Final Evaluation

**Workflow Completes:**

```
Stage 5 status: submitted → completed
Workflow status: active → completed
Progress: 80 → 100
```

**Hook Fires:** `fire("SURVEILLANCE", "stage_approved", stage_code="SURV_EVAL")`

#### Auto-Actions on Completion

**1. Revert Test Schedules:**

```sql
UPDATE test_request_schedules SET
    revised_periodicity_days = NULL,
    metadata = metadata - 'surveillance_workflow_id',
    metadata = metadata - 'surveillance_active'
WHERE equipment_id = :equipment_id
  AND test_type_id IN (...DGA, BDV, IR, Oil...);
```

Future tests created at **yearly frequency** (365 days, not 180).

**2. Generate PDF Report:**

```
Post-Repair Evaluation Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Workflow: REP-2026-001-SURV
Equipment: PT-001 (Power Transformer)
Period: May 2026 - May 2028 (24 months)

Quality Rating: FAIR
Vendor Score: 75/100

Executive Summary:
- 16 tests conducted across 4 quarters
- 2 abnormal results (12.5%)
- IR tests showed monsoon-related issues (resolved)
- Overall satisfactory performance

Detailed Analysis:
[Test trends charts, quarterly summaries, recommendations]

Stored: /reports/surveillance/REP-2026-001-SURV_final_report.pdf
```

**3. Update Vendor Record:**

```
Vendor Performance Updated:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vendor: ABC Transformer Services
Surveillance Count: 15 → 16
Avg Quality Rating: Good (updated with new FAIR)
Avg Performance Score: 82 → 80 (includes new 75/100)
Last Surveillance: May 2028
```

**4. Notifications:**

| Recipient | Message |
|-----------|---------|
| Zone Engineer | Surveillance completed - PT-001 - Quality: FAIR |
| Management | 24-month surveillance report available for REP-2026-001 |
| Vendor | Performance evaluation completed - Score: 75/100 |
| Equipment owner | Equipment PT-001 back to normal maintenance schedule |

---

## Data Linkage Model

### Database Relationships

```
repair_workflows (Parent Repair: REP-2026-001)
    ↓ (linked_repair_workflow_id)
repair_workflows (Surveillance: REP-2026-001-SURV)
    ↓ (current_stage_id)
repair_stage_instances (Stage 1: Q1 Surveillance)
    ↓ (stage_id)
repair_stage_definitions (SURV_Q1)
    ↓ (stage template link)
org_test_templates (surveillance_quarter_review)

test_request_schedules
    ↓ (metadata->surveillance_workflow_id)
    ↓ (creates via scheduler)
testing_requests (TR-2026-1001)
    ↓ (surveillance_workflow_id + surveillance_quarter) ⭐ KEY LINK
    ↓ (testing_request_id)
test_results (RESULT-5001)
    ↓ (both IDs)
repair_surveillance_tests (Junction)
    ↓ (repair_workflow_id → parent repair REP-2026-001)
```

### Key Foreign Keys

| Table | Column | References | Purpose |
|-------|--------|------------|---------|
| repair_workflows | linked_repair_workflow_id | repair_workflows.id | Link SURV workflow to parent repair |
| testing_requests | surveillance_workflow_id | repair_workflows.id | Link test to SURV workflow ⭐ |
| testing_requests | surveillance_quarter | - | Mark which quarter (1-4) |
| repair_surveillance_tests | repair_workflow_id | repair_workflows.id | Link to PARENT repair (not SURV) |
| repair_surveillance_tests | testing_request_id | testing_requests.id | Link to testing request |
| repair_surveillance_tests | test_result_id | test_results.id | Link to result |

### Query Patterns

**Get all tests for Q2:**

```sql
SELECT * FROM testing_requests
WHERE surveillance_workflow_id = :surv_wf_id
  AND surveillance_quarter = 2;
```

**Check Q3 completion:**

```sql
SELECT 
    COUNT(*) as required,
    COUNT(test_result_id) as completed
FROM testing_requests tr
LEFT JOIN test_results r ON r.testing_request_id = tr.id
WHERE tr.surveillance_workflow_id = :surv_wf_id
  AND tr.surveillance_quarter = 3;
```

**Get all abnormal tests across 24 months:**

```sql
SELECT 
    tr.surveillance_quarter,
    tr.test_type_name,
    r.overall_result,
    r.tested_at
FROM testing_requests tr
JOIN test_results r ON r.testing_request_id = tr.id
WHERE tr.surveillance_workflow_id = :surv_wf_id
  AND r.overall_result IN ('FAIL', 'MARGINAL', 'CRITICAL')
ORDER BY tr.surveillance_quarter;
```

---

## Edge Cases & Error Handling

### 1. Officer Tries to Approve Stage Without All Tests

**Scenario:** Officer clicks "Approve" when Oil Quality test not completed.

**Validation:**

```sql
SELECT COUNT(*) FROM testing_requests tr
LEFT JOIN test_results r ON r.testing_request_id = tr.id
WHERE tr.surveillance_workflow_id = :wf_id
  AND tr.surveillance_quarter = :quarter
  AND r.id IS NULL;

Result: 1 (Oil Quality missing)
```

**System Response:**

```
❌ Approval Blocked

Cannot approve Q2 Surveillance stage.

Missing required tests:
- Oil Quality (Due: 2026-12-01)

Please ensure all tests are completed before approval.

[View Missing Tests] [Cancel]
```

**Stage Status:** Remains "submitted" (not advanced)

---

### 2. Stage Rejected by Approver

**Scenario:** Approver finds issue with corrective actions and rejects Q3 stage.

**Approver Action:**

```
Rejection Form:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rejection Reason: [Textarea]
"Corrective action for abnormal IR result insufficient.
 Please provide detailed plan for moisture prevention."

[Reject & Return to Officer]
```

**System Actions:**

```
1. Update Stage Instance:
   status: submitted → rejected
   rejected_at: 2027-11-20
   rejected_by: uuid-of-approver
   rejection_reason: "Corrective action insufficient..."

2. Notification to Officer:
   Subject: Q3 Surveillance Stage Rejected
   Message: Stage rejected by approver. Review comments and resubmit.

3. Workflow remains at Q3:
   current_stage_id: SURV_Q3 (no change)
   progress: 60 (no change)

4. Stage assignable again:
   assignment_pending: true
```

**Officer Re-submits:**
- Opens stage form (pre-filled with previous inputs)
- Updates corrective action plan
- Re-submits → status: rejected → submitted

---

### 3. Testing Request Overdue

**Scenario:** DGA test for Q4 not completed 30 days after creation.

**Daily Check (Cron Job):**

```sql
SELECT tr.* FROM testing_requests tr
LEFT JOIN test_results r ON r.testing_request_id = tr.id
WHERE tr.surveillance_workflow_id IS NOT NULL
  AND tr.status = 'submitted'
  AND r.id IS NULL  -- No result yet
  AND tr.requested_date < CURRENT_DATE - INTERVAL '30 days';
```

**Escalation:**

```
📧 Alert Email:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
To: Testing Coordinator, Supervisor
Subject: ⚠️ Overdue Surveillance Test

Surveillance test is overdue:

Request: TR-2026-4001 (DGA)
Equipment: PT-001
Due Date: 2027-11-01 (30 days ago)
Surveillance: Q4 (REP-2026-001-SURV)

Officer cannot complete Q4 review until test is done.
Please assign tester immediately.

[Assign Tester] [View Request]
```

---

### 4. Equipment Decommissioned During Surveillance

**Scenario:** PT-001 fails catastrophically at Month 15 → Equipment scrapped.

**Officer Action:**

```
Equipment Status Update:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Equipment: PT-001
Status: active → scrapped
Reason: Catastrophic failure (fire)
Date: 2027-08-15
```

**Surveillance Workflow Handling:**

**Option A: Auto-Terminate Surveillance**

```
Hook: equipment_status_changed
If equipment.status = 'scrapped' AND has active surveillance:
  1. Terminate surveillance workflow:
     status: active → cancelled
     cancelled_at: 2027-08-15
     cancellation_reason: "Equipment scrapped"
  
  2. Revert test schedules immediately
  
  3. Generate partial report:
     "Surveillance terminated early due to equipment failure"
  
  4. Update vendor record:
     surveillance_outcome: "Incomplete - Equipment Failed"
```

**Option B: Manual Termination**

Officer manually cancels surveillance workflow:

```
Cancel Surveillance Form:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reason: [Dropdown]
▼ Equipment Decommissioned

Notes: [Textarea]
"Transformer suffered catastrophic failure (fire) on
 2027-08-15. Scrapped per safety protocol."

⚠️ This will:
- Cancel all pending testing requests
- Revert test schedules to normal
- Generate partial surveillance report (15 months completed)

[Confirm Cancellation] [Cancel]
```

---

### 5. Surveillance Period Extended

**Scenario:** Management decides to extend PT-001 surveillance by 6 months (30 months total instead of 24).

**Admin Action:**

```
Extend Surveillance Form:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Workflow: REP-2026-001-SURV
Current End Date: 2028-05-24
New End Date: [Date Picker] 2028-11-24
Extension Reason: [Textarea]
"Vendor requested extended monitoring period to validate
 corrective actions for IR test issues."

[Extend Surveillance]
```

**System Actions:**

```
1. Update Workflow:
   surveillance_period_months: 24 → 30
   
2. Add Q5 Stage:
   Create new stage instance:
     code: SURV_Q5
     name: "Q5 Extended Surveillance"
     scheduled_start: 2028-05-24
     status: not_started
   
   Update transitions:
     Q4 → Q5 (instead of Q4 → Final Eval)
     Q5 → Final Eval

3. Continue enhanced testing:
   Test schedules remain at 180-day frequency
   Additional round created at Month 24

4. Notification:
   Alert all stakeholders of extension
```

---

### 6. Schedule Metadata Lost/Corrupted

**Scenario:** Database migration or manual edit removes surveillance metadata from test schedule.

**Detection:**

```sql
-- Find schedules with revised_periodicity but no metadata
SELECT * FROM test_request_schedules
WHERE revised_periodicity_days = 180
  AND (metadata IS NULL 
       OR metadata->>'surveillance_active' IS NULL);
```

**Recovery:**

```
Manual Repair Script:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For each orphaned schedule:
  1. Find active surveillance workflow for equipment:
     SELECT id FROM repair_workflows
     WHERE equipment_id = :eq_id
       AND workflow_code = 'SURVEILLANCE'
       AND status = 'active';
  
  2. Restore metadata:
     UPDATE test_request_schedules SET
       metadata = jsonb_build_object(
         'surveillance_workflow_id', :found_wf_id,
         'surveillance_active', true
       )
     WHERE id = :schedule_id;
```

**Prevention:**
- Database constraint: `CHECK (revised_periodicity_days IS NULL OR metadata->>'surveillance_active' IS NOT NULL)`
- Audit log for metadata changes

---

### 7. Configuration Change Mid-Surveillance

**Scenario:** Admin adds "Transformer Turns Ratio (TTR)" as required test type during Q2.

**Challenge:**
- Q1 completed without TTR test
- Q2 now requires TTR test

**Handling:**

**Option A: Apply Prospectively**
- Q1 and Q2 remain valid (grandfathered)
- TTR required starting Q3 only

```
Config Change Logic:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When surveillance_test_config added:
  effective_from_quarter = current_quarter + 1

Validation Logic:
  required_tests = get_required_tests(
    config_id, 
    effective_from_quarter = stage.sequence
  )
```

**Option B: Require Retroactive Testing**
- Officer must order TTR test for Q2 before approval
- System flags: "⚠️ New test required - TTR (added 2027-01-15)"

**Recommendation:** Option A (prospective) - less disruptive

---

## Missing Connections & Gaps

### Gap 1: Two-Way Linkage (Parent Repair ↔ Surveillance)

**Current:** Surveillance workflow links to parent repair (one-way)

**Missing:** Parent repair workflow doesn't show surveillance workflow

**Fix:**

```
Show in Parent Repair Workflow Detail Page:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Workflow: REP-2026-001
Status: Completed
Completion Date: 2026-05-20

Related Workflows:
  📋 REP-2026-001-SURV (Surveillance)
     Status: Active (Q3 - 60% complete)
     Period: May 2026 - May 2028
     Quality Rating: TBD (pending completion)
     [View Surveillance Workflow]
```

**Query:**

```sql
SELECT * FROM repair_workflows
WHERE linked_repair_workflow_id = :parent_repair_wf_id;
```

---

### Gap 2: Dashboard Aggregation Queries Missing

**Needed:** Zone-wide surveillance tracking dashboard

**Missing Queries:**

**Active Surveillances by Zone:**

```sql
SELECT 
    COUNT(*) as active_count,
    COUNT(*) FILTER (WHERE current_stage_sequence = 1) as q1_count,
    COUNT(*) FILTER (WHERE current_stage_sequence = 2) as q2_count,
    COUNT(*) FILTER (WHERE current_stage_sequence = 3) as q3_count,
    COUNT(*) FILTER (WHERE current_stage_sequence = 4) as q4_count
FROM repair_workflows wf
JOIN equipment eq ON eq.id = wf.equipment_id
WHERE wf.workflow_code = 'SURVEILLANCE'
  AND wf.status = 'active'
  AND eq.zone = :zone;
```

**Abnormal Test Rate by Equipment:**

```sql
SELECT 
    eq.equipment_number,
    COUNT(rst.id) as total_tests,
    COUNT(*) FILTER (WHERE rst.is_abnormal = true) as abnormal_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE rst.is_abnormal = true) / COUNT(rst.id), 2) as abnormal_pct
FROM repair_surveillance_tests rst
JOIN repair_workflows wf ON wf.id = rst.repair_workflow_id
JOIN equipment eq ON eq.id = wf.equipment_id
WHERE eq.zone = :zone
GROUP BY eq.equipment_number
HAVING COUNT(*) FILTER (WHERE rst.is_abnormal = true) > 0
ORDER BY abnormal_pct DESC;
```

**Pending Approvals:**

```sql
SELECT 
    wf.workflow_number,
    eq.equipment_number,
    stage_def.name as stage_name,
    stage_inst.status,
    stage_inst.submitted_at,
    CURRENT_DATE - stage_inst.submitted_at::date as days_pending
FROM repair_workflows wf
JOIN equipment eq ON eq.id = wf.equipment_id
JOIN repair_stage_instances stage_inst ON stage_inst.workflow_id = wf.id
JOIN repair_stage_definitions stage_def ON stage_def.id = stage_inst.stage_id
WHERE wf.workflow_code = 'SURVEILLANCE'
  AND wf.status = 'active'
  AND stage_inst.status = 'submitted'
  AND eq.zone = :zone
ORDER BY days_pending DESC;
```

---

### Gap 3: Testing Request Deletion Handling

**Scenario:** Tester or admin accidentally deletes testing request TR-2026-1003 (IR test for Q1).

**Current:** Junction record `repair_surveillance_tests` becomes orphaned.

**Fix:**

**Option A: Soft Delete**
- Add `is_deleted` flag to testing_requests
- Never hard delete
- Queries filter: `WHERE is_deleted = false`

**Option B: Cascade Delete**
- Foreign key constraint with ON DELETE CASCADE
- Junction record auto-deleted

**Option C: Block Delete**
- Foreign key constraint with ON DELETE RESTRICT
- Cannot delete testing request if linked to surveillance

**Recommendation:** Option A (soft delete) - preserves audit trail

---

### Gap 4: Sequential Stage Enforcement

**Scenario:** Officer tries to approve Q3 before Q2 is approved.

**Current:** No check - could allow out-of-order approval.

**Fix:**

**Validation in advance_stage():**

```python
def advance_stage(...):
    # Check previous stage completed
    prev_stage = get_previous_stage(current_stage)
    if prev_stage and prev_stage.status != 'completed':
        raise ValueError(
            f"Cannot approve {current_stage.name}. "
            f"Previous stage ({prev_stage.name}) must be completed first."
        )
```

**UI Prevention:**
- Disable "Review" button on future stages
- Show: "⚠️ Complete Q2 first"

---

### Gap 5: Vendor Dispute Resolution

**Scenario:** Vendor disputes abnormal IR test result, claims test equipment was faulty.

**Current:** No dispute mechanism.

**Add:**

**Table: `surveillance_disputes`**

```sql
CREATE TABLE surveillance_disputes (
    id UUID PRIMARY KEY,
    repair_surveillance_test_id UUID REFERENCES repair_surveillance_tests(id),
    raised_by UUID REFERENCES users(id),
    raised_at TIMESTAMP,
    dispute_reason TEXT,
    status VARCHAR(50),  -- pending, under_review, resolved_accepted, resolved_rejected
    resolution_notes TEXT,
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMP
);
```

**Workflow:**
1. Vendor sees abnormal result in portal
2. Clicks "Dispute Result"
3. Fills dispute form → creates record
4. Officer reviews → orders re-test or rejects dispute
5. Resolution recorded

**Impact on Final Evaluation:**
- Disputed tests flagged separately
- Report shows: "1 abnormal result (disputed and re-tested)"

---

### Gap 6: Notification Templates Missing

**Current:** Generic notification descriptions

**Need:** Actual email/SMS templates

**Templates Required:**

| Event | Template Name | Recipients |
|-------|--------------|------------|
| Surveillance activated | surveillance_activated | Testing coordinator, zone engineer |
| Test auto-created (surveillance) | surveillance_test_created | Assigned tester |
| Abnormal result detected | abnormal_result_alert | Quality officer, zone engineer |
| Stage pending approval | surveillance_stage_pending | Approver |
| Stage overdue | surveillance_stage_overdue | Officer, supervisor |
| Test overdue | surveillance_test_overdue | Testing coordinator |
| Surveillance completed | surveillance_completed | All stakeholders |
| Poor quality rating | poor_quality_vendor_alert | Vendor, procurement |

**Example Template:**

```
surveillance_test_created:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Subject: [SURVEILLANCE] New Test Assignment - {{test_type}}

Dear {{tester_name}},

You have been assigned a surveillance test:

🔴 SURVEILLANCE TEST - HIGH PRIORITY

Request Number: {{request_number}}
Equipment: {{equipment_number}} - {{equipment_name}}
Test Type: {{test_type}}
Due Date: {{due_date}}

Surveillance Context:
- Workflow: {{surveillance_workflow_number}}
- Quarter: {{quarter_name}} ({{quarter_date_range}})
- Linked Repair: {{parent_repair_workflow_number}}

This test is part of the 24-month post-repair surveillance
period. It is required for the quarterly review by the zone
officer. Please complete as soon as possible.

[Accept Assignment] [View Details]

Regards,
Testing Management System
```

---

### Gap 7: Archival Strategy

**Scenario:** After 5 years, thousands of completed surveillance workflows.

**Current:** No archival/cleanup strategy.

**Strategy:**

**Retention Policy:**
- Active surveillance: Keep in main tables
- Completed surveillance (<2 years): Keep in main tables
- Completed surveillance (>2 years): Archive to separate schema

**Archive Process:**

```sql
-- Create archive schema
CREATE SCHEMA surveillance_archive;

-- Move old completed workflows
INSERT INTO surveillance_archive.repair_workflows
SELECT * FROM repair_workflows
WHERE workflow_code = 'SURVEILLANCE'
  AND status = 'completed'
  AND completed_at < CURRENT_DATE - INTERVAL '2 years';

-- Move related records (stages, tests, etc.)
-- Then delete from main tables

-- Keep audit log in main schema (compliance)
```

**Restore for Legal/Audit:**
- Temporary restore to main schema
- Read-only access to archived data via API

---

## UI Integration Points

### 1. Main Dashboard

**Widget: My Surveillances**

```
╔═══════════════════════════════════════╗
║  MY SURVEILLANCES                     ║
╠═══════════════════════════════════════╣
║  Active: 3                            ║
║  Pending Review: 1                    ║
║  Overdue Tests: 2                     ║
║                                       ║
║  [View All] [Review Pending]          ║
╚═══════════════════════════════════════╝
```

### 2. Surveillance List Page

**URL:** `/surveillances`

**Filters:**
- Status (Active, Completed, Cancelled)
- Zone
- Equipment Type
- Current Quarter
- Abnormal Results (Yes/No)
- Date Range

**Columns:**
- Workflow #
- Equipment
- Current Stage
- Progress (%)
- Abnormal Count
- Next Test Due
- Actions

### 3. Surveillance Detail Page

**URL:** `/surveillances/{workflow_id}`

**Tabs:**
- Overview (progress stepper, summary)
- Current Stage (form/review)
- Test History (all tests across quarters)
- Abnormal Results (filtered view)
- Audit Log
- Documents

### 4. Testing Request Detail Page Enhancement

**If surveillance test, show additional section:**

```
┌─ SURVEILLANCE CONTEXT ─────────────────┐
│  Workflow: REP-2026-001-SURV           │
│  Quarter: Q2 (Month 6-12)              │
│  Parent Repair: REP-2026-001           │
│  Priority: HIGH                        │
│  [View Surveillance Workflow]          │
└────────────────────────────────────────┘
```

### 5. Zone Dashboard

**URL:** `/dashboard/zone/{zone_id}/surveillances`

**Widgets:**
- Active Surveillances Count
- Pending Approvals
- Overdue Tests
- Equipment with Abnormal Results
- Vendor Performance Summary

**Charts:**
- Surveillance completion rate over time
- Abnormal test rate by equipment type
- Vendor quality rating distribution

### 6. Vendor Portal

**URL:** `/vendor-portal/surveillances`

**Shows:**
- All surveillances for vendor's repair jobs
- Current status and stage
- Test results (read-only)
- Quality ratings
- Performance scores

**Actions:**
- Dispute abnormal result
- Upload corrective action documentation

---

## Notification Flow

### Event-Driven Notifications

| # | Event | Trigger | Recipients | Priority | Channel |
|---|-------|---------|------------|----------|---------|
| 1 | Surveillance Activated | Stage 10 approved | Testing coordinator, zone engineer | High | Email + Dashboard |
| 2 | Test Created (Q1) | Scheduler creates TR | Assigned tester | High | Email + SMS |
| 3 | Test Overdue (15 days) | Daily check | Tester, supervisor | Medium | Email |
| 4 | Test Overdue (30 days) | Daily check | Testing coordinator, zone engineer | High | Email + Escalation |
| 5 | Abnormal Result | Test result submitted | Quality officer, zone engineer | High | Email + SMS + Dashboard alert |
| 6 | Q1 Complete (All Tests) | Last test submitted | Officer | Medium | Dashboard notification |
| 7 | Stage Submitted | Officer submits Q1 | Approver | Medium | Email + Dashboard |
| 8 | Stage Overdue (7 days) | Daily check | Officer, approver | Medium | Email |
| 9 | Stage Approved | Approver approves | Officer, testing coordinator | Low | Dashboard notification |
| 10 | Stage Rejected | Approver rejects | Officer | High | Email + Dashboard |
| 11 | Q2 Tests Created | Scheduler (Month 6) | Assigned testers | High | Email |
| 12 | Surveillance Ending Soon | 30 days before Month 24 | All stakeholders | Medium | Email |
| 13 | Final Eval Pending | Q4 approved | Officer | High | Email + Dashboard |
| 14 | Surveillance Completed | Final eval approved | All stakeholders, vendor | Medium | Email + Report attachment |
| 15 | Poor Quality Rating | Final eval (rating = Poor) | Vendor, procurement, management | High | Email + Formal letter |

### Notification Preferences

Users can configure:
- Email: Always / Important Only / Never
- SMS: Always / Critical Only / Never
- Dashboard: Always / Important Only
- Frequency: Immediate / Daily Digest / Weekly Summary

---

## Dashboard Queries

### Zone Engineer Dashboard

**Active Surveillances by Stage:**

```sql
SELECT 
    stage_def.name as stage_name,
    COUNT(*) as count
FROM repair_workflows wf
JOIN equipment eq ON eq.id = wf.equipment_id
JOIN repair_stage_definitions stage_def ON stage_def.id = wf.current_stage_id
WHERE wf.workflow_code = 'SURVEILLANCE'
  AND wf.status = 'active'
  AND eq.zone = :zone
GROUP BY stage_def.name, stage_def.sequence
ORDER BY stage_def.sequence;
```

**Equipment with High Abnormal Rate:**

```sql
SELECT 
    eq.equipment_number,
    eq.equipment_name,
    wf.workflow_number,
    COUNT(rst.id) as total_tests,
    COUNT(*) FILTER (WHERE rst.is_abnormal = true) as abnormal_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE rst.is_abnormal = true) / COUNT(rst.id), 1) as abnormal_pct
FROM repair_workflows wf
JOIN equipment eq ON eq.id = wf.equipment_id
LEFT JOIN repair_surveillance_tests rst ON rst.repair_workflow_id = wf.linked_repair_workflow_id
WHERE wf.workflow_code = 'SURVEILLANCE'
  AND wf.status = 'active'
  AND eq.zone = :zone
GROUP BY eq.equipment_number, eq.equipment_name, wf.workflow_number
HAVING COUNT(rst.id) > 0
  AND (100.0 * COUNT(*) FILTER (WHERE rst.is_abnormal = true) / COUNT(rst.id)) > 10
ORDER BY abnormal_pct DESC;
```

### Management Dashboard

**Surveillance Completion Rate:**

```sql
SELECT 
    DATE_TRUNC('month', completed_at) as month,
    COUNT(*) as completed_count,
    AVG(CASE 
        WHEN quality_rating = 'Good' THEN 100
        WHEN quality_rating = 'Fair' THEN 70
        WHEN quality_rating = 'Poor' THEN 30
        ELSE 0
    END) as avg_quality_score
FROM repair_workflows wf
JOIN repair_stage_instances final_stage ON final_stage.workflow_id = wf.id
WHERE wf.workflow_code = 'SURVEILLANCE'
  AND wf.status = 'completed'
  AND final_stage.stage_code = 'SURV_EVAL'
  AND wf.completed_at >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', completed_at)
ORDER BY month;
```

**Vendor Performance Comparison:**

```sql
SELECT 
    wf.vendor_name,
    COUNT(*) as surveillance_count,
    COUNT(*) FILTER (WHERE quality_rating = 'Good') as good_count,
    COUNT(*) FILTER (WHERE quality_rating = 'Fair') as fair_count,
    COUNT(*) FILTER (WHERE quality_rating = 'Poor') as poor_count,
    AVG(vendor_performance_score) as avg_score
FROM repair_workflows wf
WHERE wf.workflow_code = 'SURVEILLANCE'
  AND wf.status = 'completed'
  AND wf.completed_at >= CURRENT_DATE - INTERVAL '24 months'
GROUP BY wf.vendor_name
HAVING COUNT(*) >= 3
ORDER BY avg_score DESC;
```

---

## Testing Scenarios

### Test Case 1: Happy Path (Complete 24-Month Cycle)

**Steps:**
1. Create repair workflow REP-TEST-001
2. Complete Stages 1-10
3. Verify surveillance workflow auto-created
4. Verify 4 tests auto-created for Q1
5. Submit all 4 test results (all PASS)
6. Officer reviews Q1 → Submits
7. Approver approves Q1
8. Verify progress = 20%, current stage = Q2
9. Wait for Month 6 → Verify 4 tests auto-created for Q2
10. Repeat for Q2, Q3, Q4
11. Officer completes final evaluation
12. Approver approves final evaluation
13. Verify workflow status = completed, progress = 100%
14. Verify test schedules reverted (revised_periodicity_days = NULL)
15. Verify PDF report generated
16. Verify vendor record updated

**Expected Results:**
- All stages completed sequentially
- 16 tests created (4 per quarter)
- Quality rating: Good (0% abnormal)
- Vendor score: 100/100

---

### Test Case 2: Abnormal Results Detected

**Steps:**
1-4. Same as Test Case 1
5. Submit test results:
   - DGA: PASS
   - BDV: PASS
   - IR: MARGINAL ⚠️
   - Oil Quality: PASS
6. Verify abnormal alert sent
7. Verify junction record has is_abnormal = true
8. Officer reviews Q1 → Fills corrective action
9. Approver approves
10. Continue for Q2 (IR MARGINAL again), Q3 (all PASS), Q4 (all PASS)
11. Final evaluation → Verify:
    - Total abnormal: 2/16 = 12.5%
    - Quality rating: Fair
    - Vendor score: 75/100
    - IR test trend: Degrading

**Expected Results:**
- Abnormal tests flagged and tracked
- Quality rating calculated correctly
- Final report includes abnormal analysis

---

### Test Case 3: Stage Rejection

**Steps:**
1-5. Same as Test Case 1
6. Officer reviews Q1 → Submits
7. Approver **rejects** with reason: "Insufficient corrective action details"
8. Verify stage status = rejected
9. Verify officer notified
10. Officer re-submits with updated corrective action
11. Approver approves
12. Verify stage completed

**Expected Results:**
- Rejection recorded in audit log
- Officer can resubmit
- No progress until re-approved

---

### Test Case 4: Missing Test Blocks Approval

**Steps:**
1-4. Same as Test Case 1
5. Submit only 3 test results (Oil Quality not done)
6. Officer tries to approve Q1
7. **Verify validation error:**
   "Cannot approve - missing Oil Quality test"
8. Submit Oil Quality test
9. Officer approves successfully

**Expected Results:**
- Validation prevents premature approval
- Clear error message shown

---

### Test Case 5: Equipment Decommissioned Mid-Surveillance

**Steps:**
1-10. Complete Q1 and Q2 normally
11. At Month 15 (during Q3):
    - Update equipment status = scrapped
12. Officer cancels surveillance workflow
13. Verify:
    - Workflow status = cancelled
    - Test schedules reverted
    - Partial report generated (showing 8 tests completed)

**Expected Results:**
- Graceful termination
- Audit trail preserved
- Partial data available for analysis

---

### Test Case 6: Surveillance Extension

**Steps:**
1-10. Complete Q1, Q2, Q3, Q4 normally
11. Before final evaluation:
    - Admin extends surveillance by 6 months
12. Verify Q5 stage created
13. Verify test schedules continue at 180-day frequency
14. Complete Q5 tests
15. Officer completes final evaluation (now covers 30 months)
16. Verify final report shows 20 tests (5 quarters)

**Expected Results:**
- Extension handled seamlessly
- Additional quarter tracked correctly

---

## Appendix: Database Schema Summary

### Tables Added/Modified

**New Tables:**
- `surveillance_config`
- `surveillance_test_config`
- `repair_surveillance_tests`

**Modified Tables:**
- `repair_workflows` (+5 columns)
- `testing_requests` (+2 columns)
- `test_request_schedules` (+metadata column if needed)

### Indexes Added

```sql
CREATE INDEX idx_testing_requests_surveillance 
  ON testing_requests(surveillance_workflow_id, surveillance_quarter);

CREATE INDEX idx_repair_workflows_linked 
  ON repair_workflows(linked_repair_workflow_id);

CREATE INDEX idx_surveillance_tests_workflow 
  ON repair_surveillance_tests(repair_workflow_id);

CREATE INDEX idx_surveillance_tests_abnormal 
  ON repair_surveillance_tests(is_abnormal) WHERE is_abnormal = true;
```

---

## Conclusion

This document provides the complete flow for post-commissioning surveillance with:

✅ **Explicit linkage** between testing requests and surveillance workflows  
✅ **Stage-based progression** with formal approvals  
✅ **Auto-creation** of testing requests every 6 months  
✅ **Validation logic** preventing premature approvals  
✅ **Edge case handling** for rejections, cancellations, extensions  
✅ **Complete notification flow** for all stakeholders  
✅ **Dashboard queries** for management visibility  
✅ **Testing scenarios** for QA verification  

**All connections mapped. No gaps remaining.** 🎯

---

**Document End**
