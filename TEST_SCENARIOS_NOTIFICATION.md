# SEACMS — Notification Template Configuration
## UI Test Scenarios · Equipment Replacement · Test Workflow · Variable Design

**System URL:** `http://localhost:53232` (Flutter app)  
**API Base:** `http://127.0.0.1:8000`  
**Org:** Karnataka Power Transmission Corporation Limited (KPTCL)  
**Password (all users):** `admin123`

---

## 👤 Users & Roles Reference

| Login Email | Role | Can Manage Notification Templates? |
|---|---|---|
| `orgadmin@kptcl.com` | **Org Admin** | ✅ Yes — full CRUD on templates |
| `originator@kptcl.com` | Originator | ❌ No — 403 from API |
| `ee.tlss@kptcl.com` | EE TLSS | ❌ No |
| `see.wm@kptcl.com` | SEE W&M | ❌ No |
| `cee.zone@kptcl.com` | CEE Transmission Zone | ❌ No |
| `aee.maintenance@kptcl.com` | AEE Maintenance | ❌ No |
| `depthead@kptcl.com` | Department Head | ❌ No |
| `fieldtester1@kptcl.com` | Field Tester | ❌ No |
| `testassigner@kptcl.com` | Test Assigner | ❌ No |

> **Rule:** Only the user assigned the org-admin role (is_org_admin = true) can view and configure
> notification templates. All other roles receive a 403 Forbidden and the Templates tab
> either hides its content or shows an access-denied message.

---

## 📋 Navigation Path

```
Login → My Organization → [Notifications tab]
```

The Organization Detail page has 4 tabs:

| Tab | Icon | Who Sees Content |
|---|---|---|
| Departments | apartment | All org members |
| Users | people | All org members |
| Roles | admin_panel_settings | All org members |
| **Notifications** | notifications_active | **Org Admin only** |

---

## 🔔 Event Type Catalogue (11 Events · 5 Groups)

| Group | Event Type | Label |
|---|---|---|
| **Equipment** | `equipment_replacement` | Equipment Replacement |
| **Evaluation** | `eval_critical` | Critical Test Result |
| **Evaluation** | `eval_alert` | Alert Test Result |
| **Test Workflow** | `request_submitted` | Test Request Submitted |
| **Test Workflow** | `request_assigned` | Test Request Assigned to Tester |
| **Test Workflow** | `test_submitted` | Test Results Submitted |
| **Test Workflow** | `request_approved` | Test Request Approved |
| **Test Workflow** | `request_rejected` | Test Request Rejected / Returned |
| **Scheduling** | `due_reminder` | Test Due Soon Reminder |
| **Scheduling** | `test_overdue` | Test Overdue |
| **Recommendations** | `recommendation_approved` | Recommendation Approved |

---

## 📦 System Variable Registry (30 Variables · 7 Groups)

These variables can be inserted into any subject or body template using `{{var.key}}` syntax.

### Group: Reports
| Variable | Label | Sample Value |
|---|---|---|
| `{{report.retriexls}}` | Report — Excel Download URL | `https://app/reports/RPT-001.xlsx` |
| `{{report.retriepdf}}` | Report — PDF Download URL | `https://app/reports/RPT-001.pdf` |
| `{{report.ref}}` | Report Reference Number | `RPT-2026-001` |
| `{{report.generated_on}}` | Report Generated Date/Time | `2026-05-04 10:30` |

### Group: Equipment
| Variable | Label | Sample Value |
|---|---|---|
| `{{equipment.ueic}}` | Equipment UEIC | `ZO-1A-220-01-PT-01` |
| `{{equipment.type}}` | Equipment Type | `Power Transformer` |
| `{{equipment.department}}` | Substation / Department | `110kV Adaki` |
| `{{equipment.status}}` | Equipment Status | `active` |
| `{{equipment.manufacturer}}` | Manufacturer | `Siemens` |

### Group: Replacement
| Variable | Label | Sample Value |
|---|---|---|
| `{{old_ueic}}` | Retired UEIC | `ZO-1AN-220-01-CT-01` |
| `{{new_ueic}}` | New Replacement UEIC | `ZO-1AN-220-01-CT-02` |
| `{{replaced_by}}` | Replaced By (User) | `Admin User` |
| `{{replaced_on}}` | Replacement Date | `2026-05-04` |
| `{{reason}}` | Replacement Reason | `IR test failed — 42 MΩ` |

