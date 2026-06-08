# DFR / IDAX Transformer Testing — End-to-End Flow

> **Template:** `dfr_idax_transformer` — Dielectric Frequency Response (DFR / IDAX)
> **Equipment:** Power Transformer
> **Sessions:** 5 (FACTORY → SITE_RECEIPT → ON_BED → PRE_COMMISSIONING → MAINTENANCE)
> **Cross-session comparison:** Each non-FACTORY session is automatically compared against the FACTORY baseline. Deviations beyond configured thresholds raise ALERT or CRITICAL.

---

## Roles Involved

| Role | Who | Responsibilities |
|---|---|---|
| **Reviewing Officer** | AEE / EE (field supervisor) | Creates test request, reviews results, approves recommendation |
| **Test & Work Coordinator** | TWC / Section Officer | Assigns tester to the request |
| **Test Engineer** | Field tester | Fills in test data for each session |
| **Senior Management Approver** | SE / CE | Final approval on CRITICAL findings |

---

## Sample User IDs (for API testing)

```
Reviewing Officer   :  user_id = "rO-001"   email: reviewing.officer@org.com
Test & Work Coord.  :  user_id = "tWC-002"  email: twc.coordinator@org.com
Test Engineer       :  user_id = "tE-003"   email: test.engineer@org.com
Sr. Mgmt Approver   :  user_id = "sMA-004"  email: sr.approver@org.com
```

> In production, these are UUIDs from the `users` table.

---

## Step-by-Step Flow

---

### STEP 1 — Reviewing Officer creates the test request

**Who:** Reviewing Officer (`rO-001`)
**Status after:** `draft` → `submitted`

The Reviewing Officer raises a DFR test request for a Power Transformer via the app.

**What happens automatically:**
- `is_multi_session = True` is stamped from template (`supports_multi_session: true`)
- `total_sessions_planned = 5` is derived from `len(session_types)`
- `session_types = ["FACTORY", "SITE_RECEIPT", "ON_BED", "PRE_COMMISSIONING", "MAINTENANCE"]` returned in response

**API (Flutter calls):**
```
POST /testing_requests
{
  "title": "DFR Test — Transformer TX-220-001",
  "equipment_id": "<equipment_uuid>",
  "test_type_id": <dfr_test_type_id>,
  "organization_id": "<org_uuid>",
  "department_id": "<dept_uuid>",
  "priority": "high",
  "scheduled_start_date": "2026-07-01T00:00:00Z"
}

Response includes:
  "is_multi_session": true,
  "total_sessions_planned": 5,
  "session_types": ["FACTORY","SITE_RECEIPT","ON_BED","PRE_COMMISSIONING","MAINTENANCE"]
```

**Flutter UI:**
- Reviewing Officer sees the request in "My Requests" with status `submitted`
- No sessions exist yet

---

### STEP 2 — Test & Work Coordinator assigns a tester

**Who:** Test & Work Coordinator (`tWC-002`)
**Status after:** `submitted` → `accepted`

The coordinator reviews the submitted request and assigns a Test Engineer.

**API:**
```
PUT /testing_requests/{request_id}/assign
{
  "tester_id": "tE-003"
}
```

**Flutter UI:**
- TWC sees the request in the "Pending Assignment" queue
- Selects Test Engineer from the dropdown and confirms
- Test Engineer receives an in-app / email notification: *"You have been assigned a DFR test"*

---

### STEP 3 — Test Engineer accepts the assignment

**Who:** Test Engineer (`tE-003`)
**Status after:** `accepted` (no change — already set on assign)

**API:**
```
PUT /testing/{request_id}/accept
```

**Flutter UI:**
- Test Engineer sees the request in "My Tests"
- Taps **Accept** → request moves to active work queue

---

### STEP 4 — Sessions are auto-generated

**Who:** System (triggered by Flutter on first open of the Sessions tab)
**Sessions created:** 5

Flutter calls the auto-generate endpoint. The backend reads `session_types` from the DFR template and names sessions accordingly:

