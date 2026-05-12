# CogniWatt / KPTCL API — UI Endpoint Reference

> **Perspective**: Flutter UI (what each screen calls, who calls it, and what body to send)  
> **Base URL**: `http://localhost:8000` (dev) · `https://test2.aapromoters.com` (staging)  
> **Auth**: All protected endpoints require `Authorization: Bearer <token>`

---

## 1. User Roles & Login Credentials

### North Department (10 roles)

| Role Key | Email | Password | Scope |
|----------|-------|----------|-------|
| OrgAdmin (dept) | `orgadmin.north@kptcl.com` | `TestDept@123` | Org-wide admin for north |
| DeptHead | `depthead.north@kptcl.com` | `TestDept@123` | North dept head |
| Originator | `originator.north@kptcl.com` | `TestDept@123` | Creates testing requests |
| Tester | `tester.north@kptcl.com` | `TestDept@123` | Performs tests |
| TestAssigner | `assigner.north@kptcl.com` | `TestDept@123` | Assigns testers to TRs |
| TechApprover | `techapprover.north@kptcl.com` | `TestDept@123` | Approves/rejects test results |
| FinanceApprover | `financeapprover.north@kptcl.com` | `TestDept@123` | Finance-approves procurement |
| EE TLSS | `eetlss.north@kptcl.com` | `TestDept@123` | EE-level engineer, starts repair workflows |
| TAQC Officer | `taqc.north@kptcl.com` | `TestDept@123` | TA&QC inspection submissions |
| SectionHead | `sectionhead.north@kptcl.com` | `TestDept@123` | Read-only section head |

### South Department
| Role | Email | Password |
|------|-------|----------|
| Originator | `originator.south@kptcl.com` | `TestDept@123` |
| TAQC Officer | `taqc.south@kptcl.com` | `TestDept@123` |

### Mysuru Department
| Role | Email | Password |
|------|-------|----------|
| Originator | `originator.mysuru@kptcl.com` | `TestDept@123` |
| TAQC Officer | `taqc.mysuru@kptcl.com` | `TestDept@123` |

### Organisation-Level (KPTCL HQ)
| Role | Email | Password | Scope |
|------|-------|----------|-------|
| KptclAdmin | `orgadmin@kptcl.com` | `admin123` | All orgs, all depts |
| KptclOriginator | `originator@kptcl.com` | `admin123` | Org-level originator |

### Circle / Zone Level (hierarchy scope)
| Role | Email | Password | Scope |
|------|-------|----------|-------|
| EE Circle | `ee.circle@kptcl.com` | `TestDept@123` | Sees all divisions under circle |
| SEE Circle | `see.circle@kptcl.com` | `TestDept@123` | Circle scope |
| CEE Zone | `cee.zone@kptcl.com` | `TestDept@123` | Sees entire zone subtree |
| SEE Zone | `see.zone@kptcl.com` | `TestDept@123` | Zone scope |

---

## 2. Status Machines

### Testing Request (TR) Status Flow

```
draft
  └─[Originator: submit]──► submitted
                               └─[TestAssigner: assign]──► assigned
                                                              └─[Tester: accept]──► accepted
                                                                                      └─[Tester: start]──► in_progress
                                                                                                             ├─[Tester: submit_results]──► under_approval
                                                                                                             │                               ├─[TechApprover: approve_results]──► approved
                                                                                                             │                               └─[TechApprover: reject_results]──► rejected
                                                                                                             └─[Tester: decline]──► submitted (re-enters queue)
```

**TR Categories**: `test` · `maintenance` · `inspection` · `repair_lifecycle`

### Repair Workflow Status Flow

```
(start) ──► active
               ├─[EE: save stage data]
               ├─[EE: advance]──► next_stage ──► ... ──► completed
               └─[EE: reject]──► rejected
```

---

## 3. Authentication

### `POST /auth/login`
**Who**: All users (no token required)  
**Body**:
```json
{ "email": "user@kptcl.com", "password": "TestDept@123" }
```
**Returns**: `{ "access_token": "...", "token_type": "bearer" }`  
**Error cases**: `401` wrong password · `403` account locked after multiple failures

### `GET /users/me`
**Who**: Any authenticated user  
**Use**: Resolve the logged-in user's own `id` (used before assigning tester)  
**Returns**: `{ "id": "<uuid>", "email": "...", "firstname": "...", ... }`