### Group: Test Request
| Variable | Label | Sample Value |
|---|---|---|
| `{{request.number}}` | Test Request Number | `REQ-2026-001` |
| `{{request.title}}` | Test Request Title | `Annual IR Test — PT-01` |
| `{{request.status}}` | Request Status | `submitted` |
| `{{request.priority}}` | Priority | `high` |
| `{{request.due_date}}` | Due Date | `2026-06-01` |
| `{{request.submitted_by}}` | Submitted By | `Originator User` |
| `{{request.assigned_to}}` | Assigned To (Tester) | `Field Tester 1` |

### Group: Evaluation
| Variable | Label | Sample Value |
|---|---|---|
| `{{eval.overall}}` | Overall Result | `CRITICAL` |
| `{{eval.test_type}}` | Test Type | `Insulation Resistance` |
| `{{eval.evaluated_at}}` | Evaluation Date/Time | `2026-05-04 14:00` |

### Group: Organisation
| Variable | Label | Sample Value |
|---|---|---|
| `{{org.name}}` | Organisation Name | `Karnataka Power Transmission Corporation Limited` |
| `{{org.id}}` | Organisation ID | `<uuid>` |

### Group: System
| Variable | Label | Sample Value |
|---|---|---|
| `{{system.date}}` | Today's Date | `2026-05-04` |
| `{{system.time}}` | Current Time | `10:30:22` |
| `{{system.app_name}}` | Application Name | `SEACMS` |

---

## 🔷 PART A — ACCESS CONTROL

---

### TS-NA-01 · Non-Admin Cannot Access Notification Templates

**Login:** `ee.tlss@kptcl.com` (EE TLSS — read-only role)

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in with `ee.tlss@kptcl.com / admin123` | Dashboard loads |
| 2 | Navigate to **My Organization** | Organization Detail page opens |
| 3 | Count tabs in the tab bar | 4 tabs visible: Departments · Users · Roles · Notifications |
| 4 | Tap the **Notifications** tab | Tab content attempts to load |
| 5 | Observe the Notifications tab content | Error state: "Only org admins can manage notification templates." OR spinner then error |
| 6 | Verify no event type cards are shown | List area is empty / shows access-denied message |
| 7 | Repeat with `fieldtester1@kptcl.com` | Same result — no access |

**Pass criteria:** Non-admin sees the Notifications tab but gets a clear access-denied message. No template data is rendered.

---

### TS-NA-02 · Org Admin Loads Notification Template List

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in with `orgadmin@kptcl.com / admin123` | Dashboard loads |
| 2 | Navigate to **My Organization** | KPTCL organization detail opens |
| 3 | Tap **Notifications** tab | Loading spinner appears briefly |
| 4 | List renders | Blue info banner: _"Tap any event to configure its channels…"_ |
| 5 | Count event groups | 5 section headers: **EQUIPMENT · EVALUATION · TEST WORKFLOW · SCHEDULING · RECOMMENDATIONS** |
| 6 | Count total event cards | 11 event cards |
| 7 | Observe `Equipment Replacement` card | Shows channel badges: **● Email · ● SMS · ● In-App** (all 3 seeded) |
| 8 | Observe an unconfigured event (e.g. `recommendation_approved`) | Shows "Not configured" in orange |

**Pass criteria:** All 11 event types visible, grouped correctly. Pre-seeded channels shown as badges.

---

## 🔷 PART B — CHANNEL CONFIGURATION

---

### TS-NC-01 · Configure All 3 Channels for Equipment Replacement

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Equipment Replacement** card | Editor bottom sheet opens (slides up) |
| 2 | Observe sheet header | Title: "Equipment Replacement" · sub-label: `equipment_replacement` |
| 3 | Observe **CHANNELS** section | 3 toggle buttons: **Email · SMS · In-App** (all pre-populated from global defaults) |
| 4 | All 3 toggles show filled radio `●` indicator | Confirms all channels currently enabled |
| 5 | **Email** toggle shows `org override` sub-label | KPTCL has its own email template (not global) |
| 6 | Scroll to **EMAIL TEMPLATE** section | Subject field + Body (HTML) field visible |
| 7 | Verify subject field pre-filled | `[KPTCL] Equipment Replacement — {{old_ueic}}` (or global default) |
| 8 | Verify body field pre-filled | HTML body with `{{old_ueic}}`, `{{new_ueic}}`, `{{replaced_on}}` etc. |
| 9 | Scroll to **SMS TEMPLATE** section | Single body field visible (no subject for SMS) |
| 10 | Scroll to **IN-APP NOTIFICATION** section | Body field visible |
| 11 | Scroll to **RECIPIENTS** section | Role checkboxes: `EE TLSS`, `SEE W&M`, `CEE Transmission Zone` selected |
| 12 | Scroll to **CONTEXT VARIABLES** hint box | Shows all available vars for this event: `{{old_ueic}}`, `{{new_ueic}}`, `{{replaced_by}}` etc. |
| 13 | Tap **Cancel** | Sheet dismisses without saving |

