# Surveillance Test Scheduler Integration

## Overview

Surveillance test creation is now **fully integrated** with the existing `test_request_schedules` infrastructure instead of using a separate daily cron job.

## Architecture Change

### Before (Separate Scheduler)
```
Surveillance Workflow Created
  ↓
surveillance_test_scheduler.run_daily_scheduler() (separate cron, 1:00 AM)
  ↓
Creates testing_requests directly
  ↓
Sets surveillance_workflow_id and surveillance_quarter
```

### After (Integrated with Existing Infrastructure)
```
Surveillance Workflow Created
  ↓
surveillance_hooks._create_surveillance_test_schedules()
  ↓
Creates TestRequestSchedule records (with surveillance_workflow_id + surveillance_quarter)
  ↓
TestRequestScheduleService.run_daily_scheduler() (existing cron, already runs daily)
  ↓
Creates testing_requests from schedules
  ↓
Copies surveillance_workflow_id and surveillance_quarter from schedule
```

## Implementation

### 1. Migration 013 - Add Surveillance Linkage to Schedules

**File:** `migrations/013_add_surveillance_to_schedules.sql`

Adds two columns to `test_request_schedules`:
- `surveillance_workflow_id UUID` - Links schedule to surveillance workflow
- `surveillance_quarter INTEGER` - Quarter number (1-4)

These fields are copied to testing_requests when the daily scheduler creates them.

**Run migration:**
```bash
python run_migration_013.py
```

### 2. Updated Models

**File:** `models.py` (lines ~2687-2708)

Added to `TestRequestSchedule` model:
```python
# SURVEILLANCE WORKFLOW LINKAGE
surveillance_workflow_id = Column(
    UUID(as_uuid=True),
    ForeignKey("public.repair_workflows.id", ondelete="CASCADE"),
    nullable=True,
    index=True,
)

surveillance_quarter = Column(
    Integer,
    nullable=True,
)
```

### 3. Updated Surveillance Hooks

**File:** `surveillance_hooks.py`

#### Function: `_create_surveillance_test_schedules()`

Creates `TestRequestSchedule` records when surveillance workflow is created:

```python
def _create_surveillance_test_schedules(
    db: Session,
    surveillance_workflow: RepairWorkflow,
    start_date: datetime,
    quarter_months: int,
    user_id: UUID
) -> int:
    """
    Create TestRequestSchedule records for all surveillance quarters.

    The existing TestRequestScheduleService.run_daily_scheduler() will automatically
    create testing requests from these schedules at the appropriate times.
    """
    # Get equipment and test configs
    equipment = db.query(Equipment).filter(...).first()
    test_configs = db.query(SurveillanceTestConfig).filter(...).all()

    # Create schedules for each quarter (1-4)
    for quarter in range(1, 5):
        quarter_start = start_date + relativedelta(months=(quarter - 1) * quarter_months)

        # Create schedule for each test type (DGA, BDV, IR, Oil Quality)
        for test_config in test_configs:
            schedule = TestRequestSchedule(
                organization_id=surveillance_workflow.organization_id,
                equipment_id=equipment.id,
                test_type_id=test_config.test_type_id,
                frequency=ScheduleFrequency.semi_annual,  # 6 months
                next_run_date=quarter_start,
                # Surveillance linkage
                surveillance_workflow_id=surveillance_workflow.id,
                surveillance_quarter=quarter,
                ...
            )
            db.add(schedule)
```

**Key Points:**
- Creates 16 schedule records total (4 quarters × 4 test types)
- `next_run_date` set to quarter start date
- `advance_days` = 1 (creates request 1 day before due)
- `frequency` = semi_annual (6 months)
- Explicitly links to surveillance workflow via `surveillance_workflow_id`

### 4. Updated Test Request Schedule Service

**File:** `services/test_request_schedule_service.py` (lines ~465-479)

Modified `create_one_ticket()` to copy surveillance fields:

