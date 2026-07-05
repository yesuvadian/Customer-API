# TR Workflow — Functional Testing Scenarios

> Scope: UI/functional only. No API calls. Covers routing resolution, stage configuration,
> approver permissions, tester assignment, and execution.

---

## A. Routing Rule Resolution (TR Routing Config)

### A1. Default fallback — no rules configured
- Set only a default workflow definition, no routing rules
- Create any TR → should use the default workflow
- Verify correct workflow stages appear in the flowchart

### A2. Rule by Request Type only
- Create rule: `request_type = Testing` → Workflow A
- Create a Testing TR → routes to Workflow A
- Create a Maintenance TR → falls back to default workflow

### A3. Rule by Equipment Type only
- Create rule: `equipment_type = Power Transformer` → Workflow B
- Create TR on a Power Transformer → routes to Workflow B
- Create TR on a different equipment type → falls back to default

### A4. Rule by Test Type only
- Create rule: `test_type = Transformer Oil Test` → Workflow C
- Create TR with that test type → routes to Workflow C
- Create TR with a different test type → falls back to default

### A5. Combined specificity — most specific rule wins
| Rule | Filters | Specificity |
|------|---------|-------------|
| Rule 1 | request_type = Testing | 4 |
| Rule 2 | request_type = Testing + equipment_type = Power Transformer | 6 |
| Rule 3 | request_type = Testing + equipment_type = Power Transformer + test_type = Oil Test | 7 |

- TR matching all three → must route via Rule 3 (Workflow C)
- TR matching Rule 1 + 2 only → must route via Rule 2 (Workflow B)
- TR matching only Rule 1 → must route via Rule 1 (Workflow A)

### A6. Priority breaks ties at equal specificity
- Two rules with same filters (e.g. both `request_type = Testing` only)
- Give one a higher priority number
- Create a matching TR → higher priority rule wins

### A7. Rule with Approver Role override (`override_role_id`)
- Configure rule with `override_role_id = AEE_TLM`
- Create TR matching that rule → routing logic sets `resolved_l3_role_id = AEE_TLM` on the TR instance
- The workflow's stage role list defines who *can* participate; the rule override decides *which* role actually handles this TR
- At role-scoped stages downstream, only AEE_TLM users see it — AEE_MAINTENANCE users do NOT, even if they are on the same stage
- AEE_MAINTENANCE users with `can_act_as_tester` still see it (tester visibility bypasses role scoping)

### A8. Rule with Tester Role override (`override_tester_role_id`)
- Configure rule with `override_tester_role_id = AEE_MAINTENANCE`
- Create TR matching that rule → routing logic sets `resolved_tester_role_id = AEE_MAINTENANCE`
- Tester assignment dropdown at the assignment stage shows only users whose role = AEE_MAINTENANCE
- Users from other tester-eligible roles are not offered in the picker

### A8a. Both overrides on the same rule
- Configure rule with `override_role_id = AEE-R&D` AND `override_tester_role_id = AE-R&D`
- TR matches rule → `resolved_l3_role_id = AEE-R&D`, `resolved_tester_role_id = AE-R&D`
- Sequence of effect:
  1. TR created → routing resolves both overrides from the matching rule
  2. TR reaches L2 Approval & Route stage → routing endpoint fires on approve → routes to AEE-R&D
  3. Role-scoped stages downstream → only AEE-R&D users see the TR
  4. At assignment stage → tester picker restricted to AE-R&D users only
- Stage role configuration is unchanged — overrides only affect which role is resolved for this specific TR

### A9. Definition default role — no rule override
- Set `default_l3_role_id` on the workflow definition, no rule override
- Create TR with no matching rule → `resolved_l3_role_id` = definition default
- Verify queue visibility reflects that default role

### A10. No definition found — error case
- Remove all routing rules AND the default workflow
- Try to create a TR → clear error: "No active workflow definition found"
- Restore default and verify TR creation works again

---

## B. Stage Configuration

