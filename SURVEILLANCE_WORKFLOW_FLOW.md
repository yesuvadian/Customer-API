# Surveillance Workflow - High-Level Flow

## Overview

Post-commissioning surveillance workflow system that automatically monitors transformer health for 24 months after repair/overhaul completion through quarterly testing cycles and comprehensive evaluation.

---

## 1. TRIGGER: Repair Workflow Completes

```
┌─────────────────────────────────────────────────────────────┐
│  REPAIR WORKFLOW (Transformer Breakdown/Overhaul)           │
│                                                              │
│  Stage 1: Failure Reporting                                 │
│  Stage 2: Committee Review                                  │
│  Stage 3: Vendor Assignment                                 │
│  Stage 4: Lifting                                           │
│  Stage 5: Joint Inspection                                  │
│  Stage 6: Estimate & Work Award                             │
│  Stage 7: Repair QA                                         │
│  Stage 8: Final Inspection                                  │
│  Stage 9: Dispatch                                          │
│  Stage 10: Commissioning  ✅ APPROVED                       │
└─────────────────────────────────────────────────────────────┘
                        ↓
            🎯 SURVEILLANCE HOOK FIRES
                        ↓
```

**File:** `surveillance_hooks.py`  
**Function:** `_on_repair_workflow_completed()`  
**Trigger:** When repair workflow completes its final stage (Stage 10)

---

## 2. AUTO-CREATE: Surveillance Workflow + Schedules

### Step 1: Create Surveillance Workflow

```
┌─────────────────────────────────────────────────────────────┐
│  CREATE SURVEILLANCE WORKFLOW                                │
│                                                              │
│  • workflow_type = 'surveillance'                           │
│  • parent_workflow_id = repair_workflow.id                  │
│  • equipment_id = same transformer                          │
│  • duration = 24 months (configurable)                      │
│  • status = 'active'                                        │
│  • organization_id = from equipment                         │
└─────────────────────────────────────────────────────────────┘
```

**Database Table:** `repair_workflows`  
**Key Fields:**
- `workflow_code`: 'SURVEILLANCE'
- `workflow_type`: 'surveillance'
- `parent_workflow_id`: Links back to repair workflow
- `equipment_id`: Transformer being monitored

### Step 2: Create 5 Stages

```
┌─────────────────────────────────────────────────────────────┐
│  CREATE 5 STAGES                                            │
│                                                              │
│  1. Q1 Surveillance Testing (30 days) ← current_stage       │
│  2. Q2 Surveillance Testing (30 days)                       │
│  3. Q3 Surveillance Testing (30 days)                       │
│  4. Q4 Surveillance Testing (30 days)                       │
│  5. Final Evaluation & Report (45 days)                     │
└─────────────────────────────────────────────────────────────┘
```

**Database Table:** `repair_stage_instances`  
**Key Fields:**
- `workflow_id`: Surveillance workflow ID
- `stage_id`: Reference to stage definition
- `quarter_number`: 1, 2, 3, 4, or NULL (final evaluation)
- `status`: 'in_progress', 'completed', 'not_started'

### Step 3: Create Test Schedules (All Quarters Upfront)

```
┌─────────────────────────────────────────────────────────────┐
│  CREATE TEST SCHEDULES (All Quarters Upfront)               │
│                                                              │
│  Q1 Tests (next_run_date = today):                          │
│    • DGA (Dissolved Gas Analysis)                           │
│    • BDV (Breakdown Voltage)                                │
│    • IR (Insulation Resistance)                             │
│    • Oil Quality                                            │
│                                                              │
│  Q2 Tests (next_run_date = today + 6 months)                │
│    • DGA, BDV, IR, Oil Quality                              │
│                                                              │
│  Q3 Tests (next_run_date = today + 12 months)               │
│    • DGA, BDV, IR, Oil Quality                              │
│                                                              │
│  Q4 Tests (next_run_date = today + 18 months)               │
│    • DGA, BDV, IR, Oil Quality                              │
└─────────────────────────────────────────────────────────────┘
```

**Database Table:** `test_request_schedules`  
**Key Fields:**
- `surveillance_workflow_id`: Links to surveillance workflow
- `surveillance_quarter`: 1, 2, 3, or 4
- `next_run_date`: When to create actual testing request
- `frequency`: 'semi_annual' (6 months)
- `is_active`: True

