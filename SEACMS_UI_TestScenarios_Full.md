# SEACMS — UI Test Scenarios

**System:** SubStation Equipment and Asset Condition Monitoring System  
**Organisation:** KPTCL RT&RD  
**Scope:** Multi-Session Testing Workflow + Test Register  
**Date:** May 2026 | v1.1

---

## Summary

| Module / Role | TC Range | Total TCs | Positive | Negative |
| --- | --- | --- | --- | --- |
| Template Designer  (Admin/SEE RT) | TC-001 – TC-012 | 12 | 8 | 4 |
| Originator  —  Create Request | TC-013 – TC-022 | 10 | 7 | 3 |
| Test Assigner  —  Approve & Assign | TC-023 – TC-031 | 9 | 6 | 3 |
| Tester  —  Accept & Start | TC-032 – TC-038 | 7 | 5 | 2 |
| Tester  —  Multi-Session Entry | TC-039 – TC-055 | 17 | 12 | 5 |
| Tester  —  Submit Results | TC-056 – TC-062 | 7 | 5 | 2 |
| Result Approver  —  Review | TC-063 – TC-073 | 11 | 7 | 4 |
| Session Timeline  (All roles) | TC-074 – TC-080 | 7 | 6 | 1 |
| Dashboard Views | TC-081 – TC-093 | 13 | 11 | 2 |
| Negative / Edge Cases | TC-094 – TC-110 | 17 | 0 | 17 |
| Test Register  (EE TLSS / Admin / Read-only) | TC-111 – TC-135 | 25 | 18 | 7 |
| TOTAL |  | 135 | 85 | 50 |

---

## 1. Template Designer

> Role: Admin or SEE RT (any user with Template Management permissions). Navigate to: Settings > Test Templates > select insulation_resistance_test > Edit.

### TC-001 — Template Designer

**Steps:**
1. Open Template Designer for 'Insulation Resistance (IR) Test'
1. Locate the ir_readings table field
1. Click on pi_value column

**Expected:**
- Column editor panel opens
- Type dropdown shows: Text / Number / Calculated
- Current type is 'Calculated'

**Status:** ✅ PASS

---

### TC-002 — Template Designer

**Steps:**
1. With pi_value column selected
1. Verify Formula field is visible below the Type dropdown
1. Check the formula text

**Expected:**
- Formula field is shown and read-only for display
- Formula value: ratio(ir_value_10min, ir_value_1min)
- Tooltip or label explains: 'PI = IR 10min / IR 1min'

**Status:** ✅ PASS

---

### TC-003 — Template Designer

**Steps:**
1. Select a Number-type column (e.g. ir_value_1min)
1. Change type to Calculated
1. Enter formula: ratio(ir_value_10min, ir_value_1min)
1. Save the template

**Expected:**
- Type dropdown accepts Calculated
- Formula input field appears when Calculated is selected
- Save returns HTTP 200
- Template reloads with updated column

**Status:** ✅ PASS

---

### TC-004 — Template Designer

**Steps:**
1. Open Column Summaries section in ir_readings field editor
1. Set ir_value_1min to Average
1. Set ir_value_10min to Average
1. Set pi_value to Average
1. Save template

**Expected:**
- Column Summaries section is collapsible/expandable
- Each non-text column has a dropdown: None / Average / Sum / Min / Max
- After save, template_data.column_summaries reflects the choices
- HTTP 200 returned

**Status:** ✅ PASS

---

### TC-005 — Template Designer

**Steps:**
1. Set a column summary to Sum for ir_value_1min
1. Set another column summary to Min for ir_value_10min
1. Save and reopen the template

**Expected:**
- Dropdowns persist the selected aggregation after reload
- column_summaries in JSON: {ir_value_1min: 'sum', ir_value_10min: 'min'}

**Status:** ✅ PASS

---

### TC-006 — Template Designer

**Steps:**
1. Change pi_value type back to Number (clear calculated type)
1. Save template
1. Open test form for a request

**Expected:**
- PI Value cell becomes editable
- No auto-calculation occurs
- Tester must manually type the value

**Status:** ✅ PASS

---

### TC-007 — Template Designer

**Steps:**
1. Add a new column to ir_readings table
1. Set type to Calculated
1. Enter formula referencing a non-existent column key
1. Save template

**Expected:**
- Template saves without error (formula validation is client-side)
- In test form, calculated cell shows 0 or empty when referenced key is missing

**Status:** ✅ PASS

---

### TC-008 — Template Designer

**Steps:**
1. Open predefined rows section of ir_readings field
1. Add a predefined row: winding=HV-LV, measurement_point=HV to LV and E
1. Save template
1. Open test form for any in_progress request

**Expected:**
- Predefined rows appear pre-filled in the table when form loads
- Tester can edit cell values but row structure is preset

**Status:** ✅ PASS

---

### TC-009 — Template Designer

**Steps:**
1. Attempt to save a Calculated column without entering a formula
1. Click Save

**Expected:**
- Validation prevents save
- Error shown: 'Formula is required for calculated columns'
- Template is not updated

**Status:** ❌ FAIL

---

### TC-010 — Template Designer

**Steps:**
1. Open a template that does not exist (modify the URL ID)
1. Attempt to edit

**Expected:**
- 404 error page or error snackbar shown
- Template Designer does not load empty/broken state

**Status:** ❌ FAIL

---

### TC-011 — Template Designer

**Steps:**
1. Login as a user without Template Management permissions (e.g. Originator)
1. Navigate to template designer URL directly

**Expected:**
- Access denied message shown
- Template editor fields are read-only or page redirects

**Status:** ❌ FAIL

---

### TC-012 — Template Designer

**Steps:**
1. Delete all columns from a table field
1. Attempt to save

