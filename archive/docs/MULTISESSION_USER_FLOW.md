# Multi-Session Testing - User Flow

**Date**: 2026-04-21  
**System**: SEACMS (Sea Cable Management System)  
**Feature**: Multi-Session Testing Workflow

---

## Overview

Multi-session testing allows testers to perform multiple rounds of testing on the same equipment at different times/locations, with each session tracked independently.

**Example Scenarios**:
- Test equipment at 3 different locations
- Test equipment before, during, and after repair
- Test equipment under different environmental conditions
- Perform initial test, re-test after calibration, final verification

---

## User Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    ADMIN/COORDINATOR                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  Create Test Request  │
                  │  - Equipment details  │
                  │  - Set sessions: 3    │ ← Admin sets total_sessions_planned
                  │  - Assign tester      │
                  └───────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │   Status: ASSIGNED    │
                  └───────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         TESTER                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  1. View Assigned Request            │
        │     - TR-20260421-0004               │
        │     - Shows: 3 sessions planned      │
        │     - Status: ASSIGNED               │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  2. Accept Request                   │
        │     - Tap "Accept Request" button    │
        └──────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │   Status: ACCEPTED    │
                  └───────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  3. Start Testing                    │
        │     - Tap "Start Testing" button     │
        │     - System auto-creates Session 1  │
        └──────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  Status: IN_PROGRESS  │
                  └───────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SESSION 1 - Testing Phase                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  4. Add Readings to Session 1        │
        │     - Tap "Add Reading" button       │
        │     - Select test template           │
        │       (e.g., CT Insulation Test)     │
        │     - Fill in test data:             │
        │       • Voltage: 2500V               │
        │       • Resistance: 1000 MΩ          │
        │       • Temperature: 25°C            │
        │     - System evaluates result        │
        │     - Reading saved to Session 1     │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  5. Add More Readings (Optional)     │
        │     - Add multiple test templates    │
        │     - Edit readings if needed        │
        │     - Delete readings if needed      │
        │     - All linked to Session 1        │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  6. Complete Session 1               │
        │     - Tap "Complete Session" button  │
        │     - System shows statistics:       │
        │       • Total readings: 3            │
        │       • Pass: 2                      │
        │       • Fail: 1                      │
        │     - Session 1 marked COMPLETED     │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  Status Check:                       │
        │  ✓ Completed: 1/3 sessions           │
        │  → Status: IN_PROGRESS (continues)   │ ← Fix applied here!
        └──────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SESSION 2 - Testing Phase                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  7. Start Session 2                  │
        │     - Tap "Start New Session" button │
        │     - System creates Session 2       │
        │     - Fresh reading list             │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  8. Add Readings to Session 2        │
        │     - Different location/time        │
        │     - Same or different templates    │
        │     - Independent from Session 1     │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  9. Complete Session 2               │
        │     - View statistics for Session 2  │
        │     - Session 2 marked COMPLETED     │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  Status Check:                       │
        │  ✓ Completed: 2/3 sessions           │
        │  → Status: IN_PROGRESS (continues)   │
        └──────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SESSION 3 - Testing Phase                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  10. Start Session 3                 │
        │      - Tap "Start New Session"       │
        │      - System creates Session 3      │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  11. Add Readings to Session 3       │
        │      - Final round of testing        │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  12. Complete Session 3              │
        │      - View statistics for Session 3 │
        │      - Session 3 marked COMPLETED    │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  Status Check:                       │
        │  ✓ Completed: 3/3 sessions           │
        │  → Status: UNDER_APPROVAL ✓          │ ← Transitions ONLY when all complete
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  13. System Actions (Automatic)      │
        │      - Creates recommendation        │
        │      - Derives result from all       │
        │        sessions (PASS/FAIL/COND)     │
        │      - Notifies approvers            │
        │      - Shows in Approval Queue       │
        └──────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APPROVER/SUPERVISOR                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  14. Review All Sessions             │
        │      - View Session 1 results        │
        │      - View Session 2 results        │
        │      - View Session 3 results        │
        │      - Review recommendation         │
        │      - Check timeline/history        │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  15. Approve or Reject               │
        │      Option A: Approve               │
        │      → Status: APPROVED              │
        │      → Equipment cleared for use     │
        │                                      │
        │      Option B: Reject                │
        │      → Status: REJECTED              │
        │      → Back to tester with notes     │
        └──────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  Status: APPROVED or  │
                  │         REJECTED      │
                  └───────────────────────┘
                              │
                              ▼
                        ┌─────────┐
                        │   END   │
                        └─────────┘
