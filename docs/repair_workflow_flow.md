# Repair Lifecycle Workflow — Approve & Reject Flow

> **Scope:** 10-stage transformer repair lifecycle  
> **API prefix:** `POST /repair-workflows/{workflow_id}/advance` (approve) · `POST /repair-workflows/{workflow_id}/reject`  
> **RBAC:** Stage-level — same roles that can edit a stage can also approve/reject it (`can_edit = can_approve = true`)  
> **Progress:** Each stage carries weight = 10; progress = completed stages × 10%

---

## Stage Map

```
 [1] Failure Reporting  ──approve──►  [2] Committee Review  ──approve──►  [3] Vendor Assignment
       (0% → 10%)                          (10% → 20%)                         (20% → 30%)
                                   ◄──reject──┘

 [3] Vendor Assignment  ──approve──►  [4] Lifting  ──approve──►  [5] Joint Inspection
       (30% → 40%)                      (40% → 50%)
                                                         ◄──reject──┘ (explicit: back to Lifting)

 [5] Joint Inspection  ──approve──►  [6] Estimate & Work Award  ──approve──►  [7] Repair QA
       (50% → 60%)                          (60% → 70%)

 [7] Repair QA  ──approve──►  [8] Final Inspection  ──approve──►  [9] Dispatch
    (70% → 80%)                     (80% → 90%)             ◄──reject──┘ (explicit: back to QA)

 [9] Dispatch  ──approve──►  [10] Commissioning  (100% — COMPLETE)
    (90% → 100%)
```

---

## Approve Flow (stage-by-stage)

| # | Stage | Authorized Roles | Approve → Next Stage | Progress |
|---|-------|-----------------|----------------------|----------|
| 1 | **Failure Reporting** | AEE Maintenance, EE TLSS, Originator | Committee Review | 0% → 10% |
| 2 | **Committee Review** | CEE RT&R&D, Department Head | Vendor Assignment | 10% → 20% |
| 3 | **Vendor Assignment** | CEE RT&R&D, CEE Transmission Zone | Lifting | 20% → 30% |
| 4 | **Lifting** | EE RT, AEE Maintenance | Joint Inspection | 30% → 40% |
| 5 | **Joint Inspection** | EE RT, Field Tester | Estimate & Work Award | 40% → 50% |
| 6 | **Estimate & Work Award** | SEE W&M, Purchaser | Repair QA | 50% → 60% |
| 7 | **Repair QA** | Lab Tester, Field Tester | Final Inspection | 60% → 70% |
| 8 | **Final Inspection** | EE RT, SEE RT | Dispatch | 70% → 80% |
| 9 | **Dispatch** | EE RT, AEE Maintenance | Commissioning | 80% → 90% |
| 10 | **Commissioning** | EE TLSS, CEE RT&R&D | *(workflow complete)* | 90% → 100% |

**API call:**
```http
POST /repair-workflows/{workflow_id}/advance
Authorization: Bearer <token>
Content-Type: application/json

{ "notes": "Stage completed — approving" }
```

**Success response (200):**
```json
{
  "message": "Stage advanced",
  "current_stage": "Committee Review",
  "progress": 10
}
```

**Error responses:**
| HTTP | Reason |
|------|--------|
| 400 | `You do not have approval permission for this stage.` |
| 400 | `Workflow is not active.` |
| 404 | `Workflow not found.` |

---

## Reject Flow (stage-by-stage)

Reject moves the workflow **backwards**. Explicit reject transitions override the default sequential-reverse fallback.

