# CogniWatt Customer Portal — UI & Test Reference

---

## 1. Login Credentials

### Department Users (password: `TestDept@123`)

| Email | Role Key | Dept |
|---|---|---|
| `orgadmin.north@kptcl.com` | OrgAdmin | North |
| `depthead.north@kptcl.com` | DeptHead | North |
| `originator.north@kptcl.com` | Originator | North |
| `tester.north@kptcl.com` | Tester | North |
| `assigner.north@kptcl.com` | TestAssigner | North |
| `techapprover.north@kptcl.com` | TechApprover | North |
| `financeapprover.north@kptcl.com` | FinanceApprover | North |
| `eetlss.north@kptcl.com` | EeTlss | North |
| `taqc.north@kptcl.com` | TaqcOfficer | North |
| `sectionhead.north@kptcl.com` | SectionHead | North |
| `originator.south@kptcl.com` | Originator | South |
| `tester.south@kptcl.com` | Tester | South |
| `taqc.south@kptcl.com` | TaqcOfficer | South |
| `originator.mysuru@kptcl.com` | Originator | Mysuru |
| `tester.mysuru@kptcl.com` | Tester | Mysuru |
| `taqc.mysuru@kptcl.com` | TaqcOfficer | Mysuru |

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
| `failure_registry` | Failure Registry | Originator, EE TLSS | Log and track equipment failure incidents (direct submission) |
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
| Valid login (all 10 north roles) | `*.north@kptcl.com` / `TestDept@123` | 200 + `access_token` |
| Valid login (KPTCL admins) | `orgadmin@kptcl.com` / `admin123` | 200 + `access_token` |
| Wrong password | `orgadmin.north@kptcl.com` / `wrong` | 401 |
| Non-existent user | `nobody@kptcl.com` | 401 / 404 |

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

### Section 13 — Repair Workflow Lifecycle

| Step | API | Who | Notes |
|---|---|---|---|
| Start workflow | `POST /repair-workflows/start` | EE TLSS | Requires `equipment_id` |
| Get current form | `GET /repair-workflows/{id}/current-form` | EE TLSS | Returns form fields for current stage |
| Save stage data | `POST /repair-workflows/{id}/stages/{stage_id}/save` | EE TLSS | Submit form data for the stage |
| Advance stage | `POST /repair-workflows/{id}/advance` | EE TLSS | Moves to next stage |
| Reject workflow | `POST /repair-workflows/{id}/reject` | EE TLSS | Terminates workflow |
| View timeline | `GET /repair-workflows/{id}/timeline` | EE TLSS | Stage history |
| View progress | `GET /repair-workflows/{id}/progress` | EE TLSS | Completion % |

---

### Section 19 — Failure Registry

**Module**: `failure_registry`  
**Who**: `originator.north@kptcl.com` · `originator.south@kptcl.com` · `originator.mysuru@kptcl.com`

| Step | API | Notes |
|---|---|---|
| Submit | `POST /direct-submissions/` | `request_category: "failure_registry"`, `template_key: "failure_registry_default"` |
| List | `GET /direct-submissions/?category=failure_registry` | Dept-scoped — each originator sees only their dept |
| Get single | `GET /direct-submissions/{id}` | Own dept only |
| Attach file | `POST /direct-submissions/{id}/attach` | Binary file upload |
| Download file | `GET /direct-submissions/{id}/attachment` | Binary stream download |
| Dept isolation | North originator must NOT see South/Mysuru records | Verified across all 3 depts |

**Sample payload**:
```json
{
  "request_category": "failure_registry",
  "template_key": "failure_registry_default",
  "title": "FR Test - NORTH dept - Power Transformer",
  "equipment_id": "<pt_equip_id>",
  "test_data": {
    "failure_date": "2026-05-01",
    "failure_mode": "Insulation breakdown",
    "location": "north substation",
    "severity": "high"
  },
  "overall_result": "fail",
  "remarks": "Automated FR test",
  "priority": "high"
}
```

---

### Section 20 — TA&QC Inspections

**Module**: `taqc_inspections`  
**Who**: `taqc.north@kptcl.com` · `taqc.south@kptcl.com` · `taqc.mysuru@kptcl.com`

| Step | API | Notes |
|---|---|---|
| Submit | `POST /direct-submissions/` | `request_category: "taqc_inspection"`, `template_key: "taqc_inspection_default"` |
| List | `GET /direct-submissions/?category=taqc_inspection` | Dept-scoped — each TAQC officer sees only their dept |
| Get single | `GET /direct-submissions/{id}` | Own dept only |
| Dept isolation | TAQC north must NOT see South/Mysuru inspection records | Verified across all 3 depts |

**Sample payload**:
```json
{
  "request_category": "taqc_inspection",
  "template_key": "taqc_inspection_default",
  "title": "TAQC Inspection - NORTH - Power Transformer",
  "equipment_id": "<pt_equip_id>",
  "test_data": {
    "inspection_date": "2026-05-06",
    "inspector_name": "TAQC Officer north",
    "equipment_condition": "fair",
    "oil_level": "normal",
    "bushing_condition": "good",
    "cooling_system": "ok"
  },
  "overall_result": "pass",
  "remarks": "Automated TAQC test",
  "priority": "normal"
}
```

---

### What happens after Failure Registry / TA&QC submission

Both modules **bypass the normal tester-assignment flow**. A single `POST /direct-submissions/` atomically creates 3 records and lands straight in the approval queue:

```
POST /direct-submissions/
   ├── TestingRequest  (status = under_approval, is_direct_submission = true)
   ├── TestResult      (test_data saved, tested_by = submitter)
   └── Recommendation  (approval_status = pending)
         └── 🔔 Notification sent to approvers
```

**`overall_result` → Recommendation type mapping:**

| overall_result | Recommendation type |
|---|---|
| `"fail"` *(FR default)* | `fail` |
| `"advisory"` *(TAQC default)* | `conditional` |
| `"pass"` | `pass` |
| `"retest"` | `retest` |
| `"conditional_pass"` | `conditional` |

**Next steps after submission (TechApprover / OrgAdmin):**

| Action | API | Result |
|---|---|---|
| View pending | `GET /approvals/pending` | Sees the FR or TAQC record |
| Approve | `PUT /approvals/{rec_id}/approve` | → `approved` |
| Reject | `PUT /approvals/{rec_id}/reject` | → `rejected` |

**Full lifecycle (no tester, no assignment step):**
```
Submitter  →  POST /direct-submissions/  →  under_approval
                                                 ├── Approve  →  approved
                                                 └── Reject   →  rejected
```

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