```

---

## Detailed Step-by-Step Flow

### Phase 1: Request Creation (Admin/Coordinator)

**Step 1**: Admin creates testing request
- **Where**: Admin portal / Web dashboard
- **Actions**:
  - Enter equipment details (CT, VT, etc.)
  - Set `total_sessions_planned = 3`
  - Assign to tester (e.g., John Doe)
  - Save request
- **Result**: Request TR-20260421-0004 created with status `ASSIGNED`

---

### Phase 2: Request Acceptance (Tester)

**Step 2**: Tester views assigned request
- **Where**: Flutter app → Testing Dashboard → Assigned tab
- **See**:
  ```
  TR-20260421-0004
  Equipment: CT-001
  Sessions Planned: 3
  Status: ASSIGNED
  ```

**Step 3**: Tester accepts request
- **Action**: Tap "Accept Request" button
- **Result**: Status changes to `ACCEPTED`

**Step 4**: Tester starts testing
- **Action**: Tap "Start Testing" button
- **Backend Action**: System automatically creates Session 1
- **Result**: 
  - Status changes to `IN_PROGRESS`
  - Session 1 created with status `in_progress`
  - Tester sees "Testing Sessions (0 of 3 completed)" badge

---

### Phase 3: Session 1 Testing

**Step 5**: View Session 1
- **Where**: Testing Details page
- **See**:
  ```
  📋 Testing Sessions (0 of 3 completed)
  
  Session 1
  Status: IN_PROGRESS
  Started: 2026-04-21 10:30 AM
  Readings: 0
  
  [Add Reading] button
  ```

**Step 6**: Add first reading
- **Action**: Tap "Add Reading"
- **Flow**:
  1. Select template: "CT Insulation Test"
  2. Fill form:
     - Test Voltage: 2500 V
     - Insulation Resistance: 1000 MΩ
     - Temperature: 25°C
  3. System evaluates automatically
  4. Shows result: ✅ PASS (resistance > 500 MΩ)
  5. Tap "Save & Submit"
- **Backend**: 
  - Creates `test_result` record
  - Links to Session 1 via `test_session_id`
  - Stores evaluation result
- **Result**: Reading appears in Session 1 list

**Step 7**: Add more readings (optional)
- **Action**: Repeat Step 6 for other templates
- **Examples**:
  - "CT Ratio Test" → ✅ PASS
  - "CT Polarity Test" → ❌ FAIL
- **Result**: Session 1 now has 3 readings

**Step 8**: Edit or delete readings (if needed)
- **Edit**: Tap reading → Modify values → Save
- **Delete**: Long-press reading → Confirm delete
- **Result**: Session 1 updated

**Step 9**: Complete Session 1
- **Action**: Tap "Complete Session" button
- **Confirmation Dialog**:
  ```
  Complete Session 1?
  
  This session will be marked as complete.
  You won't be able to add more readings.
  
  [Cancel]  [Complete]
  ```
- **Backend Actions**:
  1. Marks Session 1 as `completed`
  2. Calculates statistics:
     - Total readings: 3
     - Pass: 2, Fail: 1
     - Overall: CONDITIONAL
  3. Checks completion: 1 of 3 sessions done
  4. **Keeps status as IN_PROGRESS** ← Fix applied!
- **UI Updates**:
  ```
  📋 Testing Sessions (1 of 3 completed)
  
  ✅ Session 1 - COMPLETED
  Completed: 2026-04-21 11:45 AM
  Duration: 1h 15m
  Readings: 3 (Pass: 2, Fail: 1)
  Overall: CONDITIONAL
  
  [Start New Session] button enabled
  ```

---

### Phase 4: Session 2 Testing

**Step 10**: Start Session 2
- **Action**: Tap "Start New Session"
- **Backend**: Creates Session 2 with status `in_progress`
- **Result**:
  ```
  📋 Testing Sessions (1 of 3 completed)
  
  ✅ Session 1 - COMPLETED (collapsed)
  
  Session 2 - IN_PROGRESS
  Started: 2026-04-21 02:00 PM
  Location: Different site
  Readings: 0
  
  [Add Reading] button
  ```

**Step 11-13**: Repeat testing process
- Add readings to Session 2
- Edit/delete as needed
- Complete Session 2
- **Status**: Still `IN_PROGRESS` (2 of 3 completed)

---

### Phase 5: Session 3 Testing (Final)

**Step 14**: Start Session 3
- **Action**: Tap "Start New Session"
- **Backend**: Creates Session 3

**Step 15-16**: Complete final testing
- Add readings to Session 3
- Complete Session 3

**Step 17**: System transitions to approval
- **Backend Logic**:
  ```python
  # After Session 3 completion:
  completed_sessions = 3
  total_sessions_planned = 3
  
  if completed_sessions >= total_sessions_planned:
      request.status = UNDER_APPROVAL  # ✓ Transitions now!
  ```
- **Actions**:
  1. ✅ Status changes to `UNDER_APPROVAL`
  2. ✅ Creates recommendation from ALL sessions
  3. ✅ Derives overall result (PASS/FAIL/CONDITIONAL)
  4. ✅ Notifies approvers
  5. ✅ Request appears in Approval Queue

---

### Phase 6: Approval (Approver)

**Step 18**: Approver reviews request
- **Where**: Approval Queue
- **See**:
  ```
  TR-20260421-0004
  Equipment: CT-001
  Recommendation: CONDITIONAL PASS
  Sessions: 3 (all completed)
  
  [View Details] button
  ```

**Step 19**: View all session data
- **Session 1**: 3 readings, 2 pass, 1 fail
- **Session 2**: 4 readings, 4 pass
- **Session 3**: 3 readings, 3 pass
- **Overall**: 10 readings, 9 pass, 1 fail
- **Recommendation**: Conditional pass with monitoring

**Step 20**: Make decision
- **Option A**: Approve → Status: `APPROVED`
- **Option B**: Reject → Status: `REJECTED`, back to tester

---

## Key Features of Multi-Session

### 1. Independent Sessions
- Each session has its own readings
- Sessions can be completed at different times/locations
- Edit/delete only affects current session

### 2. Session Statistics
- **Per Session**: Pass/Fail counts for that session only
- **Overall**: Aggregated across all completed sessions
- **Backend-Calculated**: Accurate real-time stats

### 3. Status Transitions (FIXED!)

| Completed Sessions | Status         | Can Add Sessions? | Can Submit? |
|-------------------|----------------|-------------------|-------------|
| 0 of 3            | IN_PROGRESS    | ✅ Yes             | ❌ No        |
| 1 of 3            | IN_PROGRESS    | ✅ Yes             | ❌ No        |
| 2 of 3            | IN_PROGRESS    | ✅ Yes             | ❌ No        |
| 3 of 3            | UNDER_APPROVAL | ❌ No              | ✅ Yes       |

**Before Fix**: Would go to UNDER_APPROVAL after Session 1 ❌  
**After Fix**: Only goes to UNDER_APPROVAL after ALL sessions complete ✅

### 4. Timeline View
Tester can see complete history:
```
Timeline
├─ Request Created (Apr 21, 9:00 AM)
├─ Request Accepted (Apr 21, 10:00 AM)
├─ Testing Started (Apr 21, 10:30 AM)
├─ Session 1 Completed (Apr 21, 11:45 AM)
│  └─ 3 readings, 2 pass, 1 fail
├─ Session 2 Started (Apr 21, 2:00 PM)
├─ Session 2 Completed (Apr 21, 3:30 PM)
│  └─ 4 readings, 4 pass
├─ Session 3 Started (Apr 21, 4:00 PM)
├─ Session 3 Completed (Apr 21, 5:00 PM)
│  └─ 3 readings, 3 pass
└─ Submitted for Approval (Apr 21, 5:00 PM)
```

---

## Mobile UI Screens

### Screen 1: Request Details (Before Starting)
```
┌─────────────────────────────────┐
│ ← Back    TR-20260421-0004      │
├─────────────────────────────────┤
│ Equipment Details               │
│ Type: Current Transformer       │
│ ID: CT-001                      │
│ Status: ACCEPTED                │
│                                 │
│ 📋 Multi-Session Testing        │
│ Total Sessions: 3               │
│ Completed: 0                    │
│                                 │
│ [ Start Testing ]               │
└─────────────────────────────────┘
```

### Screen 2: Active Testing (1 of 3 Sessions)
```
┌─────────────────────────────────┐
│ ← Back    TR-20260421-0004      │
├─────────────────────────────────┤
│ 📋 Testing Sessions (1/3 ✅)    │
│                                 │
│ ✅ Session 1 - COMPLETED        │
│    Apr 21, 11:45 AM             │
│    Readings: 3                  │
│    Pass: 2  Fail: 1             │
│    [View Details]               │
│                                 │
│ [ + Start New Session ]         │
│                                 │
│ ⚠️ 2 more sessions required     │
│    before submission            │
└─────────────────────────────────┘
```

### Screen 3: All Sessions Complete
```
┌─────────────────────────────────┐
│ ← Back    TR-20260421-0004      │
├─────────────────────────────────┤
│ 📋 Testing Sessions (3/3 ✅)    │
│                                 │
│ ✅ Session 1 - COMPLETED        │
│ ✅ Session 2 - COMPLETED        │
│ ✅ Session 3 - COMPLETED        │
│                                 │
│ Overall Statistics:             │
│ Total Readings: 10              │
│ Pass: 9  Fail: 1                │
│                                 │
│ Status: UNDER APPROVAL          │
│ Submitted: Apr 21, 5:00 PM      │
│                                 │
│ Awaiting supervisor approval... │
└─────────────────────────────────┘
```

---

## Backend Logic (Simplified)

### Session Completion Check
```python
def submit_test_results(request_id):
    request = get_request(request_id)
    
    if request.is_multi_session:
        # Count completed sessions
        completed = count_sessions(
            request_id=request_id,
            status="completed"
        )
        
        # Check if all sessions done
        if completed >= request.total_sessions_planned:
            # ✅ All sessions complete
            request.status = "under_approval"
            create_recommendation(request)
            notify_approvers(request)
        else:
            # ⏳ More sessions needed
            request.status = "in_progress"
    else:
        # Single-session: immediate approval
        request.status = "under_approval"
