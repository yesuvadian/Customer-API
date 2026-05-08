# CogniWatt — Notification System: Functional Flow & Test Reference

---

## 1. Architecture Overview

```
Event occurs (e.g. TR submitted)
  |
  v
NotificationService.fire_event(db, event_type, source_id, source_type, context)
  |
  +-- Query: active NotificationTemplate(s) for org + event_type
  |
  +-- For each matching template + each recipient role/email:
  |     |
  |     +-- VariableResolver.build_context(db, source_type, source_id, extra=context)
  |     |     Resolves {{dept.code}}, {{user.name}}, {{tr.status}}, etc.
  |     |
  |     +-- _render(subject_template, context)  -> rendered subject
  |     +-- _render(body_template,    context)  -> rendered HTML body
  |     |
  |     +-- CREATE NotificationLog  (status=pending, attachment_vars copied from template)
  |     +-- CREATE UserNotification (in-app bell entry, is_read=False)
  |
  v
APScheduler — process_pending_notifications (every 1 min)
  |
  +-- Fetch NotificationLog where status=pending AND send_after <= now
  |
  +-- For each log:
  |     +-- _build_report_attachments(db, source_type, source_id, attachment_vars)
  |     |     -> generates PDF and/or Excel bytes from the triggering record
  |     |
  |     +-- _send_email(log, to_email, subject, body, attachments)
  |     |     If attachments:  EmailService.send_multi_attachment_email_starttls()
  |     |     Otherwise:       EmailService.send_email_starttls()
  |     |
  |     +-- log.status = "sent"    (on success)
  |         log.status = "failed"  (on error, increments attempt_count)
  |
  v
APScheduler — retry_failed_notifications (every 5 min)
  |
  +-- Fetch logs where status=failed AND attempt_count < 3
  +-- Same send pipeline as above
  +-- After 3 failures: status = "permanently_failed"

APScheduler — fire_overdue_reminders (daily 08:00)
  |
  +-- Scans all active schedule rules (trigger_type in due_soon / overdue / escalation)
  +-- Fires fire_event() for each matching TR that meets the time condition
```

---

## 2. Variable Injection

Templates support `{{double.brace}}` and `{single.brace}` syntax. The renderer normalises both before resolving.

### Built-in system variables (33 total — partial list)

| Variable | Resolves to |
|---|---|
| `{{dept.code}}` | Department code (e.g. RT_NORTH) |
| `{{dept.name}}` | Department display name |
| `{{user.name}}` | Recipient's full name |
| `{{user.email}}` | Recipient's email |
| `{{tr.id}}` | Testing Request UUID |
| `{{tr.status}}` | Current TR status |
| `{{tr.category}}` | Request category (test/inspection/maintenance…) |
| `{{tr.submitted_at}}` | Submission timestamp |
| `{{equipment.ueic}}` | Equipment unique ID (e.g. ZO-1A-066-01-PT-01) |
| `{{equipment.name}}` | Equipment display name |
| `{{org.name}}` | Organisation name |
| `{{org.code}}` | Organisation code |

### Custom org variables

Created via `POST /notifications/variables`. Use `{{var_key}}` in any template body or subject.

---

## 3. Email Body — HTML Source Editor (Flutter UI)

The notification template config page uses `_HtmlSourceEditor` — an HTML source editor with a formatting toolbar backed by a plain `TextEditingController`. The body is stored and sent as raw HTML.

### How it works

- **Editor type**: HTML source editor (type HTML directly; toolbar wraps selection in tags)
- **Toolbar buttons**: B · I · U · H2 · H3 · p · ul · li · a · br · span(color) · `{{}}`
- **Variable insertion**: "Insert Variable" button opens a picker; inserts `{{var.key}}` at the cursor
- **Preview mode**: Toggle renders the HTML via `flutter_html` package (live preview)
- **Subject**: Plain text field with variable insert button
- **Save**: Reads `_emailBodyCtrl.text` directly — no async conversion needed
- **Web/index.html**: Summernote CDN links are present for a future full WYSIWYG upgrade

