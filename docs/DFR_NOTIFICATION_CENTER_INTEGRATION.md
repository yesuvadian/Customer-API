# DFR Cross-Session Alerts — Notification Center Integration

> How `eval_alert` and `eval_critical` events from cross-session comparison
> are wired through the Notification Center to reach the right people
> and optionally create follow-up tickets automatically.

---

## The Event Pipeline

```
Tester saves ON_BED session results
        │
        ▼
EvaluationService.run()            ← per-session threshold check
        │
        ▼
evaluate_cross_session()           ← deviation vs FACTORY baseline
        │
        │  moisture +1.3% > critical_above 1.0%
        │  oil conductivity +133% > critical_above 50%
        ▼
ev["overall"] escalated → "CRITICAL"
result.overall_result   → "fail"    ← synced automatically
        │
        ▼
_build_threshold_config_html(ev)   ← renders TWO tables:
        │                             1. Per-session thresholds
        │                             2. Cross-session deviations vs FACTORY
        ▼
NotificationService.fire("eval_critical", context={
    "request.number":        "TR-20260715-0042",
    "equipment.ueic":        "TX-220-001",
    "eval.test_type":        "Dielectric Frequency Response (DFR / IDAX)",
    "eval.overall":          "CRITICAL",
    "tester_name":           "John Doe",
    "eval.evaluated_at":     "2026-07-15 09:32",
    "alert.thresholdconfig": "<table>…per-session…</table>
                              <table>…cross-session…</table>",
    "revised_interval":      "—"
})
        │
        ├──► Find matching NotificationRoutingRule
        │         event_type     = eval_critical
        │         equipment_type = Power Transformer  ← scope filter
        │         workflow_type  = multisession        ← scope filter
        │
        ├──► Dispatch channels (email / SMS / in-app)
        │         to configured recipient roles
        │
        └──► Execute followup_action (if configured)
                  → auto-create Maintenance ticket
```

---

## Step 1 — Event Catalogue (pre-seeded, no setup needed)

Two events are seeded into `NotificationEventCatalogue`:

| Event | Label | Group | Default Roles |
|---|---|---|---|
| `eval_critical` | Threshold Critical | Threshold Alerts | Reviewing Officer, Supervisory Officer, Senior Management Approver, Maintenance Officer |
| `eval_alert` | Threshold Alert | Threshold Alerts | Reviewing Officer, Maintenance Officer |

Both events now carry full cross-session context and are visible in the Notification Center under the **Threshold Alerts** tab immediately — no admin action required.

### Available context variables

| Variable | Description | Example |
|---|---|---|
| `{{equipment}}` | Equipment label | `TX-220-001` |
| `{{equipment.ueic}}` | UEIC code | `UEIC-220-TX-001` |
| `{{eval.test_type}}` | Test name | `Dielectric Frequency Response (DFR / IDAX)` |
| `{{eval.overall}}` | Severity | `CRITICAL` |
| `{{eval.evaluated_at}}` | Timestamp | `2026-07-15 09:32` |
| `{{request.number}}` | Request number | `TR-20260715-0042` |
| `{{tester_name}}` | Tester's full name | `John Doe` |
| `{{result_summary}}` | Auto-generated summary | `Moisture deviation CRITICAL on HV-GND` |
| `{{revised_interval}}` | Revised test interval (if set) | `90 days` |
| `{{alert.thresholdconfig}}` | **Auto-rendered HTML table** — both per-session thresholds and cross-session deviations (see below) | `<table>…</table>` |

> **`{{alert.thresholdconfig}}` is the key variable.** Drop it into your email template body and it automatically renders two sections: per-session threshold breaches and cross-session deviation vs FACTORY baseline — no extra template logic needed.

---

## How `{{alert.thresholdconfig}}` renders

The `_build_threshold_config_html()` function produces two tables when cross-session fields are present:

### Section 1 — Per-session threshold breaches (if any)

```
┌───────────────────┬──────────────┬──────────┬────────┬────────┬──────────┐
│ Parameter         │ Measured Val │ Status   │ Normal │ Alert  │ Critical │
├───────────────────┼──────────────┼──────────┼────────┼────────┼──────────┤
│ Overall Result    │ FAIL         │ CRITICAL │  —     │  —     │  —       │
└───────────────────┴──────────────┴──────────┴────────┴────────┴──────────┘
```

### Section 2 — Cross-Session Comparison (vs FACTORY baseline)

Rendered in green-header style to visually distinguish from per-session:

