# Cumulative Testing — End-to-End UI Test Guide

> **Scope:** Full walkthrough of the cumulative operations lifecycle from creating a
> test request through multi-session result submission, automatic overhaul ticket
> creation, and the complete 4-stage overhaul workflow.
>
> **Organisation:** KPTCL (seeded)  
> **Default overhaul threshold:** 5,000 operations (overridable per equipment)

---

## 1. Test Users (KPTCL Organisation)

| Role | Email | Password | Responsibility in this flow |
|---|---|---|---|
| **Asset Data Officer** | `originator@utility.com` | `admin123` | **Creates** test requests |
| **Reviewing Officer** | `ee.tlss@utility.com` | `admin123` | Approves request, assigns tester, approves stage results |
| **Supervisory Officer** | `see.wm@utility.com` | `admin123` | Alternate approver for test requests |
| **Test Engineer** | `testengineer1@utility.com` | `admin123` | Submits each test session result |
| **Transformer Repair Coordinator** | `wf.coordinator@utility.com` | `admin123` | Assigns users to overhaul stages |
| **Maintenance Officer** | `aee.maintenance@utility.com` | `admin123` | Executes OVERHAUL_EXECUTION + COMPLETION_UPLOAD |
| **Senior Management Approver** | `cee.zone@utility.com` | `admin123` | Final OFFICER_VERIFICATION sign-off |

> **Super Admin** (cross-org): `superadmin@system.com` / `Admin123!`

---

## 2. Pre-requisites

Before running this flow, confirm the following in the database:

1. **Equipment exists** with a UEIC (e.g., `EQ-KPTCL-001`)
2. **Cumulative test template** seeded — template key `operations_tracking`
   - Rule type: `CUMULATIVE_DIFF`
   - `default_threshold`: **5,000 operations**
3. **Overhaul workflow stages** seeded: OVERHAUL_TRIGGER → OVERHAUL_EXECUTION →
   COMPLETION_UPLOAD → OFFICER_VERIFICATION
4. **Stage role mappings** seeded for KPTCL org (`seed_overhaul_role_mappings`)

> **Shortcut to verify threshold:**  
> `GET /api/cumulative/equipment/{equipment_id}/threshold` — returns `{"threshold_value": 5000}`

---

## 3. Flow A — Positive Path (Threshold NOT crossed)

> **Scenario:** 3-session plan, each session adds ~1,000 ops.
> Total after all 3 sessions = ~3,000 ops — below 5,000 threshold.
> **Expected outcome:** No overhaul ticket.

---

### Step 1 — Create a Cumulative Test Request

**Login as:** `originator@utility.com` / `admin123` (Asset Data Officer)

1. Open the app → sidebar → **Testing Requests**
2. Tap **+ New Request**
3. Fill in the form:
   - **Equipment:** select `EQ-KPTCL-001`
   - **Test Type:** select `Operations Tracking` *(or whichever test has enable_cumulative = true)*
   - **Multi-Session switch:** observe it **auto-locks ON** with label
     *"Required for cumulative tracking — always on"* — cannot be turned off
   - **Number of Sessions:** `3`
   - **Session dates:** schedule 3 dates (e.g., Day 1, Day 8, Day 15)
4. Tap **Save as Draft** *(optional — saves with status `draft`)*
5. Tap **Submit Request** → status changes to `submitted`

**✅ Verify:**
- Request appears in Testing Requests list with status `submitted`
- Multi-session badge shows `3 sessions`
- `is_cumulative: true` in API response (`GET /api/testing-requests/{id}`)
- Request now appears in **Testing Request Approvals** queue (visible to Reviewing Officer)

---

### Step 2 — Approve and Assign Tester

**Login as:** `ee.tlss@utility.com` / `admin123` (Reviewing Officer)