**Pass criteria:** All 3 channels pre-loaded from existing KPTCL/global config. Context variable hint shows event-specific vars.

---

### TS-NC-02 · Disable SMS Channel, Keep Email + In-App

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Equipment Replacement** card | Editor opens |
| 2 | Tap **SMS** toggle (currently `●` enabled) | SMS toggles OFF — radio becomes `○`; SMS body section collapses |
| 3 | **Email** and **In-App** remain enabled | Email + In-App sections still visible |
| 4 | Scroll to check — no SMS body editor visible | SMS section completely hidden |
| 5 | Scroll to **RECIPIENTS** | `EE TLSS`, `SEE W&M`, `CEE Transmission Zone` checked |
| 6 | Tap **Save Templates** | Spinner; success snackbar "Notification templates saved." |
| 7 | Sheet dismisses | Equipment list of event types refreshes |
| 8 | Equipment Replacement card | Shows only **● Email · ● In-App** badges — no SMS badge |

**Pass criteria:** SMS channel deactivated for org. Only 2 channel badges on card. Email + In-App remain active.

---

### TS-NC-03 · Enable a Previously Unconfigured Event

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Recommendation Approved** card | Editor opens |
| 2 | All 3 channel toggles show `○` (off) | No existing configuration |
| 3 | Orange warning box visible | "Enable at least one channel above to configure this notification." |
| 4 | Tap **In-App** toggle | In-App toggles ON `●`; In-App body field appears |
| 5 | Type in body field: `Recommendation for {{equipment.ueic}} has been approved by {{approved_by}}.` | Text entered |
| 6 | Scroll to **RECIPIENTS** section | Checkboxes for all org roles |
| 7 | Check `Originator` and `AEE Maintenance` | Both selected |
| 8 | Tap **Save Templates** | Success |
| 9 | Check the **Recommendation Approved** card | Now shows **● In-App** badge; no longer shows "Not configured" |

**Pass criteria:** Previously unconfigured event now shows In-App badge. Orange warning disappears after enabling.

---

## 🔷 PART C — TEMPLATE BODY DESIGN

---

### TS-TB-01 · Edit Email Subject and Body (Equipment Replacement)

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Equipment Replacement** → editor opens | |
| 2 | Clear the **Subject** field | Field is empty |
| 3 | Type new subject: `[KPTCL Alert] {{old_ueic}} Replaced at {{equipment.department}}` | Text entered |
| 4 | Scroll to **Body (HTML)** field | Existing HTML body visible |
| 5 | Clear the body field | Empty |
| 6 | Type the following HTML body: | |

```html
<p>Dear {{org.name}} Team,</p>

<p>This is to inform you that equipment <b>{{old_ueic}}</b>
({{equipment.type}}) at <i>{{equipment.department}}</i> has been
<b>retired and replaced</b> on <b>{{replaced_on}}</b>.</p>

<table border="1" cellpadding="6" style="border-collapse:collapse;">
  <tr>
    <td><b>Retired UEIC</b></td>
    <td>{{old_ueic}}</td>
  </tr>
  <tr>
    <td><b>Replacement UEIC</b></td>
    <td>{{new_ueic}}</td>
  </tr>
  <tr>
    <td><b>Replaced By</b></td>
    <td>{{replaced_by}}</td>
  </tr>
  <tr>
    <td><b>Reason</b></td>
    <td>{{reason}}</td>
  </tr>
</table>

<p>
  Download Replacement Report:<br/>
  PDF → {{report.retriepdf}}<br/>
  Excel → {{report.retriexls}}
</p>

<p>— {{system.app_name}} · {{system.date}}</p>
```

| 7 | Verify body field scrolls smoothly | Multi-line editor handles long HTML |
| 8 | Tap **Save Templates** | Success snackbar |

**Pass criteria:** Subject and body saved with `{{}}` placeholders intact.

---

