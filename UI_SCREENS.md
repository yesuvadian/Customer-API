# CogniWatt Customer Portal — UI & Screen Reference

> **Scope**: Every Flutter screen, provider, form flow, and status badge used in the portal.  
> Updated to reflect all modules including Lifecycle Monitoring, Annual Audit, Repair Workflow, and Failure Registry.

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
> **Key UI test logins**:
> - `orgadmin.north@kptcl.com` / `TestDept@123` — full org-wide menu, all screens visible
> - `originator.north@kptcl.com` / `TestDept@123` — create TRs, FRs; dept-scoped lists
> - `tester.north@kptcl.com` / `TestDept@123` — accept/start/submit results; multi-session forms
> - `assigner.north@kptcl.com` / `TestDept@123` — assignment queue + approve FR Pass-1 + Pass-2
> - `techapprover.north@kptcl.com` / `TestDept@123` — approve test results, recommendations
> - `financeapprover.north@kptcl.com` / `TestDept@123` — procurement approval queue
> - `eetlss.north@kptcl.com` / `TestDept@123` — repair workflows, escalation, EE dashboard
> - `taqc.north@kptcl.com` / `TestDept@123` — TA&QC inspections, annual audit

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
| `testing` | Test Schedules | Tester, OrgAdmin, EE TLSS | Scheduled testing requests assigned to testers |
| `testing_requests` | Testing Requests | Originator, OrgAdmin, EE TLSS | Raise and track equipment testing requests |
| `test_result_approvals` | Test Results | TechApprover, OrgAdmin | Review submitted test results and approve/reject |
| `recommendations` | Recommendations | TechApprover, OrgAdmin, EE TLSS | Generated recommendations for tested equipment |

### GOVERNANCE

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `approvals` | Approvals | TestAssigner, OrgAdmin | Approve or reassign incoming testing requests |
| `testing_request_approvals` | TR Approvals | TechApprover, EE TLSS | Second-level approval of testing requests |
| `ee_tlss_dashboard` | EE Dashboard | EE TLSS, OrgAdmin | Executive dashboard — testing KPIs per department/zone |

### FIELD OPERATIONS

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `failure_registry` | Failure Registry (ER) | Originator, EE TLSS | Log and track equipment failure incidents |
| `taqc_inspections` | TA&QC Inspections | TAQC Officer, OrgAdmin | Submit and view quality-control inspection records |
| `procurement_approvals` | Procurement Approvals | FinanceApprover, OrgAdmin | Review and approve procurement requests |
| `repair-workflows` | Repair Workflows | EE TLSS, OrgAdmin | 10-stage repair workflow for failed equipment |

### LIFECYCLE MONITORING *(new)*

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `calibration` | Calibration Status | Tester, OrgAdmin, EE TLSS | Per-equipment calibration lifecycle state (NORMAL / DUE / OVERDUE / NOT_CALIBRATED) |
| `cumulative` | Cumulative Counts | Tester, OrgAdmin, EE TLSS | Per-equipment cumulative operation count vs threshold |

### ANNUAL AUDIT *(new)*

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `annual_audits` | Annual Audits | TAQC Officer, OrgAdmin | Annual substation inspection — observation lifecycle |
| `annualAuditQueue` | Audit Queue | TAQC Officer, OrgAdmin, EE TLSS | Assignment queue for pending observations |

### OUTPUT

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `notifications` | Alerts | All authenticated | System notifications and status change alerts |
| `reports` | Reports | All authenticated | Download PDF reports (recommendations, test results, summaries) |

### ORGANIZATION

| Module Path | Menu Label | Roles | Purpose |
|---|---|---|---|
| `organizations` | Organizations | OrgAdmin, KptclAdmin | Manage organisation profiles and department structure |
| `org_user_roles` | User Roles | OrgAdmin | Assign roles to users within the organisation |
| `org_role_permissions` | Role Permissions | OrgAdmin | Configure which modules each org-level role can access |
| `tester_mapping` | Tester Mapping | OrgAdmin | Map testers to equipment categories and departments |
| `test_templates` | Test Templates | OrgAdmin, EE TLSS | Manage test parameter templates used during testing |

---

## 3. Flutter Screen Map

### Provider → Screen Wiring

| Provider | File | Screens that use it |
|---|---|---|
| `TestingRequestProvider` | `lib/providers/testing_request_provider.dart` | Testing Requests list, Create TR form, TR Detail |
| `TestResultProvider` | `lib/providers/test_result_provider.dart` | Test result form, structured results |
| `ApprovalProvider` | `lib/providers/approval_provider.dart` | Approvals queue, Recommendation Detail |
| `RepairWorkflowProvider` | `lib/providers/repair_workflow_provider.dart` | Repair workflow list, detail, assignment queue |
| `DirectSubmissionProvider` | `lib/providers/direct_submission_provider.dart` | FR list/submit, TAQC list/submit |
| `EquipmentProvider` | `lib/providers/equipment_provider.dart` | Equipment register, equipment search dropdowns |
| `CalibrationProvider` | `lib/providers/calibration_provider.dart` | Calibration status screen |
| `CumulativeProvider` | `lib/providers/cumulative_provider.dart` | Cumulative count screen |
| `AnnualAuditProvider` | `lib/providers/annual_audit_provider.dart` | Annual audit list, detail, assignment queue |
| `NotificationProvider` | `lib/providers/notification_provider.dart` | Alerts screen, badge count |

---

### Screen File Reference

| Screen ID | Flutter File | Module |
|---|---|---|
| TR-1 | `lib/pages/zoho/testing_requests_page.dart` | Testing Requests list |
| TR-2 | `lib/pages/zoho/create_testing_request_form.dart` | Create / Edit TR form |
| TR-3 | `lib/pages/zoho/testing_request_detail_page.dart` | TR Detail + lifecycle buttons |
| TR-4 | `lib/pages/zoho/test_result_form.dart` | Structured test result entry |
| TR-5 | `lib/pages/zoho/test_sessions_panel.dart` | Multi-session sessions list & entry |
| TR-6 | `lib/pages/zoho/approval_detail_page.dart` | Recommendation approval detail |
| TR-7 | `lib/pages/zoho/testing_request_schedule_dialog.dart` | Schedule date/frequency picker dialog |
| ER-1..12 | `lib/pages/zoho/failure_registry_*.dart` | Failure Registry (all FR screens) |
| RW-1..10 | `lib/pages/zoho/repair_workflow_*.dart` | Repair Workflow lifecycle screens |
| CAL-1 | `lib/pages/zoho/calibration_status_page.dart` | Calibration lifecycle per equipment |
| CUM-1 | `lib/pages/zoho/cumulative_status_page.dart` | Cumulative count per equipment |
| AUD-1 | `lib/pages/zoho/annual_audit_page.dart` | Annual Audit list + dashboard strip |
| AUD-2 | `lib/pages/zoho/annual_audit_detail_page.dart` | Observation detail + stage actions |
| AUD-3 | `lib/pages/zoho/annual_audit_assignment_queue_page.dart` | Audit assignment queue |