**Expected:**
- Validation prevents save OR save succeeds with empty columns array
- Test form renders gracefully (empty table, no crash)

**Status:** ❌ FAIL

---

## 2. Originator — Create Testing Request

> Role: Originator (originator@kptcl.com). Navigate to: Testing Requests > + New Request.

### TC-013 — New Request

**Steps:**
1. Login as Originator
1. Click + New Request
1. Fill all required fields: Title, Equipment Type, Test Type, Priority, Category, Due Date
1. Click Submit

**Expected:**
- Request created with status = submitted
- Request appears in Testing Requests list
- Request number assigned (e.g. TR-20260421-0001)

**Status:** ✅ PASS

---

### TC-014 — New Request

**Steps:**
1. Fill required fields
1. Click Save as Draft instead of Submit

**Expected:**
- Request created with status = draft
- Originator can re-open and edit the draft
- Submit button available in draft detail view

**Status:** ✅ PASS

---

### TC-015 — New Request

**Steps:**
1. Select Equipment Type = Current Transformer
1. Observe Test Type dropdown

**Expected:**
- Test Type dropdown loads options specific to Current Transformer
- e.g. CT Insulation Test, CT Ratio Test are listed

**Status:** ✅ PASS

---

### TC-016 — New Request

**Steps:**
1. Open a draft request
1. Edit the title and description
1. Submit

**Expected:**
- Edits are saved
- Status changes to submitted after Submit
- Updated fields visible in detail view

**Status:** ✅ PASS

---

### TC-017 — New Request

**Steps:**
1. Set Priority = High
1. Submit the request
1. View in approver's pending list

**Expected:**
- High priority requests appear with red or distinct colour highlight in approver view

**Status:** ✅ PASS

---

### TC-018 — New Request

**Steps:**
1. Set Due Date to tomorrow
1. Submit request
1. Wait for due date to pass (or check overdue logic)

**Expected:**
- Overdue requests appear in EE-TLSS dashboard overdue count
- Due date shown correctly in request detail

**Status:** ✅ PASS

---

### TC-019 — New Request

**Steps:**
1. Create request with request_category = maintenance
1. Approve, assign, accept, start
1. Open Enter Test Results form

**Expected:**
- Maintenance template loads automatically (transformer_maintenance key)
- No template picker dialog shown

**Status:** ✅ PASS

---

### TC-020 — New Request

**Steps:**
1. Leave Title field empty
1. Click Submit

**Expected:**
- Validation error shown: 'Title is required'
- Request is not created

**Status:** ❌ FAIL

---

### TC-021 — New Request

**Steps:**
1. Leave Equipment Type unselected
1. Click Submit

**Expected:**
- Validation error: 'Equipment Type is required'
- Form does not submit

**Status:** ❌ FAIL

---

### TC-022 — New Request

**Steps:**
1. Set Due Date to a past date
1. Click Submit

**Expected:**
- Validation error or warning shown for past due date
- Request creation blocked or warned

**Status:** ❌ FAIL

---

## 3. Test Assigner — Approve and Assign

> Role: Test Assigner (testassigner@kptcl.com). Navigate to: Testing Requests > filter by Submitted status.

### TC-023 — Approve & Assign

**Steps:**
1. Login as Test Assigner
1. Open a submitted request
1. Click Approve & Assign button

**Expected:**
- Dialog opens with: Tester Role dropdown, Tester User list, optional Comment field
- Confirm button is initially disabled until a tester is selected

**Status:** ✅ PASS

---

### TC-024 — Approve & Assign

**Steps:**
1. In Approve & Assign dialog
1. Select Tester Role = SEE RT
1. Observe the user list

**Expected:**
- Users with SEE RT role load in the tester list
- List shows: name, email, active request count

**Status:** ✅ PASS

---

### TC-025 — Approve & Assign

**Steps:**
1. Select Tester Role, then select specific tester
1. Add comment: 'Please complete by end of week'
1. Click Confirm

**Expected:**
- Status changes to assigned
- Assigned tester visible in request detail
- Comment saved and visible to tester

**Status:** ✅ PASS

---

### TC-026 — Approve & Assign

**Steps:**
1. Open a submitted request
1. Click Reject
1. Enter rejection reason: 'Incorrect equipment type selected'
1. Confirm

**Expected:**
- Status changes to rejected
- Rejection reason displayed in request detail
- Originator can see the rejection note

**Status:** ✅ PASS

---

### TC-027 — Approve & Assign

**Steps:**
1. Login as Test Assigner
1. Check AEE dashboard Pending Approvals KPI

**Expected:**
- KPI count matches number of submitted requests waiting for assignment

**Status:** ✅ PASS

---

### TC-028 — Approve & Assign

**Steps:**
1. Select Tester Role = Field Tester
1. Check user list

**Expected:**
- Only users with Field Tester role appear
- Users without this role are excluded

**Status:** ✅ PASS

---

### TC-029 — Approve & Assign

**Steps:**
1. Attempt to approve a request that is already in_progress

**Expected:**
- Approve & Assign button is not shown (wrong status)
- OR API returns 400: request must be in submitted state

**Status:** ❌ FAIL

---

### TC-030 — Approve & Assign

**Steps:**
1. Select a Tester Role
1. Try to select a user who does not have that role

**Expected:**
- User does not appear in the filtered list
- API rejects with 400 if attempted directly

**Status:** ❌ FAIL

---

### TC-031 — Approve & Assign

**Steps:**
1. Click Confirm without selecting a tester user

**Expected:**
- Confirm button remains disabled
- Validation error: 'Please select a tester'

**Status:** ❌ FAIL

---

## 4. Tester — Accept and Start

> Role: Tester (see.rt@kptcl.com). Navigate to: My Assignments in the sidebar.

