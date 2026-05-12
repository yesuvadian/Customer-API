# 📅 Calibration Lifecycle Implementation Plan (No Schema Change)

---

# 1. 🧠 Objective

Implement **Calibration Lifecycle Management** using the **existing schema only**:

* `testing_requests` → execution layer
* `test_results` → dynamic data (JSON)
* `equipment` → master entity

Aligned with cumulative design principles

---

# 2. 🔗 Core Design Principle

```text
CUMULATIVE:
Sessions → Aggregate → Threshold → Action

CALIBRATION:
Records → Date Logic → Next Due → Ticket → Repeat
```

---

# 3. ⚙️ No Schema Change Strategy

We will **NOT modify tables**.

All logic will be handled using:

* JOINs
* JSON extraction
* Runtime rule engine

---

# 4. 🧩 Calibration Identification

```text
test_type_id = CALIBRATION
```

---

# 5. 🔁 Data Flow

```text
Scheduler
   ↓
Create testing_request (Calibration)
   ↓
User fills dynamic form (JSON)
   ↓
test_results inserted
   ↓
Service layer extracts fields
   ↓
Rule engine executes
   ↓
Decision:
   • Next due
   • State
   • Recommendation
   ↓
Scheduler plans next cycle
```

---

# 6. ⚙️ Data Source (Existing)

## 6.1 Join to get Equipment

```sql
SELECT tr.*, req.equipment_id
FROM test_results tr
JOIN testing_requests req ON req.id = tr.testing_request_id
WHERE req.test_type_id = CALIBRATION;
```

---

## 6.2 Extract from JSON

Example stored in `test_results.test_data`:

```json
{
  "calibration_date": "2025-01-01",
  "validity_months": 12,
  "overall_result": "Fail"
}
```

---

## 6.3 Dynamic Form Definition (Add to Template)

Define these fields in your dynamic form (aligned with your template pattern):

```json
{
  "title": "Calibration",
  "fields": [
    {
      "key": "calibration_date",
      "label": "Calibration Date",
      "type": "date",
      "required": true
    },
    {
      "key": "validity_months",
      "label": "Validity (Months)",
      "type": "number",
      "required": true
    },
    {
      "key": "overall_result",
      "label": "Result",
      "type": "dropdown",
      "options": ["Pass", "Fail"],
      "required": true
    }
  ]
}
```

These fields will be stored inside `test_data` JSON and used by the rule engine at runtime.

---

# 7. ⚙️ Rule Engine (Runtime Only)

---

## 7.1 Extract Fields

```python
data = test_data

calibration_date = data["calibration_date"]
validity_months = data["validity_months"]
result = data["overall_result"]
```

---

## 7.2 Next Due (DATE_ADD)

```python
next_due = calibration_date + validity_months
```

---

## 7.3 State Logic

```python
if result == "Fail":
    state = "CRITICAL"
else:
    state = "NORMAL"
```

---

## 7.4 Failure Handling

```python
if result == "Fail":
    create_recommendation("REPAIR_OR_REPLACE")
    stop_calibration_schedule(equipment_id)
```

---

# 8. ⏰ Scheduler Logic

---

## 8.1 Fetch Latest Calibration

```sql
SELECT tr.*
FROM test_results tr
JOIN testing_requests req ON req.id = tr.testing_request_id
WHERE req.equipment_id = :eq_id
  AND req.test_type_id = CALIBRATION
ORDER BY (tr.test_data->>'calibration_date')::timestamptz DESC
LIMIT 1;
```

---

## 8.2 Pre-Due Trigger

```python
trigger_date = next_due - lead_days

if today >= trigger_date:
    create_testing_request()
```

---

# 9. 🔴 Failure Lifecycle

```text
Calibration → Fail
      ↓
State → CRITICAL (computed, not stored)
      ↓
Stop scheduling
      ↓
Trigger Repair / Replacement
```

---

# 10. 🔁 Recovery Flow

```text
Repair / Replacement completed
      ↓
New Calibration request
      ↓
Pass
      ↓
Resume schedule
```

---

# 11. 📊 UI Behavior

---

## 11.1 Calibration Form

```text
Calibration Date: [input]
Validity: [input]
Result: [Pass / Fail]

System State: 🔒 Computed
Next Due: 🔒 Computed
```

---

## 11.2 Equipment View (Computed)

```text
EQ-001

State: 🔴 CRITICAL
Last Calibration: 2025 (Fail)
Next Due: Computed at runtime
```

---

# 12. 🔐 Constraints

* No updates to old records (append-only)
* Always use latest calibration record
* Only calibration records drive calibration logic
* State is computed (not stored)

---

# 13. 🧩 Mapping to Cumulative Design

| Cumulative         | Calibration               |
| ------------------ | ------------------------- |
| Sessions           | test_results              |
| Group by equipment | JOIN via testing_requests |
| CUMULATIVE_DIFF    | DATE_ADD                  |
| Threshold          | Next Due Date             |
| Overhaul trigger   | Pre-due ticket            |

---

# 14. ⚠️ Known Limitations

| Area        | Limitation           |
| ----------- | -------------------- |
| Performance | JOIN + JSON parsing  |
| Indexing    | No index on next_due |
| State       | Not persisted        |
| Scheduler   | Logic-heavy          |

---

# 15. 🚀 Future (Optional Enhancements)

* Extract key fields into columns (performance)
* Store `current_state` in equipment
* Add state history table
* Add drift tracking (error % trends)

---

# 🏁 Final Summary

```text
testing_requests → execution
test_results → dynamic data (JSON)
equipment → master
rule engine → runtime logic
scheduler → lifecycle driver
```

---

# 💡 One-Line Insight

> Even without schema changes, calibration can run as a full lifecycle engine using computed logic.