---

## 4. Testing Request (TR) Screens

### TR-1 — Testing Requests List

**File**: `lib/pages/zoho/testing_requests_page.dart`  
**Visible to**: Originator, EE TLSS, OrgAdmin  
**Provider**: `TestingRequestProvider`

#### What is displayed
| Element | Value |
|---|---|
| Screen title | **Testing Requests** |
| List cards | One card per TR |
| Card fields | TR number (`TR-YYYYMMDD-XXXX`) · Test type · Equipment UEIC · Status badge · Category chip · Created date |
| Empty state | "No testing requests found" + FAB |
| Pull-to-refresh | Re-fetches from API with dept filter |

#### Status badge colours
| Status | Colour |
|---|---|
| `draft` | Grey |
| `submitted` | Blue |
| `assigned` | Amber |
| `accepted` | Light Green |
| `in_progress` | Orange |
| `under_approval` | Purple |
| `approved` | Green |
| `rejected` | Red |
| `outcome_active` | Teal |
| `finance_pending` | Indigo |
| `closed` | Grey-dark |

#### Category chips
| Category | Display |
|---|---|
| `test` | Test |
| `maintenance` | Maintenance |
| `inspection` | Inspection |
| `repair_lifecycle` | Repair |
| `failure_registry` | Failure Registry |
| `taqc_inspection` | TA&QC |

#### Actions
| Role | Actions |
|---|---|
| Originator | + FAB → Create new TR |
| Any | Tap card → TR-3 Detail |

---

### TR-2 — Create Testing Request Form

**File**: `lib/pages/zoho/create_testing_request_form.dart`  
**Visible to**: Originator, OrgAdmin  
**Provider**: `TestingRequestProvider`

#### User scenarios — Create mode

**Scenario 1 — Standard test type (e.g. Transformer Oil Test)**
1. Originator logs in as `originator.north@kptcl.com`
2. Taps **+** FAB on TR-1 → TR-2 form opens
3. Selects Equipment → selects Category `Testing` → selects test type `Transformer Oil Test`
4. Multi-session section appears with a toggle switch (default OFF)
5. User can freely turn multi-session ON or OFF
6. Fills in Priority, Due Date, Description → taps **Create**
7. Snackbar: "TR-XXXX created" → returns to TR-1 list

**Scenario 2 — Cumulative test type (Circuit Breaker Operations Count)**
1. Originator selects Category `Testing` → selects `Circuit Breaker Operations Count`
2. Multi-session switch **automatically turns ON** and is **greyed out** (not togglable)
3. Label beneath the switch reads: *"Required for cumulative tracking — always on"*
4. User can still change Number of Sessions and Days Between Sessions
5. Taps **Create** → TR is created with `is_multi_session=true` and `is_cumulative=true` stamped by the server

**Scenario 3 — Calibration test type (Protection Relay Calibration)**
1. Originator selects Category `Testing` → selects `Protection Relay Calibration and History`
2. Multi-session switch **automatically turns ON** and is **greyed out**
3. Label reads: *"Required for calibration lifecycle — always on"*
4. Taps **Create** → TR is created with `is_multi_session=true` and `is_calibration=true` stamped by the server

**Scenario 4 — Repair Lifecycle category**
1. Originator selects Category `Repair`
2. The multi-session section is **not shown at all**
3. The repair workflow's own stage engine manages all data capture — no generic sessions apply

---

#### User scenarios — Edit mode (reopening a saved draft)

**Scenario 5 — Reopening a cumulative draft**
1. Originator taps a `draft` TR that was created with `Circuit Breaker Operations Count`
2. Form reopens; multi-session switch is **still locked ON** and shows *"Required for cumulative tracking — always on"*
3. User cannot toggle it off

**Scenario 6 — Reopening a calibration draft**
1. Originator taps a `draft` TR created with `Protection Relay Calibration and History`
2. Multi-session switch is **locked ON**, label reads *"Required for calibration lifecycle — always on"*
3. No way to accidentally disable multi-session

**Scenario 7 — Reopening a standard multi-session draft**
1. Originator taps a `draft` TR created with a normal test type and multi-session ON
2. Switch is ON but freely togglable — user can turn it off if needed

---

#### Form fields reference

| Field | Type | Required |
|---|---|---|
| Equipment | Searchable dropdown | Yes (if registered equipment known) |
| Category | Dropdown (`Testing` · `Maintenance` · `Inspection` · `Repair`) | Yes |
| Test Type | Dropdown (filtered by equipment + category) | Yes |
| Priority | Dropdown (`Normal` · `High` · `Critical`) | Yes |
| Scheduled Date | Date picker | No |
| Due Date | Date picker | Yes (required to submit) |
| Description | Multi-line text | No |
| Multi-session toggle | Switch — freely togglable for standard types; locked ON for cumulative/calibration; hidden for repair | — |
| Number of Sessions | Stepper (min 1) | When multi-session ON |
| Days Between Sessions | Stepper (min 1) | When multi-session ON |

#### Buttons
| Button | Behaviour |
|---|---|
| **Save Draft** | Saves without validation — only title required |
| **Submit** | Full validation (due date required) → TR moves to `submitted` |
| **Cancel** | Discards changes, returns to TR-1 |

---

### TR-3 — Testing Request Detail

**File**: `lib/pages/zoho/testing_request_detail_page.dart`  
**Visible to**: All roles (dept-scoped)  
**Provider**: `TestingRequestProvider`

#### Sections displayed
| Section | Content |
|---|---|
| **Header** | TR number · Status badge · Category chip · Equipment UEIC |
| **Details** | Test type · Description · Priority · Scheduled date · Due date |
| **Assignment** | Assigned tester name + role (after assign) |
| **Sessions Panel** | Visible if `is_multi_session=true` — links to TR-5 |
| **Test Result** | Summary of submitted structured results |
| **Recommendation** | Result + next_action + schedule info (after submit) |
| **Timeline** | Status history list |