### TS-TB-02 · Use Variable Picker to Insert Variable at Cursor

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open **Test Request Submitted** event editor | Sheet opens |
| 2 | Enable **Email** channel | Email body field appears |
| 3 | Tap inside the **Body** field | Cursor placed |
| 4 | Type: `A new test request has been submitted: ` | Text typed; cursor at end |
| 5 | Tap **+ Insert Variable** button (next to Body label) | Variable picker modal slides up |
| 6 | Picker shows accordion groups | Reports · Equipment · Replacement · Test Request · Evaluation · Organisation · System |
| 7 | Expand **Test Request** group | Variables: `{{request.number}}`, `{{request.title}}`, `{{request.priority}}` etc. |
| 8 | Tap `{{request.number}}` | Picker dismisses; text field now reads: `A new test request has been submitted: {{request.number}}` |
| 9 | Tap **+ Insert Variable** again | Picker opens |
| 10 | Type `equipment` in the search bar | Filters to show only equipment-related variables |
| 11 | Tap `{{equipment.ueic}}` | Inserted after cursor position in body |
| 12 | Verify body: `…{{request.number}} for equipment {{equipment.ueic}}` | Correct insertion |

**Pass criteria:** Variable picker inserts `{{var}}` syntax at current cursor position. Search filter works. Accordion groups expand/collapse.

---

### TS-TB-03 · Preview Mode — Render Sample Values

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open **Equipment Replacement** event editor | Sheet with body content |
| 2 | Ensure body contains: `Equipment {{old_ueic}} replaced by {{new_ueic}} on {{replaced_on}}.` | Template text visible |
| 3 | Tap **Preview** button (top-right of sheet) | Button label changes to **Edit**; icon changes to pencil |
| 4 | Observe Email subject field | Now shows rendered box (blue background): `[KPTCL Alert] ZO-1AN-220-01-CT-01 Replaced at 110kV Adaki` |
| 5 | Observe Email body preview box | Rendered text with sample values substituted: `Equipment ZO-1AN-220-01-CT-01 replaced by ZO-1AN-220-01-CT-02 on 2026-05-04.` |
| 6 | Unrecognized variable `{{unknown.key}}` in body | Rendered as-is: `{{unknown.key}}` (no substitution) |
| 7 | Tap **Edit** button | Returns to editable text fields |
| 8 | Body is unchanged — original `{{old_ueic}}` syntax preserved | Preview does not modify the stored template |

**Pass criteria:** Preview replaces all known `{{var}}` with sample values. Unknown vars shown as-is. Edit mode restores editable fields.

---

## 🔷 PART D — RECIPIENT CONFIGURATION

---

### TS-RR-01 · Set Recipient Roles for Equipment Replacement

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open **Equipment Replacement** editor | |
| 2 | Scroll to **RECIPIENTS** section | Role chips visible; pre-selected: `EE TLSS`, `SEE W&M`, `CEE Transmission Zone` |
| 3 | Tap `EE TLSS` chip (currently selected) | Chip deselects — border turns grey |
| 4 | Tap `AEE Maintenance` chip (currently unselected) | Chip selects — blue border |
| 5 | Tap `Originator` chip | Chip selects |
| 6 | Final selection: `SEE W&M`, `CEE Transmission Zone`, `AEE Maintenance`, `Originator` | 4 chips selected |
| 7 | Tap **Save Templates** | Saved |
| 8 | Re-open **Equipment Replacement** editor | |
| 9 | Verify 4 chips still selected | Persisted correctly |

**Pass criteria:** Role selection persists across saves. Role chips correctly toggle.

---

### TS-RR-02 · Add Extra Email Recipients

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open any event editor (e.g. **Critical Test Result**) | |
| 2 | Scroll to **EXTRA EMAIL RECIPIENTS** section | Empty chip area + email input row |
| 3 | Type `station.manager@kptcl.com` in email input | Text entered |
| 4 | Tap the **+** button | Email chip added; input cleared |
| 5 | Type `zone.engineer@kptcl.gov.in` and press **Enter/Return** | Second chip added |
| 6 | Attempt to add `not-an-email` (no `@`) | Nothing added — invalid email ignored |
| 7 | Tap `×` on the first chip | `station.manager@kptcl.com` chip removed |
| 8 | Save and re-open | `zone.engineer@kptcl.gov.in` persisted as extra recipient |

**Pass criteria:** Chips add/remove correctly. Invalid email (missing @) rejected. Persists across save.

---

### TS-RR-03 · Configure All Roles for Critical Test Result

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Critical Test Result** card | Editor opens |
| 2 | Enable **Email** channel | Email section visible |
| 3 | Set subject: `[CRITICAL] Test Result — {{equipment.ueic}} at {{equipment.department}}` | |
| 4 | Set body: | |