```python
new_data = {
    "title": schedule.title,
    "equipment_id": equipment.id,
    "test_type_id": schedule.test_type_id,
    "source_schedule_id": schedule.id,

    # Surveillance workflow linkage (if applicable)
    "surveillance_workflow_id": (
        schedule.surveillance_workflow_id if hasattr(schedule, 'surveillance_workflow_id') else None
    ),
    "surveillance_quarter": (
        schedule.surveillance_quarter if hasattr(schedule, 'surveillance_quarter') else None
    ),
    ...
}

new_request = svc.create_request(new_data, originator_id=schedule.created_by)
```

**Result:**
- Testing requests created from surveillance schedules automatically get `surveillance_workflow_id` and `surveillance_quarter` set
- Non-surveillance schedules (normal test schedules) have these fields as NULL

### 5. Removed Files

**Deleted:** `services/surveillance_test_scheduler.py`

This separate scheduler is no longer needed. All scheduling is handled by the existing `TestRequestScheduleService.run_daily_scheduler()`.

## How It Works

### Workflow Creation Flow

```
1. Repair workflow completes
   ↓
2. surveillance_hooks._on_repair_workflow_completed() fires
   ↓
3. Creates surveillance workflow (24 months, 5 stages)
   ↓
4. Calls _create_surveillance_test_schedules()
   ↓
5. Creates 16 TestRequestSchedule records:
      - Q1: DGA schedule (next_run: Month 0)
      - Q1: BDV schedule (next_run: Month 0)
      - Q1: IR schedule  (next_run: Month 0)
      - Q1: Oil Quality schedule (next_run: Month 0)
      - Q2: DGA schedule (next_run: Month 6)
      - Q2: BDV schedule (next_run: Month 6)
      - ... (Q3, Q4 follow same pattern)
```

### Daily Scheduler Flow

```
1. APScheduler triggers TestRequestScheduleService.run_daily_scheduler() (already configured in main.py)
   ↓
2. Query: SELECT * FROM test_request_schedules WHERE next_run_date <= NOW() + advance_days
   ↓
3. For each due schedule:
      - Call create_one_ticket()
      - Create TestingRequest with surveillance_workflow_id + surveillance_quarter
      - Set source_schedule_id for traceability
      - Update schedule.next_run_date += frequency (6 months)
   ↓
4. Testing requests now visible in UI and linked to surveillance workflow
```

### Stage Submission Validation

When officer submits quarterly review stage:

```
1. Officer clicks "Submit" on Q1 Surveillance Testing stage
   ↓
2. RepairWorkflowService.submit_stage() called
   ↓
3. Validation: _validate_surveillance_tests_completed(workflow_id, quarter=1)
   ↓
4. Query: SELECT * FROM testing_requests
           WHERE surveillance_workflow_id = workflow_id
             AND surveillance_quarter = 1
   ↓
5. Check: All tests status IN ('completed', 'cancelled')?
      YES → Allow submission
      NO  → Raise ValueError("Cannot submit: 2 tests still in progress...")
```

## Benefits of This Approach

✅ **Reuses Existing Infrastructure**
- No separate cron job needed
- Leverages existing `TestRequestScheduleService.run_daily_scheduler()`
- Uses proven scheduling logic (advance_days, frequency, etc.)

✅ **Explicit Database Linkage**
- `surveillance_workflow_id` and `surveillance_quarter` on both schedules AND testing requests
- Easy to query: "Show all tests for surveillance workflow X, quarter 2"
- Referential integrity via foreign keys

✅ **Consistent with Other Workflows**
- Calibration, TAQC, Failure Registry all use test_request_schedules
- Same pattern for all recurring testing
- Unified scheduler maintenance

✅ **Auditable**
- Schedule logs capture each execution
- `source_schedule_id` links testing_request back to schedule
- Easy to debug: "Which schedule created this testing request?"

✅ **Flexible**
- Can pause surveillance schedules (set is_active=false)
- Can adjust frequency without code changes
- Can manually trigger via force_run parameter

## Configuration

### Schedule Frequency

Surveillance schedules use **semi_annual (6 months)** frequency:
- Q1 → Month 0
- Q2 → Month 6
- Q3 → Month 12
- Q4 → Month 18

This is hardcoded in `surveillance_hooks.py` but can be made configurable via `surveillance_config` table if needed.