**Why Create All Upfront?**
- Full 24-month test plan visible from day 1
- Officers can plan resources and budget
- Compliance tracking: "Are we on schedule?"
- Dashboard shows upcoming tests across all quarters

---

## 3. QUARTERLY CYCLE (Repeats 4 Times)

### Phase 1: Test Execution (Each Quarter)

```
┌─────────────────────────────────────────────────────────────┐
│  DAILY SCHEDULER (runs every day)                           │
│                                                              │
│  Service: TestRequestScheduleService.run_daily_scheduler()  │
│                                                              │
│  IF today >= schedule.next_run_date:                        │
│    → Create TestingRequest                                  │
│    → Set surveillance_workflow_id + surveillance_quarter    │
│    → Assign to Test Engineer (from schedule config)         │
│    → Status = 'submitted'                                   │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  TEST EXECUTION (Test Engineer)                             │
│                                                              │
│  Status Flow: submitted → in_progress → completed           │
│                                                              │
│  For each test:                                             │
│    1. Perform test on transformer                           │
│    2. Enter results in form                                 │
│    3. Set result_status:                                    │
│       • NORMAL: Test passed                                 │
│       • MARGINAL: Borderline, monitor                       │
│       • FAIL: Test failed                                   │
│       • CRITICAL: Immediate action needed                   │
│       • ALERT: Abnormal reading                             │
│    4. Upload supporting documents (if any)                  │
│    5. Submit test                                           │
│                                                              │
│  Tests stored in: testing_requests table                    │
│    • form_data: JSON with test results                      │
│    • surveillance_workflow_id: Link to workflow             │
│    • surveillance_quarter: 1, 2, 3, or 4                    │
└─────────────────────────────────────────────────────────────┘
```

**API Endpoint:**  
`GET /surveillance-workflows/{id}/quarter/{quarter}/tests`

**Returns:**
```json
{
  "workflow_id": "uuid",
  "quarter_number": 1,
  "tests": [
    {
      "id": "uuid",
      "test_type_name": "DGA",
      "status": "completed",
      "result_status": "NORMAL",
      "completed_at": "2026-05-27T10:30:00Z"
    }
  ],
  "summary": {
    "total_tests": 4,
    "completed_tests": 4,
    "abnormal_tests": 1,
    "abnormal_rate": 25.0,
    "all_complete": true
  }
}
```

### Phase 2: Quarterly Review (After All Tests Complete)

```
┌─────────────────────────────────────────────────────────────┐
│  QUARTERLY REVIEW STAGE (Reviewing Officer)                 │
│                                                              │
│  API: GET /surveillance-workflows/{id}/quarter/1/review-data│
│                                                              │
│  Auto-populated form shows:                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Quarter 1 Review Summary                             │   │
│  │                                                      │   │
│  │ Test Summary Table:                                  │   │
│  │  Test Type    | Status    | Result   | Date         │   │
│  │  ─────────────────────────────────────────────────   │   │
│  │  DGA          | Completed | NORMAL   | 2026-05-15   │   │
│  │  BDV          | Completed | MARGINAL | 2026-05-16   │   │
│  │  IR           | Completed | NORMAL   | 2026-05-17   │   │
│  │  Oil Quality  | Completed | NORMAL   | 2026-05-18   │   │
│  │                                                      │   │
│  │ Statistics:                                          │   │
│  │  • Total Tests: 4                                    │   │
│  │  • Completed: 4 (100%)                               │   │
│  │  • Abnormal: 1 (25%)                                 │   │
│  │                                                      │   │
│  │ Equipment Details:                                   │   │
│  │  • UEIC: BL-MYSU-066-01-PT-01                        │   │
│  │  • Type: Power Transformer                           │   │
│  │  • Rating: 25 MVA                                    │   │
│  │                                                      │   │
│  │ Officer Observations: [text field]                   │   │
│  │ Recommendations: [text field]                        │   │
│  │                                                      │   │
│  │              [Submit Review] [Save Draft]            │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Officer submits quarterly review ✅                        │
│  → Stage status changes to 'completed'                      │
│  → Next stage (Q2) status changes to 'in_progress'          │
└─────────────────────────────────────────────────────────────┘
```

**Service:** `SurveillanceTemplateService.get_quarter_review_data()`