### B1. Add a new stage to an active workflow
- Workflow has active TRs in progress
- Add a new stage → should succeed (no 409 conflict)
- Existing TRs remain at their current stage, unaffected
- New TRs created after the change go through the new stage

### B2. Stage sequence ordering
- Add stages out of order (sequence 3, then 1, then 2)
- First stage opened on workflow instantiation = lowest sequence number
- Flowchart renders in correct sequence order (1 → 2 → 3)

### B3. Stage with no roles — send-back terminal
- Create a stage with no roles configured
- Configure a transition pointing to it
- Execute that transition → workflow auto-terminates with `terminal_status`
- Verify terminal status label appears on the TR card

### B4. Stage status label assignment
- Assign a custom status (e.g. "Under Review") to a stage
- Advance a TR to that stage → TR card shows "Under Review"
- Advance to next stage → label updates to next stage's status
- Advance to terminal → label shows terminal status

### B5. `is_result_stage` flag
- Mark a stage as result stage
- Advance TR to that stage → result submission UI/buttons appear
- Advance TR past it → result stage UI disappears

### B6. `is_role_scoped` flag
- Mark a stage as role-scoped
- Multiple roles on that stage
- TR resolved to Role A → only Role A users see it
- Role B users (on same stage) → do NOT see it
- Exception: Role B with `can_act_as_tester` → still sees it

### B7. Non-role-scoped stage
- Stage with `is_role_scoped = false`
- Multiple roles on that stage
- All users with any of those roles see the TR in their queue

### B8. Duplicate role on same stage
- Try to add the same role twice to one stage
- Second add should be silently ignored
- Stage roles list shows the role only once

### B9. Edit stage roles while TRs are active
- Workflow has active TRs
- Add or remove a role from a stage → should succeed (no 409)
- Existing TRs at that stage immediately reflect the role change in visibility

### B10. Edit stage transitions while TRs are active
- Workflow has active TRs
- Modify a transition (change target stage or action code) → should succeed
- Verify the updated transition applies to the next action taken

---

## C. Stage Transition Logic

### C1. Linear happy path — full workflow
- L1 approve → L2 → L3 → Complete
- Status label changes at each stage
- Only the correct role sees each stage in queue
- TR disappears from queue when workflow completes

### C2. Reject / Return path
- L2 approver rejects → TR returns to L1
- Audit log shows `is_send_back = true`
- L1 role sees it again in their queue with rejection comment visible

### C3. Comment required on rejection
- Configure transition with `requires_comment = true`
- Try to reject without a comment → blocked with validation error
- Enter a comment → rejection proceeds

### C4. Terminal transition — null to_stage
- Configure a "Close" transition with no target stage
- Execute → workflow status = `completed`, no further stages
- TR disappears from all queues
- TR card shows terminal status label

### C5. Send-back rule — stage with zero roles
- Configure transition to a stage that has no roles
- Execute that transition → auto-terminates with `terminal_status_id`
- Verify terminal status label appears on TR

### C6. Post action on transition
- Configure `post_action` on a specific transition
- Execute that transition → verify post action fires (check side effects)

### C7. Multiple transitions from one stage
- Stage has both Approve (→ next stage) and Reject (→ previous stage) transitions
- Both buttons visible in queue
- Approve → TR advances forward
- Reject → TR returns backward

### C8. Audit trail on every transition
- Perform several transitions (approve, reject, assign, complete)
- Open TR history/audit panel
- Every action recorded: who acted, from stage, to stage, action code, timestamp, comment

---

## D. Approver Role — All Permutations

### D1. `can_approve` only
- Role has only `can_approve`, no other permissions
- User sees TR with Approve / Reject buttons only
- No Assign button, no Complete button
- Approve → TR advances to next stage

### D2. `can_approve` + `can_assign`
- User sees Approve and Assign buttons
- Can approve directly OR assign a tester first then approve
- Approving without prior assignment still works

### D3. `can_approve` + `can_act_as_tester`
- User sees Approve + Complete / Return buttons
- Can approve (move to next stage) OR complete as tester
- Both actions independently functional