#### Status-gated action buttons

| Status | Role | Buttons |
|---|---|---|
| `draft` | Originator | **Submit** |
| `submitted` | TestAssigner | **Assign Tester** |
| `assigned` | Tester | **Accept** · **Decline** |
| `accepted` | Tester | **Start Testing** |
| `in_progress` | Tester | **Enter Results** (→ TR-4) · **Submit Results** |
| `under_approval` | TechApprover | **Approve** · **Reject** |
| `under_review` | Tester | **Resubmit** |

---

### TR-4 — Test Result Form (Dynamic Template)

**File**: `lib/pages/zoho/test_result_form.dart`  
**Visible to**: Tester  
**Provider**: `TestResultProvider`

#### What is displayed
Dynamic form built from `OrgTestTemplate.template_data.sections[].fields[]`.

Each field is rendered based on `type`:
| Field type | Widget |
|---|---|
| `text` | `TextFormField` |
| `textarea` | `TextFormField` (multi-line) |
| `number` | `TextFormField` (numeric keyboard) |
| `dropdown` | `DropdownButtonFormField` |
| `date` | Date picker with `TextFormField` |
| `boolean` | `Switch` or `Checkbox` |
| `file` | File picker button + attachment preview |
| `outcome_schedule` | Shows `TestRequestScheduleDialog` picker inline |

#### Buttons
| Button | Action |
|---|---|
| **Save** | `POST /testing_requests/{id}/results/structured` |
| **Submit** | Save + `PUT /testing_requests/{id}/submit_results` |

---

### TR-5 — Multi-Session Panel

**File**: `lib/pages/zoho/test_sessions_panel.dart`  
**Visible to**: Tester (when `is_multi_session=true`)  
**Provider**: `TestingRequestProvider`

#### When shown
The sessions panel appears on TR-3 when `is_multi_session=true` on the TR.  
This is set when:
- The test type has `enable_calibration=true` (Protection Relay Cal, Tri-vector Meter Cal)
- The test type has `enable_cumulative=true` (Circuit Breaker Operations, OLTC Operations)
- The tester explicitly enables multi-session during create

#### Sessions list
| Element | Value |
|---|---|
| Session cards | Session number · Session date · Status badge |
| Status values | `planned` · `in_progress` · `completed` |
| Add session button | `POST /testing_requests/{id}/sessions/` |

#### Create session payload
```json
{
  "session_number": 1,
  "session_name": "Reading Session 1",
  "session_date": "2026-05-12T00:00:00Z"
}
```
> `session_number` and `session_date` are **required**. `session_name` is optional.

#### Per-session actions
| Button | Action |
|---|---|
| **Start** | `POST /testing_requests/{id}/sessions/{sid}/start` |
| **Add Reading** | Shows inline reading form |
| **Complete** | `POST /testing_requests/{id}/sessions/{sid}/complete` |

#### Reading payload (structured result with session)
Each session reading is submitted as a structured result bound to that session:
```
POST /testing_requests/{id}/results/structured
{
  "template_key": "circuit_breaker_operations",
  "test_session_id": "<session_uuid>",
  "test_data": { ... }
}
```
> The upsert key is `(testing_request_id, template_key, test_session_id)`.  
> Each session must use a **unique** `test_session_id`; otherwise readings overwrite each other and the cumulative diff returns 0.

---

### TR-6 — Recommendation Approval Detail

**File**: `lib/pages/zoho/approval_detail_page.dart`  
**Visible to**: TechApprover, OrgAdmin  
**Provider**: `ApprovalProvider`

#### Sections
| Section | Content |
|---|---|
| **Header** | TR number · Recommendation type chip · Equipment |
| **Test result summary** | Key-value pairs from overall_assessment |
| **Recommendation** | Summary · Next action chip · Schedule info |
| **Tester's schedule** | Start date · End date · Frequency (read-only from tester) |
| **Timeline** | Full audit history |

#### Approve / Reject buttons
| next_action | Behaviour |
|---|---|
| `test` | Direct approve → follow-up TR created |
| `replacement` | Direct approve → PR- procurement request |
| `repair_cycle` | → TR-7 Schedule Dialog → confirm → approve |
| `inspection` | → TR-7 Schedule Dialog → confirm → approve |
| `maintenance` | → TR-7 Schedule Dialog → confirm → approve |
| `none` | Direct approve → TR closed |

---

### TR-7 — Schedule Confirmation Dialog

**File**: `lib/pages/zoho/testing_request_schedule_dialog.dart`  
**Visible to**: TechApprover (triggered from TR-6)  
**Used in two modes**: `captureMode: true` (approver sets schedule) vs read-only display

#### Dialog fields
| Field | Pre-fill source | Editable |
|---|---|---|
| Start Date | `testing_request.scheduled_start_date` | ✅ |
| End Date | `testing_request.due_date` | ✅ |
| Frequency | `recommendation.schedule_frequency` | ✅ |

#### Buttons
| Button | Action |
|---|---|
| **Confirm** | Returns schedule values → approve fires with them |
| **Cancel** | Approval aborted; stays `under_approval` |

---

## 5. Lifecycle Monitoring Screens

### CAL-1 — Calibration Status

**File**: `lib/pages/zoho/calibration_status_page.dart`  
**Visible to**: Tester, EE TLSS, OrgAdmin  
**Provider**: `CalibrationProvider`  
**API**: `GET /calibration/lifecycle?equipment_id={id}`

#### What is displayed
| Element | Value |
|---|---|
| Equipment selector | Searchable dropdown — dept-scoped equipment list |
| Status card | `state` badge (NORMAL / DUE / OVERDUE / NOT_CALIBRATED) |
| Last calibration | Date of last calibration result |
| Next due date | Computed from last_cal + rule offset |
| Calibration history | List of past calibration results with date + template_key |
| Rule details | `DATE_ADD` rule offset, next_due computation |

#### Calibration states
| State | Meaning | Badge colour |
|---|---|---|
| `NORMAL` | Calibrated within due period | Green |
| `DUE` | Calibration due within advance_days window | Amber |
| `OVERDUE` | Past due date | Red |
| `NOT_CALIBRATED` | No calibration result on record | Grey |

#### How calibration is triggered
1. Tester creates a TR with a calibration test type (e.g., `Protection Relay Calibration and History`)
   - `is_calibration=true` is stamped on the TR (set by the server from `enable_calibration` flag)
   - `is_multi_session=true` is forced in the UI (via `_forceMultiSession`)