**Approval Flow:**
1. Reviewing Officer submits review
2. Stage transitions from Q1 → Q2
3. Q2 stage starts automatically
4. Q2 test schedules already exist (created upfront)
5. Daily scheduler will create Q2 tests when date arrives

---

## 4. PROGRESSION: Quarter to Quarter

```
Timeline (24 months):

Month 0-6:   Q1 Surveillance Testing
              ├─ Tests created by daily scheduler (month 0)
              ├─ Test Engineer completes 4 tests
              ├─ Reviewing Officer submits Q1 review
              └─ Approve → Q2 starts (month 6)

Month 6-12:  Q2 Surveillance Testing
              ├─ Tests created by daily scheduler (month 6)
              ├─ Test Engineer completes 4 tests
              ├─ Reviewing Officer submits Q2 review
              └─ Approve → Q3 starts (month 12)

Month 12-18: Q3 Surveillance Testing
              ├─ Tests created by daily scheduler (month 12)
              ├─ Test Engineer completes 4 tests
              ├─ Reviewing Officer submits Q3 review
              └─ Approve → Q4 starts (month 18)

Month 18-24: Q4 Surveillance Testing
              ├─ Tests created by daily scheduler (month 18)
              ├─ Test Engineer completes 4 tests
              ├─ Reviewing Officer submits Q4 review
              └─ Approve → Final Evaluation starts (month 24)
```

**Stage Transitions:**
- Q1 → Q2 → Q3 → Q4 → Final Evaluation → Complete
- Each transition requires approval (action = 'approve')
- Stored in: `repair_stage_transitions` table

---

## 5. FINAL EVALUATION (Month 24)

```
┌─────────────────────────────────────────────────────────────┐
│  FINAL EVALUATION STAGE (Senior Management)                 │
│                                                              │
│  API: GET /surveillance-workflows/{id}/final-evaluation-data│
│                                                              │
│  Auto-populated comprehensive form:                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 24-Month Surveillance Summary                        │   │
│  │                                                      │   │
│  │ Overall Statistics:                                  │   │
│  │  • Total Tests: 16 (4 tests × 4 quarters)            │   │
│  │  • Completed: 16 (100%)                              │   │
│  │  • Abnormal: 4 (25%)                                 │   │
│  │  • Quality Rating: GOOD                              │   │
│  │                                                      │   │
│  │ Quarterly Breakdown:                                 │   │
│  │  Quarter | Tests | Abnormal | Rate | Status         │   │
│  │  ─────────────────────────────────────────────────   │   │
│  │  Q1      | 4     | 1        | 25%  | ✅ Complete    │   │
│  │  Q2      | 4     | 0        | 0%   | ✅ Complete    │   │
│  │  Q3      | 4     | 2        | 50%  | ✅ Complete    │   │
│  │  Q4      | 4     | 1        | 25%  | ✅ Complete    │   │
│  │                                                      │   │
│  │ Test Trends (24-month analysis):                     │   │
│  │  • DGA: Stable ➡️                                   │   │
│  │  • BDV: Improving ⬆️                                │   │
│  │  • IR: Deteriorating ⬇️ [Action needed]            │   │
│  │  • Oil Quality: Stable ➡️                          │   │
│  │                                                      │   │
│  │ Vendor Performance:                                  │   │
│  │  • Repair Quality: Satisfactory                      │   │
│  │  • Post-repair stability: Good                       │   │
│  │                                                      │   │
│  │ Final Recommendations: [text field]                  │   │
│  │  - Continue normal maintenance schedule              │   │
│  │  - Monitor IR trend closely                          │   │
│  │  - Schedule oil change in next cycle                 │   │
│  │                                                      │   │
│  │         [Submit Final Evaluation] [Save Draft]       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Senior Management submits final evaluation ✅              │
│  → Surveillance workflow status = 'completed'               │
│  → 24-month monitoring cycle ends                           │
└─────────────────────────────────────────────────────────────┘
```

**Service:** `SurveillanceTemplateService.get_final_evaluation_data()`

**Quality Rating Logic:**
- **Excellent:** Abnormal rate < 10%
- **Good:** Abnormal rate 10-20%
- **Fair:** Abnormal rate 20-30%
- **Poor:** Abnormal rate > 30%

