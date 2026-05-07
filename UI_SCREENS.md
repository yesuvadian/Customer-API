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
**Template key**: `failure_registry` (fetched from `GET /testing/templates/by-key/failure_registry`)

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
    "outcome": "Repair"
  }
}
```

**Initial status**: `submitted` → goes to **Test Assigner** queue for `initial_approve`  
**No Recommendation created** at submission — Recommendation is created only after the child TR tester submits results.

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

#### Failure Registry (FR)

```
POST /direct-submissions/   →  TestingRequest (status=submitted)
                                    ↓
                           Test Assigner: initial_approve
                           PUT /approvals/{rec_id}/approve
                                    ↓
                           Child TR created (status=submitted → assigned)
                           Normal tester lifecycle starts
                                    ↓
                           Tester submits results → under_approval
                                    ↓
                           TechApprover: approve_results
                           → WorkflowDispatch: next_action → MN/IN/repair_cycle/replacement/none
```

> FR submission creates only `TestingRequest` + `TestResult`. No Recommendation yet.

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

| `next_action` | TR Status | Created |
|---|---|---|
| `none` | `commissioned` | Equipment record + MN schedule + IN schedule |
| `maintenance` | `outcome_active` | `TestRequestSchedule` (MN- prefix, recurring) |
| `inspection` | `outcome_active` | `TestRequestSchedule` (IN- prefix, recurring) |
| `repair_cycle` | `outcome_active` | `RepairWorkflow` (10-stage) |
| `replacement` | `finance_pending` | `ProcurementRequest` → Finance Approver queue |

> `none` on TAQC = **commissioning** — Equipment auto-created from E&C form data, MN + IN maintenance schedules auto-created.

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