1. Sidebar → **Testing Request Approvals** *(separate module from Testing Requests)*
2. The **Pending Approvals** list appears — find the new request (badge: `Pending Approval`)
3. Tap the request card → **Request Details** screen opens
4. Scroll down to the **Actions** section → tap **Approve & Assign Tester** (green button)
5. The **Approve & Assign Tester** dialog opens with two steps:
   - **Step 1 — Select Tester Role:** dropdown shows eligible roles (e.g. `Test Engineer (2 users)`)  
     → Select `Test Engineer`
   - **Step 2 — Select Tester:** list appears, sorted by workload (least active requests first)  
     → Select `testengineer1@utility.com` (Field Test Engineer)
   - **Comment (optional):** enter approval notes if needed
6. Tap **Confirm Assignment**

**✅ Verify:**
- Toast: *"Request approved and assigned successfully"*
- Request disappears from Pending Approvals list
- Status → `ASSIGNED`
- `testengineer1@utility.com` sees the request in their **Testing** assignments list

---

> **⚠️ Form note — cumulative sessions:**  
> The session form is driven by the `operations_tracking` template. It shows **only 3 fields**:
> `Operations Reading` (number), `Reading Date` (date), `Notes` (textarea).  
>
> **Per-session wizard behaviour:**
> - **Sessions 1 … N-1 (intermediate):** The Recommendation Wizard does **NOT appear**.
>   An amber info banner is shown instead: *"Recommendation will be available after all sessions are complete (N more session(s) remaining)."*
>   The cumulative engine tracks the reading silently.
> - **Session N (final):** The **Recommendation Wizard appears** below the image upload section.
>   The tester must select an outcome before submitting (see Step 5 below).

### Step 3 — Submit Session 1 Result (~1,000 ops)

**Login as:** `testengineer1@utility.com` / `admin123`

1. Sidebar → **Testing** (or open notification for assigned test)
2. Find the request → tap **Enter Results** for Session 1
3. The form shows **3 fields only** (no overall assessment):

   | Field | Label | Value to enter |
   |---|---|---|
   | `reading` | Operations Reading | `1000` |
   | `reading_date` | Reading Date | Day 1 date |
   | `notes` | Notes | `Session 1 — baseline reading` *(optional)* |

4. Tap **Save / Submit**

**✅ Verify:**
- Session 1 shows status `SUBMITTED`
- `GET /api/cumulative/equipment/{id}/lifecycle` returns:
  ```json
  { "cumulative_value": 1000, "threshold": 5000, "overhaul_triggered": false }
  ```
- **No overhaul workflow created** (cumulative 1,000 < 5,000)
- Session progress: `1 / 3 sessions completed`

---

### Step 4 — Submit Session 2 Result (~1,000 more ops)

**Login as:** `testengineer1@utility.com` / `admin123`

1. Same request → **Enter Results** for Session 2
2. Enter in the 3-field form:
   - **Operations Reading:** `2000` *(engine computes diff = 1,000)*
   - **Reading Date:** Day 8
3. Tap **Save / Submit**

**✅ Verify:**
- `cumulative_value`: `2000`, `overhaul_triggered`: `false`
- No overhaul ticket in **Overhaul Workflows** page

---

### Step 5 — Submit Session 3 Result (~1,000 more ops) — **Final session with Recommendation Wizard**

**Login as:** `testengineer1@utility.com` / `admin123`

1. Same request → **Enter Results** for Session 3
2. Enter in the 3-field section:
   - **Operations Reading:** `3000` *(diff = 1,000)*
   - **Reading Date:** Day 15

3. Scroll down — the **Recommendation Wizard** now appears (final session):

   | Wizard Step | Field | Value to select |
   |---|---|---|
   | Outcome | Recommendation Type | **Pass** |
   | Next Action | What happens next? | **None** *(no further work required)* |
   | Summary | Summary (optional) | Leave blank — auto-generated: *"Pass — no further action"* |

4. Tap **Save / Submit**

**✅ Verify:**
- `cumulative_value`: `3000`, `overhaul_triggered`: `false`
- Request status → `COMPLETED`
- **Overhaul Workflows page is empty** — no ticket created
- All 3 sessions show `SUBMITTED`
- API response body includes:
  ```json
  "recommendation": {
    "recommendation_type": "pass",
    "next_action": "none",
    "summary": "Pass — no further action"
  }
  ```

