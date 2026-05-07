# Equipment Lifecycle — Workflow Flows

> **Scope:** FR Flow · TAQC Flow · Adhoc TR Flow  
> **Engine:** `IntegratedWorkflowEngine` (DB-driven state machine)  
> **Sequencing:** from/to transition pairs — no hardcoded step numbers  
> **Conditional routing:** `condition_value` column on `WorkflowTransition`

---

## Roles (6 generic)

| Code | Role Name | Responsibility |
|------|-----------|---------------|
| R1 | **Originator** | Raises FR, TR, TAQC tickets |
| R2 | **Test Assigner** | Approves queue items, assigns testers |
| R3 | **Tester** | Performs physical testing, fills forms |
| R4 | **Technical Approver** | Validates test results, decides next_action |
| R5 | **Finance Approver** | Approves replacement/procurement spend |
| R6 | **Admin / Org Admin** | Config, workflow setup, reporting |

---

## Flow 1 — Failure Registry (FR) → Test Request

```
FAILURE REGISTRY WORKFLOW  (category = failure_registry)
══════════════════════════════════════════════════════════

[Originator]
  Fill FR form:
    • Select equipment
    • Describe failure
    • Select test type
        │
        │  POST /testing-requests/  { category: failure_registry }
        ▼
  ┌─────────────┐
  │  submitted  │  ← FR queue (Test Assigner sees this)
  └─────────────┘
        │                              │
   initial_approve                   reject
   (Test Assigner)                (Test Assigner)
        │                              │
        ▼                              ▼
  ┌─────────────┐               ┌─────────────┐
  │  approved ◉ │               │ rejected  ◉ │
  └─────────────┘               └─────────────┘
        │
        │  AUTO: TR (category=test) created
        │        department_id = approver's dept
        │        status = submitted → lands in Test Assigner queue
        ▼

TEST REQUEST WORKFLOW  (category = test)  ← spawned from FR
══════════════════════════════════════════════════════════════

  ┌─────────────┐
  │  submitted  │  ← Test Assigner queue (dept-scoped)
  └─────────────┘
        │                              │
  approve_and_assign                 reject
  (Test Assigner)                (Test Assigner)
        │                              │
        ▼                              ▼
  ┌─────────────┐               ┌─────────────┐
  │  assigned   │               │ rejected  ◉ │
  └─────────────┘               └─────────────┘
        │
      accept
     (Tester)
        │
        ▼
  ┌─────────────┐
  │  accepted   │  ← Tester fills standard test form
  └─────────────┘
        │
   submit_result
     (Tester)
        │  + next_action + schedule_frequency
        ▼
  ┌──────────────────┐
  │  under_approval  │  ← Technical Approver queue
  └──────────────────┘
        │                              │
      approve                        reject
  (Tech Approver)               (Tech Approver)
        │                              │
        ├─ next_action=maintenance     ▼
        ├─ next_action=inspection  ┌──────────────┐
        ├─ next_action=repair_cycle│ under_review │ ← Tester revises
        │                          └──────────────┘
        │                                  │
        │                          resubmit (Tester)
        │                            back to accepted
        │
        ├─[maintenance]──────────► outcome_active ◉  + MN-schedule created
        ├─[inspection]───────────► outcome_active ◉  + IN-schedule created
        ├─[repair_cycle]─────────► outcome_active ◉  + RL-workflow started
        ├─[none]─────────────────► closed ◉
        └─[replacement]──────────► finance_pending
                                        │                │
                                finance_approve    finance_reject
                                (Finance Approver) (Finance Approver)
                                        │                │
                                        ▼                ▼
                                 outcome_active ◉   under_review
                                 + PR- confirmed    (back to tester)
```

### FR Workflow — Transition Table

