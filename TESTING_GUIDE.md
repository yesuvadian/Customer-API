# Testing Guide - Complete Workflow Test

## 🎯 Test Scenario: End-to-End Testing Request Flow

This guide walks you through testing the complete workflow using the sample user accounts.

---

## Prerequisites

✅ Database has been seeded with sample data
✅ API server is running
✅ Flutter app is running

**Server URL:** `http://localhost:8000`

---

## Test Case 1: Engineer Creates Request → Auto-Assignment

### Step 1: Login as Engineer

**Credentials:**
- Email: `engineer@kptcl.com`
- Password: `admin123`

**Expected Result:**
- ✅ Login successful
- ✅ Dashboard shows "Create Testing Request" button
- ✅ User profile shows: Priya Sharma, Engineer, 220kV Yelahanka Substation

---

### Step 2: Create New Testing Request

**Action:** Navigate to Testing Requests → Create New

**Fill in the form:**
```
Equipment Details:
- Equipment Type: Transformer
- Test Type: Transformer Oil BDV Test
- Transformer Type: Power Transformer
- Transformer Rating: 100 MVA, 220/11 kV
- Manufacturer: ABB
- Serial Number: TF-2024-001

Request Information:
- Title: Transformer Oil BDV Testing - 220kV Yelahanka
- Description: Routine transformer oil breakdown voltage testing as per maintenance schedule
- Priority: Normal
- Requested Date: [Today's date]
- Due Date: [3 days from today]

Location (Auto-filled):
- Department: 220kV Yelahanka Substation
```

**Action:** Click **"Submit Request"**

**Expected Result:**
- ✅ Success message: "Request submitted successfully"
- ✅ Request number generated (e.g., REQ-2024-001)
- ✅ Initial status: "Submitted"
- ✅ **Tester automatically assigned** (tester1 or tester2)
- ✅ Status changes to: "Assigned"
- ✅ Assigned tester name visible in request details
- ✅ Request appears in "My Requests" list

---

### Step 3: Verify Auto-Assignment

**Action:** Click on the newly created request

**Expected Result:**
- ✅ Status: "Assigned"
- ✅ Assigned Tester: Suresh Reddy or Lakshmi Narayanan
- ✅ Assignment timestamp shown
- ✅ Workflow timeline shows: Draft → Submitted → Assigned

---

## Test Case 2: Tester Accepts and Processes Request

### Step 1: Logout and Login as Tester

**Action:** Logout → Login

**Credentials:**
- Email: `tester1@kptcl.com` (or whichever tester was assigned)
- Password: `admin123`

**Expected Result:**
- ✅ Login successful
- ✅ Dashboard shows "Assigned to Me" section
- ✅ New request appears in the list with badge/notification
- ✅ User profile shows: Suresh Reddy, Tester, Yelahanka Section

---

### Step 2: View and Accept Assignment

**Action:** Click on the assigned request

**Expected Result:**
- ✅ Request details visible
- ✅ Equipment information shown
- ✅ "Accept Assignment" button visible
- ✅ "Reject Assignment" button visible

**Action:** Click **"Accept Assignment"**

**Expected Result:**
- ✅ Success message: "Assignment accepted"
- ✅ Status changes to: "Accepted"
- ✅ "Start Testing" button now visible
- ✅ Accept timestamp recorded
- ✅ Workflow timeline shows: Draft → Submitted → Assigned → Accepted

---

### Step 3: Start Testing

**Action:** Click **"Start Testing"**

**Expected Result:**
- ✅ Success message: "Testing started"
- ✅ Status changes to: "In Progress"
- ✅ Start timestamp recorded
- ✅ "Submit Test Results" button visible
- ✅ Status badge color changes to indicate in-progress

---

### Step 4: Submit Test Results

**Action:** Click **"Submit Test Results"**