**Flow A complete — no overhaul triggered. ✅**

---

## 4. Flow B — Overhaul Path (Threshold Crossed)

> **Scenario:** 3-session plan, readings increase rapidly.
> Session 3 pushes cumulative value to **5,200 ops** — crosses 5,000 threshold.
> **Expected outcome:** Overhaul ticket auto-created immediately on Session 3 submit.

---

### Step 1 — Create a New Cumulative Test Request

**Login as:** `originator@utility.com` / `admin123` (Asset Data Officer)

1. Sidebar → **Testing Requests** → **+ New Request**
2. Fill:
   - **Equipment:** `EQ-KPTCL-001` *(same equipment — readings accumulate)*
   - **Test Type:** `Operations Tracking`
   - **Multi-Session:** auto-locked ON (cumulative)
   - **Number of Sessions:** `3`
3. Tap **Submit Request** → status: `submitted`

> **Note:** The cumulative engine sums readings **across all historical sessions**
> for this equipment. Sessions from Flow A (3,000 ops) are already counted.
> Threshold remaining: 5,000 − 3,000 = **2,000 ops to trigger overhaul**.

---

### Step 2 — Approve and Assign

**Login as:** `ee.tlss@utility.com` / `admin123` (Reviewing Officer)

1. Sidebar → **Testing Request Approvals**
2. Find the new request → tap to open **Request Details**
3. Tap **Approve & Assign Tester** → Step 1: select `Test Engineer` → Step 2: select `testengineer1@utility.com` → tap **Confirm Assignment**
4. Status → `ASSIGNED`

---

### Step 3 — Submit Session 1 (running total: 3,800) — intermediate

**Login as:** `testengineer1@utility.com` / `admin123`

1. **Enter Results** for Session 1 — **3-field form only** (amber banner: *"2 more sessions remaining"*):
   - **Operations Reading:** `3800` *(diff = 800 from 3,000)*
   - **Reading Date:** Day 1
2. Tap **Save / Submit**

**✅ Verify:**
- `cumulative_value`: 3,800 — still below 5,000
- Recommendation Wizard is **not shown** — amber info banner visible instead
- No overhaul ticket yet

---

### Step 4 — Submit Session 2 (running total: 4,600) — intermediate

**Login as:** `testengineer1@utility.com` / `admin123`

1. **Enter Results** for Session 2 — **3-field form only** (amber banner: *"1 more session remaining"*):
   - **Operations Reading:** `4600` *(diff = 800)*
   - **Reading Date:** Day 8
2. Tap **Save / Submit**

**✅ Verify:**
- `cumulative_value`: 4,600 — still below 5,000
- Recommendation Wizard still **not shown**
- No overhaul ticket yet

---

### Step 5 — Submit Session 3 (**OVERHAUL TRIGGERED** — running total: 5,200) — **Final session with Recommendation Wizard**

**Login as:** `testengineer1@utility.com` / `admin123`

1. **Enter Results** for Session 3 — **3-field form + Recommendation Wizard**:
   - **Operations Reading:** `5200` *(diff = 600 — pushes cumulative past 5,000)*
   - **Reading Date:** Day 15

2. Scroll down — the **Recommendation Wizard** appears:

   | Wizard Step | Field | Value to select |
   |---|---|---|
   | Outcome | Recommendation Type | **Fail** *(or Conditional)* |
   | Next Action | What happens next? | **Maintenance** *(overhaul required)* |
   | Summary | Summary (optional) | e.g. *"Cumulative threshold exceeded — overhaul initiated"* |

3. Tap **Save / Submit**

**✅ Verify — immediately after submit:**
- API response includes both `evaluation_result` and `recommendation`:
  ```json
  "evaluation_result": {
    "cumulative_lifecycle": {
      "cumulative_value": 5200,
      "threshold": 5000,
      "overhaul_triggered": true,
      "workflow_id": "<uuid>",
      "workflow_number": "OVH-20260516-0001"
    }
  },
  "recommendation": {
    "id": "<uuid>",
    "recommendation_type": "fail",
    "next_action": "maintenance",
    "summary": "Cumulative threshold exceeded — overhaul initiated"
  }
  ```