| # | Workflow | from_state | action | condition_value | to_state | Role | Side Effect |
|---|---------|-----------|--------|----------------|---------|------|-------------|
| 1 | `failure_registry` | `submitted` | `initial_approve` | — | `approved` ◉ | Test Assigner | TR(test) auto-created, same dept |
| 2 | `failure_registry` | `submitted` | `reject` | — | `rejected` ◉ | Test Assigner | — |
| 3 | `testing_request` | `submitted` | `approve_and_assign` | — | `assigned` | Test Assigner | Tester linked |
| 4 | `testing_request` | `submitted` | `reject` | — | `rejected` ◉ | Test Assigner | — |
| 5 | `testing_request` | `assigned` | `accept` | — | `accepted` | Tester | — |
| 6 | `testing_request` | `accepted` | `submit_result` | — | `under_approval` | Tester | Recommendation saved |
| 7 | `testing_request` | `under_approval` | `approve` | `maintenance` | `outcome_active` ◉ | Tech Approver | MN schedule created |
| 8 | `testing_request` | `under_approval` | `approve` | `inspection` | `outcome_active` ◉ | Tech Approver | IN schedule created |
| 9 | `testing_request` | `under_approval` | `approve` | `repair_cycle` | `outcome_active` ◉ | Tech Approver | RepairWorkflow started |
| 10 | `testing_request` | `under_approval` | `approve` | `replacement` | `finance_pending` | Tech Approver | ProcurementRequest created |
| 11 | `testing_request` | `under_approval` | `approve` | `none` | `closed` ◉ | Tech Approver | — |
| 12 | `testing_request` | `under_approval` | `reject` | — | `under_review` | Tech Approver | Rejection note saved |
| 13 | `testing_request` | `under_review` | `resubmit` | — | `accepted` | Tester | Recommendation updated |
| 14 | `testing_request` | `finance_pending` | `finance_approve` | — | `outcome_active` ◉ | Finance Approver | Procurement confirmed |
| 15 | `testing_request` | `finance_pending` | `finance_reject` | — | `under_review` | Finance Approver | Back to tester |

---

## Flow 2 — TAQC / E&C Inspection → Equipment Creation

```
TAQC WORKFLOW  (category = taqc_inspection)
════════════════════════════════════════════

[Originator]
  Fill TAQC request:
    • Select equipment TYPE (no equipment yet)
    • Location / department / bay details
        │
        │  POST /testing-requests/  { category: taqc_inspection }
        ▼
  ┌─────────────┐
  │  submitted  │  ← Test Assigner queue
  └─────────────┘
        │                              │
  approve_and_assign                 reject
  (Test Assigner)                (Test Assigner)
        │                              │
        ▼                              ▼
  ┌─────────────┐               ┌─────────────┐
  │  assigned   │               │ rejected  ◉ │
  └─────────────┘               └─────────────┘
        │
      accept
     (Tester)
        │
        ▼
  ┌─────────────┐
  │  accepted   │  ← Tester fills dynamic E&C form
  └─────────────┘      (template resolved by equipment_type_id)
        │               Fields: nameplate data, ratings, serial no,
        │                       test readings, insulation values ...
        │
   submit_ec_form
     (Tester)
        │
        ▼
  ┌──────────────────┐
  │  under_approval  │  ← Technical Approver reviews E&C data
  └──────────────────┘
        │                              │
      approve                        reject
  (Tech Approver)               (Tech Approver)
        │                              │
        ▼                              ▼
  ┌──────────────────┐        ┌──────────────┐
  │  commissioned ◉  │        │ under_review │ ← Tester fixes E&C form
  └──────────────────┘        └──────────────┘
        │                              │
  AUTO creates:                  resubmit (Tester)
    • Equipment record           back to accepted
    • equipment.status = active
    • MN-schedule (from EquipmentTypeScheduleDefault)
    • IN-schedule (from EquipmentTypeScheduleDefault)
```

### TAQC — Transition Table

| # | from_state | action | condition_value | to_state | Role | Side Effect |
|---|-----------|--------|----------------|---------|------|-------------|
| 1 | `submitted` | `approve_and_assign` | — | `assigned` | Test Assigner | E&C Tester linked |
| 2 | `submitted` | `reject` | — | `rejected` ◉ | Test Assigner | — |
| 3 | `assigned` | `accept` | — | `accepted` | Tester | E&C form unlocked |
| 4 | `accepted` | `submit_ec_form` | — | `under_approval` | Tester | E&C data saved |
| 5 | `under_approval` | `approve` | — | `commissioned` ◉ | Tech Approver | Equipment + MN + IN created |
| 6 | `under_approval` | `reject` | — | `under_review` | Tech Approver | Rejection note |
| 7 | `under_review` | `resubmit` | — | `accepted` | Tester | E&C form reopened |

> No next_action branching — TAQC approval always creates equipment. Outcome is always `commissioned`.

---

## Flow 3 — Adhoc Test Request (Direct TR)