### TC-032 — Accept & Start

**Steps:**
1. Login as assigned tester
1. Navigate to My Assignments
1. Locate the request (status = assigned)
1. Click Accept

**Expected:**
- Status changes to accepted
- Accept button disappears
- Start Testing button appears

**Status:** ✅ PASS

---

### TC-033 — Accept & Start

**Steps:**
1. With status = accepted
1. Click Start Testing

**Expected:**
- Status changes to in_progress
- Enter Test Results button appears
- Timer/start time recorded

**Status:** ✅ PASS

---

### TC-034 — Accept & Start

**Steps:**
1. Login as non-assigned user
1. Open a request assigned to another tester
1. Check action buttons

**Expected:**
- Accept and Start Testing buttons are NOT shown to unassigned users
- Read-only view only

**Status:** ✅ PASS

---

### TC-035 — Accept & Start

**Steps:**
1. After accepting, navigate away and return to My Assignments
1. Re-open the request

**Expected:**
- Status persists as accepted
- Start Testing button still present

**Status:** ✅ PASS

---

### TC-036 — Accept & Start

**Steps:**
1. Attempt to accept a request that is not in assigned state
1. (e.g. still in submitted)

**Expected:**
- Accept button not shown in UI
- API returns 400 if called directly

**Status:** ❌ FAIL

---

### TC-037 — Accept & Start

**Steps:**
1. Attempt to start testing when status is still assigned (not yet accepted)

**Expected:**
- Start Testing button not shown
- API blocks the action

**Status:** ❌ FAIL

---

### TC-038 — Accept & Start

**Steps:**
1. Login as Originator
1. Try to accept a request assigned to SEE RT

**Expected:**
- No Accept button visible — originator has no tester actions
- API returns 403 or 400

**Status:** ❌ FAIL

---

## 5. Tester — Multi-Session Test Entry

> Role: Tester. Request must be in in_progress status. Navigate to: My Assignments > open request > Enter Test Results.

### TC-039 — Session Entry

**Steps:**
1. Open an in_progress request
1. Click Enter Test Results
1. Verify form layout

**Expected:**
- Template form opens with correct sections: Equipment Info, IR Measurements, Overall Assessment
- ir_readings table is present with columns: Winding, Measurement, IR 1min, IR 10min, PI Value, Result

**Status:** ✅ PASS

---

### TC-040 — Session Entry

**Steps:**
1. In the ir_readings table, enter IR 1min = 250 and IR 10min = 450
1. Observe PI Value column

**Expected:**
- PI Value auto-calculates to 1.80 (450/250)
- PI Value cell is read-only (greyed out)
- Value updates immediately on each keystroke without clicking Save

**Status:** ✅ PASS

---

### TC-041 — Session Entry

**Steps:**
1. Enter IR 1min = 180, IR 10min = 310
1. Check PI auto-calculation

**Expected:**
- PI = 310/180 = 1.72 shown automatically
- Rounding to 2 decimal places

**Status:** ✅ PASS

---

### TC-042 — Session Entry

**Steps:**
1. Enter IR 1min = 0
1. Observe PI Value

**Expected:**
- PI Value shows 0 or blank (no division by zero error)
- No crash or exception in the form

**Status:** ✅ PASS

---

### TC-043 — Session Entry

**Steps:**
1. Fill in all header fields and 3 IR readings rows
1. Click Save (not Submit)

**Expected:**
- Form saves successfully
- Snackbar: 'Test results saved'
- Status remains in_progress
- Session count in AEE dashboard increments to 1

**Status:** ✅ PASS

---

### TC-044 — Session Entry

**Steps:**
1. After Session 1 save, click Enter Test Results again
1. Check form pre-fill

**Expected:**
- Form re-opens pre-filled with Session 1 data
- All previously entered values are present
- PI values recalculate correctly from pre-filled IR values

**Status:** ✅ PASS

---

### TC-045 — Session Entry

**Steps:**
1. Update IR readings with new values (Session 2)
1. Click Save

**Expected:**
- Session 2 saved successfully
- AEE dashboard session count increments to 2
- Last session date updates to current date

**Status:** ✅ PASS

---

### TC-046 — Session Entry

**Steps:**
1. Save Session 3 with different readings
1. Open request detail page
1. Expand Session Timeline panel

**Expected:**
- Session Timeline shows 3 rows: Session 1, 2, 3
- Each row shows: number, timestamp, template key, status=completed, tester email

**Status:** ✅ PASS

---

### TC-047 — Session Entry

**Steps:**
1. In the ir_readings table, add a second row (click + Add Row or similar)
1. Enter values for the second row

**Expected:**
- Second row accepts input
- PI auto-calculates independently for the second row
- Column summary (AVG PI) updates to reflect average of both rows

**Status:** ✅ PASS

---

### TC-048 — Session Entry

**Steps:**
1. Fill all rows with PI > 1.5
1. Check overall result suggestion

**Expected:**
- Form or auto-evaluation shows Pass recommendation
- Overall Result dropdown pre-selects or suggests Pass

**Status:** ✅ PASS

---

### TC-049 — Session Entry

**Steps:**
1. Fill a row with PI = 1.2 (below 1.5 threshold)
1. Check row result

**Expected:**
- Row Result dropdown for that row shows or suggests Fail
- Or evaluation banner indicates attention needed

**Status:** ✅ PASS

---

### TC-050 — Session Entry

**Steps:**
1. Check column summary row at bottom of ir_readings table

**Expected:**
- AVG IR 1min, AVG IR 10min, AVG PI rows displayed
- Values are accurate averages of all entered rows
- Summary row is read-only and visually distinct (e.g. different background)

**Status:** ✅ PASS

---

### TC-051 — Session Entry