---

## 4. Organisation Management

> **Accessible by**: KptclAdmin, OrgAdmin

### `GET /organizations`
**Who**: KptclAdmin  
**Returns**: List of all organisations  
**UI use**: Organisation list page, admin home

### `GET /organizations/{org_id}`
**Who**: KptclAdmin, OrgAdmin  
**Returns**: Single org detail

### `POST /organizations/with-admin`
**Who**: KptclAdmin  
**Use**: Create a new organisation with its first admin user in one call

---

## 5. Departments

> **Accessible by**: KptclAdmin, OrgAdmin

### `GET /organizations/{org_id}/departments`
**Who**: KptclAdmin, OrgAdmin  
**Returns**: List of departments in an org  
**UI use**: Populate dept dropdowns, resolve dept_id for equipment registration  
**Example**: North dept code = `RT_NORTH`, South = `RT_SOUTH`, Mysuru = `RT_MYSURU`

---

## 6. Org Roles

### `GET /organizations/{org_id}/roles`
**Who**: KptclAdmin, OrgAdmin  
**Returns**: List of roles in the organisation  
**UI use**: Role assignment dropdowns

---

## 7. Org Users

### `GET /organizations/{org_id}/users`
**Who**: KptclAdmin, OrgAdmin (403 for Tester / lower roles)  
**Returns**: List of users in the organisation  
**UI use**: User management page, fallback for resolving tester user ID

### `GET /organizations/{org_id}/users/{user_id}`
**Who**: KptclAdmin, OrgAdmin

---

## 8. Equipment (Asset Register)

### `GET /equipment`
**Who**: Any authenticated user (scoped to org/dept)  
**Query params**: `?equipment_type_id=<id>&search=<text>&limit=20`  
**Returns**: List of equipment items  
**UI use**: Equipment list page, search box in Failure Registry form

### `GET /equipment/{equipment_id}`
**Who**: Any authenticated user  
**Returns**: Full equipment detail including UEIC, nameplate data, department

### `GET /equipment/{equipment_id}/applicable-tests`
**Who**: Any authenticated user  
**Returns**: List of test types applicable to this equipment  
**UI use**: Populate test type dropdown when creating a TR

### `POST /equipment/`
**Who**: KptclAdmin, OrgAdmin  
**Body**:
```json
{
  "equipment_type_id": 17,
  "department_id": "<uuid>",
  "voltage_class": "220",
  "bay_number": "01",
  "serial_in_bay": "01",
  "nameplate_data": {
    "manufacturer": "BHEL",
    "serial_number": "TEST-PT-NORTH-001",
    "year_of_manufacture": 2022,
    "rated_capacity_mva": 100
  }
}
```
**Returns**: `201` with new equipment record  
**UI use**: Equipment registration form

### `PUT /equipment/{equipment_id}`
**Who**: KptclAdmin, OrgAdmin  
**Use**: Update equipment details

### `POST /equipment/{equipment_id}/retire`
**Who**: KptclAdmin, OrgAdmin  
**Use**: Retire/decommission an asset

### `GET /equipment/stats/counts`
**Who**: KptclAdmin, OrgAdmin  
**Returns**: Count breakdown by type/status for dashboard widgets

### `GET /equipment/export/csv`
**Who**: KptclAdmin, OrgAdmin  
**Returns**: CSV file download of equipment register

### `GET /equipment/{equipment_id}/replacement-report`
**Who**: KptclAdmin, TechApprover  
**Returns**: Replacement report for an equipment item

---

## 9. Testing Requests

### Dropdown / Helper Endpoints

#### `GET /testing_requests/equipment_types`
**Who**: Any authenticated user  
**Returns**: List of `{ id, name }` — used to resolve Power Transformer type ID  
**UI use**: Equipment type dropdown in Create TR form

#### `GET /testing_requests/request-categories`
**Who**: Any authenticated user  
**Returns**: `["test", "maintenance", "inspection", "repair_lifecycle"]`  
**UI use**: Category dropdown in Create TR form

#### `GET /testing_requests/department_hierarchy`
**Who**: Any authenticated user  
**Query params**: `?org_id=<id>&parent_id=<id>`  
**Returns**: Hierarchical list of departments/divisions  
**UI use**: Location picker dropdown