2. Tester submits structured results using template_key `protection_relay_calibration` or `tri_vector_meter_calibration`
3. `CalibrationService` finds the result, computes state from `DATE_ADD` rule
4. CAL-1 screen fetches `/calibration/lifecycle?equipment_id={id}` and shows the result

#### Template keys for calibration
| Test Type Name | Template Key | OrgTestTemplate `enable_calibration` |
|---|---|---|
| Protection Relay Calibration and History | `protection_relay_calibration` | `true` |
| Electronic Tri-vector Meter Calibration | `tri_vector_meter_calibration` | `true` |

---

### CUM-1 — Cumulative Count Status

**File**: `lib/pages/zoho/cumulative_status_page.dart`  
**Visible to**: Tester, EE TLSS, OrgAdmin  
**Provider**: `CumulativeProvider`  
**API**: `GET /cumulative/lifecycle?equipment_id={id}`

#### What is displayed
| Element | Value |
|---|---|
| Equipment selector | Searchable dropdown — dept-scoped |
| Threshold | Current threshold value (editable if OrgAdmin/EE TLSS) |
| Cumulative value | Total operation count (sum of diffs across all readings) |
| Status card | `status` badge (NORMAL / WARNING / CRITICAL / UNKNOWN) |
| Reading history | List of past cumulative readings with value + date |

#### Cumulative states
| State | Meaning | Badge colour |
|---|---|---|
| `NORMAL` | Count < threshold | Green |
| `WARNING` | Count approaching threshold | Amber |
| `CRITICAL` | Count ≥ threshold | Red |
| `UNKNOWN` | No readings on record | Grey |

#### How cumulative tracking works
1. Tester creates a TR with a cumulative test type (e.g., `Circuit Breaker Operations Count`)
   - `is_cumulative=true` stamped on the TR
   - `is_multi_session=true` forced in the UI
2. Tester creates **separate sessions** for each reading (session_number must be unique)
3. Each reading is submitted as structured result with `test_session_id=<session_uuid>` and `template_key=circuit_breaker_operations`
4. `CumulativeService` computes `cumulative_diff` = difference between successive readings (requires ≥ 2 readings with distinct session IDs)
5. CUM-1 shows total count vs threshold

> **Critical**: If both readings share the same `test_session_id` (or None), the upsert key matches → second reading overwrites first → only 1 reading exists → diff = 0.  
> Always create a new session per reading.

#### Threshold management
| API | Action |
|---|---|
| `GET /cumulative/equipment/{id}/threshold` | Read current threshold |
| `POST /cumulative/equipment/{id}/threshold` | Set threshold (OrgAdmin/EE TLSS) |

#### Template keys for cumulative
| Test Type Name | Template Key | `enable_cumulative` |
|---|---|---|
| Circuit Breaker Operations Count | `circuit_breaker_operations` | `true` |
| OLTC Operations Count | `oltc_operations` | `true` |

---

### Lifecycle Types Endpoint

**API**: `GET /testing_requests/lifecycle-types`  
**Auth**: Required  
**Purpose**: Returns calibration and cumulative test types grouped into two buckets

```json
{
  "calibration": [
    { "id": 228, "name": "Electronic Tri-vector Meter Calibration", "enable_calibration": true },
    { "id": 227, "name": "Protection Relay Calibration and History", "enable_calibration": true }
  ],
  "cumulative": [
    { "id": 229, "name": "Circuit Breaker Operations Count", "enable_cumulative": true },
    { "id": 230, "name": "OLTC Operations Count", "enable_cumulative": true }
  ]
}
```

> The Flutter `TestingRequestProvider` fetches this on boot and stores as `lifecycleTypes`. These types are **not** swapped into the test type dropdown — they are only used by CAL-1 and CUM-1 screens.

---

## 6. Annual Audit Screens

> **Theme**: Space/glass dark — `space_bg.png` background + `BackdropFilter` blur overlay, `DashboardGlassCard` surfaces, `Color(0xFF3FA9F5)` blue accent, `Color(0xFF0F2233)` dark base. Matches `testing_requests_screen.dart` theme.

### AUD-1 — Annual Audit List + Dashboard

**File**: `lib/pages/zoho/annual_audit_page.dart`  
**Visible to**: TAQC Officer, OrgAdmin, EE TLSS  
**Provider**: `AnnualAuditProvider`  
**APIs**: `GET /annual-audits/observations`, `GET /annual-audits/dashboard`, `GET /annual-audits/inspections`

#### Layout
`Stack` → `space_bg.png` + `BackdropFilter` blur → `Column`:
- **Header row**: dark pill `TabBar` + Create Inspection icon button + Refresh icon button
- **Dashboard strip**: 5 `DashboardGlassCard` metric cards
- **Tab body**: observation list as `DashboardGlassCard` cards with hover effect

#### Tabs
| Tab | Label | Filter params |
|---|---|---|
| 0 | All | `status=all` |
| 1 | Mine | `assigned_to_me=true` |
| 2 | Overdue | `overdue=true` |
| 3 | Closed | `status=closed` |

#### Dashboard strip (5 metric cards)
| Card | API field | Icon colour |
|---|---|---|
| Total | `total_observations` | Blue |
| Open | `open_observations` | Orange |
| Closed | `closed_observations` | Green |
| Overdue | `overdue_observations` | Red |
| Compliance % | `compliance_percentage` | Teal |

#### Observation list cards
| Element | Value |
|---|---|
| Number | `TR-ANU-YYYYMMDD-####` |
| Stage chip | Colored by stage (see map below) |
| Severity chip | Critical=red, High=orange, Medium=amber, Low=white54 |
| Overdue badge | Red "OVERDUE" if `is_overdue=true` |
| Tap | Opens `AnnualAuditDetailPage` in `RightPanelWrapper` (right-slide on desktop, fullscreen on mobile) |

#### Stage chip colour map
| Stage Code | Colour |
|---|---|
| `OBSERVATION_REPORTING` | Cyan |
| `OBSERVATION_ASSIGNMENT` | Amber |
| `COMPLIANCE_SUBMISSION` | `Color(0xFF3FA9F5)` blue |
| `COMPLIANCE_REVIEW` | Purple |
| `OBSERVATION_CLOSURE` | Green |

#### Create Inspection dialog (dark `AlertDialog`, `backgroundColor: Color(0xFF0F2233)`)
| Field | Type |
|---|---|
| Substation | Searchable dropdown (`GET /equipment`) |
| Inspection Date | Date picker |
| Remarks | Optional text |