**Steps:**
1. Attempt to open test form when request status = submitted (not yet in_progress)

**Expected:**
- Enter Test Results button is NOT shown
- API returns 400 if called directly

**Status:** ❌ FAIL

---

### TC-052 — Session Entry

**Steps:**
1. Enter letters in IR 1min field (numeric field)

**Expected:**
- Input rejected; only numeric characters accepted
- Keyboard type shows numeric keyboard on mobile

**Status:** ❌ FAIL

---

### TC-053 — Session Entry

**Steps:**
1. Try to type in the PI Value (calculated) cell

**Expected:**
- Cell is read-only; cursor does not appear
- No keyboard appears on tap

**Status:** ❌ FAIL

---

### TC-054 — Session Entry

**Steps:**
1. Leave required Overall Result field empty
1. Click Save & Submit (finalize)

**Expected:**
- Validation error: 'Overall Result is required'
- Form does not submit

**Status:** ❌ FAIL

---

### TC-055 — Session Entry

**Steps:**
1. After clicking Save & Submit and status moves to under_approval
1. Attempt to re-open Enter Test Results

**Expected:**
- Enter Test Results button is NOT shown for under_approval status
- Cannot add further sessions after submission

**Status:** ❌ FAIL

---

## 6. Tester — Submit Results

> Role: Tester. At least one session must be saved. Navigate to: My Assignments > open in_progress request > Enter Test Results.

### TC-056 — Submit Results

**Steps:**
1. With at least one session saved, click Save & Submit
1. Confirm the dialog

**Expected:**
- Status changes to under_approval
- Snackbar: 'Test results submitted for approval'
- Enter Test Results button disappears

**Status:** ✅ PASS

---

### TC-057 — Submit Results

**Steps:**
1. After submission, check request detail status badge

**Expected:**
- Badge shows 'Under Approval' in orange
- No action buttons shown to the tester

**Status:** ✅ PASS

---

### TC-058 — Submit Results

**Steps:**
1. After submission, check EE-TLSS dashboard

**Expected:**
- open_remediation count increments by 1
- A recommendation record is created

**Status:** ✅ PASS

---

### TC-059 — Submit Results

**Steps:**
1. After submission, check AEE dashboard Assignments list

**Expected:**
- Request moves out of 'In Progress' in assignments
- assigned_tests KPI decrements by 1
- Session count still shows correct number

**Status:** ✅ PASS

---

### TC-060 — Submit Results

**Steps:**
1. Check session count on AEE dashboard after submission

**Expected:**
- session_count remains preserved (e.g. 3 sessions)
- last_session_date shows the date of the last save

**Status:** ✅ PASS

---

### TC-061 — Submit Results

**Steps:**
1. Attempt to submit without saving any session data first

**Expected:**
- API returns 400: no test results found
- Error snackbar shown to tester

**Status:** ❌ FAIL

---

### TC-062 — Submit Results

**Steps:**
1. After status = under_approval, attempt to click Save again

**Expected:**
- Save and Save & Submit buttons are not shown
- Cannot modify or add sessions

**Status:** ❌ FAIL

---

## 7. Result Approver — Review and Decision

> Role: Result Approver (orgadmin@kptcl.com). Navigate to: Approvals in the sidebar.

### TC-063 — Approver Review

**Steps:**
1. Login as Result Approver
1. Navigate to Approvals
1. Locate the submitted request (status = under_approval)

**Expected:**
- Request appears in the Approvals list
- Status badge shows 'Under Approval'

**Status:** ✅ PASS

---

### TC-064 — Approver Review

**Steps:**
1. Open the request in Approval Detail view
1. Scroll to Session Timeline section

**Expected:**
- Session Timeline shows all saved sessions with timestamps and tester names
- Session count matches number of saves made by tester

**Status:** ✅ PASS

---

### TC-065 — Approver Review

**Steps:**
1. Click 'Download PDF Report' in Approval Detail

**Expected:**
- PDF downloads successfully
- PDF contains: equipment info, IR readings table, PI values, column summary row (AVG PI, AVG IR1, AVG IR10)
- Tester details and submission timestamp on the report

**Status:** ✅ PASS

---

### TC-066 — Approver Review

**Steps:**
1. Verify column summary row in the PDF
1. Check AVG PI calculation

**Expected:**
- AVG PI = average of all PI values in the table
- AVG IR 1min and AVG IR 10min also shown
- Values match those shown in the UI form

**Status:** ✅ PASS

---

### TC-067 — Approver Review

**Steps:**
1. Click Approve Results
1. Add an optional comment
1. Confirm

**Expected:**
- Status changes to approved
- Recommendation and replacement products section visible to originator
- Approver cannot change decision after approving

**Status:** ✅ PASS

---

### TC-068 — Approver Review

**Steps:**
1. Click Reject Results
1. Enter reason: 'PI values below acceptable threshold; retest required'
1. Confirm

**Expected:**
- Status changes to rejected
- Tester is notified
- Rejection reason displayed in request detail

**Status:** ✅ PASS

---

### TC-069 — Approver Review

**Steps:**
1. After approval, check that originator sees Replacement Products section

**Expected:**
- Replacement products or recommendations section appears in request detail
- Originator can initiate procurement

**Status:** ✅ PASS

---

### TC-070 — Approver Review

**Steps:**
1. Login as Originator
1. Try to access the Approval Detail page

**Expected:**
- Approve/Reject buttons are not shown
- Read-only view only

**Status:** ❌ FAIL

---

### TC-071 — Approver Review

**Steps:**
1. Attempt to approve a request in submitted (not under_approval) status

**Expected:**
- Approve button not visible
- API returns 400 if attempted directly

**Status:** ❌ FAIL

---

### TC-072 — Approver Review

**Steps:**
1. Click Reject without entering a rejection reason