### Advance Days

Set to **1 day** by default:
```python
advance_days=1  # Create testing request 1 day before quarter start
```

This means:
- Q1 tests created 1 day before surveillance starts
- Q2 tests created 1 day before Month 6
- etc.

### Test Types

Determined by `surveillance_test_config` table:
```sql
SELECT test_type_id, default_priority
FROM surveillance_test_config
WHERE equipment_type_id = {transformer_type}
  AND is_active = true
```

Typical test types (from `CategoryDetails` table):
- DGA (Dissolved Gas Analysis)
- BDV (Breakdown Voltage)
- IR (Insulation Resistance)
- Oil Quality

## Migration Runbook

### Fresh Installation

```bash
# Run migrations in order
python run_migration_008.py  # Surveillance workflow schema
python run_migration_013.py  # Surveillance linkage to schedules

# Seed surveillance configuration
python seed.py  # Loads surveillance JSON configs
```

### Existing Installation (Upgrade)

```bash
# Add surveillance linkage to existing test_request_schedules
python run_migration_013.py

# No need to re-run seed.py if already done
```

## Troubleshooting

### Tests Not Created

**Symptom:** Surveillance workflow created but no testing requests appear

**Diagnosis:**
```sql
-- Check if schedules were created
SELECT * FROM test_request_schedules
WHERE surveillance_workflow_id = '{workflow_id}'
ORDER BY surveillance_quarter, test_type_id;

-- Should return 16 rows (4 quarters × 4 test types)
```

**Possible Causes:**
1. ❌ No `surveillance_test_config` for equipment type
   - Fix: Add config via admin UI or seed script
2. ❌ Schedules created with `is_active=false`
   - Fix: UPDATE test_request_schedules SET is_active=true WHERE ...
3. ❌ `next_run_date` in future beyond scheduler window
   - Fix: Check SCHEDULE_ADVANCE_DAYS config (default 15)

### Tests Created but Not Linked

**Symptom:** Testing requests exist but `surveillance_workflow_id` is NULL

**Diagnosis:**
```sql
-- Check testing requests
SELECT id, title, surveillance_workflow_id, surveillance_quarter, source_schedule_id
FROM testing_requests
WHERE source_schedule_id IN (
    SELECT id FROM test_request_schedules
    WHERE surveillance_workflow_id = '{workflow_id}'
);
```

**Possible Causes:**
1. ❌ Migration 013 not run (columns don't exist on schedules)
   - Fix: Run `python run_migration_013.py`
2. ❌ Old code still running (before integration)
   - Fix: Restart application, ensure latest code deployed

### Duplicate Tests Created

**Symptom:** Multiple testing requests for same quarter/test type

**Diagnosis:**
```sql
-- Check for duplicate schedules
SELECT surveillance_workflow_id, surveillance_quarter, test_type_id, COUNT(*)
FROM test_request_schedules
WHERE surveillance_workflow_id IS NOT NULL
GROUP BY surveillance_workflow_id, surveillance_quarter, test_type_id
HAVING COUNT(*) > 1;
```

**Possible Causes:**
1. ❌ Surveillance hook fired multiple times (idempotency check failed)
   - Fix: Check logs for duplicate workflow creations
2. ❌ Manual schedule creation
   - Fix: Delete duplicate schedules, keep earliest

## Related Files

### Core Files
- `surveillance_hooks.py` - Creates schedules when workflow starts
- `services/test_request_schedule_service.py` - Daily scheduler (existing, modified)
- `services/repair_workflow_service.py` - Stage validation (checks test completion)

### Configuration Files
- `surveillance_test_config` table - Test types per equipment type
- `surveillance_config` table - Organization-specific settings

### Migration Files
- `migrations/008_surveillance_workflow.sql` - Surveillance tables
- `migrations/013_add_surveillance_to_schedules.sql` - Schedule linkage
- `run_migration_013.py` - Migration runner

### Documentation
- `SURVEILLANCE_VALIDATION.md` - Stage submission validation
- `SURVEILLANCE_WORKFLOW_FLOW.md` - Overall flow documentation
- This file - Scheduler integration details