### Toolbar buttons

| Button | Wraps selection in | Result |
|---|---|---|
| **B** | `<b>…</b>` | Bold |
| *I* | `<i>…</i>` | Italic |
| U | `<u>…</u>` | Underline |
| H2 | `<h2>…</h2>` | Heading 2 |
| H3 | `<h3>…</h3>` | Heading 3 |
| p | `<p>…</p>` | Paragraph |
| ul | `<ul><li>…</li></ul>` | Bulleted list |
| li | `<li>…</li>` | List item |
| a | `<a href="">…</a>` | Hyperlink |
| br | `…<br>` | Line break |
| span | `<span style="color:#0066cc">…</span>` | Coloured text |
| `{{}}` | `{{…}}` | Variable placeholder |

### Flutter widget flow

```
NotificationTemplateConfigPage
  |
  +-- EventTypeList (left panel)
  |     Lists all 15 event types, grouped by category
  |
  +-- TemplateEditorSheet (bottom sheet — opens on tap)
        |
        +-- _EventTypeSelector     (dropdown: which event)
        +-- _RecipientSection      (role checkboxes + extra emails)
        +-- _ChannelToggleRow      (Email / SMS / In-App toggles)
        |
        +-- _EmailChannelSection   (shown when Email enabled)
        |     +-- Subject TextFormField + "Insert variable" button
        |     +-- _HtmlSourceEditor  (formatting toolbar + HTML textarea)
        |     +-- _VarPickerButton   (inserts {{var.key}} at cursor)
        |     +-- [Preview] toggle   (renders HTML via flutter_html)
        |     +-- _AttachmentVarsSection (PDF/Excel attachment config)
        |     +-- HtmlEditor       (Summernote — full rich text)
        |     +-- _VariablePickerAccordion (insert {{var}} at cursor)
        |     +-- _AttachmentVarsSection (PDF / Excel attachment config)
        |
        +-- _SmsChannelSection     (plain text body)
        +-- _InAppChannelSection   (plain text body)
        |
        +-- [Save] -> POST /notifications/templates/bulk-upsert
```

---

## 4. Attachment Pipeline (PDF / Excel)

When `attachment_vars` is configured on a template's email channel the service generates and attaches reports in-memory at send time — no URLs, no pre-stored files.

### attachment_vars format (stored on NotificationTemplate + copied to NotificationLog)

```json
[
  {"var_key": "report.retriepdf",  "type": "pdf"},
  {"var_key": "report.retriexls",  "type": "excel"}
]
```

### Source type to report service mapping

| `source_type` | PDF generator | Excel generator |
|---|---|---|
| `test_result` | `TestResultPDFService` | `ReportingService(query_key="test_result_report")` |
| `testing_request` | `TestingRequestPDFService` | `ReportingService(query_key="testing_request_report")` |
| `recommendation` | `RecommendationPDFService` | `ReportingService(query_key="recommendation_report")` |
| `equipment_replacement` | `EquipmentReplacementPDFService` | — |
| `approval` | `ReportService.generate_approval_report()` | — |

Attachments are sent via `EmailService.send_multi_attachment_email_starttls(attachments=[...])`.

---

## 5. Routing Rules

Routing rules override which channels and recipients receive notifications for specific workflow types or test categories.