**Expected:**
- Validation error: 'Rejection reason is required'
- Confirmation blocked

**Status:** ❌ FAIL

---

### TC-073 — Approver Review

**Steps:**
1. After approving, attempt to reject the same request

**Expected:**
- Approve/Reject buttons no longer shown (status = approved)
- Cannot reverse decision through UI

**Status:** ❌ FAIL

---

## 8. Session Timeline — All Roles

> The Session Timeline panel is visible in the request detail to all users who have access to the request. It appears once at least one session exists (status in_progress or later).

### TC-074 — Session Timeline

**Steps:**
1. Login as any role with request access
1. Open a request with status = in_progress and 2 saved sessions
1. Scroll to Session Timeline section

**Expected:**
- Panel header shows: '2 sessions  |  Last: DD MMM YYYY'
- Panel is collapsed by default

**Status:** ✅ PASS

---

### TC-075 — Session Timeline

**Steps:**
1. Click the Session Timeline panel header to expand

**Expected:**
- Timeline expands showing rows for each session
- Each row: session number, date/time, template key, status badge, tester email
- Sessions listed in chronological order

**Status:** ✅ PASS

---

### TC-076 — Session Timeline

**Steps:**
1. After tester saves a 3rd session, refresh the request detail

**Expected:**
- Session count in panel header updates to 3
- New session row appears at the bottom of the expanded timeline

**Status:** ✅ PASS

---

### TC-077 — Session Timeline

**Steps:**
1. Click Session Timeline header again

**Expected:**
- Panel collapses back to the summary line
- Toggle works reliably

**Status:** ✅ PASS

---

### TC-078 — Session Timeline

**Steps:**
1. Open a request with status = draft (no sessions yet)

**Expected:**
- Session Timeline panel is NOT shown (no sessions exist)
- Panel only appears once first session is saved

**Status:** ✅ PASS

---

### TC-079 — Session Timeline

**Steps:**
1. Open a request with status = approved (sessions exist)

**Expected:**
- Session Timeline still visible with full history
- Sessions are read-only; no edit or delete options

**Status:** ✅ PASS

---

### TC-080 — Session Timeline

**Steps:**
1. Try to edit or delete a session entry from the UI

**Expected:**
- No edit or delete buttons shown in Session Timeline
- Sessions are immutable audit records

**Status:** ❌ FAIL

---

## 9. Dashboard Views

> Each role's dashboard loads automatically when the user logs in. Navigate to: Dashboard in the sidebar.

### TC-081 — AEE Dashboard

**Steps:**
1. Login as AEE Maintenance (aee.maintenance@kptcl.com)
1. Navigate to Dashboard

**Expected:**
- AEE dashboard loads with 4 KPI cards: Pending Approvals, Assigned Tests, Equipment Units, Maintenance Due
- Data is live (not hardcoded)

**Status:** ✅ PASS

---

### TC-082 — AEE Dashboard

**Steps:**
1. Check Assignments list on AEE dashboard after a tester saves Session 1

**Expected:**
- The request shows session_count = 1 in the assignments list
- session badge is visible below the status line

**Status:** ✅ PASS

---

### TC-083 — AEE Dashboard

**Steps:**
1. Check Assignments list after tester saves 3 sessions

**Expected:**
- session_count = 3 shown
- last_session_date = today's date shown

**Status:** ✅ PASS

---

### TC-084 — AEE Dashboard

**Steps:**
1. Check Pending Approvals KPI after approving a request

**Expected:**
- Pending Approvals count decrements by 1
- Dashboard reflects real-time state

**Status:** ✅ PASS

---

### TC-085 — EE-TLSS Dashboard

**Steps:**
1. Login as EE TLSS (ee.tlss@kptcl.com)
1. Navigate to Dashboard

**Expected:**
- Dashboard shows: Test Compliance %, Overdue Tests, Alert/Critical, Open Remediation, Maintenance Completion
- All values are numeric, not 0 when data exists

**Status:** ✅ PASS

---

### TC-086 — EE-TLSS Dashboard

**Steps:**
1. After tester submits results (status = under_approval)
1. Check EE-TLSS open_remediation count

**Expected:**
- open_remediation increments by 1
- Reflects that a new recommendation is pending

**Status:** ✅ PASS

---

### TC-087 — SEE Dashboard

**Steps:**
1. Login as SEE RT (see.rt@kptcl.com)
1. Navigate to Dashboard

**Expected:**
- SEE dashboard loads with role-appropriate KPIs
- No hardcoded or mock data shown

**Status:** ✅ PASS

---

### TC-088 — CEE Dashboard

**Steps:**
1. Login as CEE Zone (cee.zone@kptcl.com)
1. Navigate to Dashboard

**Expected:**
- CEE dashboard loads with zone-level KPIs
- Budget Utilization KPI is NOT shown (was removed)

**Status:** ✅ PASS

---

### TC-089 — CEE Dashboard

**Steps:**
1. Verify no Budget Utilization % card on CEE dashboard

**Expected:**
- Budget Utilization card is absent from the layout
- No hardcoded '67%' value displayed

**Status:** ✅ PASS

---

### TC-090 — Dashboard Routing

**Steps:**
1. Login as a user whose defaultModulePath = 'aee_dashboard'
1. Navigate to Dashboard

**Expected:**
- AEE dashboard component loads
- Not the generic welcome screen

**Status:** ✅ PASS

---

### TC-091 — Dashboard Routing

**Steps:**
1. Login as a user with no defaultModulePath set

**Expected:**
- Welcome / generic dashboard shown
- No crash or blank screen

**Status:** ✅ PASS

---

### TC-092 — Dashboard Routing

**Steps:**
1. Login as Admin
1. Navigate to Dashboard

