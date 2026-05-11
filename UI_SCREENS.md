# CogniWatt Customer Portal — UI & Test Reference

---

## 1. Login Credentials

### Department Users (password: `TestDept@123`)

All 10 roles exist for **each** of the 3 departments. Email pattern: `{role}.{dept}@kptcl.com`

| Role | Email prefix | North | South | Mysuru | OrgRole |
|---|---|---|---|---|---|
| Org Admin | `orgadmin` | `orgadmin.north@kptcl.com` | `orgadmin.south@kptcl.com` | `orgadmin.mysuru@kptcl.com` | `Org Admin` |
| Dept Head | `depthead` | `depthead.north@kptcl.com` | `depthead.south@kptcl.com` | `depthead.mysuru@kptcl.com` | `Dept Head` |
| Originator | `originator` | `originator.north@kptcl.com` | `originator.south@kptcl.com` | `originator.mysuru@kptcl.com` | `Originator` |
| Tester | `tester` | `tester.north@kptcl.com` | `tester.south@kptcl.com` | `tester.mysuru@kptcl.com` | `Tester` |
| Test Assigner | `assigner` | `assigner.north@kptcl.com` | `assigner.south@kptcl.com` | `assigner.mysuru@kptcl.com` | `Test Assigner` |
| Technical Approver | `techapprover` | `techapprover.north@kptcl.com` | `techapprover.south@kptcl.com` | `techapprover.mysuru@kptcl.com` | `Technical Approver` |
| Finance Approver | `financeapprover` | `financeapprover.north@kptcl.com` | `financeapprover.south@kptcl.com` | `financeapprover.mysuru@kptcl.com` | `Finance Approver` |
| EE TLSS | `eetlss` | `eetlss.north@kptcl.com` | `eetlss.south@kptcl.com` | `eetlss.mysuru@kptcl.com` | `EE TLSS` |
| TA&QC Officer | `taqc` | `taqc.north@kptcl.com` | `taqc.south@kptcl.com` | `taqc.mysuru@kptcl.com` | `TA&QC Officer` |
| Section Head | `sectionhead` | `sectionhead.north@kptcl.com` | `sectionhead.south@kptcl.com` | `sectionhead.mysuru@kptcl.com` | `Section Head` |

> **30 users total** — 10 roles × 3 departments. Seeded by `seed_dept_filter_users()` in `seed.py`.
>
> **Repair workflow UI test logins**:
> - `eetlss.north@kptcl.com` / `TestDept@123` — EE TLSS user, should see `Repair Workflows`
> - `eetlss.south@kptcl.com` / `TestDept@123` — EE TLSS user, should see `Repair Workflows`
> - `eetlss.mysuru@kptcl.com` / `TestDept@123` — EE TLSS user, should see `Repair Workflows`
> - `orgadmin.north@kptcl.com` / `TestDept@123` — Org Admin user, full org-wide menu scope
> - `assigner.north@kptcl.com` / `TestDept@123` — Test Assigner, should see `Approvals` and assignment queues
> - `financeapprover.north@kptcl.com` / `TestDept@123` — Finance Approver, should see `Procurement Approvals`

### Hierarchy Users (password: `TestDept@123`)

| Email | Role | Scope |
|---|---|---|
| `ee.circle@kptcl.com` | EE Circle | Sees all leaf divisions under circle |
| `see.circle@kptcl.com` | SEE Circle | Sees all leaf divisions under circle |
| `cee.zone@kptcl.com` | CEE Zone | Sees full subtree under zone |
| `see.zone@kptcl.com` | SEE Zone | Sees full subtree under zone |

### Platform / KPTCL Admins (password: `admin123`)

| Email | Role Key | Scope |
|---|---|---|
| `orgadmin@kptcl.com` | KptclAdmin | All organizations |
| `originator@kptcl.com` | KptclOriginator | All organizations |

---

## 2. Portal Modules

> Menu items shown depend on: DB `modules` table (`is_menu = true`) + RBAC `can_view` permission for the logged-in user.

### ASSETS

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `equipment` | Equipment Register | OrgAdmin, EE TLSS, KptclAdmin | View and manage electrical equipment inventory per department |

### CONDITION MONITORING

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `testing` | Test Schedules | Tester, OrgAdmin, EE TLSS | View and manage scheduled testing requests assigned to testers |
| `testing_requests` | Testing Requests | Originator, OrgAdmin, EE TLSS | Raise and track equipment testing requests |
| `test_result_approvals` | Test Results | TechApprover, OrgAdmin | Review submitted test results and approve/reject recommendations |
| `recommendations` | Recommendations | TechApprover, OrgAdmin, EE TLSS | View generated recommendations for tested equipment |

### GOVERNANCE

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `approvals` | Approvals | TestAssigner, OrgAdmin | Approve or reassign incoming testing requests before scheduling |
| `testing_request_approvals` | TR Approvals | TechApprover, EE TLSS | Second-level approval of testing requests |
| `ee_tlss_dashboard` | EE Dashboard | EE TLSS, OrgAdmin | Executive dashboard summarising testing KPIs per department/zone |

### FIELD OPERATIONS

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `failure_registry` | Failure Registry (ER) | Originator, EE TLSS | Log and track equipment failure incidents; 6 next_action outcomes; 2-pass approval before tester assignment |
| `taqc_inspections` | TA&QC Inspections | TAQC Officer, OrgAdmin | Submit and view quality-control inspection records |
| `procurement_approvals` | Procurement Approvals | FinanceApprover, OrgAdmin | Review and approve procurement requests linked to field work |
| `repair-workflows` | Repair Workflows | EE TLSS, OrgAdmin | Track multi-stage repair workflow progress for failed equipment |