### D4. `can_act_as_tester` only (no `can_approve`)
- User sees TR in queue (tester visibility rule applies)
- No Approve button — only Complete / Return buttons
- Complete → advances the stage; cannot approve

### D5. `can_assign` only
- User sees TR with Assign button only
- Can assign a tester → TR stays at same stage
- Cannot approve or complete

### D6. `can_edit` only
- User can open and edit TR fields
- No Approve / Assign / Complete buttons visible

### D7. All permissions on one role
- Role has `can_approve` + `can_assign` + `can_act_as_tester` + `can_edit`
- All buttons visible: Approve, Reject, Assign, Complete, Return
- Each action works independently

### D8. Multiple roles on same stage — union of permissions
- Stage has Role A (`can_approve`) and Role B (`can_act_as_tester`)
- User with Role A → Approve button only
- User with Role B → Complete button only
- User with both Role A and Role B → all buttons

### D9. Same role at L1 and L3 — queue shows correct stage only
- R1 configured at L1 (`can_approve`) and L3 (`can_approve` + `can_act_as_tester`)
- TR at L1 → R1 sees it, can approve
- TR at L2 (R2's stage) → R1 does NOT see it
- TR at L3 → R1 sees it again, can approve and complete

### D10. Resolved L3 role scoping at approver stage
- Stage `is_role_scoped = true`
- Two roles: AEE_TLM (`can_approve`) and AEE_MAINTENANCE (`can_approve`)
- TR resolved to AEE_TLM
- AEE_TLM user → sees it, can approve ✓
- AEE_MAINTENANCE user → does NOT see it (role-scoped, wrong resolved role)
- If AEE_MAINTENANCE also has `can_act_as_tester` → sees it despite role scoping

### D11. Approve at terminal stage
- Last stage: approve → null to_stage (terminal)
- Approver clicks Approve → workflow completes
- TR disappears from all queues
- TR card shows terminal status

### D12. Reject at any stage → audit trail
- Approver rejects with a comment
- TR returns to configured prior stage (or terminates per transition config)
- Audit log: who rejected, from/to stage, comment, timestamp
- History panel shows rejection event

---

## E. Tester Assignment & Execution

### E1. Only `can_act_as_tester` roles appear in assign dropdown
- Open Assign dialog at assignment stage
- Dropdown lists only users whose role has `can_act_as_tester`
- Users without that permission are not listed

### E2. After assignment — tester and peer testers see TR
- Assign tester (aeerd.hoody)
- Assigned tester's queue → TR visible with Complete / Return buttons
- Peer user with same workflow's `can_act_as_tester` role (aeem.hoody) → also sees it
- User with no `can_act_as_tester` in that workflow → does NOT see it

### E3. Assigner also sees TR
- The user who performed the assignment (assigner role) → TR still visible in their queue
- They can reassign or take other permitted actions

### E4. Reassign tester
- Assign to Tester A, then reassign to Tester B
- Tester A's queue → TR disappears
- Tester B's queue → TR appears with Complete / Return

### E5. Complete execution — testing kit mandatory
- Tester opens Submit Test Results form
- Click "Save & Submit" without selecting a Testing Kit → blocked with red snackbar
- Select a Testing Kit → Submit proceeds
- "Save Draft" without kit → allowed (no block)

### E6. Complete execution advances stage
- Tester submits and clicks Complete
- TR moves to next configured stage
- Previous tester's queue → TR disappears
- Next stage's role queue → TR appears

### E7. Return from execution
- Tester clicks Return (with comment)
- TR moves back to configured prior stage
- Audit log records who returned it and why

### E8. `completed_by` recorded correctly
- After a tester completes execution, `completed_by` on the stage instance = the user who clicked Complete
- Even if TR was assigned to a different user (aeerd.hoody assigned, aeem.hoody completed) → `completed_by` = aeem.hoody

---

## F. Role Management

### F1. Create custom role with slash in name
- Go to User Roles → Create Custom Role
- Enter `AEE_MAINTENANCE/AEE_TLM`
- Should create successfully with green success message
- Role appears in the roles list

### F2. Role uniqueness per stage (not across workflow)
- Assign `AEE_MAINTENANCE` to both L1 and L3 → allowed
- Try assigning `AEE_MAINTENANCE` twice to L1 → second silently ignored, only one entry shown

### F3. Role assignment to user
- Assign a role to a user
- Log in as that user → queue visibility reflects the newly assigned role immediately

---

## G. Notification Coverage

### G1. Single notification per stage advance
- User with a role in multiple stages (e.g. L1 and L3) advances a TR
- That user receives only ONE notification, not two

### G2. Originator always notified
- TR originator receives a notification on every stage advance
- Even if originator has no role in the workflow

### G3. Assignee notified on tester assignment
- Assign a tester → that tester receives a notification
- Other tester-role users do NOT receive the assignment notification

### G4. Notification channel — inapp only for ds_originator_review
- Advance a document request to `ds_originator_review` status
- Notification fires in-app only (not email or SMS)

---

## H. Execute as Assigner — Full Flow

> The assigner sees the TR with an Assign Tester panel at the top of the action bar.
> Their role has `can_assign` at the current stage.

### H1. Assigner sees Assign Tester panel
- Log in as user with `can_assign` role at the execution stage
- Open the TR from the queue
- Action bar shows: Role dropdown (or preset role chip) + User picker + "Assign Tester" button
- Other non-assign actions (Approve, Reject) appear below the assign controls

### H2. Role pre-set via `resolved_tester_role_id`
- Configure a routing rule with `override_tester_role_id = AEE_MAINTENANCE`
- Open the TR → Role section shows a read-only chip "Role: AEE_MAINTENANCE" instead of dropdown
- User picker immediately loads users with that role

### H3. Role dropdown when no preset
- No `override_tester_role_id` on the routing rule
- Open the TR → Role dropdown appears listing all roles with `can_act_as_tester` at this stage
- Select a role → user picker loads users for that role only

### H4. User picker — active requests count shown
- User picker shows each tester's name, email, and "N active" badge
- User with 0 active requests → badge is neutral
- User with active requests → badge is red to indicate they are already busy

### H5. Auto-select when only one user available
- Select a role that has exactly one user
- User picker auto-selects that user without manual click

### H6. No testers available in department
- Select a role that has no users in this department
- User picker shows "No testers available in this department."
- Assign Tester button remains disabled

### H7. Assign button disabled until both role and user selected
- Role selected, no user → Assign Tester button disabled
- User selected, no role → Assign Tester button disabled
- Both selected → Assign Tester button enabled

### H8. Assigner performs assignment
- Select role + user → tap "Assign Tester"
- Green snackbar: "Tester assigned"
- Queue refreshes — TR may still be visible to assigner (assigner keeps visibility)
- Assigned tester's queue → TR now appears

### H9. Assigner also has `can_approve` — both actions available
- Role has `can_assign` + `can_approve`
- Action bar shows: Assign controls + Approve + Reject buttons
- Assigner can approve directly without assigning, OR assign and then approve later
- Both flows work independently

### H10. Assigner with `can_approve` approves without assigning
- Skip the assign section entirely
- Tap "Approve" → TR advances to next stage
- Assignment never required if the stage doesn't mandate it

### H11. Comment required on rejection by assigner
- Assigner's stage has a Reject transition with `requires_comment = true`
- Reject button is grayed out until comment field is filled
- Add comment → Reject becomes active → rejection succeeds

### H12. Reassign — change tester
- TR already assigned to Tester A
- Assigner opens TR → assign panel still visible (reassign action available)
- Select Tester B → assign → Tester A's queue loses it, Tester B gains it

---

## I. Execute as Act as Tester — Full Flow

> The tester sees the TR with "Fill Test Result" and "Return" buttons.
> Their role has `can_act_as_tester` at the execution stage (or anywhere in the workflow
> if the TR is in assigned state).

### I1. Tester sees TR in queue
- Log in as user with `can_act_as_tester` role
- TR is in assigned/execution state → appears in their queue
- Peer tester (different user, same role) → also sees the same TR

### I2. Action bar for tester — no Assign controls
- Open the TR detail sheet as a tester
- Action bar does NOT show the assign panel (no `assign` action code for this user)
- Shows only: "Fill Test Result" button + "Return" button

### I3. "Fill Test Result" opens test result form
- Tap "Fill Test Result"
- Test result form opens as a bottom sheet
- Form shows test template fields for the TR's test type
- Testing Kit dropdown shows "Select Testing Kit *" (required)

### I4. Save Draft — kit not required
- Fill some form fields, leave Testing Kit empty
- Tap "Save Draft" → saves successfully, no error
- Reopen form → previously entered data is pre-filled

### I5. Save & Submit — kit mandatory
- Fill form fields, leave Testing Kit empty
- Tap "Save & Submit" → red snackbar: "Please select a Testing Kit before submitting."
- Form stays open, no submission occurs

### I6. Save & Submit — full happy path
- Select Testing Kit
- Fill all required fields
- Tap "Save & Submit"
- Form closes, TR advances to next stage
- Tester's queue → TR disappears (stage completed)
- Next stage role's queue → TR appears

### I7. Return (send back) by tester
- Tap "Return" button in detail sheet
- If return transition requires comment → comment field turns red, button disabled until filled
- Add comment, tap Return → TR goes back to configured prior stage
- Audit log records: action = "return", performed_by = this tester, comment shown

### I8. Tester without `can_act_as_tester` cannot see TR
- Log in as user whose role has only `can_approve` at some other stage
- That user has no `can_act_as_tester` anywhere in this workflow
- TR in execution stage → does NOT appear in their queue

### I9. Tester with `can_act_as_tester` + `can_approve` — both actions
- Role has both permissions at this stage
- Action bar shows: Fill Test Result + Return + Approve + Reject
- Tester can complete execution (Fill Test Result → Submit) or approve directly
- Both flows independent

### I10. `completed_by` tracks who actually executed
- TR assigned to Tester A, but Tester B (peer with same role) fills and submits
- After completion, audit log shows "Completed by: Tester B"
- Not Tester A, even though Tester A was the assigned user

### I11. Multi-session test — intermediate session
- TR has multiple test sessions planned
- First session: tester fills partial results, submits → saves as intermediate (no recommendation section)
- Second session: recommendation section appears and is required
- Only the final session's submit advances the stage

### I12. Test result pre-fill from saved draft
- Tester saves a draft with partial data
- Another tester with same role opens the same TR → form pre-fills with saved draft data
- They can continue from where the first tester left off

---

## J. Stage Settings — Routing Rules Summary Panel

> When "Use Routing Endpoint on Approve" is ON, the Settings tab shows a read-only
> summary of all routing rules mapped to this workflow. No schema change required —
> rules are surfaced from the same data the flowchart badges already display.

### J1. Routing rules card appears only when toggle is ON
- Open a stage with `use_l2_route = false`
- Settings tab → no "Rules mapped to this stage" card visible
- Toggle ON → card appears immediately below the toggle

### J2. Rules card shows correct rule count
- Workflow has 10 active routing rules
- Card header shows "10 rules"
- Each rule listed as a row: criteria + override role name

### J3. Rule row format — criteria + role
- Rule with `test_type = Transformer Oil Test` and `override_role_id = AEE-R&D`
- Row shows: `Transformer Oil Test → AEE-R&D`
- Rule with no override role → row shows criteria only (no `→` suffix)

### J4. Default (catch-all) rule displayed
- Workflow is set as org default with no match conditions
- Card shows: `Default (catch-all)` as a row
- No criteria shown because it matches everything

### J5. No rules mapped — helpful message
- Workflow has no active routing rules and is not the org default
- Card shows: "No routing rules mapped — all requests fall through to the default workflow."
- Rule count shows "0 rules"

### J6. Rules card is read-only
- Rules in the card are informational only — no edit controls
- To modify rules, user must navigate to TR Routing Config page
- Stage Settings panel has no inline add/edit for routing rules

---

## K. TR Routing Config — Add / Edit Routing Rule Form

> The routing rule form was reorganised to make it easier to understand.
> Fields are grouped by purpose with plain-English section headers.

### K1. "Add Routing Rule" dialog — field order
- Click "+ Add Rule" in TR Routing Config
- Dialog title: "Add Routing Rule"
- First field group: **ROUTE TO** → "Select Workflow" dropdown
- Second group: **WHO APPROVES AT L2?** → "Approver Role" dropdown
- Third group: **WHO PERFORMS THE TEST?** → "Tester Role" dropdown
- Fourth group: **APPLY THIS RULE WHEN…** → Request Type, Equipment Type, Activity/Test Type

### K2. Select Workflow — default option
- "Select Workflow" dropdown defaults to "— Organisation default —"
- Saving with this default → rule inherits the org default workflow
- Select a specific workflow → rule maps to that workflow exclusively

### K3. Approver Role — default option
- "Approver Role" dropdown defaults to "— Workflow default —"
- Leaving at default → the workflow's own role configuration handles approval
- Override → that specific role is assigned as L2 approver for matching TRs

### K4. Tester Role — default option
- "Tester Role" dropdown defaults to "— Workflow default —"
- Leaving at default → workflow's tester role config applies
- Override → that specific role is the tester for matching TRs

### K5. APPLY THIS RULE WHEN — match conditions
- Request Type: Any / Normal / Failure / Special
- Equipment Type: Any or specific type
- Activity / Test Type: multi-select checklist grouped by Test / Maintenance / Inspection / Repair
- Selecting multiple test types → creates one rule row per type on save

### K6. Save disabled until at least one field set
- Open Add Routing Rule dialog, touch nothing → Save button disabled
- Set any single field (workflow, role, or match condition) → Save becomes enabled

### K7. Edit Routing Rule — pre-populated
- Click edit on an existing rule group
- Dialog title: "Edit Routing Rule"
- All existing values pre-filled in the correct fields
- Change any value and Save → rule updated, list refreshes

### K8. Delete Routing Rule
- Click delete on a rule group
- Dialog title: "Delete Routing Rule" with confirmation prompt
- Confirm → rule removed from list; rules card in Stage Settings updates accordingly

### K9. "Configure Test Routing" button in flowchart
- Open a workflow with a `use_l2_route` stage
- Flowchart shows routing badges on that stage
- Button labelled "Configure Test Routing" (regardless of whether rules exist)
- Tap → opens TR Routing Config page / sheet

### K10. Multiple test types → multiple rule rows
- In Add Routing Rule, select 3 test types
- Button label changes to "Add 3 Rules"
- Save → 3 separate rule rows created, all sharing the same role and workflow mapping

---

## L. Nameplate Exclusion

### L1. Nameplate not in New Testing Request form
- Open New Testing Request
- Check Test Type dropdown → "Nameplate" must NOT appear

### L2. Nameplate not in per-equipment test type list
- Select equipment (UEIC) in the testing request form
- Test types loaded for that equipment → "Nameplate" must NOT appear

---

## Test Coverage Summary

| Area | Scenarios |
|------|-----------|
| Routing resolution | A1–A10 |
| Stage configuration | B1–B10 |
| Transition logic | C1–C8 |
| Approver permissions | D1–D12 |
| Tester assignment & execution | E1–E8 |
| Role management | F1–F3 |
| Notifications | G1–G4 |
| Execute as Assigner | H1–H12 |
| Execute as Act as Tester | I1–I12 |
| Stage Settings — routing rules panel | J1–J6 |
| TR Routing Config — add/edit rule form | K1–K10 |
| Nameplate exclusion | L1–L2 |
| **Total** | **99 scenarios** |