Submit: `POST /annual-audits/inspections`

#### Create Observation dialog (dark-themed)
| Field | Type |
|---|---|
| Category | Dropdown from audit categories |
| Severity | Dropdown (Low / Medium / High / Critical) |
| Target Compliance Date | Date picker |
| Description | Multi-line text |

Submit: `POST /annual-audits/inspections/{inspection_id}/observations`

#### FAB
`+` → Create Observation (selects or creates inspection first)

---

### AUD-2 — Annual Audit Observation Detail

**File**: `lib/pages/zoho/annual_audit_detail_page.dart`  
**Opened via**: `RightPanelWrapper.show()` from AUD-1 observation tap  
**Visible to**: TAQC Officer, OrgAdmin, EE TLSS, Workflow Coordinator, AEE Maintenance  
**Provider**: `AnnualAuditProvider`

#### Layout pattern (identical to `testing_request_detail.dart`)
`Material(transparent)` → `ClipRect` → `Stack`:
- `BackdropFilter(blur sigmaX/Y=6)` + `Colors.black.withOpacity(0.6)` — blurs the space background visible through the panel
- `Column`:
  - **Header bar** — `Container` with bottom border: `IconButton` (close/back) + observation number + stage chip inline
  - **Body** — `Expanded` → `SingleChildScrollView(padding: 16)` → `Column` of `_glassSection` containers  
    (each: `BoxDecoration: color=black.0.35, borderRadius=14, border=white.0.12`)

#### Glass sections
| Section | Visible when |
|---|---|
| **Observation Details** (stage, severity chip, substation, category, target date, assigned to, overdue) | Always |
| **Workflow Progress** (API-driven 5-step Stepper) | Always |
| **Read Only notice** | No actionable permissions |
| **Stage Form** (`SharedDynamicForm` from `form['template_data']`) | `form` available; editable only if `can_submit=true` |
| **Remarks** (`TextField`) | `can_submit=true` or `can_approve=true` |
| **Actions** (`ElevatedButton.icon` row) | `available-actions` non-empty |
| **Timeline** (dot-and-line list) | Always |

#### Workflow Stepper states
| stage `status` | `StepState` | Subtitle |
|---|---|---|
| `completed` | `complete` | "Completed" (green) |
| `rejected` | `error` | "Rejected" (red) |
| Current stage code match | `editing` | — |
| Others | `indexed` | — |

Stepper uses `ThemeData.dark()` with `primary: Color(0xFF3FA9F5)`.  
Falls back to hardcoded 5-stage list when `detail['workflow']['stages']` not loaded.

#### Action buttons — driven by `GET .../available-actions`
| `can_*` flag | Button | Style | API endpoint |
|---|---|---|---|
| `can_assign` | **Assign** | Blue filled | `POST .../stages/{stage_id}/assign` |
| `can_submit` | **Save Draft** | White outlined | `POST .../stages/{stage_id}/save` (no validation) |
| `can_submit` | **Submit** | Blue filled | save → `POST .../stages/{stage_id}/submit` (validates required fields) |
| `can_approve` | **Approve** | Green filled | `POST .../stages/{stage_id}/approve` |
| `can_reject` | **Reject** | Red outlined | Dark reason dialog → `POST .../stages/{stage_id}/reject` |

> **Save vs Submit**: Save is always a draft — no required-field validation. Validation (including file upload fields) runs at submit time only.  
> **File uploads**: Upload via `POST /repair-workflows/{workflow_id}/stages/{stage_id}/upload` (`field_key` + `file` multipart) **before** submitting. The upload auto-patches `form_data[field_key]` with a document reference dict which passes submit validation.

#### Assign dialog (dark `AlertDialog`, `backgroundColor: Color(0xFF1E1E2E)`)
Dropdown from `GET .../stages/{stage_id}/eligible-users` → confirm → `POST .../stages/{stage_id}/assign`

#### 5-Stage Annual Audit Lifecycle
| # | Stage Code | Role filling | Role approving | Next stage |
|---|---|---|---|---|
| 1 | `OBSERVATION_REPORTING` | TaqcOfficer | TaqcOfficer | `OBSERVATION_ASSIGNMENT` |
| 2 | `OBSERVATION_ASSIGNMENT` | WfCoordinator | WfCoordinator | `COMPLIANCE_SUBMISSION` |
| 3 | `COMPLIANCE_SUBMISSION` | AeeMaint (uploads evidence) | AeeMaint | `COMPLIANCE_REVIEW` |
| 4 | `COMPLIANCE_REVIEW` | TaqcOfficer | TaqcOfficer approve → stage 5; reject → back to stage 3 | `OBSERVATION_CLOSURE` |
| 5 | `OBSERVATION_CLOSURE` | TaqcOfficer | TaqcOfficer | `COMPLETED` (terminal) |

#### Observation numbering
- Observations: `TR-ANU-YYYYMMDD-####` (e.g., `TR-ANU-20260513-0001`)
- Inspections: `TR-ANU-INSP-YYYYMMDD-####` (e.g., `TR-ANU-INSP-20260513-0001`)

---

### AUD-3 — Annual Audit Assignment Queue

**File**: `lib/pages/zoho/annual_audit_assignment_queue_page.dart`  
**Visible to**: TAQC Officer, OrgAdmin  
**Provider**: `AnnualAuditProvider`  
**API**: `GET /annual-audits/assignment-queue`

#### What is displayed
| Element | Value |
|---|---|
| Queue cards | Observation number · Category · Severity · Target date · Substation |
| Pending stage | `pending_stage.stage_name` + `instance_status` badge |
| Overdue badge | Red "OVERDUE" if `is_overdue=true` |
| Empty state | "No observations pending assignment" |

#### Actions
| Button | Action |
|---|---|
| **Assign** | User picker dialog → `POST /annual-audits/observations/{id}/stages/{stage_id}/assign` |
| Tap card | → AUD-2 detail |

---