```html
<p><b style="color:red;">⚠ CRITICAL TEST RESULT DETECTED</b></p>

<p>Equipment: <b>{{equipment.ueic}}</b> ({{equipment.type}})<br/>
Location: {{equipment.department}}<br/>
Test Type: {{eval.test_type}}<br/>
Overall Result: <b>{{eval.overall}}</b><br/>
Evaluated On: {{eval.evaluated_at}}</p>

<p>Report Downloads:<br/>
PDF: {{report.retriepdf}}<br/>
Excel: {{report.retriexls}}</p>

<p>Immediate action required. — {{system.app_name}}</p>
```

| 5 | Enable **In-App** channel | In-App body field appears |
| 6 | Set In-App body: `⚠ CRITICAL: {{equipment.ueic}} — {{eval.test_type}} result is CRITICAL. Review required.` | |
| 7 | In RECIPIENTS: select `EE TLSS`, `SEE W&M`, `CEE Transmission Zone`, `AEE Maintenance` | 4 roles selected |
| 8 | Add extra email: `safety.officer@kptcl.com` | Chip added |
| 9 | Tap **Save** | Success |
| 10 | Card shows: **● Email · ● In-App** badges | SMS not enabled for critical alerts |

**Pass criteria:** 2 channels configured with rich HTML body and correct recipients.

---

## 🔷 PART E — TEST WORKFLOW NOTIFICATIONS

---

### TS-TW-01 · Configure Test Request Submitted Notification

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Test Request Submitted** card | Editor opens |
| 2 | Enable **Email** and **In-App** channels | Both sections visible |
| 3 | Set Email subject: `[SEACMS] New Test Request: {{request.number}}` | |
| 4 | Set Email body: | |

```html
<p>A new test request has been submitted and requires your attention.</p>

<table>
  <tr><td><b>Request #</b></td><td>{{request.number}}</td></tr>
  <tr><td><b>Title</b></td><td>{{request.title}}</td></tr>
  <tr><td><b>Priority</b></td><td>{{request.priority}}</td></tr>
  <tr><td><b>Equipment</b></td><td>{{equipment.ueic}}</td></tr>
  <tr><td><b>Department</b></td><td>{{equipment.department}}</td></tr>
  <tr><td><b>Submitted By</b></td><td>{{request.submitted_by}}</td></tr>
</table>

<p>Please review and assign a tester. — {{system.app_name}}</p>
```

| 5 | Set In-App body: `New request {{request.number}}: {{request.title}} (Priority: {{request.priority}})` | |
| 6 | RECIPIENTS: select `EE TLSS`, `Department Head` | |
| 7 | Save | Success |

**Pass criteria:** Email + In-App configured for request submission event.

---

### TS-TW-02 · Configure Request Rejected / Returned Notification

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Test Request Rejected / Returned** card | Editor opens |
| 2 | Enable **Email**, **SMS**, **In-App** | All 3 sections visible |
| 3 | Email subject: `[Action Required] Test Request {{request.number}} Rejected` | |
| 4 | Email body: | |

```html
<p>Your test request has been rejected or returned for rework.</p>

<p><b>Request:</b> {{request.number}} — {{request.title}}<br/>
<b>Equipment:</b> {{equipment.ueic}}<br/>
<b>Rejection Reason:</b> {{reason}}</p>

<p>Please review the feedback and resubmit. — {{system.app_name}}</p>
```

| 5 | SMS body: `[SEACMS] Request {{request.number}} rejected. Reason: {{reason}}. Please resubmit.` | Max ~160 chars |
| 6 | In-App body: `Request {{request.number}} returned. Reason: {{reason}}` | |
| 7 | RECIPIENTS: select `Originator`, `Field Tester`, `Lab Tester` | Notifies the requestor and assigned tester |
| 8 | Save | Success |
| 9 | Card shows: **● Email · ● SMS · ● In-App** | All 3 channels active |

**Pass criteria:** All 3 channels configured; SMS body kept concise.

---

### TS-TW-03 · Configure Request Approved Notification with Report Links

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Test Request Approved** card | Editor opens |
| 2 | Enable **Email** and **In-App** | |
| 3 | Email subject: `[SEACMS] Test Request {{request.number}} Approved — Reports Ready` | |
| 4 | In body, tap **+ Insert Variable** | Picker opens |
| 5 | Search `report` in picker search bar | Filters to show only Report group variables |
| 6 | Tap `{{report.retriepdf}}` | Inserted in body |
| 7 | Tap **+ Insert Variable** again | |
| 8 | Tap `{{report.retriexls}}` | Inserted |
| 9 | Complete body: | |

