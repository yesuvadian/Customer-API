# TR Workflow — Functional Document: Config to Execution

---

## 1. Overview

The Testing Request (TR) Workflow Engine is a **configurable, stage-based system** that moves a testing request through a defined sequence of stages — from initial approval through tester assignment, test execution, result review, and closure. Each stage, its roles, and its allowed actions are fully configurable by the admin without any code changes.

---

## 2. Configuration (Admin Setup)

Done once by an admin before any requests flow through.

### 2.1 Workflow Definition

Create a named workflow definition. It holds:

- **Name** — e.g. "Standard Testing Workflow"
- **Default L3 Role** — the role used at role-scoped stages (e.g. "AEE Lead")
- **Default Tester Role** — the role used for tester assignment if no routing rule overrides it
- **Active / Default flags**

### 2.2 Statuses

Define the status labels the request passes through. Each status has:

- A code and display name
- A color for UI display
- Flags: `approval_required`, `assignment_required`, `is_terminal`

Examples: *Pending L2 Approval, L3 Tester Assignment, L4 Test Execution, L3 Result Review, Completed, Rejected*

### 2.3 Stages

Define stages in sequence order. Each stage has:

| Field | Purpose |
|---|---|
| Name / Code | Display name and machine identifier |
| Sequence | Order of progression |
| Linked Status | Which status becomes active when this stage is entered |
| Is Mandatory | Cannot be skipped |
| Show Recommendation | Shows the replacement products panel in the detail view when active |
| Is Result Stage | Marks this as where testers fill in results |
| Is Role Scoped | Only users with the resolved L3 role see requests at this stage |

### 2.4 Stage Roles

Assign org roles to each stage. Per role, configure:

| Flag | Meaning |
|---|---|
| Can Approve | Can take action (approve, complete, etc.) |
| Can Assign | Can assign testers to the request |
| Can Edit | Can edit request fields |
| Can Act As Tester | This role fills in test results |

### 2.5 Stage Transitions

Define which actions are valid at each stage and where they lead:

- **From Stage → Action → To Stage**
- Available actions: Approve, Reject, Assign, Return, Complete, Cancel, Close, Reassign
- Each transition can require a comment
- A transition with no target stage (or whose target has no roles) is **terminal** — it ends the workflow and applies a terminal status (e.g. Rejected, Completed)

### 2.6 Routing Rules

Control which workflow definition handles which combination of request. Match on:

- Request type (test / maintenance / inspection / etc.)
- Equipment type
- Test type

More specific rules take priority. A **Routing Default** is the fallback when no rule matches. Rules can also override the L3 role or tester role for specific combinations.

---

## 3. Workflow Start (On L2 Approval)

When an L2 approver approves a testing request:

1. The system finds the best-matching workflow definition based on the request's type, equipment type, and test type
2. The L3 role and tester role are resolved from the matched rule or definition defaults
3. A workflow instance is created, pointing to the **first stage**
4. The request status updates to the first stage's linked status
5. The full audit trail begins

---

## 4. Stage-by-Stage Execution

### Who sees what

Each user sees only the requests where their org role is assigned to the **current active stage**. At role-scoped stages, visibility is further restricted to users who hold the resolved L3 role for that workflow stream. Requests are also scoped to the user's department and its descendants.

### Taking an action

When a user acts on a request:

1. The system finds the transition matching the current stage + selected action
2. If the action requires a comment, one must be provided
3. The current stage is closed and the next stage opens
4. The request status updates to the next stage's linked status
5. The audit log records: who acted, from/to stage, from/to status, timestamp, and any comment

### Send-back

If the target stage has a lower sequence number than the current stage, it is recorded as a **send-back** in the audit trail and shown distinctly in the flowchart.

### Terminal actions

If the transition points to no next stage (or the target stage has no roles configured), the workflow ends. The instance is marked as completed or terminated and the terminal status is applied to the request.

---

## 5. Standard Stage Flow

```
Request Submitted
        │
        ▼
  L2 Approval
  (L2 Manager approves)
        │ Approve
        ▼
  L3 Tester Assignment        ← role-scoped: only L3 role sees this
  (L3 assigns a tester)
        │ Assign
        ▼
  L4 Test Execution           ← tester fills results here
  (Tester submits test form)
        │ Complete
        ▼
  L3 Result Review            ← replacement/recommendation panel shown
  (L3 reviews results)
        │ Approve
        ▼
  Completed (Terminal)
```

At any stage, a **Reject** or **Return** transition can send the request back to a prior stage or directly to a terminal status.

---

## 6. Test Execution — Tester Experience

When the workflow reaches the test execution stage:

1. The assigned tester sees the request in their **My Assignments** list
2. They open the request and tap **Fill Test Results**
3. The test result form opens showing:
   - **Equipment History Panel** (if the request is linked to a specific asset) — displays the equipment's overall health score, risk level, and last 5 test results so the tester has historical context while filling in current readings
   - Dynamic form fields driven by the test template
   - Overall result selection (Pass / Fail / Marginal) and remarks
   - Image upload section
4. Tester submits the form and then clicks **Complete** to advance the workflow to the result review stage

---

## 7. Result Review — Reviewer Experience

When the workflow reaches a stage with **Show Recommendation** enabled:

- The **Replacement Products / Recommendation panel** appears in the request detail view
- The reviewer can see manually entered or system-generated replacement product suggestions alongside the submitted test results
- They either **Approve** (progresses to completion) or **Return** (sends back to tester for re-work)

---

## 8. Audit Trail & Flowchart

Every stage transition is permanently recorded showing:

- Which stage it moved from and to
- Who performed the action and when
- The action taken and any comment
- Whether it was a send-back or a terminal action

This history is visible as a **vertical flowchart** on the request — boxes are color-coded:

| Color | Meaning |
|---|---|
| Blue | Current active stage |
| Green | Completed stages |
| Red | Rejected or terminal stage |
| Grey | Stages not yet reached |

---

## 9. Workflow Completion

When a terminal transition fires (approve at the final stage, or reject at any stage):

- The workflow instance is marked **completed** or **terminated**
- The request status is set to the configured terminal status (e.g. *Completed*, *Rejected*, *Cancelled*)
- No further actions are possible on the workflow
- The full audit trail remains readable for reference