**API:**
```
POST /testing_requests/{request_id}/sessions/auto-generate
```

**Sessions created:**

| session_number | session_name       | status      |
|----------------|--------------------|-------------|
| 1              | `FACTORY`          | `scheduled` |
| 2              | `SITE_RECEIPT`     | `scheduled` |
| 3              | `ON_BED`           | `scheduled` |
| 4              | `PRE_COMMISSIONING`| `scheduled` |
| 5              | `MAINTENANCE`      | `scheduled` |

**Flutter UI:**
- Sessions panel shows 5 cards with the above names
- Each card shows status chip: 🔵 Scheduled
- Only **FACTORY** session is available to enter results first (tester starts from session 1)

---

### STEP 5 — Test Engineer fills FACTORY session (Baseline)

**Who:** Test Engineer (`tE-003`)
**Session:** `FACTORY` (session_number = 1)
**Status after:** session → `completed`; request → `in_progress`

The tester performs the DFR test at the factory / test lab and enters results.

**API:**
```
PUT /testing/{request_id}/results/structured
{
  "template_key": "dfr_idax_transformer",
  "test_session_id": "<factory_session_uuid>",
  "test_data": {
    "transformer_type": "Three Winding",
    "transformer_rating_mva": 100,
    "hv_voltage_kv": 220,
    "lv_voltage_kv": 33,
    "test_kit": "IDAX 350",
    "test_voltage_v": 140,
    "ambient_temp_c": 28,
    "oil_temp_c": 32,

    "dfr_measurements": [
      {"frequency_hz": 0.001, "capacitance_pf": 12450, "tan_delta_percent": 0.42},
      {"frequency_hz": 0.01,  "capacitance_pf": 12380, "tan_delta_percent": 0.38},
      {"frequency_hz": 0.1,   "capacitance_pf": 12310, "tan_delta_percent": 0.35},
      {"frequency_hz": 1.0,   "capacitance_pf": 12270, "tan_delta_percent": 0.31},
      {"frequency_hz": 10.0,  "capacitance_pf": 12240, "tan_delta_percent": 0.28}
    ],

    "analysis_results": [
      {"test_configuration":"HV-GND", "moisture_percent":0.8, "oil_conductivity_psm":12, "moisture_in_oil_percent":4.2, "assessment":"Good"},
      {"test_configuration":"HV-LV",  "moisture_percent":0.7, "oil_conductivity_psm":10, "moisture_in_oil_percent":3.8, "assessment":"Good"},
      {"test_configuration":"LV-GND", "moisture_percent":0.9, "oil_conductivity_psm":13, "moisture_in_oil_percent":4.5, "assessment":"Good"},
      {"test_configuration":"LV-TV",  "moisture_percent":0.8, "oil_conductivity_psm":11, "moisture_in_oil_percent":4.0, "assessment":"Good"},
      {"test_configuration":"TV-GND", "moisture_percent":0.7, "oil_conductivity_psm":10, "moisture_in_oil_percent":3.9, "assessment":"Good"},
      {"test_configuration":"TV-HV",  "moisture_percent":0.8, "oil_conductivity_psm":12, "moisture_in_oil_percent":4.1, "assessment":"Good"}
    ],

    "overall_result": "PASS"
  },
  "overall_result": "pass"
}
```

**What happens automatically:**
- `EvaluationService.run()` evaluates per-session thresholds → NORMAL (all values within range)
- Cross-session comparison: **skipped** — current session IS the FACTORY baseline
- Session 1 marked `completed`
- `evaluation_result.overall = "NORMAL"` stored on `TestResult`
- FACTORY baseline result stored → available for future sessions to compare against

**Flutter UI:**
- FACTORY session card turns green ✅ Completed
- SITE_RECEIPT session card becomes active → **Enter Results** button enabled

---

### STEP 6 — Transformer arrives on site → SITE_RECEIPT session

**Who:** Test Engineer (`tE-003`)
**Session:** `SITE_RECEIPT` (session_number = 2)
**Status after:** session → `completed`

