# GAP 4 — Annual Audit Escalation Notifications

## Status
Deferred. To be implemented in a future sprint.

---

## Design Requirement (§14E–14G)

When an annual audit observation becomes overdue (`is_overdue = true`), the system must send escalation notifications to the following roles in the observation's organisation:

| Escalation Level | Role |
|---|---|
| Level 1 | EE TLSS |
| Level 2 | SEE W&M |
| Level 3 | CEE Transmission Zone |

### Escalation Trigger Condition (§14E)

```text
today > target_compliance_date
AND current_stage_code != OBSERVATION_CLOSURE
```

### Escalation Flow (§14G)

```text
Observation overdue
    ↓
Scheduler detects SLA breach (daily at 09:00)
    ↓
is_overdue = true
    ↓
Notification created
    ↓
Alerts sent to:
    - EE TLSS
    - SEE W&M
    - CEE Transmission Zone
```

---

## Where to Implement

**File:** `C:\Yesu\CustomerAPI\Customer-API\services\annual_audit_service.py`

**Method:** `run_overdue_check()` — extend to call a new `_send_escalation_notifications()` helper after setting `is_overdue = True`.

---

## Implementation Notes

- Resolve escalation recipients via `OrgUserRole` → `OrgRole` join, filtered by `OrgRole.name IN ('EE TLSS', 'SEE W&M', 'CEE Transmission Zone')` and `organization_id`.
- Use `UserNotification` model (table: `user_notifications`) for in-app notifications.
- **Dedup guard required:** Check if a `UserNotification` with `event_type = 'annual_audit_escalation'` and `source_id = obs.id` was already created today before inserting. This prevents duplicate alerts on repeated scheduler runs.
- Notification payload:
  - `event_type`: `"annual_audit_escalation"`
  - `title`: `"Overdue Audit Observation: {observation_number}"`
  - `body`: Include observation number, substation UEIC, days overdue, severity.
  - `severity`: `"critical"`
  - `source_id`: `obs.id`
  - `source_type`: `"annual_audit_observation"`

---

## Scheduler Integration

The daily scheduler job `_annual_audit_overdue_check` in `main.py` already runs at 09:00 UTC and calls `run_overdue_check()`. Once this gap is implemented, escalation notifications will fire automatically as part of that job — no additional scheduler change is needed.

---

## Models Required

| Model | Table | Purpose |
|---|---|---|
| `OrgUserRole` | `org_user_roles` | Join to resolve users by role |
| `OrgRole` | `org_roles` | Filter by escalation role names |
| `UserNotification` | `user_notifications` | Store in-app notification per recipient |

---

## Notification Routing (Optional Enhancement)

The existing `NotificationService.fire()` can also dispatch email/push notifications if a `NotificationTemplate` row is configured for `event_type = 'annual_audit_escalation'`. This can be configured via the admin UI without code changes once the `UserNotification` insertion is in place.