| # | Stage | Authorized Roles | Reject → Previous Stage | Transition Type | Progress |
|---|-------|-----------------|------------------------|-----------------|----------|
| 1 | **Failure Reporting** | *(N/A — first stage)* | ❌ Cannot reject | — | — |
| 2 | **Committee Review** | CEE RT&R&D, Department Head | Failure Reporting | Explicit | 20% → 0% |
| 3 | **Vendor Assignment** | CEE RT&R&D, CEE Transmission Zone | Committee Review | Sequential fallback | 30% → 10% |
| 4 | **Lifting** | EE RT, AEE Maintenance | Vendor Assignment | Sequential fallback | 40% → 20% |
| 5 | **Joint Inspection** | EE RT, Field Tester | Lifting | Explicit | 50% → 30% |
| 6 | **Estimate & Work Award** | SEE W&M, Purchaser | Joint Inspection | Sequential fallback | 60% → 40% |
| 7 | **Repair QA** | Lab Tester, Field Tester | Estimate & Work Award | Sequential fallback | 70% → 50% |
| 8 | **Final Inspection** | EE RT, SEE RT | Repair QA | Explicit | 80% → 60% |
| 9 | **Dispatch** | EE RT, AEE Maintenance | Final Inspection | Sequential fallback | 90% → 70% |
| 10 | **Commissioning** | EE TLSS, CEE RT&R&D | Dispatch | Sequential fallback | 100% → 80% |

**API call:**
```http
POST /repair-workflows/{workflow_id}/reject
Authorization: Bearer <token>
Content-Type: application/json

{ "notes": "Non-compliance found — rejecting back" }
```

**Success response (200):**
```json
{
  "message": "Stage rejected — returned to previous stage",
  "current_stage": "Failure Reporting",
  "progress": 0
}
```

**Error responses:**
| HTTP | Reason |
|------|--------|
| 400 | `You do not have approval permission for this stage.` |
| 400 | `Cannot reject — already at the first stage.` |
| 400 | `Workflow is not active.` |

---

## RBAC Rules

- **Edit (save form data):** Role must have `can_edit = true` in `repair_stage_roles` for the current stage.
- **Approve / Reject:** Role must have `can_approve = true` in `repair_stage_roles` for the current stage.
- **Currently:** `can_edit = can_approve = true` for all assigned roles.
- **Global bypass:** A user with no OrgUserRole entries (system super-admin) bypasses all stage RBAC.
- **Org admin bypass:** Org admins can manage stage config (GET/PUT `/config/stages`) but are still subject to stage RBAC for workflow operations (advance/reject/save).

### Who Can Do What (Quick Reference)

| Role | Edit | Approve/Reject | Stages |
|------|------|----------------|--------|
| AEE Maintenance | ✅ | ✅ | 1 (Failure Reporting), 4 (Lifting), 9 (Dispatch) |
| EE TLSS | ✅ | ✅ | 1 (Failure Reporting), 10 (Commissioning) |
| Originator | ✅ | ✅ | 1 (Failure Reporting) |
| CEE RT&R&D | ✅ | ✅ | 2 (Committee Review), 3 (Vendor Assignment), 10 (Commissioning) |
| Department Head | ✅ | ✅ | 2 (Committee Review) |
| CEE Transmission Zone | ✅ | ✅ | 3 (Vendor Assignment) |
| EE RT | ✅ | ✅ | 4 (Lifting), 5 (Joint Inspection), 8 (Final Inspection), 9 (Dispatch) |
| Field Tester | ✅ | ✅ | 5 (Joint Inspection), 7 (Repair QA) |
| SEE W&M | ✅ | ✅ | 6 (Estimate & Work Award) |
| Purchaser | ✅ | ✅ | 6 (Estimate & Work Award) |
| Lab Tester | ✅ | ✅ | 7 (Repair QA) |
| SEE RT | ✅ | ✅ | 8 (Final Inspection) |

---

## Full Workflow Lifecycle

```
Equipment Failure Registered (FR- ticket)
         │
         ▼
  Failure Registry Approved (outcome = repair)
         │  auto-trigger
         ▼
┌─────────────────────────────────────┐
│  RepairWorkflow created (status=active) │
│  Equipment.status → under_repair        │
└─────────────────────────────────────┘
         │
         ▼
[1] Failure Reporting  ─── AEE Maintenance / EE TLSS / Originator
         │ approve
         ▼
[2] Committee Review   ─── CEE RT&R&D / Department Head
         │ approve         │ reject → [1]
         ▼
[3] Vendor Assignment  ─── CEE RT&R&D / CEE Transmission Zone
         │ approve         │ reject → [2]
         ▼
[4] Lifting            ─── EE RT / AEE Maintenance
         │ approve         │ reject → [3]
         ▼
[5] Joint Inspection   ─── EE RT / Field Tester
         │ approve         │ reject → [4] (explicit)
         ▼
[6] Estimate & Work Award ─ SEE W&M / Purchaser
         │ approve         │ reject → [5]
         ▼
[7] Repair QA          ─── Lab Tester / Field Tester
         │ approve         │ reject → [6]
         ▼
[8] Final Inspection   ─── EE RT / SEE RT
         │ approve         │ reject → [7] (explicit)
         ▼
[9] Dispatch           ─── EE RT / AEE Maintenance
         │ approve         │ reject → [8]
         ▼
[10] Commissioning     ─── EE TLSS / CEE RT&R&D
         │ approve         │ reject → [9]
         ▼
┌──────────────────────────────────┐
│  Workflow COMPLETED (100%)       │
│  Equipment.status → active       │
└──────────────────────────────────┘
```