```
ADHOC TEST REQUEST WORKFLOW  (category = test)
═══════════════════════════════════════════════

[Originator]
  Fill TR form:
    • Select existing equipment
    • Select test type
    • Describe reason
        │
        │  POST /testing-requests/  { category: test }
        ▼
  ┌─────────────┐
  │  submitted  │  ← Test Assigner queue
  └─────────────┘
        │                              │
  approve_and_assign                 reject
  (Test Assigner)                (Test Assigner)
        │                              │
        ▼                              ▼
  ┌─────────────┐               ┌─────────────┐
  │  assigned   │               │ rejected  ◉ │
  └─────────────┘               └─────────────┘
        │
      accept
     (Tester)
        │
        ▼
  ┌─────────────┐
  │  accepted   │  ← Tester fills standard test form
  └─────────────┘
        │
   submit_result
     (Tester)
        │  next_action: maintenance | inspection |
        │               repair_cycle | replacement | none
        │  schedule_frequency: monthly | quarterly | yearly ...
        ▼
  ┌──────────────────┐
  │  under_approval  │  ← Technical Approver queue
  └──────────────────┘
        │                              │
      approve                        reject
  (Tech Approver)               (Tech Approver)
        │                              ▼
        │                       ┌──────────────┐
        │                       │ under_review │ ← Tester revises
        │                       └──────────────┘
        │                              │ resubmit
        │                          back to accepted
        │
        ├─[maintenance]──────────► outcome_active ◉  + MN-schedule
        ├─[inspection]───────────► outcome_active ◉  + IN-schedule
        ├─[repair_cycle]─────────► outcome_active ◉  + RL-workflow
        ├─[none]─────────────────► closed ◉
        └─[replacement]──────────► finance_pending
                                        │              │
                                finance_approve  finance_reject
                                        │              │
                                 outcome_active ◉  under_review
```

*(Same transition table as TR rows in FR flow — shares `testing_request` workflow_type)*

---

## next_action Dispatch Summary

| next_action | Ticket Created | Prefix | Table |
|------------|---------------|--------|-------|
| `maintenance` | TestRequestSchedule (recurring) | MN- | `test_request_schedules` |
| `inspection` | TestRequestSchedule (recurring) | IN- | `test_request_schedules` |
| `repair_cycle` | RepairWorkflow (10-stage) | RL- | `repair_workflows` |
| `replacement` | ProcurementRequest (finance queue) | PR- | `procurement_requests` |
| `none` | — (TR closed) | — | — |

---

## State Inventory

| State | Terminal? | Visible To |
|-------|-----------|-----------|
| `submitted` | No | Test Assigner queue |
| `assigned` | No | Tester (pending accept) |
| `accepted` | No | Tester (active work) |
| `under_approval` | No | Technical Approver queue |
| `under_review` | No | Tester (revise & resubmit) |
| `finance_pending` | No | Finance Approver queue |
| `outcome_active` | **Yes** | Read-only history |
| `commissioned` | **Yes** | Read-only history (TAQC only) |
| `closed` | **Yes** | Read-only history |
| `approved` | **Yes** | Read-only history (FR only) |
| `rejected` | **Yes** | Read-only history |

---

## Workflow Engine — Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/testing-requests/` | Create FR / TR / TAQC ticket |
| `GET` | `/testing-requests/approvals/pending` | Test Assigner queue (submitted) |
| `POST` | `/testing-requests/approvals/{id}/initial-approve` | FR Pass 1 — creates test TR |
| `POST` | `/testing-requests/approvals/{id}/approve-and-assign` | TR Pass 2 — assign tester |
| `POST` | `/testing-requests/approvals/{id}/reject` | Reject from queue |
| `POST` | `/testing-requests/{id}/accept` | Tester accepts assignment |
| `POST` | `/testing-requests/{id}/submit-result` | Tester submits result + next_action |
| `GET` | `/approvals/pending` | Technical Approver queue |
| `PUT` | `/approvals/{id}/approve` | Tech approve (dispatches by next_action) |
| `PUT` | `/approvals/{id}/reject` | Tech reject → under_review |
| `POST` | `/recommendations/{id}/resubmit` | Tester resubmit after rejection |
| `GET` | `/validation_requests/` | Finance Approver queue |
| `PUT` | `/validation_requests/{id}/finance-approve` | Finance approve |
| `PUT` | `/validation_requests/{id}/finance-reject` | Finance reject → under_review |

---

## Conditional Transition Logic

The `WorkflowTransition` table has a `condition_value` column.  
For `approve` from `under_approval`, the engine picks the matching transition:

```python
# Engine resolution
for transition in transitions_from_current_state:
    if transition.condition_value is None:          # unconditional — always matches
        return transition
    if context["next_action"] == transition.condition_value:   # conditional match
        return transition
```

`context["next_action"]` is read from `Recommendation.next_action` at approval time.

---

## Repair Lifecycle (RL) — 10 Stages

See `docs/repair_workflow_flow.md` for full detail.  
Auto-triggered from TR/FR approval when `next_action = repair_cycle`.
