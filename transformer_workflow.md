# Transformer Repair Workflow System

## 📌 Overview

This system manages the end-to-end lifecycle of transformer repair using:
- Stage-driven workflow
- Role-based execution
- Centralized assignment control
- Form-based data capture
- Status-based progress tracking

---

# 🧩 1. Workflow Stages

[
  {"name": "Failure Reporting", "sequence": 1},
  {"name": "Committee Review", "sequence": 2},
  {"name": "Vendor Assignment", "sequence": 3},
  {"name": "Lifting", "sequence": 4},
  {"name": "Joint Inspection", "sequence": 5},
  {"name": "Estimate & Work Award", "sequence": 6},
  {"name": "Repair QA", "sequence": 7},
  {"name": "Final Inspection", "sequence": 8},
  {"name": "Dispatch", "sequence": 9},
  {"name": "Commissioning", "sequence": 10}
]

---

# 👥 2. Stage Roles + Assignment Role

[
  {
    "stage_code": "FAILURE_REPORT",
    "roles": ["AEE Maintenance", "EE TLSS", "Originator"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "COMMITTEE_REVIEW",
    "roles": ["CEE RT&R&D", "Department Head"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "VENDOR_ASSIGNMENT",
    "roles": ["CEE RT&R&D", "CEE Transmission Zone"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "LIFTING",
    "roles": ["EE RT", "AEE Maintenance"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "JOINT_INSPECTION",
    "roles": ["EE RT", "Field Tester"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "ESTIMATE",
    "roles": ["SEE W&M", "Purchaser"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "QA",
    "roles": ["Lab Tester", "Field Tester"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "FINAL_INSPECTION",
    "roles": ["EE RT", "SEE RT"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "DISPATCH",
    "roles": ["EE RT", "AEE Maintenance"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  },
  {
    "stage_code": "COMMISSIONING",
    "roles": ["EE TLSS", "CEE RT&R&D"],
    "assignment_role": "WORKFLOW_COORDINATOR"
  }
]

---

# 🔄 3. Workflow Status Model

PENDING → ASSIGNED → IN_PROGRESS → SUBMITTED → APPROVED / REJECTED

---

# 🔁 4. Transition Rules

[
  {"from": "Failure Reporting", "action": "approve", "to": "Committee Review"},
  {"from": "Committee Review", "action": "approve", "to": "Vendor Assignment"},
  {"from": "Committee Review", "action": "reject", "to": "Failure Reporting"},
  {"from": "Vendor Assignment", "action": "approve", "to": "Lifting"},
  {"from": "Joint Inspection", "action": "reject", "to": "Lifting"},
  {"from": "Final Inspection", "action": "reject", "to": "Repair QA"},
  {"from": "Dispatch", "action": "approve", "to": "Commissioning"}
]

---

# 🗄️ 5. Data Storage

## Main Table: workflow_instance

{
  "id": "WF123",
  "stage_code": "QA",
  "status": "IN_PROGRESS",
  "current_role": "Lab Tester",
  "assigned_user": "user_123",
  "assignment_pending": false,
  "progress": 65
}

## History Table: workflow_stage_history

{
  "workflow_id": "WF123",
  "stage_code": "FAILURE_REPORT",
  "status": "APPROVED",
  "assigned_user": "user_1"
}

## Assignment Queue

{
  "workflow_id": "WF123",
  "from_stage": "COMMITTEE_REVIEW",
  "to_stage": "VENDOR_ASSIGNMENT",
  "status": "PENDING"
}

---

# 🚀 Final Outcome

Transformer repaired, tested, commissioned, and workflow closed.