Tester performs DFR test upon transformer arrival at site.

**API:**
```
PUT /testing/{request_id}/results/structured
{
  "template_key": "dfr_idax_transformer",
  "test_session_id": "<site_receipt_session_uuid>",
  "test_data": {
    "test_kit": "IDAX 350",
    "test_voltage_v": 140,
    "ambient_temp_c": 31,
    "oil_temp_c": 35,

    "dfr_measurements": [
      {"frequency_hz": 0.001, "capacitance_pf": 12440, "tan_delta_percent": 0.45},
      {"frequency_hz": 0.01,  "capacitance_pf": 12370, "tan_delta_percent": 0.41},
      {"frequency_hz": 0.1,   "capacitance_pf": 12300, "tan_delta_percent": 0.38},
      {"frequency_hz": 1.0,   "capacitance_pf": 12260, "tan_delta_percent": 0.34},
      {"frequency_hz": 10.0,  "capacitance_pf": 12230, "tan_delta_percent": 0.30}
    ],

    "analysis_results": [
      {"test_configuration":"HV-GND", "moisture_percent":0.9, "oil_conductivity_psm":13, "moisture_in_oil_percent":4.5, "assessment":"Good"},
      ...
    ],

    "overall_result": "PASS"
  }
}
```

**What happens automatically — Cross-Session Comparison:**

1. Backend fetches FACTORY baseline result
2. Compares `dfr_measurements.tan_delta_percent` (avg):
   - FACTORY avg: **0.348%**
   - SITE_RECEIPT avg: **0.376%**
   - Deviation: **+0.028%** → within `normal_max: 0.3` → **NORMAL** ✅
3. Compares `analysis_results` row-by-row by `test_configuration`:
   - `HV-GND moisture_percent`: 0.9 − 0.8 = **+0.1** → NORMAL ✅
   - All rows within normal range
4. `evaluation_result.overall = "NORMAL"` — no alert fired

**Flutter UI:**
- SITE_RECEIPT card turns green ✅
- No alert banner shown

---

### STEP 7 — ON_BED session (transformer installed, deviation detected)

**Who:** Test Engineer (`tE-003`)
**Session:** `ON_BED` (session_number = 3)

Tester performs DFR after transformer is placed on its foundation. Moisture has increased.

**API:**
```
PUT /testing/{request_id}/results/structured
{
  "test_session_id": "<on_bed_session_uuid>",
  "test_data": {
    "ambient_temp_c": 33,
    "oil_temp_c": 38,

    "dfr_measurements": [
      {"frequency_hz": 0.001, "tan_delta_percent": 1.10},
      {"frequency_hz": 0.01,  "tan_delta_percent": 0.98},
      {"frequency_hz": 0.1,   "tan_delta_percent": 0.88},
      {"frequency_hz": 1.0,   "tan_delta_percent": 0.79},
      {"frequency_hz": 10.0,  "tan_delta_percent": 0.72}
    ],

    "analysis_results": [
      {"test_configuration":"HV-GND", "moisture_percent":2.1, "oil_conductivity_psm":28, "moisture_in_oil_percent":7.2, "assessment":"Acceptable"},
      {"test_configuration":"HV-LV",  "moisture_percent":1.9, "oil_conductivity_psm":24, "moisture_in_oil_percent":6.8, "assessment":"Acceptable"},
      ...
    ],

    "overall_result": "ALERT"
  }
}
```

**What happens automatically — Cross-Session Comparison:**

| Field | FACTORY | ON_BED | Deviation | Threshold | Status |
|---|---|---|---|---|---|
| `tan_delta_percent` avg | 0.348% | 0.894% | **+0.546%** | critical_above: 1.5 | ⚠️ **ALERT** (normal_max: 0.3 exceeded) |
| `HV-GND moisture_percent` | 0.8% | 2.1% | **+1.3%** | critical_above: 1.0 | 🔴 **CRITICAL** |
| `HV-GND oil_conductivity_psm` | 12 pS/m | 28 pS/m | **+133%** | critical_above: 50% relative | 🔴 **CRITICAL** |
| `HV-GND moisture_in_oil_percent` | 4.2% | 7.2% | **+3.0%** | critical_above: 15.0 | ✅ NORMAL |