**Fill in the test results form:**
```
Test Information:
- Test Date: [Today's date]
- Test Time: [Current time]
- Test Location: 220kV Yelahanka Testing Lab
- Test Equipment Used: Megger Oil BDV Tester OTS 60PB

Test Parameters:
- Oil Sample: 500 ml
- Test Voltage: 60 kV
- Gap Between Electrodes: 2.5 mm
- Number of Breakdowns: 6
- Average BDV: 58 kV

Test Results:
- Breakdown Voltage 1: 57 kV
- Breakdown Voltage 2: 59 kV
- Breakdown Voltage 3: 58 kV
- Breakdown Voltage 4: 57 kV
- Breakdown Voltage 5: 60 kV
- Breakdown Voltage 6: 57 kV

Observations:
- Oil color: Clear, light yellow
- Oil temperature: 27°C
- Weather conditions: Clear, dry
- No visible contamination

Recommendation: Pass
- Oil BDV values within acceptable range (>50 kV)
- No immediate action required
- Next testing: 6 months

Notes:
- All readings stable
- Equipment calibration valid until Dec 2024
```

**Action:** Upload test report PDF (sample file)

**Action:** Upload test images (2-3 sample images)

**Action:** Click **"Submit Results"**

**Expected Result:**
- ✅ Success message: "Test results submitted successfully"
- ✅ Status changes to: "Test Submitted"
- ✅ Submission timestamp recorded
- ✅ Request moves to "Pending Approval" queue
- ✅ Department Head receives notification
- ✅ Workflow timeline shows: ...In Progress → Test Submitted

---

## Test Case 3: Department Head Reviews and Approves

### Step 1: Logout and Login as Department Head

**Action:** Logout → Login

**Credentials:**
- Email: `depthead@kptcl.com`
- Password: `admin123`

**Expected Result:**
- ✅ Login successful
- ✅ Dashboard shows "Pending Approvals" section
- ✅ New submission appears with badge/notification
- ✅ User profile shows: Ramesh Kumar, Department Head, RT North Division

---

### Step 2: Review Test Results

**Action:** Click on the pending request

**Expected Result:**
- ✅ Complete request details visible
- ✅ Equipment information shown
- ✅ Requester details: Priya Sharma (Engineer)
- ✅ Tester details: Suresh Reddy (Tester)
- ✅ All test parameters visible
- ✅ Test results data displayed
- ✅ Uploaded test report downloadable
- ✅ Test images viewable in gallery
- ✅ Tester recommendation: Pass
- ✅ "Approve" button visible
- ✅ "Reject" button visible

**Action:** Download and review test report PDF

**Expected Result:**
- ✅ PDF downloads successfully
- ✅ Report contains all test data
- ✅ Images are clear and readable

---

### Step 3: Approve Results

**Action:** Click **"Approve"**

**Fill in approval form:**
```
Approval Comments:
- Test results reviewed and verified
- BDV values within acceptable limits
- Documentation complete
- Approved for continued operation
```

**Action:** Click **"Confirm Approval"**

**Expected Result:**
- ✅ Success message: "Test results approved successfully"
- ✅ Status changes to: "Approved"
- ✅ Approval timestamp recorded
- ✅ Request marked as completed
- ✅ All parties receive notification (Engineer, Tester)
- ✅ Workflow timeline shows complete flow: Draft → ... → Approved
- ✅ Request moves to "Completed Requests" list

---

## Test Case 4: Verify Complete Workflow

### Step 1: Login as Engineer (Original Requester)

**Action:** Logout → Login as `engineer@kptcl.com`

**Expected Result:**
- ✅ Request visible in "My Requests"
- ✅ Status: "Approved"
- ✅ Complete workflow history visible
- ✅ Test results accessible
- ✅ Can download test report
- ✅ Can view test images

---

### Step 2: View Workflow Timeline

**Action:** Click on the completed request → View Timeline

**Expected Result:**
```
✅ Draft          - [timestamp] - Priya Sharma
✅ Submitted      - [timestamp] - Priya Sharma
✅ Assigned       - [timestamp] - System (Auto-assigned to Suresh Reddy)
✅ Accepted       - [timestamp] - Suresh Reddy
✅ In Progress    - [timestamp] - Suresh Reddy
✅ Test Submitted - [timestamp] - Suresh Reddy
✅ Approved       - [timestamp] - Ramesh Kumar
```