```
Cross-Session Comparison (vs FACTORY baseline)
┌────────────────────────────────┬──────────┬─────────┬────────────┬──────────┐
│ Parameter                      │ Baseline │ Current │ Deviation  │ Status   │
├────────────────────────────────┼──────────┼─────────┼────────────┼──────────┤
│ Analysis Results [HV-GND]      │ 0.8%     │ 2.1%    │ +1.3%      │ CRITICAL │
│ — moisture_percent             │          │         │            │          │
├────────────────────────────────┼──────────┼─────────┼────────────┼──────────┤
│ Analysis Results [HV-GND]      │ 12 pS/m  │ 28 pS/m │ +133.33%   │ CRITICAL │
│ — oil_conductivity_psm         │          │         │            │          │
├────────────────────────────────┼──────────┼─────────┼────────────┼──────────┤
│ DFR Measurements               │ 0.348%   │ 0.894%  │ +0.546%    │ ALERT    │
│ — tan_delta_percent (avg)      │          │         │            │          │
└────────────────────────────────┴──────────┴─────────┴────────────┴──────────┘
```

If only per-session thresholds fired (no cross-session), only Section 1 is shown.
If only cross-session deviations fired, only Section 2 is shown.
If both fired, both sections appear in one `{{alert.thresholdconfig}}` block.

---

## Step 2 — Admin configures a Routing Rule

**Who:** Org Admin
**Where:** Organization → Notification Center → Threshold Alerts tab → `eval_critical` → Configure → + Add Rule

### Rule for DFR / Power Transformer CRITICAL

```
Event:           eval_critical

── Scope Filters ──────────────────────────────────────────────
Workflow:        [multisession]
Equipment Type:  [Power Transformer]

── Notification Routing ───────────────────────────────────────
Channels:        [✅ Email]  [✅ In-App]
Recipient Roles: [Reviewing Officer]  [Senior Management Approver]

── Template Variant ───────────────────────────────────────────
Email template:  "DFR Critical Alert"   ← custom variant (Step 3)

── Follow-Up Action ───────────────────────────────────────────
Auto-create ticket:  [✅ Yes]
Next Action:         [Maintenance]
Frequency:           [Yearly]
Summary:             "CRITICAL insulation deviation — drying/maintenance required"
```

### Rule for DFR ALERT (monitoring only)

```
Event:           eval_alert
Workflow:        [multisession]
Equipment Type:  [Power Transformer]
Channels:        [✅ In-App]
Recipient Roles: [Reviewing Officer]
Follow-Up:       None
```

---

## Step 3 — Admin creates a notification template

**Where:** Organization → Notification Center → Templates → eval_critical → + New Variant

```
Name:    DFR Critical Alert
Event:   eval_critical
Channel: email

Subject:
  🔴 CRITICAL: DFR Insulation Deviation — {{equipment}} ({{request.number}})

Body:
  <p>A <strong>CRITICAL insulation deviation</strong> has been detected during
  DFR / IDAX testing on transformer <strong>{{equipment}}</strong>.</p>

  <p><strong>Tested by:</strong> {{tester_name}}<br/>
  <strong>Evaluated at:</strong> {{eval.evaluated_at}}<br/>
  <strong>Request:</strong> {{request.number}}</p>

  <h3>Threshold & Deviation Report</h3>
  {{alert.thresholdconfig}}

  <p>Please review immediately and authorise corrective action.</p>
```

> The admin inserts `{{alert.thresholdconfig}}` from the variable picker in the template editor — it is now listed as an available variable for `eval_critical` and `eval_alert` events.

---

## Step 4 — What happens at runtime

```
1. Tester saves ON_BED results (session 3 of DFR test)
        ↓
2. Cross-session comparison: CRITICAL
   (moisture +1.3%, oil conductivity +133% vs FACTORY)
        ↓
3. result.overall_result set to "fail" automatically
        ↓
4. NotificationService.fire("eval_critical") called
   alert.thresholdconfig = two-section HTML table (built automatically)
        ↓
5. Routing rule match:
   eval_critical + Power Transformer + multisession → Rule found
        ↓
6. Channels dispatched:
   ┌─ Email → Reviewing Officer + Senior Management Approver
   │          "DFR Critical Alert" template
   │          Body contains cross-session deviation table
   │
   └─ In-App → Bell notification to same roles
               "🔴 CRITICAL: DFR Insulation Deviation — TX-220-001"
        ↓
7. followup_action:
   - Guard: no open Maintenance request for TX-220-001?
   - Create Maintenance TestingRequest:
     title: "CRITICAL insulation deviation — drying/maintenance required"
     source: TR-20260715-0042
```