**Expected:**
- Welcome screen shown (no dedicated Admin KPI dashboard yet)
- No hardcoded inline admin dashboard
- No crash or error

**Status:** ❌ FAIL

---

### TC-093 — Dashboard Data

**Steps:**
1. Disconnect API and reload any dashboard

**Expected:**
- Error state shown: 'Error loading dashboard: ...'
- Error icon and message visible
- No blank/frozen screen

**Status:** ❌ FAIL

---

## 10. Negative and Edge Case Tests

> These tests verify system behaviour under invalid inputs, unauthorised access, and boundary conditions.

### TC-094 — Auth

**Steps:**
1. Navigate to any protected page without logging in

**Expected:**
- Redirect to login page
- No page content shown without valid session

**Status:** ❌ FAIL

---

### TC-095 — Auth

**Steps:**
1. Login as Originator
1. Try to access /dashboard/aee directly via URL

**Expected:**
- Access denied OR wrong dashboard shown
- Originator does not see AEE KPIs (no matching defaultModulePath)

**Status:** ❌ FAIL

---

### TC-096 — Auth

**Steps:**
1. Login as Tester
1. Try to access Approve & Assign endpoint directly

**Expected:**
- API returns 403 or 400
- No approval action possible

**Status:** ❌ FAIL

---

### TC-097 — Concurrent Access

**Steps:**
1. Login as two testers
1. Both try to accept the same assigned request

**Expected:**
- Only the assigned tester can accept (assignment is single-user)
- Second user gets 400: not the assigned tester

**Status:** ❌ FAIL

---

### TC-098 — Session Ordering

**Steps:**
1. Save Session 1 at 09:00, Session 2 at 13:00
1. Check session timeline ordering

**Expected:**
- Sessions displayed in chronological order (oldest first)
- Session numbers are sequential and correct

**Status:** ❌ FAIL

---

### TC-099 — Calculated Field — Formula Error

**Steps:**
1. Template has formula referencing a column key that was renamed
1. Open test form for a request using this template

**Expected:**
- Calculated cell shows 0 or blank
- No crash; form remains usable
- Tester can still save and submit

**Status:** ❌ FAIL

---

### TC-100 — Column Summary — Empty Table

**Steps:**
1. Open test form with no rows in ir_readings table
1. Check column summary row

**Expected:**
- Summary row shows 0 or blank (no divide-by-zero error)
- Form remains functional

**Status:** ❌ FAIL

---

### TC-101 — PDF — No Sessions

**Steps:**
1. Attempt to download PDF for a request with no saved results
1. Trigger before any session is saved

**Expected:**
- PDF generation fails gracefully
- Error message: 'No test results found for this request'
- No blank PDF generated

**Status:** ❌ FAIL

---

### TC-102 — Submit — Duplicate Submit

**Steps:**
1. Rapidly double-click Save & Submit button

**Expected:**
- Only one submission processed
- Button disabled after first click
- No duplicate session records created

**Status:** ❌ FAIL

---

### TC-103 — Template — Missing Section

**Steps:**
1. Template has no Overall Assessment section
1. Tester opens test form

**Expected:**
- Form renders without crashing
- Fields from available sections shown normally

**Status:** ❌ FAIL

---

### TC-104 — Navigation

**Steps:**
1. Tester clicks away mid-form (navigates to another page) without saving
1. Returns to the form

**Expected:**
- Unsaved changes are lost (expected behaviour)
- OR browser warns before navigation — either is acceptable
- No corrupt data saved to server

**Status:** ❌ FAIL

---

### TC-105 — Table — Large Number of Rows

**Steps:**
1. Add 20 rows to the ir_readings table
1. Fill each with values
1. Save and check column summary

**Expected:**
- All 20 rows saved correctly
- Column summary averages 20 values accurately
- No performance freeze in the UI

**Status:** ❌ FAIL

---

### TC-106 — Offline

**Steps:**
1. Disable network connection
1. Attempt to save session data

**Expected:**
- Error snackbar: 'Network error — unable to save'
- No partial data written
- Data in form is preserved for retry

**Status:** ❌ FAIL

---

### TC-107 — Long Text

**Steps:**
1. Enter 1000-character text in Remarks field
1. Save

**Expected:**
- Long text accepted and saved correctly
- Text wraps correctly in form and PDF

**Status:** ❌ FAIL

---

### TC-108 — Special Characters

**Steps:**
1. Enter special characters (quotes, ampersands, HTML tags) in text fields
1. Save and view

**Expected:**
- Special characters displayed correctly without XSS or encoding errors
- No HTML injection rendered

**Status:** ❌ FAIL

---

### TC-109 — Session Count — Dashboard Cache

**Steps:**
1. Save a new session
1. Immediately check AEE dashboard session count

**Expected:**
- Dashboard reflects latest session count without requiring manual refresh
- Cache TTL is short enough for real-time use

**Status:** ❌ FAIL

---

### TC-110 — Status Badge

**Steps:**
1. Check status badge display for all 9 statuses in the request detail

**Expected:**
- Each status has a distinct colour: draft=grey, submitted=blue, assigned=purple, accepted=teal, in_progress=green, under_approval=orange, approved=dark green, procurement=dark purple, completed=dark grey
- Badge text is human-readable (no underscores)

**Status:** ❌ FAIL

---

## 11. Test Register

> Role: EE TLSS (eetlss@kptcl.com) and Department Head (depthead@kptcl.com) — create, edit, deactivate templates; Admin (admin@kptcl.com) — same write access; Originator, Tester, Field Tester — read-only view.
> Navigate to: Navigation Drawer > Test Register. Test data spans equipment types: Power Transformer, Circuit Breaker, Isolator, Current Transformer; test types: IR Test, Oil Dielectric Strength Test, Tan Delta Test, Partial Discharge (PD) Test, Earthing Resistance Test.