#### `GET /testing_requests/testers`
**Who**: KptclAdmin, TestAssigner  
**Returns**: List of users with Tester role (system-level role join)  
**UI use**: Tester assignment dropdown  
> ⚠️ Returns only users with **system-level** `UserRole`, not org-level `OrgUserRole`.  
> Use `GET /users/me` to resolve the tester's own ID if the list appears empty.

#### `GET /testing_requests/stats`
**Who**: KptclAdmin, OrgAdmin  
**Returns**: Count breakdown by status, category  
**UI use**: Dashboard stats widgets

### CRUD

#### `POST /testing_requests/`
**Who**: Originator, KptclOriginator  
**Body**:
```json
{
  "equipment_id": "<uuid>",
  "title": "Power Transformer Annual Test",
  "request_category": "test",
  "description": "Routine annual testing",
  "priority": "normal"
}
```
**Returns**: `201` with `{ "id": "<uuid>", "request_number": "TR-...", "status": "draft" }`

#### `GET /testing_requests/`
**Who**: All authenticated users (filtered by dept scope)  
**Query params**: `?limit=500&status=submitted`  
**Returns**: List of TRs visible to the logged-in user's department  
**Scoping rules**:
- Dept user (Originator, Tester, etc.): sees own dept only
- OrgAdmin / KptclAdmin: sees all depts in org
- Circle/Zone users: sees full subtree of divisions

#### `GET /testing_requests/{request_id}`
**Who**: All authenticated users (if scoped to their dept)  
**Returns**: Full TR detail

#### `PUT /testing_requests/{request_id}`
**Who**: Originator (draft state only)  
**Use**: Edit a TR before submission

#### `DELETE /testing_requests/{request_id}`
**Who**: Originator (draft state only)

### Lifecycle Transitions

#### `PUT /testing_requests/{request_id}/submit`
**Who**: Originator  
**State**: `draft` → `submitted`  
**Body**: `{}`

#### `PUT /testing_requests/{request_id}/assign`
**Who**: TestAssigner, KptclAdmin  
**State**: `submitted` → `assigned`  
**Body**:
```json
{ "tester_id": "<uuid>" }
```
> Get the tester's UUID from `GET /users/me` (tester logs in) or `GET /organizations/{org_id}/users`

---

## 10. Testing Request Approvals

### `GET /testing-requests/approvals/pending`
**Who**: TestAssigner, KptclAdmin  
**Returns**: TRs awaiting assigner approval/action  
**UI use**: Testing Request Approvals screen

### `GET /testing-requests/approvals/{request_id}/tester-roles`
**Who**: TestAssigner, KptclAdmin  
**Returns**: Roles eligible to test this equipment type

### `GET /testing-requests/approvals/{request_id}/tester-roles/{role_id}/users`
**Who**: TestAssigner, KptclAdmin  
**Returns**: Users in a given tester role for dropdown

### `POST /testing-requests/approvals/{request_id}/approve-and-assign`
**Who**: TestAssigner, KptclAdmin  
**Use**: Approve the request AND assign a tester in one call

### `POST /testing-requests/approvals/{request_id}/reject`
**Who**: TestAssigner, KptclAdmin  
**Body**: `{ "reason": "..." }`  
**Use**: Reject a submitted request

---

## 11. Testing (Tester Workflow)

> All endpoints under `/testing/` are called by the **assigned Tester**

### `GET /testing/my-assignments`
**Who**: Tester  
**Returns**: All TRs assigned to the logged-in tester  
**UI use**: Tester's task list / my assignments screen

### `PUT /testing/{request_id}/accept`
**Who**: Assigned Tester  
**State**: `assigned` → `accepted`  
**Body**: `{}`

### `PUT /testing/{request_id}/start`
**Who**: Assigned Tester  
**State**: `accepted` → `in_progress`  
**Body**: `{}`

### `GET /testing/{request_id}/results`
**Who**: Assigned Tester, TechApprover  
**Returns**: All test results (TestResult records) for this TR

### `POST /testing/{request_id}/results/structured`
**Who**: Assigned Tester  
**Use**: Save test form data (JSONB) against a template  
**Body**:
```json
{
  "template_key": "power_transformer_test",
  "test_data": {
    "oil_temperature": "45",
    "winding_resistance_hv": "0.5",
    "insulation_resistance": "1000",
    "turns_ratio": "11.0"
  },
  "overall_result": "pass",
  "remarks": "All parameters within range"
}
```
> This saves a `TestResult` record used by `submit_results` legacy path.

