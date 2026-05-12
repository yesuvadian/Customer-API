# Repair / Lifecycle – Unified Implementation Guide (Final)

*(Dynamic JSON Rules + Multi-Session + CUMULATIVE_DIFF + Overhaul Trigger + UI + Dropdown Integration)*

---

## 1. Introduction

The system currently supports:

* Dynamic template engine (JSON-based forms)
* Multi-session data capture
* Rule definitions stored in JSON
* Workflow-driven Repair / Lifecycle module

Limitation:

* Only **stateless aggregations (SUM, AVG)**
* No **usage-based lifecycle tracking**
* UI is **workflow-only oriented**

---

## 2. Objective

Enhance system to support:

* **Cumulative operations tracking**
* **Stateful rule execution (CUMULATIVE_DIFF)**
* **Automatic Overhaul triggering**
* **Lifecycle visibility in UI**
* **Reuse existing Test Type dropdown (no new module)**

---

## 3. Design Principles

| Layer               | Responsibility             |
| ------------------- | -------------------------- |
| Multi-session       | Data capture               |
| JSON Rules          | Define calculations        |
| Rule Engine         | Execute logic              |
| Service Layer       | Decision (threshold check) |
| DB (Recommendation) | Lifecycle state            |
| Workflow Engine     | Execution                  |
| UI                  | Visualization              |

---

## 4. UI Architecture Changes (Minimal & Reuse-Based)

### 4.1 Reuse Test Type Dropdown (UPDATED)

Instead of creating new module:

```text id="ui1"
Test Type:
Repair / Lifecycle
    ├── Breakdown Repair
    ├── Preventive Maintenance
    ├── Major Maintenance (Overhaul)
    └── Operations Tracking ⭐ (NEW)
```

---

### 4.2 Behavior Switch Based on Selection

When user selects:

```text id="ui2"
Operations Tracking
```

UI must:

* Enable **multi-session mode**
* Enable **rule configuration**
* Disable **pass/fail fields**
* Disable **manual workflow start**

---

### 4.3 Template Builder UI (Enhanced)

📄 `form_builder_screen.dart`

Add:

```text id="ui3"
Supports Multi-Session [ON]
```

Add Rule:

```text id="ui4"
Rule: CUMULATIVE_DIFF
```

Config:

```text id="ui5"
Order By: reading_date
Reset on drop: ✔
```

---

### 4.4 Multi-Session Entry UI (NEW USAGE)

📄 `session_list_screen.dart`

```text id="ui6"
Operations Tracking

[ + Add Session ]

Date        Reading     Status
--------------------------------
01 Jan      1000        ✔
01 Feb      1200        ✔
```

---

📄 `session_entry_screen.dart`

Dynamic fields:

* reading
* reading_date

---

### 4.5 Session Submission (Trigger Point)

```text id="ui7"
User clicks: Submit / Approve
```

Triggers backend processing.

---

### 4.6 Equipment Detail UI (NEW SECTION)

📄 `equipment_detail_screen.dart`

```text id="ui8"
Lifecycle Status

Cumulative: 500
Threshold: 400

Status: 🔴 OVERHAUL DUE
Workflow: [View]
```

---

### 4.7 Dashboard UI (Enhanced)

📄 `dashboard_screen.dart`

```text id="ui9"
🟢 Normal
🟡 Warning
🔴 Overhaul Due
```

---

### 4.8 Workflow UI (No Structural Change)

Only metadata added:

```text id="ui10"
Workflow Type: OVERHAUL
Source: CUMULATIVE
```

---

## 5. Data Flow

```text id="flow1"
User selects Operations Tracking
        ↓
User submits session (multi-session)
        ↓
Rule engine executes (CUMULATIVE_DIFF)
        ↓
Cumulative value calculated
        ↓
Threshold check
        ↓
OverhaulRecommendation created
        ↓
Workflow triggered automatically
        ↓
Dashboard + UI updated
```

---

## 6. Database Changes

### 6.1 RepairWorkflow

```python id="db1"
workflow_type = Column(String, default="BREAKDOWN")
source = Column(String)  # manual / cumulative / scheduled
```

---

### 6.2 Equipment Threshold Config

```python id="db2"
equipment_id
threshold_value
```

---

### 6.3 OverhaulRecommendation (Source of Truth)

```python id="db3"
equipment_id
workflow_id
cumulative_value
threshold_value
status  # OPEN / CLOSED
triggered_at
closed_at
```

---

### Constraints