### OUTPUT

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `notifications` | Alerts | All authenticated | System notifications and status change alerts |
| `reports` | Reports | All authenticated | Download PDF reports (recommendations, test results, summaries) |

### ORGANIZATION *(users with an organisation only)*

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `organizations` | Organizations | OrgAdmin, KptclAdmin | Manage organisation profiles and department structure |
| `org_user_roles` | User Roles | OrgAdmin | Assign roles to users within the organisation |
| `org_role_permissions` | Role Permissions | OrgAdmin | Configure which modules each org-level role can access |
| `tester_mapping` | Tester Mapping | OrgAdmin | Map testers to equipment categories and departments |
| `test_templates` | Test Templates | OrgAdmin, EE TLSS | Manage test parameter templates used during testing |

### SYSTEM ADMIN *(platform super-admins only — no org)*

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `roles` | Roles | SuperAdmin | Define system-wide roles |
| `modules` | Modules | SuperAdmin | Enable/disable portal modules and control menu visibility |
| `role_module_privileges` | Role Permissions | SuperAdmin | Assign CRUD permissions per role per module |
| `user_roles` | User Roles | SuperAdmin | Assign system roles to individual user accounts |

### ZOHO / CUSTOMER PORTAL

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `validation_requests` | Validation Requests | FinanceApprover, OrgAdmin | Formal validation requests raised via Customer Portal |

---

## 3. Testing Scenarios

### Section 1 — Authentication

| Scenario | Login | Expected |
|---|---|---|
| Valid login — all 10 roles, North dept | `*.north@kptcl.com` / `TestDept@123` | 200 + `access_token` |
| Valid login — all 10 roles, South dept | `*.south@kptcl.com` / `TestDept@123` | 200 + `access_token` |
| Valid login — all 10 roles, Mysuru dept | `*.mysuru@kptcl.com` / `TestDept@123` | 200 + `access_token` |
| Valid login — KPTCL admins | `orgadmin@kptcl.com` / `admin123` | 200 + `access_token` |
| Wrong password | `orgadmin.north@kptcl.com` / `wrong` | 401 |
| Non-existent user | `nobody@kptcl.com` | 401 / 404 |

> **30 logins verified** in one loop (10 roles × 3 depts). North tokens stored as `TOKENS["RoleKey"]`; all dept tokens available as `TOKENS["RoleKey_North"]` / `TOKENS["RoleKey_South"]` / `TOKENS["RoleKey_Mysuru"]`.

---

### Section 7 — Testing Request Lifecycle

**TR Categories**: `test` · `maintenance` · `inspection` · `repair_lifecycle`

| Step | Action | Who | Status Transition |
|---|---|---|---|
| 7a | Create TR | Originator | → `draft` |
| 7d | Submit TR | Originator | → `submitted` |
| 8 | Assign tester | TestAssigner / KptclAdmin | → `assigned` |
| 9a | Accept | Tester | → `accepted` |
| 9b | Start | Tester | → `in_progress` |
| 9c | Post structured test data | Tester | (same status, test data saved) |
| 9d | Submit results | Tester | → `under_approval` |
| 9e | Approve results | TechApprover / KptclAdmin | → `approved` |

> **`submit_results` body**: `{ "recommendation_type": "pass" | "fail" | "conditional" | "retest", "summary": "..." }`

---

### Section 9 — Submit / Approve / Reject Results

| Scenario | Who | Action | Expected |
|---|---|---|---|
| Submit results (pass) | Tester | `PUT /testing/{id}/submit_results` | 200 → `under_approval` |
| Approve results | TechApprover | `PUT /testing/{id}/approve_results` | 200 → `approved` |
| Reject results | TechApprover | `PUT /testing/{id}/reject_results` | 200 → `rejected` |
| Tester decline | Tester | `PUT /testing/{id}/decline` | 200 → back to `submitted` |

---

## Repair Workflow Stage Access Matrix

The Repair Workflow module contains a 10-stage lifecycle.

Each stage exposes different UI actions depending on the logged-in user's role and transition permissions.

---

## Repair Workflow Roles

| Login | Expected Access |
|---|---|
| `eetlss.north@kptcl.com` | Full workflow management access |
| `orgadmin.north@kptcl.com` | Full org-wide workflow visibility |
| `assigner.north@kptcl.com` | Assignment queue + assignment actions |
| `financeapprover.north@kptcl.com` | Approval-only access for finance stages |
| `techapprover.north@kptcl.com` | Technical approval stages |
| `tester.north@kptcl.com` | Assigned execution stages only |
| `originator.north@kptcl.com` | Workflow initiation + tracking |
| `taqc.north@kptcl.com` | TAQC inspection stages |
| `sectionhead.north@kptcl.com` | Review visibility depending on stage |
| `depthead.north@kptcl.com` | Department-level workflow visibility |

---

# 10-Stage Repair Workflow UI Lifecycle