---

## Step 5 — What recipients see

### In-App notification

```
🔴  CRITICAL Threshold Alert
    TX-220-001 · DFR / IDAX · TR-20260715-0042
    Moisture [HV-GND]: 0.8% → 2.1% (+1.3%)  CRITICAL
    Tap to view →
```

### Email (rendered `{{alert.thresholdconfig}}`)

```
Subject: 🔴 CRITICAL: DFR Insulation Deviation — TX-220-001 (TR-20260715-0042)

A CRITICAL insulation deviation has been detected during DFR / IDAX testing
on transformer TX-220-001.

Tested by: John Doe
Evaluated at: 2026-07-15 09:32
Request: TR-20260715-0042

Threshold & Deviation Report

[Per-session table — if any per-session fields breached]

Cross-Session Comparison (vs FACTORY baseline)
┌────────────────────────────┬──────────┬─────────┬───────────┬──────────┐
│ Parameter                  │ Baseline │ Current │ Deviation │ Status   │
├────────────────────────────┼──────────┼─────────┼───────────┼──────────┤
│ Analysis [HV-GND] moisture │ 0.8%     │ 2.1%    │ +1.3%     │ CRITICAL │
│ Analysis [HV-GND] oil cond │ 12 pS/m  │ 28 pS/m │ +133.33%  │ CRITICAL │
│ DFR tan_delta (avg)        │ 0.348%   │ 0.894%  │ +0.546%   │ ALERT    │
└────────────────────────────┴──────────┴─────────┴───────────┴──────────┘

Please review immediately and authorise corrective action.
```

### Auto-created Maintenance ticket

```
Maintenance Request — TR-20260715-0043
Title:      CRITICAL insulation deviation — drying/maintenance required
Equipment:  TX-220-001
Status:     submitted
Source:     TR-20260715-0042 (DFR test)
```

---

## Notification Center UI — Wiring Explanation (updated)

The **"How threshold alerts are triggered"** help text in the Notification Center now reads:

1. Threshold limits are defined inside each test template field (critical / alert / normal bands).
2. When the tester submits results, the engine evaluates every measured value against those bands.
3. If any value falls outside the normal band the engine fires an `eval_alert` or `eval_critical` event automatically.
4. For multi-session templates with cross-session comparison enabled (e.g. DFR / IDAX), the engine also compares the current session against the baseline session (e.g. FACTORY). Deviations beyond the configured thresholds escalate the same `eval_alert` / `eval_critical` event — no separate setup needed.
5. Use `{{alert.thresholdconfig}}` in your email template body to automatically render both per-session and cross-session deviation tables.
6. This configuration decides who receives the notification and via which channels.

---

## Multiple Routing Rules — Layered Coverage

```
Rule 1 — DFR CRITICAL (org-specific, priority 10)
  eval_critical + Power Transformer + multisession
  → Email + In-App to Reviewing Officer + Sr. Mgmt
  → Auto-create Maintenance ticket

Rule 2 — DFR ALERT (org-specific, priority 10)
  eval_alert + Power Transformer + multisession
  → In-App only to Reviewing Officer
  → No ticket (monitor only)

Rule 3 — All CRITICAL fallback (global, priority 0)
  eval_critical + (any equipment) + (any workflow)
  → Email + In-App to Reviewing Officer
  → No ticket
```

Org-specific rules (priority 10) always win over global fallback (priority 0).

---

## What was changed in the codebase

| File | Change |
|---|---|
| `services/testing_service.py` | `_build_threshold_config_html()` now renders two separate tables — per-session (existing) and cross-session deviation (new green-header section) |
| `seed.py` | `eval_critical` / `eval_alert` event catalogue entries updated: descriptions mention cross-session; `alert.thresholdconfig`, `request.number`, `tester_name`, `revised_interval` added to `context_vars` |
| `lib/pages/organization/notification_center_page.dart` | Wiring explanation updated: steps 4 and 5 added explaining cross-session and `{{alert.thresholdconfig}}` |

---

## No-Setup Fallback

If no routing rule is configured at all:

> All channels fire to all default roles for `eval_critical`:
> Reviewing Officer, Supervisory Officer, Senior Management Approver, Maintenance Officer

The cross-session CRITICAL alert will still be delivered — the Notification Center configuration is only needed for org-specific scoping, custom templates, and auto-ticket creation.

---

*Template: `dfr_idax_transformer` v1 | Updated: 2026-06-03*