**Trend Analysis:**
- **Improving:** Last 2 quarters better than first 2
- **Stable:** No significant change
- **Deteriorating:** Last 2 quarters worse than first 2

---

## 6. DASHBOARDS & MONITORING

### Surveillance Dashboard (`/surveillance-dashboard`)

```
┌─────────────────────────────────────────────────────────────┐
│  ORGANIZATION-WIDE SURVEILLANCE METRICS                     │
│                                                              │
│  Workflow Summary:                                          │
│  • Active workflows: 45                                     │
│  • Completed: 12                                            │
│  • On hold: 2                                               │
│                                                              │
│  Quality Ratings Distribution:                              │
│  ┌────────────────────────────────────────┐                 │
│  │ Excellent ████████ 27% (12)            │                 │
│  │ Good      █████████████████ 56% (25)   │                 │
│  │ Fair      ████ 13% (6)                 │                 │
│  │ Poor      ██ 4% (2)                    │                 │
│  └────────────────────────────────────────┘                 │
│                                                              │
│  Test Statistics:                                           │
│  • Total tests: 720 (45 workflows × 16 tests)               │
│  • Completed: 580 (81%)                                     │
│  • Abnormal: 107 (18.5%)                                    │
│  • Abnormal trend: ↓ Decreasing                             │
│                                                              │
│  Quarterly Completion Status:                               │
│  • Q1: 40/45 completed (89%)                                │
│  • Q2: 30/45 completed (67%)                                │
│  • Q3: 15/45 in progress (33%)                              │
│  • Q4: 0/45 not started (0%)                                │
│                                                              │
│  Recent Activities:                                         │
│  • Transformer BL-001: Q2 review submitted (2 hours ago)    │
│  • Transformer BL-015: DGA test completed (4 hours ago)     │
│  • Transformer BL-032: Final evaluation approved (1 day)    │
│                                                              │
│  Alerts & Attention Needed:                                 │
│  🔴 3 overdue quarterly reviews                             │
│  🟡 5 workflows with failed tests                           │
│  🟠 8 workflows approaching Q3 deadline                     │
└─────────────────────────────────────────────────────────────┘
```

**API Endpoint:** `GET /surveillance-dashboard/`

**Metrics Calculated:**
- Active/completed workflow counts
- Quality rating distribution
- Overall abnormal test rate
- Quarterly completion percentages
- Recent activity timeline
- Overdue/failing workflow alerts

### Test Schedule Compliance (`/test-schedule-compliance`)

```
┌─────────────────────────────────────────────────────────────┐
│  EQUIPMENT-LEVEL TEST TRACKING (Card View)                  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 🔧 BL-MYSU-066-01-PT-01                              │   │
│  │ Details: 25 MVA Power Transformer                    │   │
│  │ Status: Active | Health: Good                        │   │
│  │                                                      │   │
│  │ Q1: [✅ DGA] [✅ BDV] [✅ IR] [✅ Oil]                │   │
│  │ Q2: [🟡 DGA] [✅ BDV] [⏳ IR] [⏳ Oil]                │   │
│  │ Q3: [⏳ DGA] [⏳ BDV] [⏳ IR] [⏳ Oil]                │   │
│  │ Q4: [⏳ DGA] [⏳ BDV] [⏳ IR] [⏳ Oil]                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 🔧 BL-MYSU-067-02-PT-02                              │   │
│  │ Details: 16 MVA Distribution Transformer             │   │
│  │ Status: Active | Health: Fair                        │   │
│  │                                                      │   │
│  │ Q1: [✅ DGA] [✅ BDV] [🔴 IR] [✅ Oil]                │   │
│  │ Q2: [🟠 DGA] [⏳ BDV] [⏳ IR] [⏳ Oil]                │   │
│  │ Q3: [⏳ DGA] [⏳ BDV] [⏳ IR] [⏳ Oil]                │   │
│  │ Q4: [⏳ DGA] [⏳ BDV] [⏳ IR] [⏳ Oil]                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Legend:                                                    │
│  ✅ OK (completed, normal)                                  │
│  🟡 Due Soon (within 7 days)                                │
│  🟠 Imminent (within 3 days)                                │
│  🔴 Overdue                                                 │
│  ⏳ Pending (future test)                                   │
└─────────────────────────────────────────────────────────────┘
```

**UI Component:** `test_schedule_compliance_tab.dart`