* Only one OPEN recommendation per equipment
* Linked to workflow

---

## 7. Dynamic JSON Rule Structure

```json id="json1"
{
  "field": "reading",
  "rules": [
    {
      "type": "CUMULATIVE_DIFF",
      "config": {
        "order_by": "reading_date",
        "group_by": "equipment_id",
        "requires_multi_session": true,
        "reset_on_drop": true
      }
    }
  ]
}
```

---

## 8. Rule Engine Enhancements

### 8.1 Rule Type

```text id="rule1"
CUMULATIVE_DIFF
```

---

### 8.2 Execution Logic

```python id="rule2"
def cumulative_diff(rows, field):

    rows = sorted(rows, key=lambda x: x["reading_date"])

    total = 0
    for i in range(1, len(rows)):
        if rows[i][field] < rows[i-1][field]:
            continue

        total += rows[i][field] - rows[i-1][field]

    return total
```

---

### 8.3 Validation

* Only for multi-session templates
* Numeric field required
* order_by required

---

## 9. Service Layer

### 9.1 Trigger Point

```python id="svc1"
def _post_session_processing(self, workflow, stage_id):

    template = self._get_template(stage_id)

    if template.key != "operations_tracking":
        return

    self.evaluate_overhaul_trigger(workflow.equipment_id)
```

---

### 9.2 Overhaul Trigger Logic

```python id="svc2"
def evaluate_overhaul_trigger(self, equipment_id):

    cumulative = self._calculate_cumulative(equipment_id)
    threshold = self._get_threshold(equipment_id)

    if cumulative < threshold:
        return

    if self._get_open_overhaul(equipment_id):
        return

    self._trigger_overhaul_workflow(equipment_id, cumulative, threshold)
```

---

### 9.3 Cumulative Calculation

```python id="svc3"
def _calculate_cumulative(self, equipment_id):

    rows = self._get_all_sessions(equipment_id)

    rule = self._get_rule("reading", "CUMULATIVE_DIFF")

    return apply_rule(rule, rows)
```

---

### 9.4 Trigger Workflow

```python id="svc4"
def _trigger_overhaul_workflow(self, equipment_id, cumulative, threshold):

    workflow = self.start_workflow(
        equipment_id,
        workflow_type="OVERHAUL"
    )

    rec = OverhaulRecommendation(
        equipment_id=equipment_id,
        workflow_id=workflow.id,
        cumulative_value=cumulative,
        threshold_value=threshold
    )

    self.db.add(rec)
    self.db.commit()
```

---

## 10. Validation Rules

### Data

* reading must be numeric
* reading must not decrease
* duplicate dates not allowed

---

### Rule

* Only for multi-session
* Requires ordering

---

### Workflow

* Only one active overhaul
* Recommendation must close before new

---

## 11. Dashboard Logic

```python id="dash1"
if open_overhaul:
    status = "OVERHAUL_DUE"
elif cumulative >= threshold * 0.8:
    status = "WARNING"
else:
    status = "NORMAL"
```

---

## 12. API Response (UI Integration)

```json id="api1"
{
  "equipment_id": "UUID",
  "status": "OVERHAUL_DUE",
  "overhaul": {
    "cumulative": 500,
    "threshold": 400,
    "status": "OPEN"
  }
}
```

---

## 13. Final Flow

```text id="flow2"
Dropdown → Operations Tracking selected
        ↓
Multi-session entry
        ↓
Session submitted
        ↓
Rule engine executes
        ↓
Cumulative calculated
        ↓
Threshold reached
        ↓
Recommendation created
        ↓
Workflow triggered
        ↓
UI updated
```

---

## 14. Implementation Checklist

### Backend

* [ ] Add workflow_type field
* [ ] Create overhaul_recommendations table
* [ ] Create equipment_overhaul_config
* [ ] Implement CUMULATIVE_DIFF rule
* [ ] Add rule validation
* [ ] Hook post-session processing
* [ ] Implement trigger logic

---

### Frontend

* [ ] Update Test Type dropdown
* [ ] Add Operations Tracking subtype
* [ ] Add multi-session UI
* [ ] Extend form builder (rules + toggle)
* [ ] Update dashboard
* [ ] Add lifecycle section

---

## 15. Final Note

This design:

* Reuses existing UI components
* Keeps rules fully JSON-driven
* Avoids new modules
* Adds lifecycle intelligence cleanly

---

## Key Insight

> Same UI → smarter behavior
> Same dropdown → different engine
> Same workflows → better triggers

---