---

## Test Case 5: Organization Admin Views All Requests

### Step 1: Login as Organization Admin

**Credentials:**
- Email: `orgadmin@kptcl.com`
- Password: `admin123`

**Expected Result:**
- ✅ Login successful
- ✅ Access to all modules
- ✅ Can view all requests across organization

---

### Step 2: View Organization Dashboard

**Action:** Navigate to Analytics Dashboard

**Expected Result:**
- ✅ Total requests count: 1
- ✅ Completed requests: 1
- ✅ Completion rate: 100%
- ✅ Average turnaround time displayed
- ✅ Department performance chart
- ✅ Tester workload distribution

---

## Test Case 6: Test Rejection Flow

### Step 1: Create Another Request

**Action:** Login as `engineer@kptcl.com` → Create new request

**Fill in basic details and submit**

---

### Step 2: Tester Rejects Assignment

**Action:** Login as assigned tester

**Action:** View assigned request → Click **"Reject Assignment"**

**Fill in rejection reason:**
```
Rejection Reason:
- Equipment not accessible today due to maintenance
- Will be available tomorrow
```

**Action:** Confirm rejection

**Expected Result:**
- ✅ Status changes to: "Rejected"
- ✅ System attempts auto-reassignment to another tester
- ✅ If available, reassigns to tester2
- ✅ Original tester removed from assignment

---

## Test Case 7: Test Results Rejection

### Step 1: Submit Incomplete Results

**Action:** Login as tester → Accept request → Start testing

**Action:** Submit results with minimal data (missing key parameters)

---

### Step 2: Department Head Rejects

**Action:** Login as `depthead@kptcl.com`

**Action:** Review results → Click **"Reject"**

**Fill in rejection reason:**
```
Rejection Reason:
- Missing breakdown voltage readings
- Test images not clear
- Equipment calibration certificate not attached
Please resubmit with complete data
```

**Action:** Confirm rejection

**Expected Result:**
- ✅ Status changes to: "Rejected"
- ✅ Tester receives notification with rejection reason
- ✅ Request visible in tester's "Rejected Requests"
- ✅ Can view rejection comments

---

## Test Case 8: Manual Reassignment

### Step 1: Reassign Tester

**Action:** Login as `depthead@kptcl.com`

**Action:** Navigate to any assigned request

**Action:** Click **"Reassign Tester"**

**Select new tester from dropdown**

**Fill in reassignment reason:**
```
Reassignment Reason:
- Original tester on leave
- Workload balancing
```

**Action:** Confirm reassignment

**Expected Result:**
- ✅ Previous tester unassigned
- ✅ New tester assigned
- ✅ New tester receives notification
- ✅ Status remains "Assigned"
- ✅ Audit log records reassignment

---

## Test Case 9: Workload Statistics

### Step 1: View Tester Workload

**Action:** Login as `depthead@kptcl.com` or `orgadmin@kptcl.com`

**Action:** Navigate to Tester Assignment → Workload Stats

**Expected Result:**
```
Tester Workload Dashboard:
┌──────────────────┬────────────┬────────────┬───────────┐
│ Tester           │ Active     │ Completed  │ Total     │
├──────────────────┼────────────┼────────────┼───────────┤
│ Suresh Reddy     │ 2          │ 1          │ 3         │
│ Lakshmi Narayanan│ 1          │ 0          │ 1         │
└──────────────────┴────────────┴────────────┴───────────┘
```

- ✅ Active requests per tester shown
- ✅ Completed requests count
- ✅ Average turnaround time
- ✅ Visual chart/graph displayed

---

## Test Case 10: API Direct Testing

### Test Auto-Assignment API

```bash
POST http://localhost:8000/tester-assignment/auto-assign
Headers: Authorization: Bearer <token>
Body: {
  "testing_request_id": "uuid-here",
  "strategy": "least_loaded"
}

Expected Response:
{
  "success": true,
  "tester_id": "uuid-of-assigned-tester",
  "tester_name": "Suresh Reddy",
  "tester_email": "tester1@kptcl.com",
  "message": "Tester auto-assigned successfully",
  "strategy_used": "least_loaded"
}
```