**Display Logic:**
- Each equipment shown as a card
- Horizontal scrollable test badges per quarter
- Color-coded status indicators
- Filters by department/substation

---

## 7. KEY ACTORS & ROLES

```
┌──────────────────────────────────────────────────────────────┐
│  ROLE                          │  PERMISSIONS                 │
├──────────────────────────────────────────────────────────────┤
│  Test Engineer                 │  • Execute surveillance tests│
│                                │  • Upload test results       │
│                                │  • View testing requests     │
│                                │  • Cannot approve stages     │
├──────────────────────────────────────────────────────────────┤
│  Reviewing Officer             │  • View surveillance workflows│
│  (Q1-Q4 stages)                │  • Submit quarterly reviews  │
│                                │  • Approve quarterly stages  │
│                                │  • Edit stage data           │
├──────────────────────────────────────────────────────────────┤
│  Maintenance Officer           │  • View surveillance workflows│
│  (Q1-Q4 stages)                │  • Submit quarterly reviews  │
│                                │  • Approve quarterly stages  │
│                                │  • Edit stage data           │
├──────────────────────────────────────────────────────────────┤
│  Supervisory Officer           │  • View surveillance workflows│
│  (Q1-Q4 + Final stages)        │  • Submit reviews/evaluation │
│                                │  • Approve all stages        │
│                                │  • Can be assigned to final  │
├──────────────────────────────────────────────────────────────┤
│  Senior Management Approver    │  • View surveillance workflows│
│  (Final Evaluation stage)      │  • Submit final evaluation   │
│                                │  • Approve final stage       │
│                                │  • Close surveillance cycle  │
├──────────────────────────────────────────────────────────────┤
│  Transformer Repair Coordinator│  • Assign officers to stages │
│                                │  • Monitor all workflows     │
│                                │  • View all surveillance data│
│                                │  • Cannot edit/approve       │
└──────────────────────────────────────────────────────────────┘
```

**Role Configuration:**  
File: `seed_surveillance_workflow.py` → `STAGE_ROLES`

**Permission Types:**
- `can_view`: Can see the stage data
- `can_edit`: Can modify stage form data
- `can_approve`: Can approve stage and move to next
- `can_assign`: Can assign users to the stage
- `can_be_assigned`: Can be assigned as responsible for stage

---

## 8. DATA FLOW SUMMARY

```
┌──────────────────────────────────────────────────────────────┐
│                   DATA MODEL RELATIONSHIPS                    │
└──────────────────────────────────────────────────────────────┘

RepairWorkflow (parent - completed repair)
    │
    │ parent_workflow_id
    ↓
RepairWorkflow (surveillance - auto-created)
    │
    │ workflow_id
    ↓
RepairStageInstance (5 instances)
    │
    │ quarter_number (1,2,3,4,NULL)
    ↓
RepairStageDefinition (5 definitions)
    │
    │ stage definitions: Q1_SURVEILLANCE, Q2_SURVEILLANCE...
    │
TestRequestSchedule (16 schedules: 4 tests × 4 quarters)
    │
    │ surveillance_workflow_id + surveillance_quarter
    │ next_run_date (when to fire)
    ↓
TestingRequest (created by daily scheduler)
    │
    │ surveillance_workflow_id + surveillance_quarter
    │ form_data (JSON with results)
    │ result_status (NORMAL/MARGINAL/FAIL/CRITICAL/ALERT)
    ↓
Quarterly Review (auto-calculated)
    │
    │ Aggregates test results for the quarter
    │ Stored in RepairStageInstance.form_data
    ↓
Final Evaluation (24-month summary)
    │
    │ Aggregates all 4 quarterly reviews
    │ Calculates trends and quality rating
    │ Stored in RepairStageInstance.form_data
    ↓
Surveillance Complete ✅
    │
    │ RepairWorkflow.status = 'completed'
    │ RepairWorkflow.completed_at = timestamp
```

---

## 9. API ENDPOINTS

### Workflow Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/surveillance-workflows` | GET | List all surveillance workflows (filtered by org/dept) |
| `/surveillance-workflows/{id}` | GET | Get workflow detail with full timeline |
| `/surveillance-workflows/{id}/timeline` | GET | Get workflow audit trail |
| `/surveillance-workflows/{id}/progress` | GET | Get current stage and progress % |
| `/surveillance-workflows/{id}/summary` | GET | Get comprehensive surveillance summary |