| Stage No | Stage Name | Primary Role | Expected UI Actions |
|---|---|---|---|
| 1 | Failure Assessment | Originator / EE TLSS | Create workflow, save assessment |
| 2 | Initial Review | Section Head | Review notes, approve/reject |
| 3 | Technical Inspection | Tester / Inspector | Submit inspection findings |
| 4 | Repair Estimation | EE TLSS | Upload estimate, submit |
| 5 | Technical Approval | Tech Approver | Approve/reject estimate |
| 6 | Procurement Review | Finance Approver | Approve procurement-related stages |
| 7 | Repair Execution | Assigned Engineer | Submit execution updates |
| 8 | QA / TAQC Inspection | TAQC Officer | Inspection submission |
| 9 | Final Approval | Dept Head / EE TLSS | Final approve/reject |
| 10 | Workflow Closure | Org Admin / EE TLSS | Close workflow |

---

# Stage-Based UI Behavior

## Stage 1 — Failure Assessment

### Visible To

- Originator
- EE TLSS
- OrgAdmin

### Expected UI

- Dynamic form fields
- Save draft
- Submit stage
- Equipment details visible

---

## Stage 2 — Initial Review

### Visible To

- Section Head
- EE TLSS
- OrgAdmin

### Expected UI

- Review comments
- Approve button
- Reject button
- Timeline visibility

---

## Stage 3 — Technical Inspection

### Visible To

- Tester
- Assigned inspector

### Expected UI

- Upload reports
- Save inspection data
- Submit for approval

---

## Stage 4 — Repair Estimation

### Visible To

- EE TLSS
- Assigned engineer

### Expected UI

- Estimate form
- File uploads
- Cost fields
- Submit action

---

## Stage 5 — Technical Approval

### Visible To

- Technical Approver
- OrgAdmin

### Expected UI

- Approve button
- Reject button
- Estimate review panel

---

## Stage 6 — Procurement Review

### Visible To

- Finance Approver
- OrgAdmin

### Expected UI

- Approval-only actions
- Procurement review notes
- Financial attachments

---

## Stage 7 — Repair Execution

### Visible To

- Assigned engineer
- EE TLSS

### Expected UI

- Work progress updates
- Execution notes
- Upload completion evidence

---

## Stage 8 — QA / TAQC Inspection

### Visible To

- TAQC Officer
- OrgAdmin

### Expected UI

- QA inspection form
- Inspection checklist
- Submit findings

---

## Stage 9 — Final Approval

### Visible To

- Dept Head
- EE TLSS
- OrgAdmin

### Expected UI

- Final review summary
- Approve/reject actions
- Timeline audit visibility

---

## Stage 10 — Workflow Closure

### Visible To

- OrgAdmin
- EE TLSS

### Expected UI

- Read-only workflow summary
- Completion status
- Final timeline
- Close workflow action

---

# Assignment Queue UI

## Visible To

| Login | Expected |
|---|---|
| `assigner.north@kptcl.com` | Sees pending assignment queue |
| `eetlss.north@kptcl.com` | Can manually assign stages |
| `orgadmin.north@kptcl.com` | Full assignment visibility |

---

## Assignment Queue Behaviors

| Scenario | Expected |
|---|---|
| Pending assignment exists | ASSIGN badge visible |
| Tap Assign | Assignment dialog opens |
| Assignment success | Workflow refreshes |
| Assigned stage | Badge disappears |

---

# Approval-Only UI Behavior

| Login | Expected UI |
|---|---|
| `financeapprover.north@kptcl.com` | Only Approve/Reject visible |
| `techapprover.north@kptcl.com` | Technical approval actions only |

These users must NOT see:

- Submit button
- Assignment controls
- Edit form actions

---

# Workflow Detail Screen Validation

Every stage detail screen should show:

- workflow number
- equipment UEIC
- current stage
- status badge
- dynamic actions
- timeline history
- performer names
- stage notes
- timestamps

---

# Timeline Validation

Timeline must include:

| Action | Example |
|---|---|
| assign | User assigned |
| submit | Stage submitted |
| approve | Stage approved |
| reject | Stage rejected |
| upload | Document uploaded |
| cancel | Workflow cancelled |

Each timeline entry should show:

- stage name
- performer name
- note
- timestamp

---

### Section 19 — Failure Registry (ER — Equipment Register)

**Module**: `failure_registry`  
**Who**: `originator.north@kptcl.com` · `originator.south@kptcl.com` · `originator.mysuru@kptcl.com`  
**Template key**: `failure_registry` (fetched from `GET /testing/templates/by-key/failure_registry`)

#### 19a — Submission

| Step | API | Notes |
|---|---|---|
| Submit | `POST /direct-submissions/` | `request_category: "failure_registry"`, `template_key: "failure_registry"` |
| List | `GET /direct-submissions/?category=failure_registry` | Dept-scoped — each originator sees only their dept |
| Get single | `GET /direct-submissions/{id}` | Own dept only |
| Attach file | `POST /direct-submissions/{id}/attach` | Binary file upload |
| Download file | `GET /direct-submissions/{id}/attachment` | Binary stream download |
| Dept isolation | North originator must NOT see South/Mysuru records | Verified across all 3 depts |

**Sample payload** (fields match the `failure_registry` template):
```json
{
  "request_category": "failure_registry",
  "template_key": "failure_registry",
  "title": "FR Test - NORTH dept - Power Transformer",
  "equipment_id": "<pt_equip_id>",
  "overall_result": "fail",
  "remarks": "Automated FR test",
  "priority": "high",
  "test_data": {
    "failure_date": "2026-05-01",
    "failure_category": "Electrical",
    "failure_description": "Insulation breakdown at north substation",
    "root_cause_analysis": "Overload and moisture ingress",
    "outage_duration_hours": "4",
    "affected_consumers": "250",
    "outage_impact": "Supply interrupted to residential sector",
    "outcome": "Under investigation"
  }
}
```