- A banner or notification appears: *"Overhaul workflow auto-created"*
- **Overhaul Workflows page** shows a new ticket:
  - Workflow number: `OVH-YYYYMMDD-XXXX`
  - Status: `ACTIVE`
  - Stage: `Overhaul Triggered`
  - Source: *"Auto-triggered — ops threshold exceeded"*
  - Orange accent colour throughout

---

## 5. Overhaul Workflow — 4-Stage Execution

### Stage 1: OVERHAUL_TRIGGER — Reviewing Officer Reviews

**Login as:** `ee.tlss@utility.com` / `admin123`  
**Role:** Reviewing Officer

1. Sidebar → **Overhaul Workflows**
2. Find ticket `OVH-YYYYMMDD-XXXX` (status: `ACTIVE`, stage: `Overhaul Triggered`)
3. Bottom sheet opens automatically — observe:
   - **Orange overhaul context banner** showing workflow number, source, triggered date
   - Stage: `Overhaul Triggered` — status `PENDING` (awaiting coordinator assignment)
   - Progress: `0%`

> **Assignment pending first** — coordinator must assign before Reviewing Officer can act.

**Switch to Coordinator:**

**Login as:** `wf.coordinator@utility.com` / `admin123`  
**Role:** Transformer Repair Coordinator

1. Sidebar → **Overhaul Workflows**
2. Open `OVH-YYYYMMDD-XXXX`
3. Observe **"ASSIGN"** badge on the ticket card
4. Inside the sheet → action: **Assign** → select `ee.tlss@utility.com` (Reviewing Officer)
5. Confirm assignment

**Back to Reviewing Officer:**

**Login as:** `ee.tlss@utility.com` / `admin123`

1. Open the overhaul ticket
2. Stage `Overhaul Triggered` now shows `ASSIGNED`
3. Fill in the **Stage Form** — section: *Overhaul Trigger Summary*:

   | Field | Label | Type | Notes |
   |---|---|---|---|
   | `cumulative_value` | Cumulative Operations Count | Number | **Read-only** — auto-filled from lifecycle engine |
   | `threshold_value` | Configured Threshold | Number | **Read-only** — auto-filled (e.g. 5000) |
   | `triggered_at` | Triggered At | Date | **Read-only** — timestamp of auto-trigger |
   | `trigger_remarks` | Remarks | Textarea | Optional — enter review comments here |

   > The three read-only fields are pre-populated automatically. Only `Remarks` requires input.

4. Enter remarks (e.g. *"Cumulative ops crossed 5,000 — overhaul warranted"*)
5. Tap **Save Stage Form**
6. Tap **Submit for Review** → add remarks → confirm

**✅ Verify:**
- Stage status: `SUBMITTED`
- Progress: `25%`

**Reviewing Officer approves their own submission (or a second Reviewing Officer):**

1. Tap **Approve** → enter remarks → confirm

**✅ Verify:**
- Stage `Overhaul Triggered` → `COMPLETED`
- Workflow advances to Stage 2: `Overhaul Execution`
- Progress: `25%` → continues

---

### Stage 2: OVERHAUL_EXECUTION — Maintenance Officer / Test Engineer

**Login as:** `wf.coordinator@utility.com` / `admin123`

1. Open the ticket → Stage `Overhaul Execution` shows `PENDING`
2. **Assign** → select `aee.maintenance@utility.com` (Maintenance Officer)

**Login as:** `aee.maintenance@utility.com` / `admin123`  
**Role:** Maintenance Officer

1. Sidebar → **Overhaul Workflows** → open ticket
2. Stage `Overhaul Execution` → status `ASSIGNED`
3. Fill Stage Form:
   - Work started date
   - Scope of overhaul (winding replacement / core inspection / etc.)
   - Assigned team
