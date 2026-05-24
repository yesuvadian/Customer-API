# Surveillance Stage Validation Implementation

## Problem

When an officer submits a quarterly review stage (Q1-Q4) while testing requests are still in progress, the system would:
- Allow submission with incomplete data
- Calculate quality ratings on partial data (misleading)
- Lose later test completions after stage closes
- Create inaccurate surveillance reports

## Solution: Stage-Level Validation

Added validation in `RepairWorkflowService.submit_stage()` to **block submission** of quarterly stages until all testing requests are completed.

### Implementation

**File:** `services/repair_workflow_service.py`

#### 1. Added validation call in `submit_stage()` (line ~637)

```python
# Surveillance-specific validation: quarterly stages require all tests completed
if workflow.workflow_type == 'surveillance' and instance.quarter_number:
    self._validate_surveillance_tests_completed(workflow_id, instance.quarter_number)

instance.status = "submitted"
```

- Executes **before** status changes to "submitted"
- Only for surveillance workflows
- Only for quarterly stages (Q1-Q4), not final evaluation

#### 2. Added validation method `_validate_surveillance_tests_completed()` (line ~1786)

```python
def _validate_surveillance_tests_completed(self, workflow_id: UUID, quarter_number: int) -> None:
    """
    Validate that all surveillance testing requests for this quarter are completed.
    Raises ValueError if any tests are pending/in-progress.
    """
    from models import TestingRequest

    testing_requests = (
        self.db.query(TestingRequest)
        .filter(
            TestingRequest.surveillance_workflow_id == workflow_id,
            TestingRequest.surveillance_quarter == quarter_number
        )
        .all()
    )

    if not testing_requests:
        return  # No tests created yet - allow (tests created by daily scheduler)

    # Check for incomplete tests
    incomplete = [
        tr for tr in testing_requests
        if tr.status not in ['completed', 'cancelled']
    ]

    if incomplete:
        test_names = [tr.title or f"Test {tr.test_type.name}" for tr in incomplete[:3]]
        count = len(incomplete)
        msg = (
            f"Cannot submit quarterly review: {count} testing request(s) still in progress. "
            f"Please complete all tests before submitting this stage. "
            f"Incomplete tests: {', '.join(test_names)}"
        )
        if count > 3:
            msg += f" and {count - 3} more"
        raise ValueError(msg)
```

**Logic:**
1. Query all testing requests for this surveillance workflow + quarter
2. If no tests found → allow submission (tests will be created by daily scheduler)
3. Find incomplete tests (status not in `['completed', 'cancelled']`)
4. If any incomplete → raise `ValueError` with detailed message
5. Message shows first 3 incomplete test names for user clarity

### Why Not Use Hooks?

The existing `stage_approved` hook (fired in `advance_stage`) **cannot block** approvals because `workflow_hooks.fire()` catches all exceptions:

```python
# workflow_hooks.py
for fn in handlers:
    try:
        fn(db, workflow, user_id, **kwargs)
    except Exception as exc:
        logger.warning(...)  # Logged but never blocks
```

This is intentional - hooks are for **side effects** (like creating surveillance workflows), not validation.

Direct validation in `submit_stage()` is the correct approach because:
- ✅ Runs before status change
- ✅ Can raise `ValueError` to block submission
- ✅ Provides immediate user feedback
- ✅ Prevents invalid state (submitted without complete tests)

## User Experience

### Before Fix
```
Officer fills Q1 review form → Clicks Submit
→ Success (even though 2 tests still in progress)
→ Approver sees incomplete data
→ Later test completions lost
```

### After Fix
```
Officer fills Q1 review form → Clicks Submit
→ Error: "Cannot submit quarterly review: 2 testing request(s) still in progress.
          Please complete all tests before submitting this stage.
          Incomplete tests: DGA - Q1 Surveillance - TR-001, BDV - Q1 Surveillance - TR-001"
→ Officer completes remaining tests → Clicks Submit again
→ Success
```

## Testing

### Test Case 1: All tests completed
```python
# Create surveillance workflow Q1 stage
# Create 4 testing requests (DGA, BDV, IR, Oil Quality)
# Mark all as status='completed'
# Submit stage → Should succeed
```

### Test Case 2: Some tests incomplete
```python
# Create surveillance workflow Q1 stage
# Create 4 testing requests
# Mark 2 as 'completed', 2 as 'in_progress'
# Submit stage → Should fail with error listing incomplete tests
```

### Test Case 3: No tests created yet
```python
# Create surveillance workflow Q1 stage
# Don't create any testing requests yet
# Submit stage → Should succeed (tests will be created by daily scheduler)
```

### Test Case 4: All tests cancelled
```python
# Create surveillance workflow Q1 stage
# Create 4 testing requests
# Mark all as status='cancelled'
# Submit stage → Should succeed (cancelled tests don't block)
```

## Edge Cases Handled

1. **No tests created yet:** Allows submission (tests created by daily scheduler within 24h)
2. **Cancelled tests:** Treats cancelled as "complete" (doesn't block submission)
3. **Multiple incomplete tests:** Shows first 3 names, then "and N more" for readability
4. **Final evaluation stage:** No validation (quarter_number is NULL for final stage)

## Configuration

No configuration needed. Validation is:
- **Automatic** for all surveillance workflows
- **Quarter-specific** (only Q1-Q4, not final evaluation)
- **Hard requirement** (cannot be bypassed)

## Related Files

- `services/repair_workflow_service.py` - Validation logic
- `services/test_request_schedule_service.py` - Creates testing requests from schedules (daily cron)
- `services/surveillance_tracking_service.py` - Updates RepairSurveillanceTest when tests complete
- `models.py` - TestingRequest.surveillance_workflow_id, surveillance_quarter
- `routers/repair_workflow.py` - POST /repair-workflows/{id}/stages/{id}/submit endpoint

## Future Enhancements

If soft validation (warning instead of blocking) is needed later:
1. Add `allow_partial_submission` config flag to `surveillance_config` table
2. Modify validation to check flag before raising error
3. Show warning modal in UI if flag is enabled