```

### Reading-Session Link
```sql
-- Each reading is linked to a specific session
INSERT INTO test_results (
    testing_request_id,
    test_session_id,  -- Links to specific session
    template_key,
    test_data,
    overall_result
) VALUES (
    'uuid-of-request',
    'uuid-of-session-1',  -- Session 1, 2, or 3
    'ct_insulation_test',
    '{"voltage": 2500, "resistance": 1000}',
    'pass'
);
```

---

## Common Scenarios

### Scenario 1: Equipment Tested at 3 Locations
- **Session 1**: Factory (before shipment)
- **Session 2**: On-site (after installation)
- **Session 3**: Final site (after commissioning)

### Scenario 2: Re-testing After Repair
- **Session 1**: Initial test (found issues)
- **Session 2**: After repair (still issues)
- **Session 3**: After second repair (all pass)

### Scenario 3: Environmental Testing
- **Session 1**: Normal temperature (25°C)
- **Session 2**: High temperature (45°C)
- **Session 3**: Low temperature (5°C)

---

## Backward Compatibility

### Single-Session Requests
Old behavior still works:
1. Create request with `total_sessions_planned = 1` (or NULL)
2. Tester completes one session
3. Immediately goes to `UNDER_APPROVAL`
4. No changes to existing workflow

### Legacy Data
- Old test results without `test_session_id`: Remain NULL
- Still viewable and functional
- No migration needed for old data

---

## Summary

✅ **Multi-session enabled**: Tester can complete multiple testing rounds  
✅ **Independent sessions**: Each session has separate readings and stats  
✅ **Smart status logic**: Only submits when ALL sessions complete  
✅ **Edit/delete support**: Flexible reading management per session  
✅ **Timeline tracking**: Complete audit trail of all activities  
✅ **Backward compatible**: Single-session requests unaffected  

---

**Questions?** Refer to:
- `SEACMS_MultiSession_Testing_UserManual.md` - Complete user guide
- `UI_WORKFLOW_GUIDE.md` - Detailed UI interactions
- `MIGRATION_COMPLETE.md` - Database schema changes