4. **Save Stage Form**
5. **Submit for Review**

**Login as:** `ee.tlss@utility.com` / `admin123` (Reviewing Officer — approver)

1. Open ticket → Stage `Overhaul Execution` → status `SUBMITTED`
2. Tap **Approve** → confirm

**✅ Verify:**
- Stage `Overhaul Execution` → `COMPLETED`
- Advances to Stage 3: `Completion Record Upload`
- Progress: `50%`

---

### Stage 3: COMPLETION_UPLOAD — Test Engineer Uploads Records

**Login as:** `wf.coordinator@utility.com` / `admin123`

1. Open ticket → assign `testengineer1@utility.com` to `Completion Record Upload`

**Login as:** `testengineer1@utility.com` / `admin123`  
**Role:** Test Engineer

1. Sidebar → **Overhaul Workflows** → open ticket
2. Stage `Completion Record Upload` → status `ASSIGNED`
3. Fill Stage Form:
   - Upload completion certificate (PDF)
   - Upload final test report
   - Completion date
   - Observations
4. **Save Stage Form** → **Submit for Review**

**Login as:** `ee.tlss@utility.com` / `admin123` (Reviewing Officer)

1. Review uploaded documents
2. Tap **Approve** → confirm

**✅ Verify:**
- Stage `Completion Record Upload` → `COMPLETED`
- Advances to Stage 4: `Officer Verification`
- Progress: `75%`

---

### Stage 4: OFFICER_VERIFICATION — Senior Management Final Sign-off

**Login as:** `wf.coordinator@utility.com` / `admin123`

1. Open ticket → assign `cee.zone@utility.com` (Senior Management Approver)

**Login as:** `cee.zone@utility.com` / `admin123`  
**Role:** Senior Management Approver

1. Sidebar → **Overhaul Workflows** → open ticket
2. Stage `Officer Verification` → status `ASSIGNED`
3. Fill Stage Form:
   - Final verification remarks
   - Sign-off date
   - Equipment cleared for return to service: `Yes`
4. **Save Stage Form** → **Submit for Review**

**Login as:** `ee.tlss@utility.com` / `admin123` (Reviewing Officer — also an approver here)

1. Review submission
2. Tap **Approve** → enter remarks → confirm

**✅ Verify (final state):**
- Stage `Officer Verification` → `COMPLETED`
- **Workflow status: `COMPLETED`**
- Progress: `100%`
- All 4 stages show green `COMPLETED` badges
- `OverhaulRecommendation` record: status → `CLOSED`
- **Overhaul Workflows page** shows ticket with `DONE` filter active

---

## 6. Rejection Path (OFFICER_VERIFICATION → COMPLETION_UPLOAD)

If the Senior Management Approver rejects at Stage 4:

**Login as:** `cee.zone@utility.com` / `admin123`  
After Stage 3 completion:
1. Open `Officer Verification` stage
2. Tap **Reject** → enter reason (mandatory) → confirm

**✅ Verify:**
- Stage `Officer Verification` → `REJECTED`
- Workflow **rolls back** to Stage 3: `Completion Record Upload`
- Stage 3 resets to `PENDING` (re-assignment required)
- Coordinator must re-assign and Test Engineer must re-upload

This is the configured `reject` transition:  
`OFFICER_VERIFICATION → (reject) → COMPLETION_UPLOAD`

---

## 7. Idempotency Check

The overhaul trigger is **idempotent** — if somehow `evaluate_overhaul_trigger` is
called again for the same equipment after the ticket already exists, no second ticket
is created.

**To verify:**
1. After Flow B completes, submit another test session with a higher reading
2. `GET /api/overhaul/workflows?equipment_id={id}` — should return only **1** overhaul workflow
3. The `_open_recommendation()` guard returns the existing `OPEN` recommendation instead of creating a new one

---

## 8. API Spot-Checks