**Initial status**: `submitted` → goes to **Test Assigner** queue for `initial_approve`  
**No Recommendation created** at submission — Recommendation is created only after the child TR tester submits results.

---

#### 19b — FR 2-Pass Approval (Test Assigner)

FR approval uses a **2-pass model** before a tester can begin work.

##### Pass 1 — Initial Approve (creates child TR)

| Step | API | Notes |
|---|---|---|
| Initial approve | `POST /testing-requests/approvals/{fr_id}/initial-approve` | FR must be `submitted`; creates a child TR |
| Response | `{ child_tr_id, child_tr_number, ... }` | `child_tr_id` returned directly; TR number starts with `TR-` |
| FR status after | `approved` | FR is locked; child TR is `submitted` |
| Double approve | `POST .../initial-approve` again | → 400 Bad Request |
| Non-FR request | `POST .../initial-approve` on a regular TR | → 400 Bad Request |
| Non-existent FR | `POST .../initial-approve` on fake UUID | → 404 Not Found |
| No auth | `POST .../initial-approve` without token | → 401 |

##### Pass 2 — Approve and Assign Tester

| Step | API | Notes |
|---|---|---|
| Get tester roles | `GET /testing-requests/approvals/{child_tr_id}/tester-roles` | Returns eligible roles for the child TR's org |
| Get users by role | `GET /testing-requests/approvals/{child_tr_id}/tester-roles/{role_id}/users` | Returns users with `active_requests` workload |
| Assign tester | `POST /testing-requests/approvals/{child_tr_id}/approve-and-assign` | Body: `{ tester_id, tester_role_id, comment }` |
| Child TR status after | `assigned` | Ready for tester lifecycle |

```json
// approve-and-assign body
{
  "tester_id":      "<user_uuid>",
  "tester_role_id": "<role_uuid>",
  "comment":        "Assigned for FR investigation"
}
```

##### FR Rejection

| Step | API | Notes |
|---|---|---|
| Reject | `POST /testing-requests/approvals/{fr_id}/reject` | Body: `{ "rejection_comment": "reason" }` |
| FR status after | `rejected` | Terminal state |
| Empty comment | `rejection_comment: ""` | → 400 Bad Request |
| Missing field | No `rejection_comment` key | → 422 Unprocessable |
| Reject approved FR | Reject after Pass-1 | → 400 Bad Request |

---

#### 19c — Tester Lifecycle on Child TR

After Pass-2 assign, the child TR follows the standard tester flow:

| Step | API | Status |
|---|---|---|
| Accept | `PUT /testing/{child_tr_id}/accept` | → `accepted` |
| Start | `PUT /testing/{child_tr_id}/start` | → `in_progress` |
| Upload structured results | `POST /testing/{child_tr_id}/results/structured` | Saves `test_data` including `next_action` selection |
| Submit results | `PUT /testing/{child_tr_id}/submit_results` | → `under_review` → recommendation created |

**`submit_results` body for FR child TR:**
```json
{
  "recommendation_type": "fail",
  "summary": "Critical insulation failure — replacement required",
  "next_action": "maintenance",
  "schedule_frequency": "monthly"
}
```

---

#### 19d — `next_action` Options (Tester Selects in Form)

The test result form (`overall_assessment` template) shows a `next_action` dropdown with 6 options. The tester selects one and optionally fills the `outcome_schedule` picker.

| Display Label | Enum Value | Schedule Required | Approver Dialog |
|---|---|---|---|
| `Test` | `test` | No | No — direct approve |
| `Procurement` | `replacement` | No | No — direct approve |
| `Repair` | `repair_cycle` | Yes (dates/frequency) | ✅ Schedule confirm dialog |
| `Inspection` | `inspection` | Yes (dates/frequency) | ✅ Schedule confirm dialog |
| `Maintenance` | `maintenance` | Yes (dates/frequency) | ✅ Schedule confirm dialog |
| `None` | `none` | No | No — direct approve |

> **Backward compat**: Old label `"Repair Lifecycle"` in saved drafts is automatically normalised to `"Repair"` when the form loads.

---

#### 19e — Recommendation Approval & Outcome Dispatch

After the tester submits results, the TechApprover approves the recommendation.  
For **Maintenance / Inspection / Repair**, the approver first sees a **schedule confirmation dialog** pre-filled with the tester's chosen dates and frequency — they can confirm or modify before approving.

**Approve API:**
```
PUT /approvals/{rec_id}/approve
```

**Body (direct approve — Test / Procurement / None):**
```json
{ "notes": "Approved via portal" }
```

**Body (schedule-required — Maintenance / Inspection / Repair):**
```json
{
  "notes": "Approved via portal",
  "schedule_start_date": "2026-06-01T00:00:00Z",
  "schedule_end_date":   "2027-06-01T00:00:00Z",
  "schedule_frequency":  "monthly"
}
```
> `schedule_start_date` / `schedule_end_date` / `schedule_frequency` are optional overrides. If omitted, the tester's original values are used.

**Outcome dispatch table:**