### API

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/notifications/routing-rules/meta` | `workflow_types`, `test_types`, `channels` (no auth gate) |
| GET | `/notifications/routing-rules` | Global defaults + org overrides (org admin only) |
| POST | `/notifications/routing-rules` | Create org rule |
| PUT | `/notifications/routing-rules/{id}` | Update |
| DELETE | `/notifications/routing-rules/{id}` | Soft-delete org rule |
| POST | `/notifications/routing-rules/{id}/clone` | Clone global as org override |

### Payload example

```json
{
  "event_type": "eval_critical",
  "applicable_workflow_types": ["repair_cycle"],
  "applicable_test_types": ["power_transformer"],
  "channels_enabled": ["email", "inapp"],
  "recipient_roles": ["EE TLSS", "Technical Approver"],
  "extra_recipient_emails": ["manager@kptcl.com"],
  "is_active": true
}
```

---

## 6. Schedule Rules

Schedule rules drive time-based and status-transition notifications.

### API

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/notifications/schedule-rules/meta` | trigger types, severity levels, workflow statuses (no auth gate) |
| GET | `/notifications/schedule-rules` | Global + org overrides (org admin only) |
| POST | `/notifications/schedule-rules` | `label` field required |
| PUT | `/notifications/schedule-rules/{id}` | Update |
| DELETE | `/notifications/schedule-rules/{id}` | Soft-delete org rule |
| POST | `/notifications/schedule-rules/{id}/clone` | Clone global as org override |

### Trigger types

| Type | When |
|---|---|
| `due_soon` | N days BEFORE test due date |
| `overdue` | Test passes due date without completion |
| `escalation` | Overdue by more than N days |
| `status_transition` | Workflow status changes to a specified value |
| `both` | Time-based AND status-based combined |

### Payload example

```json
{
  "event_type": "due_reminder",
  "label": "5-day due-soon alert",
  "trigger_type": "due_soon",
  "offset_days": 5,
  "severity": "info",
  "applicable_workflow_types": ["direct_test", "schedule"],
  "applicable_categories": ["test", "inspection"],
  "is_active": true
}
```

---

## 7. Admin Backend