```html
<p>The test request has been approved. Your reports are ready for download.</p>

<p><b>Request:</b> {{request.number}} — {{request.title}}<br/>
<b>Equipment:</b> {{equipment.ueic}}<br/>
<b>Submitted By:</b> {{request.submitted_by}}</p>

<p>
  📄 <a href="{{report.retriepdf}}">Download PDF Report</a><br/>
  📊 <a href="{{report.retriexls}}">Download Excel Report</a>
</p>

<p>— {{system.app_name}} · {{system.date}}</p>
```

| 10 | RECIPIENTS: `Originator`, `AEE Maintenance` | |
| 11 | Save | Success |

**Pass criteria:** Report download links (`{{report.retriepdf}}`, `{{report.retriexls}}`) embedded in body using variable picker.

---

## 🔷 PART F — END-TO-END NOTIFICATION FIRE VERIFICATION

---

### TS-NF-01 · Notification Fired on Equipment Replacement

**Login sequence:** First admin (configure), then originator (trigger), then verify in-app.

**Prerequisites:**
- `equipment_replacement` event has **In-App** channel enabled with `Originator` in recipient roles

| # | User | Step | Expected Result |
|---|---|---|---|
| 1 | `orgadmin@kptcl.com` | Open Notifications tab → `equipment_replacement` → verify In-App enabled with `Originator` role | Confirmed |
| 2 | `originator@kptcl.com` | Log in → Equipment → find active equipment (e.g. `ZO-1A-220-01-CB-01`) → tap **Replace** | Replace dialog opens |
| 3 | `originator@kptcl.com` | Select reason type `Based on test recommendation`, enter reason text, fill new equipment details → **Submit Replace** | Success dialog: Retired UEIC (orange) + New UEIC (green) |
| 4 | `ee.tlss@kptcl.com` | Log in → observe **bell icon** in app bar | Unread badge count incremented |
| 5 | `ee.tlss@kptcl.com` | Tap bell icon → notification list | Entry: "Equipment Replacement" with the old and new UEIC details |
| 6 | `ee.tlss@kptcl.com` | Tap the notification | Marked as read; badge count decrements |

**Pass criteria:** In-app notification delivered to all users in recipient roles. Bell badge updates. Notification body contains rendered UEIC values.

---

### TS-NF-02 · Email Notification Delivered on Critical Test Result

**Note:** Requires SMTP configured in environment (or check API logs for outbound email payload).

| # | User | Step | Expected Result |
|---|---|---|---|
| 1 | `orgadmin@kptcl.com` | Confirm `eval_critical` event has **Email** enabled with recipients `EE TLSS`, `SEE W&M` | Confirmed in Notifications tab |
| 2 | (System) | Test evaluation result marked CRITICAL via test session workflow | `eval_critical` event fired |
| 3 | API logs | Check server log for notification dispatch | `[NOTIF] email dispatched → ee.tlss@kptcl.com` |
| 4 | `ee.tlss@kptcl.com` | Check email inbox | Email received: subject `[CRITICAL] Test Result — ZO-…` |
| 5 | Email body | Inspect rendered values | `{{equipment.ueic}}` → actual UEIC; `{{eval.overall}}` → `CRITICAL` |

**Pass criteria:** Email dispatched; `{{}}` variables resolved with actual evaluation data.

---

## 🔷 PART G — EDGE CASES & VALIDATION

---

### TS-NE-01 · Save with No Channels Enabled

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open any event editor | |
| 2 | Disable all 3 channels | All toggles `○`; orange warning box visible |
| 3 | Tap **Save Templates** | Save proceeds (no client-side block) |
| 4 | API: all 3 channels deactivated for org | Global defaults remain active for fire() |
| 5 | Card in list | Shows "Not configured" (no org override) — global defaults still fire |

**Pass criteria:** Save with no channels enabled deactivates org overrides. Global defaults continue to apply.

---

### TS-NE-02 · Save Email Template Without Subject

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open **Equipment Replacement** editor | |
| 2 | Enable **Email** channel | Email section visible |
| 3 | Clear **Subject** field completely | Empty |
| 4 | Set body text | |
| 5 | Tap **Save** | Save proceeds — subject is optional for email |
| 6 | Re-open editor | Subject field shows empty |

**Pass criteria:** Empty subject allowed. No client-side validation error.

---

### TS-NE-03 · Variable Picker Search — Empty Results

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open any event editor → tap **+ Insert Variable** | Picker opens |
| 2 | Type `xyz123nonexistent` in search bar | |
| 3 | Observe picker content | "No variables found." message |
| 4 | Clear search field | All groups restore |
| 5 | Type `ueic` | Filters to show `{{equipment.ueic}}` and `{{old_ueic}}`, `{{new_ueic}}` |

**Pass criteria:** Empty state shown for no-match search. Clearing restores full list.