---

## Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/repair-workflows/start` | Start a new repair workflow for equipment |
| `GET` | `/repair-workflows` | List all workflows |
| `GET` | `/repair-workflows/{id}` | Get workflow detail with all stage instances |
| `GET` | `/repair-workflows/{id}/progress` | Current stage + progress % |
| `GET` | `/repair-workflows/{id}/current-form` | Form template for current stage |
| `POST` | `/repair-workflows/{id}/stages/{stage_id}/save` | Save form data for current stage |
| `POST` | `/repair-workflows/{id}/stages/{stage_id}/upload` | Upload document for stage |
| `POST` | `/repair-workflows/{id}/advance` | Approve current stage → advance |
| `POST` | `/repair-workflows/{id}/reject` | Reject current stage → go back |
| `GET` | `/repair-workflows/{id}/timeline` | Full audit trail of all transitions |
| `GET` | `/repair-workflows/{id}/stages/{stage_id}/documents` | List uploaded documents for a stage |

> `{stage_id}` in save/upload endpoints is the **stage definition ID** (from `current_stage.id` in the workflow response), not the stage instance ID.

---

## Validated Test Results

All scenarios tested against live API (`features/repaircycle` branch):

### Approve
| Stage | Authorized User | Result |
|-------|----------------|--------|
| 1 → 2 | AEE Maintenance | ✅ PASS |
| 2 → 3 | CEE RT&R&D | ✅ PASS |
| 3 → 4 | CEE RT&R&D | ✅ PASS |
| 4 → 5 | EE RT | ✅ PASS |
| 5 → 6 | EE RT | ✅ PASS |
| 6 → 7 | SEE W&M | ✅ PASS |
| 7 → 8 | Field Tester | ✅ PASS |
| 8 → 9 | EE RT | ✅ PASS |
| 9 → 10 | EE RT | ✅ PASS |

### Reject
| Stage | Authorized User | Rejected To | Result |
|-------|----------------|-------------|--------|
| 2 | CEE RT&R&D | Stage 1 | ✅ PASS |
| 5 | Field Tester | Stage 4 | ✅ PASS |
| 7 | Field Tester | Stage 6 | ✅ PASS |
| 8 | SEE RT | Stage 7 (QA) | ✅ PASS |
| 8 | EE RT | Stage 7 (QA) | ✅ PASS |
| 9 | EE RT | Stage 8 | ✅ PASS |
| 10 | CEE RT&R&D | Stage 9 | ✅ PASS |
| 10 | EE TLSS | Stage 9 | ✅ PASS |
| 1 | AEE Maintenance | ❌ `Cannot reject — already at the first stage.` | ✅ PASS |

### Unauthorized Access (all correctly blocked)
| Stage | Blocked Role | Operation | Result |
|-------|-------------|-----------|--------|
| 1 | EE RT | save / approve | ✅ Blocked |
| 1 | CEE RT&R&D | save / approve | ✅ Blocked |
| 2 | AEE Maintenance | save / approve | ✅ Blocked |
| 2 | EE RT | save / approve | ✅ Blocked |
| 7 | EE RT | save / reject | ✅ Blocked |
| 8 | AEE Maintenance | save / reject | ✅ Blocked |
| 10 | AEE Maintenance | save / reject | ✅ Blocked |
| 10 | EE RT | save / reject | ✅ Blocked |