| `next_action` | Child TR Status After | Created Artifact |
|---|---|---|
| `test` | `outcome_active` | New follow-up `TR-` test request (`status=submitted`) |
| `replacement` | `finance_pending` | `PR-` Procurement Request → Finance Approver queue |
| `repair_cycle` | `outcome_active` | Repair Workflow (10-stage, `RL-` prefix) |
| `inspection` | `outcome_active` | `IN-` Inspection Schedule (recurring) |
| `maintenance` | `outcome_active` | `MN-` Maintenance Schedule (recurring) |
| `none` | `closed` | No artifact — FR investigation closed |

> **Schedule ticket timing**: For `inspection` and `maintenance`, the first actual ticket is created only when `start_date ≤ advance_days` away (configurable, default 15 days). The schedule record is always created immediately.

---

#### 19f — FR Approver Schedule Dialog (Flutter UI)

When an approver taps **Approve** on an FR recommendation with `next_action` in `{maintenance, inspection, repair_cycle}`:

1. `TestRequestScheduleDialog` opens in `captureMode: true`
2. Pre-filled with the tester's values:
   - Start date → `testing_request.scheduled_start_date`
   - End date → `testing_request.due_date`
   - Frequency → `recommendation.schedule_frequency`
3. Approver can modify or confirm
4. **Cancel** → approval aborted; FR stays `under_approval`
5. **Confirm** → `schedule_start_date`, `schedule_end_date`, `schedule_frequency` sent in approve body

For `next_action` in `{test, replacement, none}` — dialog is skipped; approve fires directly.

---

#### 19g — FR Regression Test Coverage (`tests/test_fr_regression.py`)

52 tests across 7 classes — run with:
```
pytest tests/test_fr_regression.py -v
```

| Class | Tests | What is covered |
|---|---|---|
| `TestFRSubmission` | 8 | Create, list, get, pagination, equipment link, priority, rich test_data |
| `TestFRAttachment` | 5 | Upload text, upload PDF, download, missing attachment 404, fake FR 404 |
| `TestFRPass1` | 7 | initial-approve success, child TR created, FR→approved, double-approve 400, fake 404, non-FR 400, no-auth 401 |
| `TestFRPass2` | 6 | approve-and-assign, fake request 404, invalid tester 404/400, no-auth 401, tester-roles list, users-by-role |
| `TestFRRejection` | 6 | Reject success, status→rejected, empty comment 400, reject-after-approve 400, fake 404, missing field 422 |
| `TestFROutcomes` | 6 | Full lifecycle for all 6 next_actions: test/procurement/repair/inspection/maintenance/none |
| `TestFRNegative` | 14 | Auth (401), validation (422), wrong category (400/422), double-approve (400), nonexistent rec (404) |

**Outcome assertions:**

| Outcome | Asserted |
|---|---|
| `test` | `next_action=test`, `status=outcome_active`, `created` starts with `TR-` |
| `procurement` | `next_action=replacement`, `status=finance_pending`, `created` starts with `PR-` |
| `repair` | `next_action=repair_cycle`, `status=outcome_active` |
| `inspection` | `next_action=inspection`, `status=outcome_active`, `created` starts with `IN-` |
| `maintenance` | `next_action=maintenance`, `status=outcome_active`, `created` starts with `MN-` |
| `none` | `next_action=none`, `status` in `{closed, outcome_active}` |

---

### Section 20 — TA&QC Inspections

**Module**: `taqc_inspections`  
**Who**: `taqc.north@kptcl.com` · `taqc.south@kptcl.com` · `taqc.mysuru@kptcl.com`  
**Template key**: `taqc_inspection` (fetched from `GET /testing/templates/by-key/taqc_inspection`)

| Step | API | Notes |
|---|---|---|
| Submit | `POST /direct-submissions/` | `request_category: "taqc_inspection"`, `template_key: "taqc_inspection"` |
| List | `GET /direct-submissions/?category=taqc_inspection` | Dept-scoped — each TAQC officer sees only their dept |
| Get single | `GET /direct-submissions/{id}` | Own dept only |
| Dept isolation | TAQC north must NOT see South/Mysuru inspection records | Verified across all 3 depts |

**Sample payload** (fields match the `taqc_inspection` template):
```json
{
  "request_category": "taqc_inspection",
  "template_key": "taqc_inspection",
  "title": "TAQC Inspection - NORTH - Power Transformer",
  "equipment_id": "<pt_equip_id>",
  "overall_result": "advisory",
  "remarks": "Automated TAQC test",
  "priority": "normal",
  "test_data": {
    "substation": "North Grid Substation",
    "inspection_date": "2026-05-06",
    "inspection_category": "Electrical Safety",
    "observation_description": "Routine inspection — all parameters nominal.",
    "severity": "Minor",
    "target_compliance_date": "2026-06-01"
  }
}
```

**Initial status**: `under_approval` → goes directly to **TechApprover** queue (no tester assignment step).  
**Recommendation** is auto-created on submission (unlike FR).

---

### What happens after FR / TA&QC submission

FR and TAQC have **different flows** after submission:

---

#### Failure Registry (FR / ER — Equipment Register)