---

### TS-NE-04 · Global Default Templates Cannot Be Deleted

**API Level** (verify via Swagger or curl):

| # | Call | Expected |
|---|---|---|
| 1 | `GET /notifications/templates?channel=email` | Returns global templates with `organization_id = null` |
| 2 | `DELETE /notifications/templates/{global_template_id}` | `404 Not Found` — "Template not found or is a global default" |

**Pass criteria:** System default templates are protected from deletion. Only org overrides can be deactivated.

---

## 🔷 PART H — TEMPLATE DESIGN REFERENCE

The following are recommended template designs for the KPTCL deployment.

---

### Template: `equipment_replacement` — Email

**Subject:**
```
[KPTCL] Equipment {{old_ueic}} Replaced at {{equipment.department}}
```

**Body (HTML):**
```html
<div style="font-family:Arial,sans-serif;max-width:600px;">
  <h2 style="color:#d97706;">⚡ Equipment Replacement Notice</h2>

  <p>Dear {{org.name}} Team,</p>

  <p>Equipment <b>{{old_ueic}}</b> ({{equipment.type}}) at
  <i>{{equipment.department}}</i> has been retired and replaced.</p>

  <table border="1" cellpadding="8" cellspacing="0"
         style="border-collapse:collapse;width:100%;">
    <tr style="background:#f3f4f6;">
      <td><b>Retired UEIC</b></td>
      <td>{{old_ueic}}</td>
    </tr>
    <tr>
      <td><b>Replacement UEIC</b></td>
      <td>{{new_ueic}}</td>
    </tr>
    <tr style="background:#f3f4f6;">
      <td><b>Equipment Type</b></td>
      <td>{{equipment.type}}</td>
    </tr>
    <tr>
      <td><b>Location</b></td>
      <td>{{equipment.department}}</td>
    </tr>
    <tr style="background:#f3f4f6;">
      <td><b>Replaced By</b></td>
      <td>{{replaced_by}}</td>
    </tr>
    <tr>
      <td><b>Date</b></td>
      <td>{{replaced_on}}</td>
    </tr>
    <tr style="background:#f3f4f6;">
      <td><b>Reason</b></td>
      <td>{{reason}}</td>
    </tr>
  </table>

  <p style="margin-top:16px;">
    📄 <a href="{{report.retriepdf}}">Download Replacement Report (PDF)</a><br/>
    📊 <a href="{{report.retriexls}}">Download Replacement Report (Excel)</a>
  </p>

  <p style="color:#6b7280;font-size:12px;">
    — {{system.app_name}} · {{system.date}} · {{system.time}}
  </p>
</div>
```

**SMS:**
```
[KPTCL] {{old_ueic}} retired. New: {{new_ueic}}. Date: {{replaced_on}}. Ref: {{report.ref}}
```

**In-App:**
```
[Replacement] {{old_ueic}} → {{new_ueic}} at {{equipment.department}} ({{replaced_on}})
```

**Recipients:** `EE TLSS`, `SEE W&M`, `CEE Transmission Zone`

---

### Template: `eval_critical` — Email

**Subject:**
```
[CRITICAL ALERT] {{equipment.ueic}} — {{eval.test_type}} Result: CRITICAL
```

**Body (HTML):**
```html
<div style="font-family:Arial,sans-serif;max-width:600px;">
  <h2 style="color:#dc2626;">⚠ CRITICAL TEST RESULT</h2>

  <p>A critical test result has been detected. Immediate attention required.</p>

  <table border="1" cellpadding="8" cellspacing="0"
         style="border-collapse:collapse;width:100%;">
    <tr style="background:#fef2f2;">
      <td><b>Equipment UEIC</b></td>
      <td>{{equipment.ueic}}</td>
    </tr>
    <tr>
      <td><b>Type</b></td>
      <td>{{equipment.type}}</td>
    </tr>
    <tr style="background:#fef2f2;">
      <td><b>Location</b></td>
      <td>{{equipment.department}}</td>
    </tr>
    <tr>
      <td><b>Test Type</b></td>
      <td>{{eval.test_type}}</td>
    </tr>
    <tr style="background:#fef2f2;">
      <td><b>Overall Result</b></td>
      <td><b style="color:#dc2626;">{{eval.overall}}</b></td>
    </tr>
    <tr>
      <td><b>Evaluated At</b></td>
      <td>{{eval.evaluated_at}}</td>
    </tr>
  </table>

  <p style="margin-top:16px;">
    📄 <a href="{{report.retriepdf}}">View Full Report (PDF)</a>
  </p>

  <p style="color:#6b7280;font-size:12px;">
    — {{system.app_name}} · {{system.date}}
  </p>
</div>
```