### TC-111 — View Catalogue (EE TLSS)

**Steps:**
1. Login as eetlss@kptcl.com
1. Open Navigation Drawer > tap Test Register
1. Observe Catalogue tab (default active tab)

**Expected:**
- Templates grouped by equipment type (Transformer, Circuit Breaker, Isolator)
- Each card shows: title, frequency badge, next-run date, Active status
- Search bar and Equipment Type filter visible at top
- + Add Template FAB visible (write-role user)

**Status:** ✅ PASS

---

### TC-112 — Create Template — Annual IR Test (EE TLSS)

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Select Equipment Type = Power Transformer
1. Enter Title = Annual Insulation Resistance (IR) Test
1. Select Frequency = Annual (1 year)
1. Set First Run Date = 2026-06-01
1. Tap Save

**Expected:**
- Template card appears under Power Transformer group
- Card shows Annual badge and next-run date 2026-06-01
- Active (green) status badge shown

**Status:** ✅ PASS

---

### TC-113 — Create Template — Semi-Annual Oil Test (EE TLSS)

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Select Equipment Type = Power Transformer
1. Enter Title = Oil Dielectric Strength Test
1. Select Frequency = Semi-Annual (6 months)
1. Set First Run Date = 2026-04-01
1. Enter OEM Reference = IEC 60156:2018
1. Tap Save

**Expected:**
- Template added under Power Transformer group
- Semi-Annual badge shown on card
- OEM ref IEC 60156:2018 displayed on card meta-row

**Status:** ✅ PASS

---

### TC-114 — Create Template — Tan Delta Test (Department Head)

**Steps:**
1. Login as depthead@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Select Equipment Type = Power Transformer
1. Enter Title = Tan Delta (Dissipation Factor) Test
1. Select Frequency = Annual (1 year)
1. Set First Run Date = 2026-05-15
1. Tap Save

**Expected:**
- Template created successfully by Department Head user
- Department Head has same write access as EE TLSS
- Card visible under Power Transformer group

**Status:** ✅ PASS

---

### TC-115 — Create Template — Biennial Earthing Test (Admin)

**Steps:**
1. Login as admin@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Select Equipment Type = Isolator
1. Enter Title = Earthing Resistance Test
1. Select Frequency = Biennial (2 years)
1. Set First Run Date = 2026-07-01
1. Tap Save

**Expected:**
- Template created under Isolator group
- Biennial (2 years) frequency badge shown on card
- Admin role can create Test Register templates

**Status:** ✅ PASS

---

### TC-116 — Create Template — Quarterly PD Test (Circuit Breaker)

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Select Equipment Type = Circuit Breaker
1. Enter Title = Partial Discharge (PD) Test
1. Select Frequency = Quarterly (3 months)
1. Set First Run Date = 2026-04-15
1. Tap Save

**Expected:**
- Circuit Breaker group appears in catalogue with PD Test card
- Quarterly (3 months) badge shown
- Multiple equipment type groups now visible

**Status:** ✅ PASS

---

### TC-117 — Edit Template — Add OEM Reference (EE TLSS)

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Find Annual Insulation Resistance (IR) Test under Power Transformer
1. Tap Edit button on card
1. Enter OEM Ref = IS 2026 Part 1
1. Verify Equipment Type dropdown is disabled (greyed out)
1. Tap Save

**Expected:**
- Card updates to show OEM ref IS 2026 Part 1
- Equipment Type field was correctly disabled in edit mode
- Title and Frequency fields unchanged

**Status:** ✅ PASS

---

### TC-118 — Edit Template — Set ALERT Override (EE TLSS)

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Find Oil Dielectric Strength Test under Power Transformer
1. Tap Edit
1. Enter ALERT Override Days = 30
1. Tap Save

**Expected:**
- Card shows ALERT override badge: 30 d override
- Indicates that after an ALERT result the test repeats in 30 days not 6 months
- Other template fields unchanged

**Status:** ✅ PASS

---

### TC-119 — Filter by Equipment Type

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. In Equipment Type filter dropdown, select Power Transformer

**Expected:**
- Only Power Transformer templates shown in catalogue
- Circuit Breaker and Isolator groups hidden from view
- Clear Filter option appears in filter bar

**Status:** ✅ PASS

---

### TC-120 — Search Template by Title Keyword

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Type Insulation in the search box

**Expected:**
- Only templates whose title contains Insulation are shown
- Oil Dielectric, Tan Delta, Earthing and PD templates hidden
- Live search updates results as user types each character

**Status:** ✅ PASS

---

### TC-121 — Read-only View — Originator

**Steps:**
1. Login as originator@kptcl.com
1. Navigate to Test Register via Navigation Drawer
1. Inspect Catalogue tab and individual template cards

**Expected:**
- All active templates visible and grouped by equipment type
- No + Add Template FAB rendered for Originator role
- No Edit or Deactivate buttons appear on any card

**Status:** ✅ PASS

---

### TC-122 — Equipment Schedules Tab — List All Units

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Tap Equipment Schedules tab

**Expected:**
- List shows all commissioned equipment units
- Each row shows: equipment name, type, substation, Schedules button
- Refresh button visible at top of tab

**Status:** ✅ PASS

---

### TC-123 — View Schedules — Power Transformer Unit

**Steps:**
1. Login as eetlss@kptcl.com, Test Register > Equipment Schedules tab
1. Find 220 kV Power Transformer T1 in equipment list
1. Tap Schedules button for T1

**Expected:**
- Dialog opens showing all active test schedules for 220 kV PT T1
- Rows include: Annual IR Test (due 2026-06-01) and Oil Dielectric Test (due 2026-10-01)
- Each schedule row shows template title, frequency, and next due date