### Annual Audit API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/annual-audits/config/ensure` | POST | Seed stage definitions, templates, role mappings (idempotent) |
| `/annual-audits/inspections` | POST | Create inspection (`substation_id`, `inspection_date`, `remarks`) |
| `/annual-audits/inspections` | GET | List inspections (dept-scoped) |
| `/annual-audits/inspections/{id}` | GET | Inspection detail with nested `observations[]` |
| `/annual-audits/inspections/{id}/observations` | POST | Create observation under inspection |
| `/annual-audits/observations` | GET | List observations — filters: `status`, `assigned_to_me`, `overdue` |
| `/annual-audits/observations/{id}` | GET | Observation detail — includes `workflow_id`, `workflow.stages[]` |
| `/annual-audits/observations/{id}/current-form` | GET | Current stage: `stage_id`, `stage_code`, `template_data`, `saved_form_data` |
| `/annual-audits/observations/{id}/timeline` | GET | Audit log — `action`, `note`, `performed_at` |
| `/annual-audits/observations/{id}/available-actions` | GET | `can_assign`, `can_submit`, `can_approve`, `can_reject`, `can_cancel` |
| `/annual-audits/observations/{id}/stages/{stage_id}/eligible-users` | GET | Users eligible to be assigned to this stage |
| `/annual-audits/observations/{id}/stages/{stage_id}/assign` | POST | Assign stage to user (`user_id`) |
| `/annual-audits/observations/{id}/stages/{stage_id}/save` | POST | Save form draft — no validation |
| `/annual-audits/observations/{id}/stages/{stage_id}/submit` | POST | Submit — validates all required fields incl. file uploads |
| `/annual-audits/observations/{id}/stages/{stage_id}/approve` | POST | Approve → advance to next stage |
| `/annual-audits/observations/{id}/stages/{stage_id}/reject` | POST | Reject → bounce to previous stage |
| `/annual-audits/assignment-queue` | GET | Pending-assignment queue for coordinators |
| `/annual-audits/dashboard` | GET | 5-metric summary |
| `/annual-audits/sla/run-overdue-check` | POST | Recompute `is_overdue` flags |
| `/repair-workflows/{workflow_id}/stages/{stage_id}/upload` | POST | Upload file field — `field_key` + `file` multipart; patches `form_data[field_key]` with document reference dict |

---

## 7. Repair Workflow Screens

### 10-Stage Repair Workflow

| Stage # | Stage Name | Primary Role | UI Actions |
|---|---|---|---|
| 1 | Failure Assessment | Originator / EE TLSS | Create, save assessment |
| 2 | Initial Review | Section Head | Review notes, approve/reject |
| 3 | Technical Inspection | Tester | Upload inspection findings |
| 4 | Repair Estimation | EE TLSS | Cost estimate, file upload, submit |
| 5 | Technical Approval | Tech Approver | Approve/reject estimate |
| 6 | Procurement Review | Finance Approver | Approve procurement items |
| 7 | Repair Execution | Assigned Engineer | Progress updates, upload completion evidence |
| 8 | QA / TAQC Inspection | TAQC Officer | QA inspection form, checklist |
| 9 | Final Approval | Dept Head / EE TLSS | Final approve/reject |
| 10 | Workflow Closure | OrgAdmin / EE TLSS | Close workflow, read-only summary |

#### Repair Workflow number prefix: `RL-YYYYMMDD-XXXX`

### Workflow Detail Required Fields
Every stage detail screen must display:
- Workflow number · Equipment UEIC · Current stage · Status badge
- Dynamic form fields for current stage
- Available actions (role-gated)
- Timeline history (stage name · performer · note · timestamp)

### Repair Workflow Role Access
| Login | Expected Access |
|---|---|
| `eetlss.north` | Full workflow management |
| `orgadmin.north` | Full org-wide visibility |
| `assigner.north` | Assignment queue + assign actions |
| `financeapprover.north` | Stage 6 procurement approval only |
| `techapprover.north` | Stage 5 technical approval only |
| `tester.north` | Stage 3, 7 execution only |
| `originator.north` | Stage 1 initiation + tracking |
| `taqc.north` | Stage 8 QA inspection only |

---

## 8. Testing Request Lifecycle

**TR Categories**: `test` · `maintenance` · `inspection` · `repair_lifecycle`

| Step | Action | Who | API | Status Transition |
|---|---|---|---|---|
| 1 | Create TR | Originator | `POST /testing_requests/` | → `draft` |
| 2 | Submit TR | Originator | `PUT /testing_requests/{id}/submit` | → `submitted` |
| 3 | Assign tester | TestAssigner | `POST /testing-requests/approvals/{id}/approve-and-assign` | → `assigned` |
| 4 | Accept | Tester | `PUT /testing/{id}/accept` | → `accepted` |
| 5 | Start | Tester | `PUT /testing/{id}/start` | → `in_progress` |
| 6 | Post structured results | Tester | `POST /testing/{id}/results/structured` | (status unchanged) |
| 7 | Submit results | Tester | `PUT /testing/{id}/submit_results` | → `under_approval` |
| 8 | Approve results | TechApprover | `PUT /approvals/{rec_id}/approve` | → `approved` |

---

## 9. Failure Registry (ER) Screens

### FR Flow Overview

```
Originator submits FR
        ↓
Test Assigner: Pass-1 initial-approve → child TR created
        ↓
Test Assigner: Pass-2 approve-and-assign → tester assigned
        ↓
Tester: accept → start → enter results (next_action selection)
        ↓
TechApprover: approve (with or without schedule dialog)
        ↓
WorkflowDispatch → outcome artifact
```

### FR Screens

| Screen | File | Description |
|---|---|---|
| ER-1 | Failure Registry list | FR cards, status badges, dept-scoped |
| ER-2 | Submit new FR | Dynamic form with failure template fields |
| ER-3 | FR Detail | Read-only detail, child TR link, timeline |
| ER-4 | Test Assigner queue | Initial-approve or reject FR |
| ER-5 | Assign tester dialog | Role dropdown + tester dropdown + workload badge |
| ER-6 | Tester child TR | Source FR reference, standard tester lifecycle |
| ER-7 | Test Result Form | `overall_assessment` template — next_action dropdown |
| ER-8 | Approval Detail | Recommendation summary, approve/reject with dialog |
| ER-9 | Schedule Dialog | Pre-filled dates/frequency for Repair/Inspection/Maintenance |

### Next Action Options (Tester selects in ER-7)

| Display | Enum | Schedule picker | Outcome artifact |
|---|---|---|---|
| Test | `test` | No | New `TR-` follow-up |
| Procurement | `replacement` | No | `PR-` procurement request |
| Repair | `repair_cycle` | ✅ | `RL-` repair workflow |
| Inspection | `inspection` | ✅ | `IN-` inspection schedule |
| Maintenance | `maintenance` | ✅ | `MN-` maintenance schedule |
| None | `none` | No | FR closed |

### FR Snackbar Messages