```
POST /direct-submissions/   →  FR TestingRequest (status=submitted)
                                          ↓
                           ┌─── PASS 1 (Test Assigner) ─────────────────────────┐
                           │  POST /testing-requests/approvals/{fr_id}/          │
                           │       initial-approve                               │
                           │  → FR status = approved                             │
                           │  → Child TR created (TR-prefix, status=submitted)   │
                           │  Response includes child_tr_id + child_tr_number    │
                           └─────────────────────────────────────────────────────┘
                                          ↓
                           ┌─── PASS 2 (Test Assigner) ─────────────────────────┐
                           │  GET  /testing-requests/approvals/{child_tr_id}/    │
                           │       tester-roles                                  │
                           │  GET  .../tester-roles/{role_id}/users              │
                           │  POST /testing-requests/approvals/{child_tr_id}/    │
                           │       approve-and-assign                            │
                           │  → Child TR status = assigned                       │
                           └─────────────────────────────────────────────────────┘
                                          ↓
                           Tester: accept → start → upload structured result
                                          ↓
                           Tester selects next_action:
                             Test | Procurement | Repair | Inspection | Maintenance | None
                                          ↓
                           PUT /testing/{child_tr_id}/submit_results
                           → Recommendation created (approval_status=pending)
                                          ↓
                           ┌─── TechApprover ────────────────────────────────────┐
                           │  For Maintenance / Inspection / Repair:              │
                           │    → Schedule dialog shown (pre-filled, modifiable)  │
                           │    → Approve body includes schedule_start/end/freq   │
                           │  For Test / Procurement / None:                      │
                           │    → Direct approve (no dialog)                      │
                           │  PUT /approvals/{rec_id}/approve                     │
                           └─────────────────────────────────────────────────────┘
                                          ↓
                           WorkflowDispatch → outcome artifact:
                             test        →  New TR-  (follow-up test, submitted)
                             replacement →  PR-  (Procurement Request, finance_pending)
                             repair_cycle→  RL-  (Repair Workflow, 10-stage)
                             inspection  →  IN-  (Inspection Schedule, recurring)
                             maintenance →  MN-  (Maintenance Schedule, recurring)
                             none        →  FR closed
```

> FR submission creates only `TestingRequest` + `TestResult`. No Recommendation yet.  
> Recommendation is created by the **tester** when they call `submit_results` on the child TR.

---

#### TA&QC Inspection (TAQC)

```
POST /direct-submissions/   →  TestingRequest (status=under_approval)
                            +  TestResult (test_data saved)
                            +  Recommendation (approval_status=pending)
                                    ↓
                           TechApprover: approve_results
                           PUT /approvals/{rec_id}/approve  (with next_action)
```

**After TechApprover approval — `next_action` determines outcome:**

| `next_action` | TR Status | Created | Approver Dialog |
|---|---|---|---|
| `none` | `commissioned` | Equipment record + MN schedule + IN schedule | No |
| `test` | `outcome_active` | New `TR-` follow-up test request | No |
| `maintenance` | `outcome_active` | `MN-` `TestRequestSchedule` (recurring) | ✅ Schedule dialog |
| `inspection` | `outcome_active` | `IN-` `TestRequestSchedule` (recurring) | ✅ Schedule dialog |
| `repair_cycle` | `outcome_active` | `RL-` `RepairWorkflow` (10-stage) | ✅ Schedule dialog |
| `replacement` | `finance_pending` | `PR-` `ProcurementRequest` → Finance Approver queue | No |

> `none` on TAQC = **commissioning** — Equipment auto-created from E&C form data, MN + IN maintenance schedules auto-created.  
> For FR child TR outcomes, `none` = `closed` (no commissioning step).

---

#### `overall_result` → Recommendation type mapping

| `overall_result` | Recommendation type |
|---|---|
| `"fail"` *(FR default)* | `fail` |
| `"advisory"` *(TAQC default)* | `conditional` |
| `"pass"` | `pass` |
| `"retest"` | `retest` |
| `"conditional_pass"` | `conditional` |

---

#### Approval APIs (TechApprover / OrgAdmin)

| Action | API | Notes |
|---|---|---|
| View pending | `GET /approvals/pending` | Sees the FR or TAQC record |
| Approve | `PUT /approvals/{rec_id}/approve` | Triggers WorkflowDispatch |
| Reject | `PUT /approvals/{rec_id}/reject` | → `rejected` |

---

#### Additional Status Values (new)

| Status | When |
|---|---|
| `commissioned` | TAQC approved with `next_action=none` → equipment commissioned |
| `closed` | Non-TAQC TR approved with `next_action=none` → terminal state |
| `outcome_active` | Approved with maintenance/inspection/repair_cycle |
| `finance_pending` | Approved with replacement → awaiting Finance |

---

### Tester Resubmit (under_review → accepted)

When a TechApprover sends results back for revision (`under_review`), the tester can resubmit:

| Action | API | Notes |
|---|---|---|
| Resubmit | `PUT /testing/{id}/resubmit` | Status must be `under_review`; only assigned tester can call |
| Result | → `accepted` | Moves TR back to accepted so tester can update and re-submit |

---

### Section 12 — Validation Requests (Procurement)

| Scenario | Who | API | Expected |
|---|---|---|---|
| List | FinanceApprover | `GET /validation_requests/` | 200 |
| Finance approve | FinanceApprover | `PUT /validation_requests/{id}/finance-approve` | 200 |
| Finance reject | FinanceApprover | `PUT /validation_requests/{id}/finance-reject` | 200 |
| Tester tries to finance-approve | Tester | `PUT /validation_requests/{id}/finance-approve` | 403 |

---

### Section 16 — Department Filter Isolation

| Check | Expected |
|---|---|
| North originator does NOT see South TRs | ✅ No overlap |
| Mysuru originator does NOT see South TRs | ✅ No overlap |
| OrgAdmin sees TRs from ALL departments | ✅ Union of all dept IDs |

