# CogniWatt Portal — Testing Module User Manual

> **Scope:** Testing workflow only (all scenarios)  
> **Portal URL:** `http://localhost:8096`  
> **Last Updated:** April 2026

---

## Table of Contents

1. [User Accounts](#1-user-accounts)
2. [Login & Navigation](#2-login--navigation)
3. [Status Flow Overview](#3-status-flow-overview)
4. [Scenario 1 — Standard End-to-End Test Flow](#4-scenario-1--standard-end-to-end-test-flow)
5. [Scenario 2 — Rejected Request (Rework)](#5-scenario-2--rejected-request-rework)
6. [Scenario 3 — Rejected Test Results (Re-test)](#6-scenario-3--rejected-test-results-re-test)
7. [Scenario 4 — Multi-Session Testing](#7-scenario-4--multi-session-testing)
8. [Scenario 5 — Scheduled / Recurring Tests](#8-scenario-5--scheduled--recurring-tests)
9. [Scenario 6 — Recommendations & Recommendation Approvals](#9-scenario-6--recommendations--recommendation-approvals)
10. [Scenario 7 — Image Attachments on Test Results](#10-scenario-7--image-attachments-on-test-results)
11. [Scenario 8 — Replacement Products on Failure](#11-scenario-8--replacement-products-on-failure)
12. [Scenario 9 — PDF Report Downloads](#12-scenario-9--pdf-report-downloads)
13. [Status & Badge Colour Reference](#13-status--badge-colour-reference)

---

## 1. User Accounts

All testing scenarios use **KPTCL** organisation accounts.

| Role | Email | Password | Sidebar Access |
|------|-------|----------|----------------|
| Originator | `originator@kptcl.com` | `admin123` | Testing Requests |
| Test Assigner | `testassigner@kptcl.com` | `admin123` | Testing Request Approvals |
| Department Head | `depthead@kptcl.com` | `admin123` | Testing Request Approvals |
| Field Tester 1 | `fieldtester1@kptcl.com` | `Tester123!` | Testing |
| Field Tester 2 | `fieldtester2@kptcl.com` | `Tester123!` | Testing |
| Lab Tester 1 | `labtester1@kptcl.com` | `Tester123!` | Testing |
| Lab Tester 2 | `labtester2@kptcl.com` | `Tester123!` | Testing |
| Approver (results) | `testassigner@kptcl.com` | `admin123` | Test Result Approvals, Approvals |
| Purchaser | `purchaser@kptcl.com` | `admin123` | Testing Requests (approved view) |

---

## 2. Login & Navigation

### Logging In

1. Open `http://localhost:8096` in Chrome
2. On the **Procurement Portal** login screen:
   - Enter **Email Address**
   - Enter **Password**
   - Click the **"Login to Procurement Portal"** button
3. The portal loads with a dark sidebar on the left

### Sidebar Navigation

The left sidebar shows only the modules your role has access to.  
Key testing sidebar items:

| Sidebar Label | Who Sees It |
|---------------|-------------|
| **Testing Requests** | Originator, Test Assigner, Dept Head, Purchaser |
| **Testing** | Field Tester, Lab Tester |
| **Testing Request Approvals** | Test Assigner, Dept Head |
| **Test Result Approvals** | Test Assigner, Dept Head |
| **Approvals** | Dept Head, Approver |
| **Recommendations** | All roles (read) |
| **Tester Mapping** | Admin, Test Assigner |
| **Test Template Management** | Admin |

Click **Logout** at the bottom of the sidebar to sign out.

---

## 3. Status Flow Overview

```
[Originator]         [Test Assigner]      [Field/Lab Tester]    [Result Approver]   [Purchaser]
     │                     │                      │                     │                 │
  draft ──────────► submitted ──────────► assigned ──────────► accepted             │
  (Save Draft)     (Submit)         (Approve & Assign)   (Accept button)            │
                   OR reject ◄──────────────────────────────────────────────        │
                                              │                     │                │
                                          in_progress ──────────────────────────    │
                                        (Start Testing)             │               │
                                              │                     │               │
                                      test_submitted ──────────► under_approval     │
                                      (Save & Submit)           (auto)              │
                                              │                     │               │
                                              │◄── reject (rework) ─┤               │
                                              │                  approved ──────────►
                                              │                                  procurement_
                                              │                                  initiated
                                              │                                     │
                                              └─────────────────────────────────► completed
```

---

## 4. Scenario 1 — Standard End-to-End Test Flow

### Step 1 — Originator: Create & Submit Request

**Login:** `originator@kptcl.com` / `admin123`

1. In the sidebar, click **"Testing Requests"**
2. The **Testing Requests** screen opens with tabs:
   - **My Requests** | **Assigned to Me** | **All Drafts** | **All Active** | **All**
3. Click the **"+ New Request"** button (bottom-right of the screen)
4. A form panel slides open. Fill in:

   | Field | Description |
   |-------|-------------|
   | **Title** | Short name for the test (e.g., "Transformer Oil Test") |
   | **Equipment Type** | Select from dropdown (e.g., Transformer, Circuit Breaker) |
   | **Test Type** | Select the applicable test standard |
   | **Department** | Select the department requesting the test |
   | **Description** | Detailed test requirements and scope |
   | **Scheduled Start Date** | When testing should begin (optional) |

5. To save without submitting: click **"Save as Draft"**  
   → Row appears in **My Requests** tab with status badge **`draft`** (grey)

6. To submit: click **"Submit"**  
   → Status badge changes to **`submitted`** (blue)  
   → Request now visible in Test Assigner's queue

---

### Step 2 — Test Assigner: Approve Request & Assign Tester

**Login:** `testassigner@kptcl.com` / `admin123`

1. In the sidebar, click **"Testing Request Approvals"**
2. The screen shows a list of requests with status **`submitted`**
3. Click on a request row → a detail panel slides open on the right
4. Review the request details (equipment, department, description)
5. At the bottom of the panel, click **"Approve & Assign Tester"**
6. A dialog box opens:
   - **Select Tester Role** — choose "Field Tester" or "Lab Tester" from dropdown
   - **Select Tester** — user list appears; click the tester's name
   - Click **"Confirm Assignment"**
7. Success toast: *"Request approved and assigned successfully"*  
   → Status changes to **`assigned`** (cyan)

---

### Step 3 — Field Tester: Accept, Start, Enter Results & Submit

**Login:** `fieldtester1@kptcl.com` / `Tester123!`

1. In the sidebar, click **"Testing"**
2. The **Testing** screen opens with two tabs:
   - **In Progress** — active assignments
   - **Completed** — finished assignments
3. In the **In Progress** tab, find the request (status badge: **`assigned`**)
4. Click the row → a detail panel slides open on the right showing:
   - Request number, title, equipment type, assigned date

#### Accept the Assignment
5. At the bottom of the panel, click the **"Accept"** button  
   → Status changes to **`accepted`** (teal)

#### Start Testing
6. Click the **"Start Testing"** button  
   → Status changes to **`in_progress`** (amber)

#### Enter Test Results
7. Click **"Add Test Results"** (or the result form opens automatically)
8. If multiple test templates exist for the organisation, a **"Select Test Template"** dialog appears:
   - Lists available templates by name
   - Click the correct template
   - Click **"Confirm"** (or it auto-selects if only one exists)
9. The **Test Result Form** panel opens (width 620px):
   - Fill in all **measurement fields** (values, units)
   - Set **pass/fail** indicators per parameter
   - Set **Overall Result** — `pass` / `fail` / `conditional` / `retest`
   - Add **Remarks** (free text observations)
10. Two save options at the bottom of the form:
    - **"Save"** — saves a draft of the results without finalising
    - **"Save & Submit"** button (filled blue) — finalises and submits

#### Submit Results
11. Click **"Save & Submit"**  
    → Loading indicator: *"Submitting..."*  
    → Status transitions: **`in_progress`** → **`test_submitted`** → **`under_approval`** (purple)  
    → Request moves to **Completed** tab

---

### Step 4 — Test Assigner / Approver: Approve Test Results

**Login:** `testassigner@kptcl.com` / `admin123`

1. In the sidebar, click **"Test Result Approvals"**
2. The **Test Result Approvals** screen shows a list of requests in **`under_approval`** status
3. Each row shows: request number, title, tester name, submitted date, status badge
4. For each request there are two action buttons inline:
   - **"Reject"** (outlined, red) — opens rejection dialog
   - **"Approve"** (filled, blue) — opens approval confirmation

#### To Approve:
5. Click **"Approve"** on the row  
   → Confirmation dialog: *"Approve Test Results"*  
   → Click **"Approve"** in the dialog  
   → Toast: *"Approved successfully"*  
   → Status changes to **`approved`** (green)

#### To Reject:
5. Click **"Reject"** on the row  
   → Dialog: *"Reject Test Results"*  
   → Enter **rejection reason** in the text field (required)  
   → Click **"Reject"**  
   → Toast: *"Rejected successfully"*  
   → Status changes to **`rejected`** (red)

---

### Step 5 — Purchaser: Initiate Procurement

**Login:** `purchaser@kptcl.com` / `admin123`

1. In the sidebar, click **"Testing Requests"**
2. Go to the **All Active** tab; filter for **`approved`** status
3. Click the approved request row
4. In the detail panel, click **"Initiate Procurement"**  
   → Status: **`approved`** → **`procurement_initiated`** (light blue)
5. Once procurement is complete, click **"Mark Complete"**  
   → Status: **`procurement_initiated`** → **`completed`** (dark green)

---

## 5. Scenario 2 — Rejected Request (Rework)

**Trigger:** Test Assigner finds the submitted request is incomplete or incorrect.

### Test Assigner: Reject the Request

**Login:** `testassigner@kptcl.com` / `admin123`  
**Sidebar:** Testing Request Approvals

1. Open the pending request from the list
2. In the detail panel, click **"Reject Request"** button
3. A dialog *"Reject Request"* appears with a text field:
   - Enter a clear **rejection reason** (e.g., "Equipment serial number missing")
4. Click **"Reject"**  
   → Status: **`submitted`** → **`rejected`** (red)  
   → Originator is notified

### Originator: Edit & Re-submit

**Login:** `originator@kptcl.com` / `admin123`  
**Sidebar:** Testing Requests

1. In the **My Requests** tab, find the request with **`rejected`** badge (red)
2. Click the row to open the detail panel
3. Click **"Edit"** — the form re-opens with existing values pre-filled
4. Correct the identified issues
5. Click **"Re-submit"**  
   → Status: **`rejected`** → **`submitted`** (blue)  
   → Request re-enters the Test Assigner's approval queue

---

## 6. Scenario 3 — Rejected Test Results (Re-test)

**Trigger:** Test result approver finds submitted results are insufficient or incorrect.

### Approver: Reject Test Results

**Login:** `testassigner@kptcl.com` / `admin123`  
**Sidebar:** Test Result Approvals

1. Find the request in **`under_approval`** status
2. Click **"Reject"** on the row
3. Dialog *"Reject Test Results"* appears
4. Type the **rejection reason** (mandatory)
5. Click **"Reject"**  
   → Toast: *"Rejected successfully"*  
   → Status: **`under_approval`** → **`rejected`** (red)

### Field Tester: Re-test & Re-submit

**Login:** `fieldtester1@kptcl.com` / `Tester123!`  
**Sidebar:** Testing → **In Progress** tab

1. The request reappears in the **In Progress** tab with **`rejected`** badge
2. Click the row → detail panel shows the rejection reason
3. Click **"Add Test Results"** to enter corrected data
4. A template selection dialog may appear — select the correct template
5. Fill in corrected measurement values
6. Click **"Save & Submit"**  
   → Status: **`rejected`** → **`under_approval`** (purple)  
   → Returns to the approver's queue for re-review

---

## 7. Scenario 4 — Multi-Session Testing

Used for tests that span multiple days (e.g., 5-week transformer monitoring, daily load readings).

### Step 1 — Originator: Create Multi-Session Request

**Login:** `originator@kptcl.com` / `admin123`  
**Sidebar:** Testing Requests → **"+ New Request"**

1. Fill in the standard fields (title, equipment, test type, department)
2. Enable the **"Multi-Session"** toggle (appears in the form)
3. Set **Session Interval (Days)** — e.g., `7` for weekly sessions
4. Set **Scheduled Start Date**
5. Click **"Submit"**  
   → Status: **`submitted`**

### Step 2 — Test Assigner: Approve & Assign (same as Scenario 1, Step 2)

The multi-session flag is visible in the detail panel before assigning.

### Step 3 — Field Tester: Accept & Start

**Login:** `fieldtester1@kptcl.com` / `Tester123!`  
**Sidebar:** Testing

1. Find the request in **In Progress** tab (status: **`assigned`**)
2. Click **"Accept"** → **"Start Testing"**  
   → Status: **`in_progress`**

### Step 4 — Field Tester: Auto-Generate Sessions

1. With the request detail panel open, locate the **Sessions** section (below the request info)
2. Click **"Auto-Generate Sessions"** button (if sessions haven't been created)  
   → The system creates session slots based on the interval, each with a **Scheduled Date**

### Step 5 — Field Tester: Complete Each Session

For each session in the sessions list:

1. Click on the session row to expand it
2. Click **"Start Session"** button  
   → Session status: **`scheduled`** → **`in_progress`**
3. Fill in the session fields:
   - **Session Name** — e.g., "Week 1 Reading"
   - **Session Date** — actual date of test
   - **Weather Conditions** — e.g., Sunny, Rainy
   - **Environmental Factors** — e.g., Temperature 32°C
   - **Conducted By** — tester name
   - **Witnessed By** — witness/observer name
   - **Notes** — any observations for this session
4. Click **"Add Reading"** button (cyan icon, bottom of session panel)  
   → A reading form appears. Fill in:
   - Parameter name / measurement point
   - Value and unit
   - Pass / Fail indicator
   - Timestamp (auto-filled, can be edited)
   - Notes for this reading
5. Click **"Submit"** for the reading  
   → Reading shows green **"Submitted"** badge
6. Repeat **"Add Reading"** for all measurement points in this session
7. Click **"Complete Session"**  
   → Session status: **`in_progress`** → **`completed`** (green badge)

Repeat Steps 1–7 for every remaining session.

### Step 6 — Auto Status Transition

When **all sessions** are marked **`completed`**:
- The system automatically transitions the testing request to **`test_submitted`**
- Then immediately moves to **`under_approval`**
- **No manual "Submit Results" is needed**

### Step 7 — Approver: Review Sessions

**Sidebar:** Test Result Approvals

- The request appears in the approvals list
- Detail panel shows all sessions, readings, and session statistics
- Approve or Reject as normal

---

## 8. Scenario 5 — Scheduled / Recurring Tests

Used when the same equipment must be tested on a repeating schedule (e.g., monthly oil testing, quarterly inspections).

### Setup: Create a Recurring Schedule

**Login:** `testassigner@kptcl.com` / `admin123`  
**Sidebar:** Testing Requests

1. Open an existing testing request (can be any status)
2. In the detail panel, locate the **Schedule** section
3. Click **"Create Schedule"** / **"Set Config"** button
4. A configuration panel appears. Set:

   | Field | Options |
   |-------|---------|
   | **Frequency** | `daily` / `weekly` / `biweekly` / `monthly` / `quarterly` / `yearly` |
   | **Next Run Date** | Date of first auto-created recurrence |
   | **End Date** | (Optional) When the schedule expires |

5. Click **"Update Config"** / **"Save"**  
   → Schedule is active. A new testing request will auto-create at each interval.

### Managing a Schedule

All controls are in the **Schedule** section of the request detail panel:

| Button | Action |
|--------|--------|
| **Pause** | Temporarily stops the schedule (no new requests created) |
| **Resume** | Re-activates a paused schedule |
| **Delete** | Permanently removes the schedule |

### Viewing Schedule Logs

1. Click **"View Logs"** in the Schedule section  
   → A log list appears showing:
   - Date each request was auto-created
   - Request number generated
   - Success / Failure status

---

## 9. Scenario 6 — Recommendations & Recommendation Approvals

When a tester submits results, the system **auto-creates a Recommendation** based on the `overall_result` field set in the test result form.

### Recommendation Types

| Value set in form | Recommendation created |
|-------------------|----------------------|
| `pass` | Equipment passed — no action needed |
| `fail` | Equipment failed — replacement/repair required |
| `conditional` | Conditionally acceptable — limited use / monitor |
| `retest` | Results inconclusive — re-test required |

### Approver: Review & Approve Recommendation

**Login:** `depthead@kptcl.com` / `admin123`  
**Sidebar:** Approvals

1. The **Approvals** screen shows pending recommendations with stats:
   - Equipment name, request number, recommendation type badge, submitted date
2. Click a recommendation row → full detail panel opens showing:
   - Test summary (equipment, test type, tester, date)
   - All result entries (parameters, values, pass/fail per entry)
   - **Overall Result** badge
   - **Replacement Products** (if any were attached)
3. Two action buttons at the bottom:

   | Button | Action |
   |--------|--------|
   | **"Approve"** | Approves the recommendation |
   | **"Reject"** | Opens rejection dialog — enter reason — click "Reject" |

4. Click **"Approve"**  
   → Toast: *"Approved successfully"*  
   → Recommendation status: **`approved`**

### Viewing Approved Recommendations

**Login:** Any role with Recommendations access  
**Sidebar:** Recommendations

1. List of all recommendations (approved, pending, rejected)
2. Click a row to view:
   - Recommendation type and summary text
   - Linked testing request details
   - Replacement products list
   - Approver name and approval date

---

## 10. Scenario 7 — Image Attachments on Test Results

Testers can attach photo evidence (meter readings, site photos, damage documentation) to individual result entries.

### Upload Images

**Login:** `fieldtester1@kptcl.com` / `Tester123!`  
**Sidebar:** Testing → open request → **"Add Test Results"**

1. After filling result fields in the **Test Result Form**, locate the **Images** section
2. Click **"Upload Images"**
3. A file picker opens — select one or more images (JPG, PNG)
4. For each image, optionally enter a **caption** (e.g., "Meter at phase A")
5. Click **"Upload"**  
   → Thumbnails appear in the form panel
6. Continue to **"Save & Submit"** as normal

### View / Download Images

Approvers and all users with view permission can:

**Sidebar:** Test Result Approvals → open request → expand result entry

1. Image thumbnails appear under the result row
2. Click a thumbnail → full-size image opens in a lightbox
3. Click **"Download"** to save the image file

---

## 11. Scenario 8 — Replacement Products on Failure

When a test result is `fail` or `conditional`, the tester attaches recommended replacement products. These flow to the Purchaser for procurement.

### Tester: Attach Replacement Products

**Login:** `fieldtester1@kptcl.com` / `Tester123!`  
In the **Test Result Form**:

1. Set **Overall Result** to **`fail`** or **`conditional`**  
   → A **"Replacement Products"** section expands at the bottom of the form
2. Click **"Add Product"**
3. Fill in:
   - **Item Name** — e.g., "33kV Transformer 10MVA"
   - **Category** — e.g., "Transformers"
   - **Quantity** — e.g., `1`
4. Add more products as needed (click **"Add Product"** again)
5. Click **"Save & Submit"**

### Purchaser: View Replacement Products

**Login:** `purchaser@kptcl.com` / `admin123`  
**Sidebar:** Testing Requests → All Active tab → open an **`approved`** request

1. Detail panel shows a **Replacement Products** section listing all items
2. Navigate to **Request Quote** in the sidebar to raise a quotation:
   - Reference the testing request and failed equipment
   - Add the recommended replacement items to the quote request
   - Send to vendor for pricing

---

## 12. Scenario 9 — PDF Report Downloads

### Testing Request PDF

**Who:** Test Assigner, Dept Head  
**Where:** Testing Request Approvals → open any request → detail panel

1. In the top-right corner of the detail panel, click the **download icon** (tooltip: *"Download PDF"*)
2. Browser downloads a PDF containing:
   - Request details (number, title, equipment, department)
   - Submission and approval timeline
   - Tester assignment details

### Recommendation Report PDF

**Who:** Dept Head, Approver, Originator  
**Where:** Approvals → open a recommendation → detail panel

1. Click **"Download Report"** button in the panel
2. PDF contains:
   - Full test parameters and results table
   - Pass/Fail per parameter
   - Overall recommendation type
   - Replacement products list (if applicable)
   - Approver name and date

### Test Template Preview PDF

**Who:** Admin (Test Template Management)  
**Where:** Sidebar → Test Template Management → open a template

1. Click **"Preview"** button
2. The template renders as an HTML form in a new tab
3. Use browser print (`Ctrl+P`) → **"Save as PDF"** to download

---

## 13. Status & Badge Colour Reference

| Status | Badge Colour | Who Actions It | Meaning |
|--------|-------------|----------------|---------|
| `draft` | Grey | Originator | Created but not yet submitted |
| `submitted` | Blue | Test Assigner | Awaiting approval and tester assignment |
| `assigned` | Cyan | Field/Lab Tester | Tester has been assigned |
| `accepted` | Teal | Field/Lab Tester | Tester accepted the task |
| `scheduled` | Cyan | System | Test scheduled for future date |
| `in_progress` | Amber | Field/Lab Tester | Testing is actively underway |
| `test_submitted` | Orange | System / Approver | Results submitted by tester |
| `under_approval` | Purple | Result Approver | Awaiting result review |
| `approved` | Green | Purchaser | Results approved — ready for procurement |
| `rejected` | Red | Originator / Tester | Rejected — action required |
| `procurement_initiated` | Light Blue | Purchaser | Procurement process has started |
| `completed` | Dark Green | — | Fully complete |

---

*CogniWatt Procurement Portal — Testing Module*  
*Powered by PowerXchange.ai*