**Prefix**: `/admin/notifications/`  
**Auth**: Internal admin (not org-scoped)

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/admin/notifications/seed-defaults` | Seeds global templates for all 15 event types |
| GET | `/admin/notifications/templates` | All templates (global + all org overrides) |
| GET | `/admin/notifications/logs` | Full audit log, paginated |
| POST | `/admin/notifications/test-fire` | Fires notification without needing a real event |

### Test-fire payload example

```json
{
  "event_type": "eval_critical",
  "source_id": "19b12a73-ae7b-4431-8e23-451c01e9b695",
  "source_type": "test_result",
  "context": {
    "equipment.ueic": "ZO-1A-066-01-PT-01",
    "dept.name": "RT North Division"
  }
}
```

---

## 8. Dept Isolation

| User | Notifications visible |
|---|---|
| `tester.north` | Only for North dept events assigned to them |
| `originator.south` | Only for South dept events |
| `orgadmin.north` | Dept-level — North dept events only |
| `orgadmin@kptcl.com` | All org events (org-level admin) |

Template management (`/notifications/templates`, routing rules, schedule rules) is restricted to users with `OrgRole.is_org_admin = True`. Only the top-level `orgadmin@kptcl.com` has this flag. Dept-level org admins (`orgadmin.north` etc.) get `403`.

---

## 9. Test Scenarios (test_api.py sections 15A–15F)

### Section 15A — User bell endpoints

| Test | API | Token | Expected |
|---|---|---|---|
| List notifications | `GET /notifications` | Originator | `200` |
| Unread count | `GET /notifications/unread-count` | Originator | `200`, has `count` field |
| Severity counts | `GET /notifications/counts` | Originator | `200`, has `critical/alert/info/total` |
| Filter unread | `GET /notifications?unread_only=true` | Originator | `200` |
| Mark one read | `PUT /notifications/{id}/read` | Originator | `200` |
| Mark all read | `PUT /notifications/read-all` | Originator | `200` |
| Unauth gate | `GET /notifications` (no token) | — | `401` |

### Section 15B — Admin template management

| Test | API | Token | Expected |
|---|---|---|---|
| Non-admin blocked | `GET /notifications/templates` | Originator | `403` |
| Event catalogue | `GET /notifications/templates/event-types` | KptclAdmin | `200`, 15 event types |
| System variables | `GET /notifications/templates/system-variables` | KptclAdmin | `200`, ≥ 33 vars |
| List templates | `GET /notifications/templates` | KptclAdmin | `200` |
| Filter by event | `GET /notifications/templates?event_type=eval_critical` | KptclAdmin | `200` |
| Channel group | `GET /notifications/templates/event/{type}` | KptclAdmin | `200`, email channel has `attachment_vars` |
| Bulk upsert | `POST /notifications/templates/bulk-upsert` | KptclAdmin | `200`, `attachment_vars` count = 2 |
| Single create | `POST /notifications/templates` | KptclAdmin | `201` |

### Section 15C — Variable registry

| Test | API | Token | Expected |
|---|---|---|---|
| List variables | `GET /notifications/variables` | KptclAdmin | `200`, 33 rows |
| Create custom | `POST /notifications/variables` | KptclAdmin | `201` |
| Delete system var | `DELETE /notifications/variables/{sys_id}` | KptclAdmin | `403` — system vars protected |

### Section 15D — Routing rules

| Test | API | Token | Expected |
|---|---|---|---|
| Meta (no auth) | `GET /notifications/routing-rules/meta` | any | `200` |
| List | `GET /notifications/routing-rules` | KptclAdmin | `200` |
| Create | `POST /notifications/routing-rules` | KptclAdmin | `201` |
| Update | `PUT /notifications/routing-rules/{id}` | KptclAdmin | `200` |
| Clone global | `POST /notifications/routing-rules/{id}/clone` | KptclAdmin | `200/201/409` |
| Delete | `DELETE /notifications/routing-rules/{id}` | KptclAdmin | `204` |

### Section 15E — Schedule rules

| Test | API | Token | Expected |
|---|---|---|---|
| Meta (no auth) | `GET /notifications/schedule-rules/meta` | any | `200` |
| List | `GET /notifications/schedule-rules` | KptclAdmin | `200` |
| Create (missing label) | `POST /notifications/schedule-rules` (no `label`) | KptclAdmin | `422` |
| Create (with label) | `POST /notifications/schedule-rules` (`label` present) | KptclAdmin | `201` |
| Update | `PUT /notifications/schedule-rules/{id}` | KptclAdmin | `200` |
| Clone global | `POST /notifications/schedule-rules/{id}/clone` | KptclAdmin | `200/201/409` |
| Delete | `DELETE /notifications/schedule-rules/{id}` | KptclAdmin | `204` |

### Section 15F — Admin backend

| Test | API | Token | Expected |
|---|---|---|---|
| Seed defaults | `POST /admin/notifications/seed-defaults` | KptclAdmin | `200` |
| List all templates | `GET /admin/notifications/templates` | KptclAdmin | `200`, ≥ 71 rows after seed |
| List logs | `GET /admin/notifications/logs` | KptclAdmin | `200` |
| Test-fire | `POST /admin/notifications/test-fire` | KptclAdmin | `200` |

---

## 10. Event Types (15 total)

| Event type | Group | Description |
|---|---|---|
| `eval_critical` | Testing | Test result flagged as critical |
| `eval_alert` | Testing | Test result flagged as alert |
| `tr_submitted` | Testing | New testing request submitted |
| `tr_assigned` | Testing | Tester assigned to TR |
| `tr_completed` | Testing | TR results approved |
| `approval_pending` | Approval | Awaiting technical/finance approval |
| `approval_decision` | Approval | Approval granted or rejected |
| `procurement_decision` | Procurement | Finance approver decision |
| `equipment_replacement` | Equipment | Equipment flagged for replacement |
| `due_reminder` | Scheduling | N days before test due date |
| `overdue_alert` | Scheduling | Test is overdue |
| `escalation` | Scheduling | Escalation after prolonged overdue |
| `recommendation_pending` | Workflow | New recommendation awaiting review |
| `repair_stage_advance` | Workflow | Repair workflow stage advanced |
| `direct_submission` | Workflow | Failure Registry / TA&QC submitted |