---

### Section 16b — Hierarchy Filter (Circle / Zone)

| Check | Login | Expected |
|---|---|---|
| Circle user sees all leaf division TRs | `ee.circle@kptcl.com` | Sees North + South + Mysuru |
| Zone user sees all divisions under zone | `cee.zone@kptcl.com` | Sees everything circle sees |

---

## 4. Department Structure & Filter Impact on UI

### KPTCL Department Hierarchy

```
KPTCL (organisation)
└── Bangalore Zone          (BLR_ZONE)      ← cee.zone / see.zone
    └── Bangalore Transmission Circle  (BLR_CIRCLE)  ← ee.circle / see.circle
        ├── RT North Division  (RT_NORTH)   ← *.north@kptcl.com
        ├── RT South Division  (RT_SOUTH)   ← *.south@kptcl.com
        └── Mysuru Division    (MYSURU)     ← *.mysuru@kptcl.com
```

Each leaf division has **identical** role coverage — 10 users, same OrgRoles, same permissions.

---

### What "dept filter" means on each UI screen

Every list endpoint (`GET /testing_requests/`, `GET /direct-submissions/`, `GET /equipment`, etc.) applies a **department scope** based on the logged-in user's `department_id` and their role's `scope` setting.

| Scope | Applied to | What the user sees |
|---|---|---|
| `exact` | Leaf-level users (*.north / .south / .mysuru) | **Only** records belonging to their own department |
| `department_tree` | Circle-level users (ee.circle, see.circle) | Records from **all divisions** under the circle (North + South + Mysuru) |
| `zone` | Zone-level users (cee.zone, see.zone) | Records from **all circles and divisions** under the zone |
| `organization` | Org Admins (orgadmin.*) | **All** records across the entire KPTCL organisation |

---

### Per-module dept-filter behaviour

#### Testing Requests list (`/testing_requests/`)

| Who logs in | Records shown |
|---|---|
| `originator.north` | Only TRs from RT North Division |
| `originator.south` | Only TRs from RT South Division |
| `originator.mysuru` | Only TRs from Mysuru Division |
| `assigner.north` | Only TRs needing assignment in North |
| `techapprover.north` | Only pending approvals for North TRs |
| `ee.circle` | TRs from all 3 leaf divisions |
| `cee.zone` | TRs from all divisions under zone |
| `orgadmin.north` | All KPTCL TRs (org-wide, despite being in North dept) |

> The Flutter list screen filters by `department_id` scoped to the user's hierarchy. A `tester.south` user who logs in will never see a North TR in any list, grid, or search result.

---

#### Failure Registry (`/direct-submissions/?category=failure_registry`)

| Who logs in | Records shown |
|---|---|
| `originator.north` | Only FR submissions from North |
| `originator.south` | Only FR submissions from South |
| `originator.mysuru` | Only FR submissions from Mysuru |
| `techapprover.north` | Only FR approvals in North (under_approval queue) |
| `orgadmin.*` | All FR submissions org-wide |

> Dept isolation verified in test §19: after submitting one FR per dept, each originator's list returns **only** their own dept's records with zero cross-dept overlap.

---

#### TA&QC Inspections (`/direct-submissions/?category=taqc_inspection`)

| Who logs in | Records shown |
|---|---|
| `taqc.north` | Only TAQC inspections from North |
| `taqc.south` | Only TAQC inspections from South |
| `taqc.mysuru` | Only TAQC inspections from Mysuru |
| `techapprover.north` | Pending TAQC approvals for North only |
| `ee.circle` | Inspections across all 3 divisions |

> Dept isolation verified in test §20: `taqc.north` list must NOT contain South or Mysuru inspection IDs.

---

#### Equipment Register (`/equipment`)

| Who logs in | Equipment shown |
|---|---|
| `eetlss.north` | Equipment in RT North Division |
| `eetlss.south` | Equipment in RT South Division |
| `eetlss.mysuru` | Equipment in Mysuru Division |
| `orgadmin.*` | All equipment across KPTCL |

---

### Flutter UI rendering rules driven by dept filter

1. **Login → Dashboard**: The default landing module (`default_module_id` on the OrgRole) is the same for the same role across all 3 depts. `tester.south` and `tester.north` both land on `aee_dashboard`.

2. **List screens refresh**: When the user pulls-to-refresh or navigates back, the API re-applies the dept filter. A user cannot see another dept's data by sharing a link or ID — the server validates `department_id` ownership.

3. **Equipment dropdown / search**: When an Originator or Tester searches for equipment (e.g., inside a Testing Request form), only equipment belonging to their `department_id` (or subtree) is returned. `originator.south` cannot accidentally link a North piece of equipment.

4. **Approvals queue**: `techapprover.north`'s pending list shows only North TRs/FRs/TAQCs. `techapprover.south` and `techapprover.mysuru` each see only their own dept's queue — no shared queue.

5. **Notifications**: System notifications (new TR submitted, approval pending, etc.) are scoped to the recipient's dept. A South tester does not receive a push for a North TR assignment.

---

### Cross-dept isolation test matrix