### `PUT /testing/{request_id}/submit_results`
**Who**: Assigned Tester  
**State**: `in_progress` → `under_approval`  
**Body (new path — recommended)**:
```json
{
  "recommendation_type": "pass",
  "summary": "Power Transformer passed all visual and electrical tests"
}
```
**Valid `recommendation_type` values**: `pass` · `fail` · `conditional` · `retest`  
> ⚠️ Do NOT send `"continue_operation"` — this is not a valid value and returns 400.

**Body (legacy path — no recommendation)**:
```json
{}
```
> Legacy path auto-derives recommendation from saved TestResult records.  
> Fails with `400` if no TestResult records exist for this TR.

### `PUT /testing/{request_id}/decline`
**Who**: Assigned Tester  
**State**: `accepted` or `in_progress` → `submitted` (back to queue)  
**Body**: `{ "reason": "Cannot access equipment due to outage" }`

### `GET /testing/pending-approval`
**Who**: TechApprover, KptclAdmin  
**Returns**: TRs in `under_approval` state awaiting result approval

### `PUT /testing/{request_id}/approve_results`
**Who**: TechApprover, KptclAdmin  
**State**: `under_approval` → `approved`  
**Body**: `{ "comment": "Results verified and approved" }`

### `PUT /testing/{request_id}/reject_results`
**Who**: TechApprover, KptclAdmin  
**State**: `under_approval` → `rejected`  
**Body**: `{ "comment": "Insufficient data — retesting required" }`

### Test Templates

#### `GET /testing/templates/{test_type_id}`
**Who**: Any authenticated user  
**Returns**: Dynamic form template for a test type  
**UI use**: Build the structured test form fields

#### `GET /testing/templates/by-key/{template_key}`
**Who**: Any authenticated user  
**Returns**: Template by its string key (e.g., `power_transformer_test`)

---

## 12. Recommendations

> Auto-created when a tester calls `submit_results`

### `GET /recommendations/`
**Who**: TechApprover, KptclAdmin  
**Returns**: All recommendations

### `GET /recommendations/pending`
**Who**: TechApprover, KptclAdmin  
**Returns**: Recommendations with `approval_status = "pending"`

### `GET /recommendations/stats`
**Who**: TechApprover, KptclAdmin  
**Returns**: Count by type and approval status

### `GET /recommendations/by-request/{request_id}`
**Who**: TechApprover, KptclAdmin  
**Returns**: Recommendation(s) linked to a specific TR

### `GET /recommendations/{recommendation_id}/detail`
**Who**: TechApprover, KptclAdmin  
**Returns**: Full recommendation detail with test results

---

## 13. Approvals (Technical)

### `GET /approvals/stats`
**Who**: TechApprover, KptclAdmin  
**Returns**: Approval counts by status

### `GET /approvals/pending`
**Who**: TechApprover, KptclAdmin  
**Returns**: Recommendations awaiting technical approval

### `GET /approvals/{recommendation_id}/detail`
**Who**: TechApprover, KptclAdmin  
**Returns**: Full recommendation detail for approval screen

### `PUT /approvals/{recommendation_id}/approve`
**Who**: TechApprover, KptclAdmin  
**Body**: `{ "notes": "Technically sound — approved" }`  
**Returns**: Updated recommendation record

### `PUT /approvals/{recommendation_id}/reject`
**Who**: TechApprover, KptclAdmin  
**Body**: `{ "notes": "Test data incomplete — rejection reason" }`

---

## 14. Procurement / Validation Requests

> Used in the Customer Portal / Zoho-side screens

### `GET /validation_requests/`
**Who**: FinanceApprover, KptclAdmin  
**Returns**: List of validation/procurement requests

### `GET /validation_requests/{id}`
**Who**: FinanceApprover  
**Returns**: Detail of a single validation request

### `POST /validation_requests/`
**Who**: Originator, TechApprover  
**Body**: `{ "testing_request_id": "...", "summary": "..." }`

### `PUT /validation_requests/{id}`
**Who**: FinanceApprover  
**Use**: Update a validation request