**Overall escalated to: `CRITICAL`**

**Cascading effects:**
- `result.overall_result` overridden to `"fail"`
- `evaluation_result.overall = "CRITICAL"` stored
- `evaluation_result.cross_session_comparison` stores full deviation breakdown
- `NotificationService.fire("eval_critical")` fired:
  - **Reviewing Officer** (`rO-001`) receives email + in-app: *"CRITICAL: DFR deviation on TX-220-001 — moisture increase 162% vs FACTORY baseline"*
  - **Senior Management Approver** (`sMA-004`) notified (if routing rule configured)
- If routing rule has `followup_action` → **ticket auto-created** (e.g. Maintenance Recommendation)

**Flutter UI:**
- ON_BED session card shows 🔴 CRITICAL badge
- Alert banner on request detail: *"Cross-session comparison: CRITICAL deviation detected vs FACTORY"*
- Deviation breakdown visible in session result view:
  ```
  HV-GND Moisture: 0.8% → 2.1% (+1.3%)  🔴 CRITICAL
  HV-GND Oil Conductivity: 12 → 28 pS/m (+133%)  🔴 CRITICAL
  Tan Delta (avg): 0.348 → 0.894% (+0.546%)  ⚠️ ALERT
  ```

---

### STEP 8 — Test Engineer submits all results

**Who:** Test Engineer (`tE-003`)
**Status after:** `in_progress` → `test_submitted`

After all planned sessions are completed (or the TWC decides to submit based on findings), the tester submits the final results with a recommendation.

**API:**
```
PUT /testing/{request_id}/submit_results
{
  "recommendation_type": "fail",
  "next_action": "maintenance",
  "summary": "Significant moisture ingress detected at ON_BED stage. Immediate drying treatment required before commissioning.",
  "outcome_notes": "HV-GND moisture increased from 0.8% to 2.1% vs FACTORY. Oil conductivity increased 133%."
}
```

> **Note:** If `is_multi_session = true` and not all 5 sessions are completed, submit_results blocks the recommendation until all sessions are done (or TWC force-submits).

**Status transitions:**
- Request → `test_submitted`
- Recommendation record created with `approval_status = "pending"`

---

### STEP 9 — Reviewing Officer reviews and approves

**Who:** Reviewing Officer (`rO-001`)
**Status after:** `test_submitted` → `approved` or `under_review`

**Flutter UI:**
- Reviewing Officer sees the request in the **Approvals** queue
- Opens the request → views:
  - All 5 session results
  - Cross-session comparison table (deviation per field per session vs FACTORY)
  - Auto-generated recommendation: *"Fail — Maintenance required"*
- Reviews evidence and either:
  - **Approves** → status = `approved`, recommendation goes to execution
  - **Rejects** → status = `under_review`, tester is notified to revise

**API (approve):**
```
POST /testing_requests/{request_id}/approve
```

**API (reject back to tester):**
```
PUT /testing/{request_id}/resubmit
{ "reason": "Please recheck ON_BED session oil temperature correction" }
```

---

### STEP 10 — Senior Management Approver gives final sign-off (if CRITICAL)

**Who:** Senior Management Approver (`sMA-004`)
**Status after:** `approved` → `outcome_active`

For CRITICAL findings, a second-level approval is required before the recommendation (maintenance/repair) is dispatched.

**Flutter UI:**
- Approver sees the CRITICAL flag and full deviation report
- Approves → recommendation dispatched → field team notified

---

## Status Flow Summary