### Test Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/surveillance-workflows/{id}/tests` | GET | Get all tests for workflow (filterable by quarter/status) |
| `/surveillance-workflows/{id}/quarter/{quarter}/tests` | GET | Get tests for specific quarter with completion status |

### Stage Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/surveillance-workflows/{id}/current-form` | GET | Get current stage form template + saved data |
| `/surveillance-workflows/{id}/quarter/{quarter}/review-data` | GET | Get pre-populated quarterly review form data |
| `/surveillance-workflows/{id}/final-evaluation-data` | GET | Get pre-populated final evaluation form data |

### Dashboard & Analytics

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/surveillance-dashboard/` | GET | Get organization-wide surveillance metrics |
| `/surveillance-dashboard/trends` | GET | Get trend analysis over time |
| `/surveillance-dashboard/equipment/{id}` | GET | Get equipment surveillance history |

---

## 10. CONFIGURATION

### Surveillance Config (Organization/Department Level)

```python
# Default config (system-wide)
surveillance_period_months = 24        # Total surveillance duration
frequency_multiplier = 2.0             # Test frequency (2x normal)
abnormal_statuses = ['FAIL', 'MARGINAL', 'CRITICAL', 'ALERT']
quality_threshold_fair = 20.0          # Abnormal rate % for "Fair" rating

# Can be overridden per organization or department
```

**File:** `seed_surveillance_workflow.py` → `seed_surveillance_config()`

**Table:** `surveillance_config`

### Test Type Configuration

```python
# Per equipment type
SurveillanceTestConfig:
    equipment_type_id = Power Transformer
    test_type_id = DGA
    is_mandatory = True
    default_priority = 'high'
    is_active = True
```

**Table:** `surveillance_test_config`

**Defines:** Which tests to run for each equipment type during surveillance

---

## 11. VALIDATION & ERROR HANDLING

### Seed Validation

```
After seeding, automatically verifies:
  ✅ Workflow definition exists (SURVEILLANCE)
  ✅ 5 stages created with correct names/codes
  ✅ Transitions configured (Q1→Q2→Q3→Q4→Final)
  ✅ Templates loaded (quarterly review + final evaluation)
  ✅ Role assignments created
```

### Runtime Error Handling

```python
# Summary endpoint - returns defaults if no tests yet
try:
    summary = SurveillanceTemplateService.get_overall_summary(db, workflow_id)
except Exception:
    summary = {
        'total_tests': 0,
        'quality_rating': 'N/A',
        'note': 'No tests scheduled yet'
    }

# Test schedule creation - logs warnings but continues
try:
    create_schedule(...)
except Exception as e:
    logger.warning(f"Failed creating schedule: {e}")
    # Continue with other schedules
```

### Access Control

```python
# Every endpoint checks:
1. Organization match (user.organization_id == workflow.organization_id)
2. Department scope (if user is not org admin):
   - workflow_dept_id = workflow.equipment.department_id
   - if workflow_dept_id != user_dept_id: raise 403

# Stage-level permissions checked via RepairStageRole table
```

---

## 12. TROUBLESHOOTING

### Issue: Surveillance workflow not created after repair completion

**Check:**
1. Repair workflow `workflow_type` is 'REPAIR', 'BREAKDOWN', or 'OVERHAUL'
2. `SURVEILLANCE` workflow definition exists in database
3. Surveillance stages seeded (5 stages)
4. Hook registered in `workflow_hooks.py`
5. Check server logs for `[SurveillanceHook]` errors

**Fix:**
```bash
# Re-run seed
python seed.py

# Or just surveillance parts
python -c "from seed_surveillance_workflow import seed_surveillance_stages; ..."
```

### Issue: Test schedules not created

**Check:**
1. `surveillance_test_config` table has records for equipment type
2. Equipment has valid `equipment_type_id`
3. Test type categories exist
4. Check logs for schedule creation errors

**Fix:**
```sql
-- Check test configs
SELECT * FROM surveillance_test_config 
WHERE equipment_type_id = 'your-equipment-type-id';