### `PUT /validation_requests/{id}/finance-approve`
**Who**: FinanceApprover  
**Body**: `{ "notes": "Finance budget confirmed" }`  
**RBAC**: Tester / lower roles → `403 Forbidden`

### `PUT /validation_requests/{id}/finance-reject`
**Who**: FinanceApprover  
**Body**: `{ "reason": "Budget unavailable this quarter" }`

### `PUT /validation_requests/{id}/complete`
**Who**: FinanceApprover  
**Use**: Mark the validation request as completed

---

## 15. Repair Workflows

### Configuration (read-only)

#### `GET /repair-workflows/config/stages`
**Who**: EE TLSS, KptclAdmin  
**Returns**: All configured repair stages in sequence

#### `GET /repair-workflows/config/transitions`
**Who**: EE TLSS, KptclAdmin  
**Returns**: Allowed stage transitions

### Lifecycle

#### `POST /repair-workflows/start`
**Who**: EE TLSS, KptclAdmin  
**Body**:
```json
{
  "equipment_id": "<uuid>",
  "remarks": "Insulation degradation — sending for repair"
}
```
**Returns**: `{ "workflow_id": "<uuid>", "status": "active" }`  
**Error**: `400` or `409` if equipment already has an active workflow

#### `GET /repair-workflows`
**Who**: EE TLSS, KptclAdmin  
**Returns**: List of all repair workflows

#### `GET /repair-workflows/{workflow_id}`
**Who**: EE TLSS, KptclAdmin  
**Returns**: Full workflow detail

#### `GET /repair-workflows/{workflow_id}/timeline`
**Who**: EE TLSS, KptclAdmin  
**Returns**: Chronological list of stage transitions

#### `GET /repair-workflows/{workflow_id}/progress`
**Who**: EE TLSS, KptclAdmin  
**Returns**: Current stage, % complete

#### `GET /repair-workflows/{workflow_id}/current-form`
**Who**: EE TLSS (must have edit permission for current stage)  
**Returns**: `{ "stage_id": "<uuid>", "form_schema": {...} }` or `404` if at terminal stage

#### `POST /repair-workflows/{workflow_id}/stages/{stage_id}/save`
**Who**: EE TLSS (must have edit permission for this stage)  
**Body**:
```json
{
  "form_data": {
    "failure_date": "2026-05-07",
    "failure_description": "Insulation breakdown in HV winding",
    "failure_mode": "Insulation breakdown",
    "failure_location": "HV winding",
    "severity": "high",
    "remarks": "Urgent repair required",
    "condition": "fair",
    "visual_inspection": "Completed",
    "recommendation": "Send for repair"
  }
}
```
**Error**: `400 "You do not have edit permission for this stage."` — check stage-role assignment

#### `POST /repair-workflows/{workflow_id}/advance`
**Who**: EE TLSS (must have approval permission for current stage)  
**Body**: `{ "remarks": "Stage completed — moving forward" }`  
**Returns**: `{ "status": "next_stage_name" }` or `completed`

#### `POST /repair-workflows/{workflow_id}/reject`
**Who**: EE TLSS, KptclAdmin  
**Body**: `{ "remarks": "Equipment not accessible — workflow rejected" }`  
**State**: `active` → `rejected`

---

## 16. Failure Registry (Direct Submissions)

> Direct submission by field users — **no tester assignment required**

### `GET /direct-submissions/?category=failure_registry`
**Who**: Originator (scoped to own dept), KptclAdmin  
**Query params**: `?category=failure_registry&limit=100`  
> ⚠️ `category` parameter is **required** — returns `422` without it  
**Returns**: List of failure registry submissions for the user's department  
**Dept isolation**: Each dept user sees only their own dept submissions

### `POST /direct-submissions/`
**Who**: Originator  
**Body**:
```json
{
  "request_category": "failure_registry",
  "template_key": "failure_registry_default",
  "title": "Power Transformer Failure — North Substation",
  "equipment_id": "<uuid>",
  "test_data": {
    "failure_date": "2026-05-01",
    "failure_mode": "Insulation breakdown",
    "location": "north substation",
    "severity": "high"
  },
  "overall_result": "fail",
  "remarks": "Immediate inspection required",
  "priority": "high"
}
```
**Returns**: `201` with `{ "id": "<uuid>", "request_number": "FR-..." }`