```
draft
  ↓  [Reviewing Officer submits]
submitted
  ↓  [Test & Work Coordinator assigns tester]
accepted
  ↓  [Test Engineer accepts + enters first result]
in_progress
  │
  │  Session 1 (FACTORY)   → completed  [baseline stored, no comparison]
  │  Session 2 (SITE_RECEIPT) → completed  [compared vs FACTORY → NORMAL]
  │  Session 3 (ON_BED)    → completed  [compared vs FACTORY → CRITICAL 🔴]
  │  Session 4 (PRE_COMMISSIONING) → completed
  │  Session 5 (MAINTENANCE) → completed
  │
  ↓  [Test Engineer submits final results + recommendation]
test_submitted
  ↓  [Reviewing Officer approves]
approved
  ↓  [Senior Management Approver final sign-off on CRITICAL]
outcome_active
```

---

## Cross-Session Comparison — What's stored in `evaluation_result`

Each non-FACTORY session's `TestResult.evaluation_result` contains:

```json
{
  "overall": "CRITICAL",
  "evaluated_at": "2026-07-15T09:32:11Z",
  "fields": [
    {
      "key": "dfr_measurements.tan_delta_percent",
      "label": "DFR Measurements — tan_delta_percent (avg)",
      "type": "table_aggregate",
      "aggregate_type": "avg",
      "baseline_value": 0.348,
      "current_value": 0.894,
      "deviation": 0.546,
      "deviation_type": "absolute",
      "status": "ALERT"
    },
    {
      "key": "analysis_results.moisture_percent",
      "label": "Analysis Results [HV-GND] — moisture_percent",
      "type": "table_row",
      "row_id": "HV-GND",
      "baseline_value": 0.8,
      "current_value": 2.1,
      "deviation": 1.3,
      "deviation_type": "absolute",
      "status": "CRITICAL"
    },
    {
      "key": "analysis_results.oil_conductivity_psm",
      "label": "Analysis Results [HV-GND] — oil_conductivity_psm",
      "type": "table_row",
      "row_id": "HV-GND",
      "baseline_value": 12.0,
      "current_value": 28.0,
      "deviation": 133.33,
      "deviation_type": "relative_percent",
      "status": "CRITICAL"
    }
  ],
  "cross_session_comparison": {
    "overall": "CRITICAL",
    "evaluated_at": "2026-07-15T09:32:11Z",
    "fields": [ ... ]
  }
}
```

---

## Thresholds Reference (DFR Template)

### `dfr_measurements` — `tan_delta_percent` (aggregate avg)

| Deviation (absolute) | Status |
|---|---|
| ≤ 0.3% | NORMAL |
| > 0.3% | ALERT |
| > 1.5% | CRITICAL |

### `analysis_results` — `moisture_percent` (row-by-row)

| Deviation (absolute) | Status |
|---|---|
| ≤ 0.3% | NORMAL |
| > 0.3% | ALERT |
| > 1.0% | CRITICAL |

### `analysis_results` — `oil_conductivity_psm` (row-by-row, relative %)

| Deviation (relative %) | Status |
|---|---|
| ≤ 20% | NORMAL |
| > 20% | ALERT |
| > 50% | CRITICAL |

### `analysis_results` — `moisture_in_oil_percent` (row-by-row)

| Deviation (absolute) | Status |
|---|---|
| ≤ 5.0% | NORMAL |
| > 5.0% | ALERT |
| > 15.0% | CRITICAL |

---

## Key API Endpoints Reference

| Action | Method | Endpoint |
|---|---|---|
| Create test request | `POST` | `/testing_requests` |
| Assign tester | `PUT` | `/testing_requests/{id}/assign` |
| Accept assignment | `PUT` | `/testing/{id}/accept` |
| Auto-generate sessions | `POST` | `/testing_requests/{id}/sessions/auto-generate` |
| List sessions | `GET` | `/testing_requests/{id}/sessions` |
| Save session results | `PUT` | `/testing/{id}/results/structured` |
| Submit final results | `PUT` | `/testing/{id}/submit_results` |
| Approve results | `POST` | `/testing_requests/{id}/approve` |
| Reject / resubmit | `PUT` | `/testing/{id}/resubmit` |
| Get request detail (includes session_types) | `GET` | `/testing_requests/{id}` |

---

*Generated: 2026-06-03 | Template: dfr_idax_transformer v1*