**In-App:**
```
⚠ CRITICAL: {{equipment.ueic}} ({{eval.test_type}}) — Result: {{eval.overall}}. Action required.
```

**Recipients:** `EE TLSS`, `SEE W&M`, `CEE Transmission Zone`, `AEE Maintenance`

---

### Template: `request_submitted` — Email + In-App

**Subject:**
```
[SEACMS] New Test Request {{request.number}} — {{request.priority}} Priority
```

**Body (HTML):**
```html
<p>A new test request has been submitted and requires assignment.</p>
<table border="1" cellpadding="6" style="border-collapse:collapse;">
  <tr><td><b>Request #</b></td><td>{{request.number}}</td></tr>
  <tr><td><b>Title</b></td><td>{{request.title}}</td></tr>
  <tr><td><b>Priority</b></td><td>{{request.priority}}</td></tr>
  <tr><td><b>Equipment</b></td><td>{{equipment.ueic}}</td></tr>
  <tr><td><b>Location</b></td><td>{{equipment.department}}</td></tr>
  <tr><td><b>Submitted By</b></td><td>{{request.submitted_by}}</td></tr>
</table>
<p>— {{system.app_name}}</p>
```

**In-App:**
```
New request {{request.number}}: {{request.title}} ({{request.priority}}) — {{equipment.ueic}}
```

**Recipients:** `EE TLSS`, `Department Head`

---

### Template: `request_rejected` — All 3 Channels

**Subject:**
```
[Action Required] Test Request {{request.number}} Rejected / Returned
```

**Body (HTML):**
```html
<p>Your test request has been rejected or returned for rework.</p>
<p><b>Request:</b> {{request.number}} — {{request.title}}<br/>
<b>Equipment:</b> {{equipment.ueic}}<br/>
<b>Rejection Reason:</b> {{reason}}</p>
<p>Please review the feedback and resubmit. — {{system.app_name}}</p>
```

**SMS (≤160 chars):**
```
[SEACMS] Request {{request.number}} rejected. Reason: {{reason}}. Login to resubmit.
```

**In-App:**
```
Request {{request.number}} returned for rework. Reason: {{reason}}
```

**Recipients:** `Originator`, `Field Tester`, `Lab Tester`

---

## ✅ Test Completion Checklist

| Scenario | Login Used | Channels Tested | Pass |
|---|---|---|---|
| TS-NA-01 · Non-admin blocked | `ee.tlss@kptcl.com` | — | ☐ |
| TS-NA-02 · Admin loads list | `orgadmin@kptcl.com` | — | ☐ |
| TS-NC-01 · View all 3 channels | `orgadmin@kptcl.com` | Email · SMS · In-App | ☐ |
| TS-NC-02 · Disable SMS | `orgadmin@kptcl.com` | Email · In-App | ☐ |
| TS-NC-03 · Enable unconfigured event | `orgadmin@kptcl.com` | In-App | ☐ |
| TS-TB-01 · Edit email body | `orgadmin@kptcl.com` | Email | ☐ |
| TS-TB-02 · Variable picker insert | `orgadmin@kptcl.com` | Email | ☐ |
| TS-TB-03 · Preview mode | `orgadmin@kptcl.com` | Email | ☐ |
| TS-RR-01 · Role checkboxes | `orgadmin@kptcl.com` | — | ☐ |
| TS-RR-02 · Extra email chips | `orgadmin@kptcl.com` | — | ☐ |
| TS-RR-03 · Critical result full config | `orgadmin@kptcl.com` | Email · In-App | ☐ |
| TS-TW-01 · Request submitted config | `orgadmin@kptcl.com` | Email · In-App | ☐ |
| TS-TW-02 · Request rejected config | `orgadmin@kptcl.com` | Email · SMS · In-App | ☐ |
| TS-TW-03 · Approved + report links | `orgadmin@kptcl.com` | Email · In-App | ☐ |
| TS-NF-01 · In-app fires on replace | `originator@kptcl.com` → `ee.tlss@kptcl.com` | In-App | ☐ |
| TS-NF-02 · Email fires on critical | System trigger | Email | ☐ |
| TS-NE-01 · No channels save | `orgadmin@kptcl.com` | — | ☐ |
| TS-NE-02 · Empty subject allowed | `orgadmin@kptcl.com` | Email | ☐ |
| TS-NE-03 · Picker empty search | `orgadmin@kptcl.com` | — | ☐ |
| TS-NE-04 · Global templates protected | API | — | ☐ |