-- If missing, run seed_surveillance_config()
```

### Issue: Tests not appearing in quarter

**Check:**
1. `next_run_date` on schedules matches expected quarter start
2. Daily scheduler is running
3. Schedule `is_active = True`
4. Check `testing_requests` table for created records

**Query:**
```sql
-- Check schedules
SELECT * FROM test_request_schedules
WHERE surveillance_workflow_id = 'your-workflow-id'
ORDER BY surveillance_quarter, next_run_date;

-- Check created tests
SELECT * FROM testing_requests
WHERE surveillance_workflow_id = 'your-workflow-id'
ORDER BY surveillance_quarter;
```

### Issue: Current stage shows "—"

**Check:**
1. `current_stage_instance_id` is set on workflow
2. Stage instance has valid `stage_id`
3. Stage definition has `name` field populated
4. Relationship loaded with `joinedload()`

**Fix:**
```python
# Verify in database
SELECT w.id, w.current_stage_instance_id, s.name
FROM repair_workflows w
LEFT JOIN repair_stage_instances si ON si.id = w.current_stage_instance_id
LEFT JOIN repair_stage_definitions s ON s.id = si.stage_id
WHERE w.workflow_type = 'surveillance';
```

---

## 13. DEPLOYMENT CHECKLIST

### Database

- [ ] Run migration 008 (surveillance schema)
- [ ] Run migration 013 (schedule linkage)
- [ ] Add `parent_workflow_id` column to `repair_workflows`
- [ ] Verify all tables created

### Seed Data

- [ ] Run `python seed.py` (full seed)
  - OR run `seed_surveillance_stages()`
  - AND run `seed_surveillance_config()`
  - AND run `seed_surveillance_role_mappings()`
- [ ] Verify 5 surveillance stages exist
- [ ] Verify surveillance config created
- [ ] Verify role assignments created

### Code Deployment

- [ ] Pull latest code from `features/surveillance` branch
- [ ] Restart FastAPI server
- [ ] Verify hooks registered (`surveillance_hooks.py`)
- [ ] Test API endpoints respond

### Testing

- [ ] Complete a repair workflow to Stage 10
- [ ] Verify surveillance workflow auto-created
- [ ] Verify 5 stages created
- [ ] Verify test schedules created
- [ ] Open surveillance workflow in UI
- [ ] Verify current stage displays correctly
- [ ] Verify summary loads (even with no tests)

---

## Files Reference

### Backend

| File | Purpose |
|------|---------|
| `surveillance_hooks.py` | Auto-create surveillance on repair completion |
| `seed_surveillance_workflow.py` | Seed stages, templates, roles |
| `routers/surveillance_workflow.py` | Workflow execution endpoints |
| `routers/surveillance_dashboard.py` | Analytics and metrics endpoints |
| `services/surveillance_template_service.py` | Summary calculations, data aggregation |
| `services/surveillance_config_service.py` | Config management |
| `SURVEILLANCE_STAGE_TEMPLATES.json` | Form templates (quarterly + final) |
| `SURVEILLANCE_STAGE_TEMPLATE_MAP.json` | Stage → template mapping |

### Frontend

| File | Purpose |
|------|---------|
| `surveillance_workflow_provider.dart` | State management + API calls |
| `surveillance_workflow_list_screen.dart` | List all surveillance workflows |
| `surveillance_workflow_detail_sheet.dart` | Workflow detail modal |
| `surveillance_workflow_page.dart` | Main surveillance page |
| `surveillance_dashboard_page.dart` | Analytics dashboard |
| `test_schedule_compliance_tab.dart` | Equipment test tracking cards |

---

## Summary

**Surveillance Workflow = Automated 24-month post-commissioning monitoring**

- **Trigger:** Repair completion (Stage 10)
- **Duration:** 24 months
- **Stages:** 5 (Q1-Q4 quarterly + final evaluation)
- **Tests:** 4 per quarter (DGA, BDV, IR, Oil Quality)
- **Schedules:** Created upfront, fired by daily scheduler
- **Reviews:** Auto-populated forms with test aggregations
- **Quality Rating:** Excellent/Good/Fair/Poor based on abnormal rate
- **Actors:** Test Engineers, Reviewing Officers, Senior Management
- **Output:** Comprehensive 24-month evaluation report

**Flow:** Repair Complete → Auto-create → Q1 Tests → Q1 Review → Q2 Tests → Q2 Review → Q3 Tests → Q3 Review → Q4 Tests → Q4 Review → Final Evaluation → Complete ✅