| Action | Snackbar |
|---|---|
| FR submitted | "FR-XXXX submitted successfully" |
| FR initial-approved | "FR approved. Test request TR-XXXX created and queued for assignment." |
| FR rejected | "FR-XXXX rejected" |
| Tester assigned | "Tester assigned: {email}" |
| Approved (test) | "Approved. Follow-up test TR-XXXX raised." (Indigo) |
| Approved (procurement) | "Approved. Procurement request PR-XXXX created." (Purple) |
| Approved (repair) | "Approved. Repair workflow RL-XXXX created." (Orange) |
| Approved (inspection) | "Approved. Inspection schedule IN-XXXX created." (Teal) |
| Approved (maintenance) | "Approved. Maintenance schedule MN-XXXX created." (Blue) |
| Approved (none) | "Approved. No further action required." (Green) |
| Schedule dialog cancelled | *(no snackbar — approval aborted silently)* |

---

## 10. TA&QC Inspections

### TAQC Flow

```
TAQC Officer submits inspection
        ↓ (status=under_approval, Recommendation auto-created)
TechApprover approves (next_action determines outcome)
        ↓
next_action=none → equipment commissioned (MN + IN schedules auto-created)
next_action=test → new follow-up TR
next_action=maintenance → MN- maintenance schedule
next_action=inspection → IN- inspection schedule
next_action=repair_cycle → RL- repair workflow
next_action=replacement → PR- procurement request
```

---

## 11. Department Filter & Scope

### KPTCL Hierarchy

```
KPTCL (organisation)
└── Bangalore Zone (BLR_ZONE)         ← cee.zone / see.zone
    └── Bangalore Transmission Circle (BLR_CIRCLE)  ← ee.circle / see.circle
        ├── RT North Division (RT_NORTH)   ← *.north@kptcl.com
        ├── RT South Division (RT_SOUTH)   ← *.south@kptcl.com
        └── Mysuru Division (MYSURU)       ← *.mysuru@kptcl.com
```

### Scope Rules

| Scope | Applied to | Sees |
|---|---|---|
| `exact` | Leaf users (`*.north` / `.south` / `.mysuru`) | Own dept only |
| `department_tree` | Circle users (`ee.circle`, `see.circle`) | All 3 leaf divisions |
| `zone` | Zone users (`cee.zone`, `see.zone`) | All circles + divisions |
| `organization` | OrgAdmin | All records across KPTCL |

---

## 12. RBAC Negative Tests

| Scenario | Who | Expected |
|---|---|---|
| Tester tries to finance-approve | Tester | 403 |
| SectionHead tries to assign tester | SectionHead | 403 |
| Unauthenticated GET `/testing_requests/` | No token | 401 |
| TAQC officer tries to approve FR | TAQC | 403 |
| Originator tries to approve results | Originator | 403 |
| Unauthenticated GET lifecycle-types | No token | 401 |

---

## 13. Multi-Session — Calibration & Cumulative User Scenarios

### Which test types force multi-session ON

| Test Type | Behaviour when selected |
|---|---|
| Protection Relay Calibration and History | Switch locked ON — *"Required for calibration lifecycle — always on"* |
| Electronic Tri-vector Meter Calibration | Switch locked ON — *"Required for calibration lifecycle — always on"* |
| Circuit Breaker Operations Count | Switch locked ON — *"Required for cumulative tracking — always on"* |
| OLTC Operations Count | Switch locked ON — *"Required for cumulative tracking — always on"* |
| Any other test type | Switch freely togglable by user |
| Any `repair_lifecycle` category | Multi-session section hidden — not applicable |

---

### Cumulative test — end-to-end user flow

**Login**: `tester.north@kptcl.com`

1. **Originator** creates TR with test type `Circuit Breaker Operations Count`
   - Multi-session switch auto-locks ON
   - Sets Number of Sessions = 2, Days Between Sessions = 30
   - Submits draft → TR assigned to tester

2. **Tester** opens the TR → taps **Accept** → **Start Testing**

3. **Tester** opens the Sessions Panel (visible on TR-3 because `is_multi_session=true`)
   - Taps **Add Session** → enters Session 1 date → saves
   - Taps **Start** on Session 1
   - Taps **Add Reading** → enters `count_value: 4500` → saves
   - Taps **Complete** on Session 1

4. Tester adds Session 2 (different session, different date)
   - Enters `count_value: 4750` → saves → completes

5. After all sessions complete, tester taps **Submit Results**
   - System computes cumulative diff: 4750 − 4500 = **250 operations**
   - Cumulative total increments on CUM-1 screen

6. **CUM-1 screen** (`cumulative.north@kptcl.com` or OrgAdmin) shows updated count vs threshold
   - If count ≥ threshold → status badge turns **CRITICAL** (red)

> **Common mistake**: If the tester submits both readings under the same session, the second reading overwrites the first — diff = 0, no cumulative increment. Always use a separate session per reading.

---

### Calibration test — end-to-end user flow

**Login**: `tester.north@kptcl.com`

1. **Originator** creates TR with test type `Protection Relay Calibration and History`
   - Multi-session switch locks ON automatically
   - Submits → assigned to tester

2. **Tester** accepts → starts testing → opens TR-4 result form
   - Enters calibration date and validity months (e.g., `calibration_date: 2026-05-13`, `validity_months: 24`)
   - Saves and submits

3. System computes `next_due = 2026-05-13 + 24 months = 2028-05-13`

4. **CAL-1 screen** shows the equipment's calibration state:
   - Today well before due → **NORMAL** (green)
   - Within advance window before due → **DUE** (amber)
   - Past due date → **OVERDUE** (red)
   - No result on record → **NOT CALIBRATED** (grey)

---

### Multi-session switch — what the user sees

| Situation | Switch appearance | Label |
|---|---|---|
| Standard test type, multi-session OFF | Toggle is OFF, enabled | *"Spread test across multiple days/sessions"* |
| Standard test type, multi-session ON | Toggle is ON, enabled | *"Spread test across multiple days/sessions"* |
| Cumulative test type selected | Toggle is ON, **greyed out** (not tappable) | *"Required for cumulative tracking — always on"* |
| Calibration test type selected | Toggle is ON, **greyed out** (not tappable) | *"Required for calibration lifecycle — always on"* |
| Repair lifecycle category | Multi-session row **not shown** | — |

When multi-session is ON (any reason), the form expands to show:
- **Number of Sessions** — stepper, minimum 1
- **Days Between Sessions** — stepper, minimum 1

---

### Reopening a saved draft — expected behaviour