### `GET /direct-submissions/{submission_id}`
**Who**: Originator (own dept), KptclAdmin  
**Returns**: Full submission detail with attachment metadata

### `POST /direct-submissions/{submission_id}/attach`
**Who**: Originator (the submitter)  
**Content-Type**: `multipart/form-data`  
**Field**: `file` (photo, PDF, or document)  
**Use**: Attach a supporting document to a submission  
**Returns**: `{ "file_name": "...", "file_size": 12345, "file_type": "image/jpeg" }`

### `GET /direct-submissions/{submission_id}/attachment`
**Who**: Originator (own dept), KptclAdmin  
**Returns**: Binary file stream for download  
**Headers in response**: `Content-Disposition: attachment; filename="..."`, `Content-Type: image/jpeg`  
**Error**: `404` if no attachment exists

---

## 17. TA&QC Inspection (Direct Submissions)

> Same endpoint as Failure Registry — differentiated by `category`

### `GET /direct-submissions/?category=taqc_inspection`
**Who**: TAQC Officer (scoped to own dept), KptclAdmin  
**Dept isolation**: Each TAQC officer sees only their own dept

### `POST /direct-submissions/`
**Who**: TAQC Officer  
**Body**:
```json
{
  "request_category": "taqc_inspection",
  "template_key": "taqc_inspection_default",
  "title": "TAQC Inspection — Power Transformer North",
  "equipment_id": "<uuid>",
  "test_data": {
    "inspection_date": "2026-05-06",
    "inspector_name": "TAQC Officer North",
    "equipment_condition": "fair",
    "oil_level": "normal",
    "bushing_condition": "good",
    "cooling_system": "ok"
  },
  "overall_result": "pass",
  "remarks": "Routine inspection completed",
  "priority": "normal"
}
```

---

## 18. Notifications

### `GET /notifications/`
**Who**: All authenticated users  
**Returns**: All notifications for the logged-in user

### `GET /notifications/unread-count`
**Who**: All authenticated users  
**Returns**: `{ "count": 5 }`  
**UI use**: Badge counter in nav bar

### `PUT /notifications/{notification_id}`
**Who**: All authenticated users  
**Use**: Mark a notification as read

### `PUT /notifications/read-all`
**Who**: All authenticated users  
**Use**: Mark all notifications as read

---

## 19. Dashboard KPI Endpoints

> Scope is automatically determined from the logged-in user's role and dept

### Individual Widget Endpoints
| Endpoint | Returns | Who |
|----------|---------|-----|
| `GET /dashboard/kpi` | Overall KPI summary | All authenticated |
| `GET /dashboard/role-view` | Role-specific summary tiles | All authenticated |
| `GET /dashboard/overdue-tests` | Overdue testing requests | OrgAdmin, EE, DeptHead |
| `GET /dashboard/active-alerts` | Active alerts count | All authenticated |
| `GET /dashboard/flagged-equipment` | Equipment flagged for attention | OrgAdmin, TechApprover |
| `GET /dashboard/repair-progress` | Active repair workflow stats | EE TLSS, KptclAdmin |
| `GET /dashboard/maintenance-overdue` | Overdue maintenance requests | EE TLSS, DeptHead |
| `GET /dashboard/procurement` | Procurement pipeline | FinanceApprover, KptclAdmin |
| `GET /dashboard/open-remediation` | Open remediation actions | TechApprover, KptclAdmin |
| `GET /dashboard/failure-registry` | Failure registry summary | OrgAdmin, EE TLSS |
| `GET /dashboard/taqc-inspections` | TAQC inspection stats | TAQC Officer, KptclAdmin |

### Full Dashboard by Role
| Endpoint | For Role |
|----------|----------|
| `GET /dashboard/full` | Resolves by `default_module` from JWT |
| `GET /dashboard/admin/full` | KptclAdmin, OrgAdmin |
| `GET /dashboard/ee-tlss/full` | EE TLSS, EE Circle |
| `GET /dashboard/see-cee/full` | SEE, CEE (circle/zone roles) |
| `GET /dashboard/field/full` | Originator, Tester, field roles |

### Role-Specific Summary Views
| Endpoint | Token to use |
|----------|-------------|
| `GET /dashboard/ee-tlss` | EE TLSS, EE Circle |
| `GET /dashboard/aee` | KptclAdmin, AEE |
| `GET /dashboard/see` | SEE Circle, SEE Zone |
| `GET /dashboard/cee` | CEE Zone |