| What to check | Endpoint |
|---|---|
| Cumulative lifecycle state | `GET /api/cumulative/equipment/{id}/lifecycle` |
| Equipment-specific threshold | `GET /api/cumulative/equipment/{id}/threshold` |
| Set a custom threshold | `PUT /api/cumulative/equipment/{id}/threshold` `{"threshold": 3000}` |
| List overhaul workflows | `GET /api/repair-workflows?workflow_type=OVERHAUL` |
| Overhaul recommendations | `GET /api/overhaul/recommendations?equipment_id={id}` |
| Stage role mappings | `GET /api/repair-workflows/{id}/stages` |
| Equipment test types (for wizard) | `GET /api/equipment/{id}` → field `types_by_category.{test,maintenance,inspection}` |
| Saved recommendation for a request | `GET /api/recommendations?testing_request_id={id}` |

> **`submit_results` enriched response** (`PUT /api/testing/{id}/submit_results`):  
> The response now includes a top-level `"recommendation"` key alongside the request data:
> ```json
> {
>   "id": "...", "status": "under_approval", ...,
>   "recommendation": {
>     "id": "<uuid>",
>     "recommendation_type": "pass | fail | conditional | retest",
>     "next_action": "none | test | maintenance | inspection | repair_cycle | replacement",
>     "schedule_frequency": "daily | weekly | biweekly | monthly | quarterly | semi_annual | yearly | triennial | null",
>     "test_types": [...],
>     "summary": "auto-generated if left blank",
>     "notes": "...",
>     "replacement_products": [...]
>   }
> }
> ```
> If `next_action` is `"replacement"` but no replacement products are provided, the API returns `400`.

---

## 9. Quick Reference — Cumulative Logic

```
CUMULATIVE_DIFF rule:
  reads all TestResult rows for this equipment ordered by reading_date
  computes: Σ max(reading[i] - reading[i-1], 0)  for all sessions
  (resets to 0 on drop — protects against meter replacement)

Trigger condition:
  cumulative >= threshold  AND  no OPEN OverhaulRecommendation exists
  → create RepairWorkflow (OVERHAUL) + OverhaulRecommendation

Default threshold: 5,000 operations
Custom threshold:  set via EquipmentOverhaulConfig (per equipment)
```

---

## 10. Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Multi-session switch is unlocked in edit mode for cumulative/calibration drafts | Edit mode populates `_selectedTest` from equipment model which lacks `enable_cumulative`/`enable_calibration` flags | **Fix in progress** — will read `is_cumulative`/`is_calibration` from the draft response and OR into the getters |
| Recommendation Wizard not shown on Session 3 | `totalSessionsPlanned` or `completedSessions` not passed from `TestingDetail` | Ensure `_getSessionCounts(ctx)` is called at the time `onEnterResults` fires and the counts are forwarded to `TestResultForm` |
| Wizard shown on intermediate session | `completedSessions` count is wrong (e.g. counting `in_progress` as completed) | `_getSessionCounts` counts only sessions with `status == 'completed'` — verify session provider has loaded sessions before the form opens |
| `400: replacement product required` on wizard submit | `Next Action` set to **Procurement** but no product selected in the wizard | Add at least one replacement product in the wizard's Replacement Products section before submitting |
| Overhaul ticket not created after threshold crossed | `seed_overhaul_stages` not run | Run seed or check `RepairWorkflowDefinition` for `OVERHAUL` |
| Stage role warnings during seed | `seed_overhaul_role_mappings` ran before `seed_overhaul_stages` | Fixed in seed.py — role mapping now runs after stages |
| `FK violation: module_id not in modules` during seed | Stale module IDs in `permissions_template` from partial run | Fixed: `_valid_module_ids` guard added at all 3 org-provisioning sites |
| Coordinator cannot see overhaul ticket | `Overhaul Workflows` module not in their role permissions | Re-run seed — `Transformer Repair Coordinator` now has `_readwrite(overhaul_workflows_module)` |
| `originator@utility.com` cannot create test request | Existing KPTCL org role has stale permissions from old seed run | Fixed: permission sync step added to `seed_kptcl_organization` — re-run seed |