**Status:** ✅ PASS

---

### TC-124 — Overdue Schedule Highlighted in Red

**Steps:**
1. Login as eetlss@kptcl.com, Test Register > Equipment Schedules tab
1. Find a unit whose next_run date is earlier than today
1. Tap Schedules for that unit

**Expected:**
- Overdue schedules shown with red/orange highlight in the schedule dialog
- Overdue indicator label displayed next to the due date
- On-time schedules displayed in normal text without highlight

**Status:** ✅ PASS

---

### TC-125 — Commission Equipment — Auto Schedule Creation

**Steps:**
1. Login as admin@kptcl.com
1. Navigate to Equipment Register > Add New Equipment
1. Enter Type = Power Transformer, Name = 220 kV Transformer T2, Substation = Hebbal 220/11 kV
1. Save equipment
1. Navigate to Test Register > Equipment Schedules tab
1. Find 220 kV Transformer T2 in list and tap Schedules

**Expected:**
- T2 appears in Equipment Schedules list immediately after save
- All active Power Transformer templates auto-commissioned as live schedules
- Schedule due dates computed from template first_run dates
- Commissioning is automatic and non-blocking

**Status:** ✅ PASS

---

### TC-126 — Alert Reschedule — Shorter Interval after ALERT Result

**Steps:**
1. Login as eetlss@kptcl.com, Test Register > Equipment Schedules tab
1. Open Schedules for a Transformer unit where Oil Dielectric Test has ALERT Override = 30 days
1. The most recent Oil Dielectric result for this unit was ALERT
1. Note the next_run date for Oil Dielectric schedule

**Expected:**
- Next due date = date of ALERT result + 30 days (not + 6 months standard)
- ALERT override active indicator shown in schedule row
- Standard 6-month schedule resumes after next non-ALERT result

**Status:** ✅ PASS

---

### TC-127 — Deactivate Template — Admin

**Steps:**
1. Login as admin@kptcl.com, navigate to Test Register
1. Find Earthing Resistance Test under Isolator
1. Tap Deactivate button on card
1. Confirm deactivation in the confirmation dialog

**Expected:**
- Card status badge changes from Active (green) to Inactive (grey)
- Template remains visible in catalogue with Inactive status for audit
- No new schedules generated from this template for future equipment commissions

**Status:** ✅ PASS

---

### TC-128 — EE TLSS Dashboard — Test Register Quick Action Tile

**Steps:**
1. Login as eetlss@kptcl.com
1. EE TLSS-role dashboard loads automatically
1. Observe Quick Actions row below KPI strip
1. Tap Test Register tile

**Expected:**
- Quick Actions row shows 4 tiles: Test Register, Equipment, Reports, Alerts
- Tapping Test Register tile navigates to /test-register route
- Test Register page loads with Catalogue tab active and templates visible

**Status:** ✅ PASS

---

### TC-129 — Role Restriction — Originator Cannot Create

**Steps:**
1. Login as originator@kptcl.com
1. Navigate to Test Register > Catalogue tab
1. Inspect page for the + Add Template FAB button

**Expected:**
- + FAB button is absent for Originator role
- No Create Template option accessible anywhere on page
- Catalogue is displayed read-only

**Status:** ❌ FAIL

---

### TC-130 — Role Restriction — Tester Cannot Edit or Deactivate

**Steps:**
1. Login as see.rt@kptcl.com (Tester role)
1. Navigate to Test Register via Navigation Drawer
1. Inspect individual template cards

**Expected:**
- Edit button not visible on any card
- Deactivate button not visible on any card
- Read-only view identical to Originator access level

**Status:** ❌ FAIL

---

### TC-131 — Validation — Title Required on Create

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Select Equipment Type = Current Transformer
1. Select Frequency = Annual (1 year), set First Run Date = 2026-06-01
1. Leave Title field blank
1. Tap Save

**Expected:**
- Save blocked by form validation
- Error message Title is required shown under Title field
- Form remains open for correction, no template created

**Status:** ❌ FAIL

---

### TC-132 — Validation — Equipment Type Required on Create

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Tap + FAB
1. Enter Title = Test Without Type
1. Select Frequency and set First Run Date
1. Leave Equipment Type unselected
1. Tap Save

**Expected:**
- Save blocked with validation error: Equipment Type is required
- Equipment Type dropdown highlighted in error state
- No template created in system

**Status:** ❌ FAIL

---

### TC-133 — Validation — Equipment Type Locked on Edit

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Open Edit dialog for Annual Insulation Resistance (IR) Test
1. Attempt to interact with Equipment Type dropdown in edit mode

**Expected:**
- Equipment Type dropdown is greyed out and non-interactive in edit mode
- Cannot change equipment type on an existing template
- All other fields (Title, Frequency, OEM Ref, ALERT Override) remain editable

**Status:** ❌ FAIL

---

### TC-134 — Validation — ALERT Override Must Be Positive

**Steps:**
1. Login as eetlss@kptcl.com, navigate to Test Register
1. Open Edit dialog for Oil Dielectric Strength Test
1. Enter ALERT Override Days = 0
1. Tap Save

**Expected:**
- Validation error displayed: ALERT override must be at least 1 day
- Form not submitted
- Zero-day override value rejected by UI validation

**Status:** ❌ FAIL

---

### TC-135 — Role Restriction — Field Tester Cannot Commission

**Steps:**
1. Login as field.tester@kptcl.com (Field Tester role)
1. Navigate to Test Register > Equipment Schedules tab
1. Inspect equipment list rows for any Commission button

**Expected:**
- No Commission button visible for Field Tester role
- Equipment list is read-only for Field Tester
- Schedules dialog accessible but no admin actions available

**Status:** ❌ FAIL

---