### Cache Management (Admin only)
#### `POST /dashboard/invalidate-cache`
**Who**: KptclAdmin only (`403` for Tester and lower roles)  
**Use**: Force-refresh the dashboard KPI cache  
**Body**: `{}`

---

## 20. Department & Hierarchy Scoping Rules

| User Level | What they see in `GET /testing_requests/` |
|------------|------------------------------------------|
| Dept user (Originator, Tester, etc.) | Only TRs in their own department |
| OrgAdmin / KptclAdmin | All TRs across all departments in org |
| Circle user (EE Circle, SEE Circle) | All TRs in all divisions under their circle |
| Zone user (CEE Zone, SEE Zone) | All TRs in the entire zone (all circles + divisions) |
| North & South | Disjoint — no cross-dept visibility |
| South & Mysuru | Disjoint — no cross-dept visibility |

**Same scoping applies to**: Failure Registry, TA&QC Inspections, Equipment list, Repair Workflows

---

## 21. Role-Based Access Control (RBAC)

| Action | Allowed Roles | Blocked Roles |
|--------|--------------|---------------|
| Create TR | Originator, KptclOriginator | Tester, SectionHead |
| Submit TR | Originator | Tester, SectionHead |
| Assign Tester | TestAssigner, KptclAdmin | SectionHead → `400/403` |
| Accept / Start | Assigned Tester only | Other testers → `403` |
| Submit Results | Assigned Tester only | Other testers → `403` |
| Approve / Reject Results | TechApprover, KptclAdmin | Tester → `403` |
| Finance Approve Procurement | FinanceApprover | Tester → `403/401` |
| List Org Users | KptclAdmin, OrgAdmin | Tester → `403` |
| Invalidate Dashboard Cache | KptclAdmin | Tester → `403` |
| Start Repair Workflow | EE TLSS, KptclAdmin | — |
| Submit Failure Registry | Originator, any field user | — |
| Submit TAQC Inspection | TAQC Officer | — |

---

## 22. Complete Testing Workflow (UI Sequence)

### Step-by-step for a single TR from creation to approval

```
1. [Originator] POST /testing_requests/
   Body: { equipment_id, title, request_category, priority }
   → status: draft

2. [Originator] PUT /testing_requests/{id}/submit
   Body: {}
   → status: submitted

3. [TestAssigner] GET /users/me  (with tester's token to resolve their ID)
   GET /testing-requests/approvals/pending
   PUT /testing_requests/{id}/assign
   Body: { "tester_id": "<uuid>" }
   → status: assigned

4. [Tester] GET /testing/my-assignments

5. [Tester] PUT /testing/{id}/accept
   Body: {}
   → status: accepted

6. [Tester] PUT /testing/{id}/start
   Body: {}
   → status: in_progress

7. [Tester] GET /testing/templates/{test_type_id}   ← load form schema

8. [Tester] POST /testing/{id}/results/structured
   Body: { template_key, test_data, overall_result, remarks }
   → saves TestResult record

9. [Tester] PUT /testing/{id}/submit_results
   Body: { "recommendation_type": "pass", "summary": "..." }
   → status: under_approval  (auto-creates Recommendation)

10. [TechApprover] GET /testing/pending-approval

11. [TechApprover] PUT /testing/{id}/approve_results
    Body: { "comment": "Approved" }
    → status: approved

--- OR ---

11. [TechApprover] PUT /testing/{id}/reject_results
    Body: { "comment": "Insufficient data" }
    → status: rejected

--- OR (Tester declines) ---

6b. [Tester] PUT /testing/{id}/decline
    Body: { "reason": "Cannot access equipment" }
    → status: submitted  (back to queue for reassignment)
```

---

## 23. Misc / Utility Endpoints

### `GET /categories/`
**Who**: Any authenticated user  
**Use**: Category master list

### `GET /testing_requests/dropdown/{master_desc}`
**Who**: Any authenticated user  
**Use**: Generic dropdown data (failure modes, severity levels, etc.)

### `GET /docs`
**No auth required** — Swagger UI (dev only)

---

*Generated from `test_api.py` scenarios — covers all 23 test sections across 10 roles × 3 departments*