### Test Eligible Testers API

```bash
GET http://localhost:8000/tester-assignment/eligible-testers/{request_id}
Headers: Authorization: Bearer <token>

Expected Response:
{
  "eligible_testers": [
    {
      "id": "uuid",
      "name": "Suresh Reddy",
      "email": "tester1@kptcl.com",
      "department": "Yelahanka Section",
      "active_requests": 2,
      "is_available": true
    },
    {
      "id": "uuid",
      "name": "Lakshmi Narayanan",
      "email": "tester2@kptcl.com",
      "department": "RT North SD1 Yelahanka",
      "active_requests": 1,
      "is_available": true
    }
  ],
  "total_eligible": 2
}
```

---

## Verification Checklist

After completing all test cases, verify:

### ✅ Authentication & Authorization
- [x] All users can login with correct credentials
- [x] Users see only permitted data (scope-based)
- [x] Role-based actions are enforced

### ✅ Auto-Assignment
- [x] Tester automatically assigned on submit
- [x] Assignment based on least workload
- [x] Considers department hierarchy
- [x] Respects max concurrent limit (5)
- [x] Reassignment works on rejection

### ✅ Workflow States
- [x] All 9 states transition correctly
- [x] State-specific actions available
- [x] Timeline shows complete history
- [x] Audit log records all changes

### ✅ Permissions
- [x] Engineers can create and view own requests
- [x] Testers see only assigned requests
- [x] Dept Heads see department tree requests
- [x] Org Admins see all requests

### ✅ Data Integrity
- [x] Request numbers unique
- [x] Timestamps accurate
- [x] File uploads work
- [x] Notifications sent

### ✅ User Experience
- [x] UI responsive and fast
- [x] Error messages clear
- [x] Success confirmations shown
- [x] Navigation intuitive

---

## Performance Testing

### Load Test: Multiple Requests

**Create 10 requests simultaneously:**
1. Login as engineer
2. Create 10 testing requests
3. Submit all

**Expected Result:**
- ✅ All requests auto-assigned
- ✅ Workload distributed evenly
- ✅ No duplicate assignments
- ✅ System remains responsive

---

### Stress Test: Tester Workload

**Assign 5+ requests to one tester:**
1. Manually assign 5 requests to tester1
2. Create new request (should auto-assign to tester2)

**Expected Result:**
- ✅ Tester1 at max capacity (5)
- ✅ New requests go to tester2
- ✅ System prevents overload

---

## Troubleshooting Test Issues

### Issue: Auto-assignment fails

**Debug Steps:**
1. Check tester has "Tester" role
2. Verify tester in same organization
3. Check department hierarchy matches
4. Verify tester is active
5. Check workload < 5

### Issue: Cannot approve results

**Debug Steps:**
1. Verify user has dept head role
2. Check request in "Test Submitted" state
3. Verify department scope includes request
4. Check permission matrix

---

## Test Data Cleanup

After testing, reset database:

```bash
cd C:\Yesu\CustomerAPI\Customer-API\migrations
.\reset_and_seed_local.ps1
```

Or use PowerShell:
```powershell
$env:PGPASSWORD='StrongPassword123!'
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" `
  -h localhost -p 5432 -U relu_user -d Relu_Vendor2 `
  -f 000_drop_all_tables.sql

& "C:\Program Files\PostgreSQL\18\bin\psql.exe" `
  -h localhost -p 5432 -U relu_user -d Relu_Vendor2 `
  -f run_all_migrations.sql

& "C:\Program Files\PostgreSQL\18\bin\psql.exe" `
  -h localhost -p 5432 -U relu_user -d Relu_Vendor2 `
  -f seed_complete_system.sql
```

---

## Success Criteria

All tests pass when:
- ✅ 0 errors in console
- ✅ All workflows complete successfully
- ✅ Auto-assignment works consistently
- ✅ Role-based permissions enforced
- ✅ Data integrity maintained
- ✅ Audit trail complete

---

**Testing Guide Version:** 1.0
**Last Updated:** March 22, 2026