| Draft type | Switch on reopen |
|---|---|
| Created with cumulative test type | Locked ON, correct label shown |
| Created with calibration test type | Locked ON, correct label shown |
| Created with standard type, multi-session ON | ON, freely togglable |
| Created with standard type, multi-session OFF | OFF, freely togglable |

---

## 14. Regression Test Files

| File | Tests | What is covered |
|---|---|---|
| `tests/test_auth.py` | ~30 | Login all 30 dept users + 2 platform admins |
| `tests/test_testing_request.py` | ~60 | Full TR lifecycle, all 4 categories, all 3 depts |
| `tests/test_fr_regression.py` | 52 | FR submit, 2-pass approval, tester lifecycle, 6 outcomes, negatives |
| `tests/test_dept_filter.py` | ~20 | Cross-dept isolation — originator/tester/approver scopes |
| `tests/test_hierarchy_filter.py` | ~15 | Circle/zone scope isolation |
| `tests/test_multi_session.py` | ~20 | Session CRUD, readings, statistics, auto-generate |
| `tests/test_schedule.py` | ~20 | TR schedule CRUD, pause/resume, log generation |
| `tests/test_repair_workflow.py` | ~35 | 10-stage repair workflow lifecycle, assignment queue |
| `tests/test_annual_audit_integration.py` | ~90 | Full 5-stage annual audit lifecycle end-to-end — file uploads, save/submit/approve/reject per stage, timeline, dashboard |
| `tests/test_lifecycle_types_integration.py` | 76 | Lifecycle types API, equipment_types flags, template provisioning, calibration lifecycle, cumulative lifecycle |

### Run all tests
```bash
cd C:\Yesu\CustomerAPI\Customer-API
pytest tests/ -v
```

### Run lifecycle integration only
```bash
pytest tests/test_lifecycle_types_integration.py -v
```

---

## 15. Status Value Master Reference

| Status | Module | Terminal? | Meaning |
|---|---|---|---|
| `draft` | TR | No | Created, not submitted |
| `submitted` | TR | No | Submitted, awaiting assignment |
| `assigned` | TR | No | Tester assigned |
| `accepted` | TR | No | Tester accepted |
| `in_progress` | TR | No | Testing ongoing |
| `under_review` | TR | No | Sent back for correction |
| `under_approval` | TR | No | Awaiting TechApprover |
| `approved` | TR | Yes | Results approved |
| `rejected` | TR | Yes | Results rejected |
| `outcome_active` | TR | No | Approval dispatched outcome artifact |
| `finance_pending` | TR | No | Awaiting Finance Approver |
| `commissioned` | TR | Yes | TAQC next_action=none → equipment commissioned |
| `closed` | TR | Yes | Non-TAQC next_action=none |
| `submitted` | FR | No | FR awaiting Pass-1 |
| `approved` | FR | No | FR Pass-1 done; child TR created |
| `rejected` | FR | Yes | FR rejected by Test Assigner |
| `OBSERVATION_REPORTING` | Annual Audit | No | Initial observation entered |
| `OBSERVATION_ASSIGNMENT` | Annual Audit | No | Assigned to field officer |
| `COMPLIANCE_SUBMISSION` | Annual Audit | No | Field compliance submitted |
| `COMPLIANCE_REVIEW` | Annual Audit | No | Under TA&QC review |
| `OBSERVATION_CLOSURE` | Annual Audit | Yes | Observation closed |
| `NORMAL` | Calibration / Cumulative | No | Within acceptable range |
| `DUE` | Calibration | No | Calibration due soon |
| `OVERDUE` | Calibration | No | Past due date |
| `NOT_CALIBRATED` | Calibration | No | No record |
| `WARNING` | Cumulative | No | Approaching threshold |
| `CRITICAL` | Cumulative | No | At or over threshold |
| `UNKNOWN` | Cumulative | No | No readings |

---

## 16. Key API Endpoints by Module

### Testing Requests
| Endpoint | Method | Notes |
|---|---|---|
| `/testing_requests/` | GET | List — dept-scoped |
| `/testing_requests/` | POST | Create draft TR |
| `/testing_requests/{id}/submit` | PUT | Draft → submitted |
| `/testing_requests/{id}/lifecycle-types` | GET | Lifecycle bucket types |
| `/testing_requests/equipment_types` | GET | All test types with enable_calibration/enable_cumulative flags |
| `/testing_requests/lifecycle-types` | GET | Calibration + cumulative buckets |
| `/testing/{id}/accept` | PUT | Tester accepts |
| `/testing/{id}/start` | PUT | Tester starts |
| `/testing/{id}/results/structured` | POST | Save test data (upserts on template_key+session_id) |
| `/testing/{id}/submit_results` | PUT | Submit → under_approval |
| `/testing/{id}/decline` | PUT | Tester declines → submitted |
| `/testing/{id}/resubmit` | PUT | Resubmit after under_review |
| `/testing_requests/{id}/sessions/` | POST | Create session |
| `/testing_requests/{id}/sessions/` | GET | List sessions |
| `/testing_requests/{id}/sessions/{sid}/start` | POST | Start session |
| `/testing_requests/{id}/sessions/{sid}/complete` | POST | Complete session |

### Calibration
| Endpoint | Method | Notes |
|---|---|---|
| `/calibration/lifecycle` | GET | `?equipment_id=` — lifecycle state + history |
| `/calibration/status` | GET | Quick state for equipment |
| `/calibration/evaluate` | POST | Re-evaluate state (testing hook) |

### Cumulative
| Endpoint | Method | Notes |
|---|---|---|
| `/cumulative/lifecycle` | GET | `?equipment_id=` — count + threshold + history |
| `/cumulative/equipment/{id}/threshold` | GET | Read threshold |
| `/cumulative/equipment/{id}/threshold` | POST | Set threshold |
| `/cumulative/evaluate` | POST | Re-evaluate state |

### Annual Audit
| Endpoint | Method | Notes |
|---|---|---|
| `/annual-audits/config/ensure` | POST | Seed config (idempotent) |
| `/annual-audits/inspections/` | POST | Create inspection |
| `/annual-audits/inspections/` | GET | List inspections |
| `/annual-audits/observations/` | GET | List observations |
| `/annual-audits/observations/{id}/advance` | POST | Advance stage |
| `/annual-audits/observations/{id}/available-actions` | GET | Available actions for current user |
| `/annual-audits/dashboard` | GET | 5-metric summary |
| `/annual-audits/sla/run-overdue-check` | POST | Update is_overdue flags |