| North user | South user | Mysuru user | Expected |
|---|---|---|---|
| sees North TRs | sees South TRs | sees Mysuru TRs | ✅ dept-exact scope |
| does NOT see South TRs | does NOT see North TRs | does NOT see South TRs | ✅ no cross-dept leak |
| `orgadmin.north` sees all | `orgadmin.south` sees all | `orgadmin.mysuru` sees all | ✅ org-admin overrides dept |
| `ee.circle` sees all 3 | `ee.circle` sees all 3 | `ee.circle` sees all 3 | ✅ circle hierarchy scope |

---

### Section 17 — RBAC Negative Tests

| Scenario | Who | Expected |
|---|---|---|
| Tester tries to finance-approve | Tester | 403 / 401 |
| SectionHead tries to assign tester | SectionHead | 403 / 401 |
| Unauthenticated GET `/testing_requests/` | No token | 401 / 403 |

---

### Section 21 — Adhoc Full Lifecycle (4 TR Types × 3 Depts)

Runs the full TR lifecycle for every combination:

| TR Categories | Departments |
|---|---|
| `test`, `maintenance`, `inspection`, `repair_lifecycle` | `north`, `south`, `mysuru` |

Each combination goes through: **Create → Submit → Assign → Accept → Start → Submit Results → Approve Results**

---

### Section 21c — Reject Path

| Step | Notes |
|---|---|
| Create TR (north / test) | Reject-path TR |
| Submit → Assign → Accept → Start | Standard lifecycle |
| Submit results with `"recommendation_type": "fail"` | → `under_approval` |
| TechApprover rejects | `PUT /testing/{id}/reject_results` → `rejected` |
| Separate TR: Tester decline path | `PUT /testing/{id}/decline` → back to `submitted` |

---

### Section 24 — Schedule (Power Transformer × 4 TR Categories)

Tests the `TestRequestSchedule` CRUD for all four TR categories applied to a Power Transformer equipment.

**Who**: `KptclAdmin` (schedule CRUD), `Originator.north` (create TR)  
**Equipment**: Power Transformer (PT), RT North Division

| Step | API | Payload | Notes |
|---|---|---|---|
| Create TR | `POST /testing_requests/` | `request_category: test \| inspection \| maintenance \| repair_lifecycle` | One TR per category |
| Submit TR | `PUT /testing_requests/{id}/submit` | — | → `submitted` |
| Create schedule | `POST /testing_requests/{id}/schedule/` | `{"frequency":"yearly","advance_days":7}` | → 201, `is_active=true` |
| Get schedule | `GET /testing_requests/{id}/schedule/` | — | Returns schedule with `next_run_date` |
| Update schedule | `PUT /testing_requests/{id}/schedule/` | `{"frequency":"quarterly","advance_days":14}` | Frequency changed |
| Pause | `PATCH /testing_requests/{id}/schedule/pause` | — | `is_active=false` |
| Resume | `PATCH /testing_requests/{id}/schedule/resume` | — | `is_active=true` |
| Get logs | `GET /testing_requests/{id}/schedule/logs` | — | Auto-generation history |

**Schedule frequencies**: `yearly` · `half_yearly` · `quarterly` · `monthly`

**Categories covered**: `test` · `inspection` · `maintenance` · `repair_lifecycle`

> Auto-dispatch also creates MN/IN schedules when a TAQC or FR TR is approved with `next_action=maintenance` or `next_action=inspection` — those use the `WorkflowDispatch` path, not this CRUD endpoint.

---

### Section 25 — Multi-Session (Power Transformer, test category)

Tests the multi-session testing workflow: create sessions, record readings per session, complete and get statistics.

**Who**: `Tester.north` (sessions + readings), `Originator.north` (TR), `TestAssigner.north` (assign)  
**Equipment**: Power Transformer (PT), RT North Division  
**TR Category**: `test`

| Step | API | Notes |
|---|---|---|
| Create TR | `POST /testing_requests/` | `request_category: test` |
| Submit → Assign → Accept → Start | Standard lifecycle | TR status → `in_progress` |
| Create session 1 | `POST /testing_requests/{id}/sessions/` | `session_number:1, session_date: today` |
| Create session 2 | `POST /testing_requests/{id}/sessions/` | `session_number:2, session_date: today+1` |
| Create session 3 | `POST /testing_requests/{id}/sessions/` | `session_number:3, session_date: today+2` |
| List sessions | `GET /testing_requests/{id}/sessions/` | Returns all 3 sessions |
| Start session 1 | `POST /testing_requests/{id}/sessions/{sid}/start` | Status → `in_progress` |
| Add reading 1 | `POST /testing_requests/{id}/sessions/{sid}/readings` | `reading_data: {insulation_resistance_mohm, temperature_c, humidity_percent}` |
| Add reading 2 | `POST /testing_requests/{id}/sessions/{sid}/readings` | Second measurement |
| List readings | `GET /testing_requests/{id}/sessions/{sid}/readings` | Returns 2 readings |
| Session statistics | `GET /testing_requests/{id}/sessions/{sid}/statistics` | `reading_count`, pass/fail, duration |
| Complete session 1 | `POST /testing_requests/{id}/sessions/{sid}/complete` | Status → `completed` |
| Auto-generate | `POST /testing_requests/{id}/sessions/auto-generate` | Creates remaining sessions if `total_sessions_planned` is set |

**Session reading payload example**:
```json
{
  "reading_number": 1,
  "reading_time": "2026-05-07T10:00:00Z",
  "reading_data": {
    "insulation_resistance_mohm": 550,
    "temperature_c": 28,
    "humidity_percent": 60
  },
  "result_status": "pass",
  "remarks": "Reading 1 — normal"
}
```
