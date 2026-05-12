# SEACMS-AI Multi-Session Testing User Manual
### Smart Equipment Asset & Compliance Management System — AI Edition
**Karnataka Power Transmission Corporation Limited (KPTCL)**  
**Module**: Multi-Session Testing  
**Version**: 2.0 · April 2026

---

## Table of Contents

1. [Multi-Session Testing Overview](#1-multi-session-testing-overview)
2. [When to Use Multi-Session Testing](#2-when-to-use-multi-session-testing)
3. [User Roles & Permissions](#3-user-roles--permissions)
4. [Creating a Multi-Session Test Request](#4-creating-a-multi-session-test-request)
5. [Viewing & Managing Sessions](#5-viewing--managing-sessions)
6. [Executing Test Sessions](#6-executing-test-sessions)
7. [Recording Session Readings](#7-recording-session-readings)
8. [Editing & Deleting Readings](#8-editing--deleting-readings)
9. [Submitting Session Results](#9-submitting-session-results)
10. [Completing Sessions](#10-completing-sessions)
11. [Session Statistics & Timeline](#11-session-statistics--timeline)
12. [Approving Multi-Session Tests](#12-approving-multi-session-tests)
13. [Reports & Analytics](#13-reports--analytics)
14. [Troubleshooting](#14-troubleshooting)
15. [Quick Reference](#15-quick-reference)

---

## 1. Multi-Session Testing Overview

### 1.1 What is Multi-Session Testing?

Multi-session testing allows KPTCL staff to perform equipment tests across **multiple sessions** (days, weeks, or stages) and track results separately for each session. This is critical for:

- **Time-based observations**: Equipment behavior over multiple days
- **Progressive testing**: Different test phases (e.g., 10-stage repair lifecycle)
- **Environmental variations**: Tests under different conditions
- **Long-duration monitoring**: Equipment performance trends

### 1.2 Key Features

✅ **Per-Session Results**: Each session has its own test result, readings, and status  
✅ **Session Timeline**: Visual timeline showing all sessions and their progress  
✅ **Reading Management**: Add, edit, and delete readings within sessions  
✅ **Automatic Statistics**: System calculates pass/fail counts per session  
✅ **Flexible Scheduling**: Sessions can be scheduled days or weeks apart  
✅ **Complete Audit Trail**: Full history of who did what and when  

### 1.3 System Architecture

```
Testing Request (Multi-Session Enabled)
  ├── Session 1 (e.g., Day 1 Morning Test)
  │   ├── Reading 1, Reading 2, Reading 3...
  │   ├── Test Result (linked to Session 1)
  │   ├── Comments
  │   └── Statistics (pass/fail counts)
  │
  ├── Session 2 (e.g., Day 7 Mid-term Test)
  │   ├── Reading 1, Reading 2, Reading 3...
  │   ├── Test Result (linked to Session 2)
  │   ├── Comments
  │   └── Statistics
  │
  └── Session 3 (e.g., Day 14 Final Test)
      ├── Reading 1, Reading 2, Reading 3...
      ├── Test Result (linked to Session 3)
      ├── Comments
      └── Statistics
```

---

## 2. When to Use Multi-Session Testing

### 2.1 Recommended Use Cases

| Scenario | Example | Sessions | Interval |
|----------|---------|----------|----------|
| **Power Transformer Monitoring** | Oil degradation test over time | 3-5 | 7-14 days |
| **Circuit Breaker Lifecycle** | 10-stage repair process | 10 | As needed |
| **Substation Inspection** | Multi-area safety audit | 4-6 | 1 day |
| **Load Testing** | Equipment performance under varying loads | 3-4 | 1-3 days |
| **Environmental Testing** | Equipment behavior in different weather | 5-7 | 7 days |
| **Commissioning Tests** | Progressive installation testing | 8-12 | Varies |

### 2.2 Single Session vs Multi-Session

| Factor | Single Session | Multi-Session |
|--------|---------------|---------------|
| **Duration** | < 1 day | Multiple days/weeks |
| **Observations** | One-time | Progressive/comparative |
| **Results** | One result | One result per session |
| **Complexity** | Simple | Complex |
| **Example** | CVT Dielectric Test | Transformer Major Maintenance |

---

## 3. User Roles & Permissions

### 3.1 Role Capabilities

| Role | Create Request | Start Session | Add Readings | Edit Readings | Submit Results | Approve |
|------|:--------------:|:-------------:|:------------:|:-------------:|:--------------:|:-------:|
| **AEE Maintenance** | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **EE TLSS** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **EE RT** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **SEE RT** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Field Tester** | — | ✅ | ✅ | ✅ | ✅ | — |
| **Lab Tester** | — | ✅ | ✅ | ✅ | ✅ | — |
| **SEE W&M** | View | — | — | — | — | ✅ |
| **CEE Zone** | View | — | — | — | — | ✅ |

### 3.2 Login Credentials

Use these credentials to test multi-session functionality:

| Role | Email | Password |
|------|-------|----------|
| **EE TLSS** | `ee.tlss@kptcl.com` | `admin123` |
| **EE RT** | `ee.rt@kptcl.com` | `admin123` |
| **Field Tester** | `field.tester@kptcl.com` | `Tester123!` |
| **Lab Tester** | `lab.tester@kptcl.com` | `Tester123!` |

---

## 4. Creating a Multi-Session Test Request

### 4.1 Step-by-Step Process

#### Step 1: Navigate to Testing Requests

1. Login as **EE TLSS** or **AEE Maintenance**
2. Click **Testing** → **Create New Request**
3. OR from Dashboard → **New Testing Request** button

#### Step 2: Fill Basic Details

```
┌───────────────────────────────────────────────┐
│ New Testing Request                           │
├───────────────────────────────────────────────┤
│                                               │
│ Equipment:      [Select Equipment ▼]         │
│                 E.g., Power Transformer PT-001│
│                                               │
│ Test Category:  [Select Category ▼]          │
│                 • test                        │
│                 • maintenance                 │
│                 • inspection                  │
│                 • repair_lifecycle            │
│                                               │
│ Test Type:      [Select Test Type ▼]         │
│                 E.g., Power Transformer       │
│                      Major Maintenance        │
│                                               │
│ Priority:       [Select Priority ▼]          │
│                 • Low                         │
│                 • Medium                      │
│                 • High ⚠️                      │
│                 • Critical 🔴                 │
│                                               │
│ Location:       [Enter Location]             │
│                 E.g., Substation 220kV Malur  │
│                                               │
│ Department:     [Select Department ▼]        │
│                 E.g., Maintenance             │
│                                               │
└───────────────────────────────────────────────┘
```

#### Step 3: Enable Multi-Session Testing

```
┌───────────────────────────────────────────────┐
│ ☑ Enable Multi-Session Testing               │
├───────────────────────────────────────────────┤
│                                               │
│ Total Sessions:        [3]         (1-50)    │
│                                               │
│ Interval (days):       [7]         (1-365)   │
│                                               │
│ Start Date:            [Apr 21, 2026] 📅     │
│                                               │
│ ☑ Auto-generate sessions on approval         │
│                                               │
│ ℹ️ System will create 3 sessions:             │
│    • Session 1: Apr 21, 2026                  │
│    • Session 2: Apr 28, 2026 (+7 days)       │
│    • Session 3: May 5, 2026 (+7 days)        │
│                                               │
└───────────────────────────────────────────────┘
```

**Field Descriptions**:

| Field | Description | Example |
|-------|-------------|---------|
| **Total Sessions** | Number of test sessions required | 3 (for weekly monitoring) |
| **Interval (days)** | Days between sessions | 7 (one week apart) |
| **Start Date** | When to begin first session | Apr 21, 2026 |
| **Auto-generate** | System creates sessions automatically | ✅ Recommended |

#### Step 4: Add Description & Remarks

```
┌───────────────────────────────────────────────┐
│ Description:                                  │
│ ┌───────────────────────────────────────────┐ │
│ │ Power transformer PT-001 requires major   │ │
│ │ maintenance with progressive monitoring   │ │
│ │ over 3 weeks to observe oil degradation  │ │
│ │ and insulation performance.               │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│ Special Remarks:                              │
│ ┌───────────────────────────────────────────┐ │
│ │ Equipment has been in service for 15      │ │
│ │ years. Last major maintenance: 2023.      │ │
│ └───────────────────────────────────────────┘ │
└───────────────────────────────────────────────┘
```

#### Step 5: Submit Request

```
[Cancel]  [Save as Draft]  [Submit Request ✅]
```

Click **Submit Request** to send for approval.

### 4.2 Request Approval Flow

```
1. EE TLSS creates request
   ↓
2. SEE W&M approves request
   ↓
3. System auto-generates 3 sessions
   ↓
4. EE TLSS assigns tester
   ↓
5. Tester receives assignment notification
   ↓
6. Ready to start testing! ✅
```

---

## 5. Viewing & Managing Sessions

### 5.1 Accessing Session Timeline

#### Option 1: From My Assignments

1. Login as **Tester** (Field or Lab)
2. Navigate to **Testing** → **My Assignments**
3. Click on multi-session request (shows **📅 3 Sessions** badge)
4. Click **View Sessions Timeline**

#### Option 2: From Request Detail

1. Open testing request detail page
2. Scroll to **Sessions** section
3. Timeline automatically displayed

### 5.2 Session Timeline View

```
┌───────────────────────────────────────────────────────┐
│ TR-2026-001 - Power Transformer Maintenance           │
│ Session Timeline                         [🔄 Refresh] │
├───────────────────────────────────────────────────────┤
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ 📊 Testing Sessions          1 of 3 completed   │  │
│ │                                                 │  │
│ │ Progress: ████████░░░░░░░░░░░░░░  33%          │  │
│ │                                                 │  │
│ │ 🕐 Last tested: Apr 21, 2026                    │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📅 1  Session 1 - Initial Inspection            ║  │
│ ║                                                 ║  │
│ ║ 📆 Apr 21, 2026 10:00 AM                        ║  │
│ ║ 🟢 Status: Completed                            ║  │
│ ║                                                 ║  │
│ ║ 📊 5 readings • ✅ 4 pass, ❌ 1 fail            ║  │
│ ║ ⏱️ Duration: 2h 15m                             ║  │
│ ║ 💬 2 comments                                    ║  │
│ ║                                                 ║  │
│ ║    [View Details]  [View Report]  [Edit]       ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📅 2  Session 2 - Mid-term Check                ║  │
│ ║                                                 ║  │
│ ║ 📆 Apr 28, 2026 10:00 AM                        ║  │
│ ║ 🟡 Status: In Progress                          ║  │
│ ║                                                 ║  │
│ ║ 📊 3 readings • All pass                        ║  │
│ ║ 💬 1 comment                                     ║  │
│ ║                                                 ║  │
│ ║    [Continue]  [Add Reading]  [Complete]       ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📅 3  Session 3 - Final Inspection              ║  │
│ ║                                                 ║  │
│ ║ 📆 May 5, 2026 10:00 AM                         ║  │
│ ║ ⚪ Status: Scheduled                            ║  │
│ ║                                                 ║  │
│ ║ Waiting for Session 2 to complete               ║  │
│ ║                                                 ║  │
│ ║    [Cannot start yet]                           ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
└───────────────────────────────────────────────────────┘
```

### 5.3 Session Status Indicators

| Status | Color | Meaning | Available Actions |
|--------|:-----:|---------|-------------------|
| **Scheduled** | ⚪ White | Not yet started | Start (if previous complete) |
| **In Progress** | 🟡 Yellow | Currently active | Add readings, Submit result, Complete |
| **Completed** | 🟢 Green | Finished | View details, View report, Edit readings |
| **Skipped** | ⚫ Gray | Not performed | — |

---

## 6. Executing Test Sessions

### 6.1 Starting a Session

#### Step 1: Click "Start Session"

From timeline, click **[🟢 Start Session]** button on scheduled session.

#### Step 2: Enter Session Details

```
┌───────────────────────────────────────────────┐
│ Start Session 1 - Initial Inspection          │
├───────────────────────────────────────────────┤
│                                               │
│ Session Name: [Auto-filled]                  │
│               (Can edit if needed)            │
│                                               │
│ Scheduled:    Apr 21, 2026 10:00 AM          │
│                                               │
│ Start Time:   [Apr 21, 2026 10:05 AM] 🕐     │
│               (Auto-set to current time)      │
│                                               │
│ Conducted By: [You - Jane Tester]            │
│                                               │
│ Weather:      [Clear ▼]                      │
│               • Clear                         │
│               • Cloudy                        │
│               • Rainy                         │
│               • Hot                           │
│               • Cold                          │
│                                               │
│ Temperature:  [25°C]                          │
│                                               │
│ Session Notes:                                │
│ ┌───────────────────────────────────────────┐ │
│ │ Equipment warmed up for 30 minutes.       │ │
│ │ All safety checks completed.              │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│    [Cancel]         [▶️ Start Session]        │
└───────────────────────────────────────────────┘
```

Click **Start Session** to begin.

#### Step 3: Session Started Confirmation

```
┌───────────────────────────────────────────────┐
│ ✅ Session 1 Started!                         │
│                                               │
│ Status: In Progress 🟡                        │
│ Started: Apr 21, 2026 10:05 AM               │
│                                               │
│ You can now:                                  │
│ • Add readings                                │
│ • Add comments                                │
│ • Enter test results                          │
│                                               │
│    [Add Reading]    [Enter Results]           │
└───────────────────────────────────────────────┘
```

---

## 7. Recording Session Readings

### 7.1 Adding a Reading

#### Step 1: Click "Add Reading"

From session page, click **[➕ Add Reading]** button.

#### Step 2: Enter Reading Data

```
┌───────────────────────────────────────────────┐
│ Add Reading - Session 1                       │
├───────────────────────────────────────────────┤
│                                               │
│ Reading Number: [1]  (Auto-incremented)      │
│                                               │
│ Reading Time:   [10:15 AM] 🕐                │
│                 (Auto-set, can edit)          │
│                                               │
│ Reading Data (JSON):                          │
│ ┌───────────────────────────────────────────┐ │
│ │ {                                         │ │
│ │   "voltage": 220,                         │ │
│ │   "current": 4.8,                         │ │
│ │   "temperature": 45,                      │ │
│ │   "oil_level": "Normal",                  │ │
│ │   "noise_level": "Low"                    │ │
│ │ }                                         │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│ Equipment Serial: [PT-001-2011]              │
│                                               │
│ Calibration Date: [Jan 15, 2026] 📅          │
│                                               │
│ Result Status:    [Pass ▼]                   │
│                   • Pass ✅                   │
│                   • Fail ❌                   │
│                   • Conditional ⚠️            │
│                   • Warning ℹ️                │
│                                               │
│ Remarks:                                      │
│ ┌───────────────────────────────────────────┐ │
│ │ Normal operation observed.                │ │
│ │ All parameters within limits.             │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│    [Cancel]         [💾 Save Reading]         │
└───────────────────────────────────────────────┘
```

#### Step 3: Reading Saved

```
┌───────────────────────────────────────────────┐
│ ✅ Reading #1 Saved!                          │
│                                               │
│ Reading added to Session 1                    │
│                                               │
│ [Add Another]    [View All Readings]          │
└───────────────────────────────────────────────┘
```

### 7.2 Viewing All Readings

```
┌───────────────────────────────────────────────────────┐
│ Session 1 - Readings                    [➕ Add New]  │
├───────────────────────────────────────────────────────┤
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📊 Reading #1                    ✏️ Edit 🗑️ Delete║  │
│ ║ Time: 10:15 AM                                  ║  │
│ ║                                                 ║  │
│ ║ Voltage: 220V | Current: 4.8A                  ║  │
│ ║ Temperature: 45°C | Oil Level: Normal          ║  │
│ ║                                                 ║  │
│ ║ Status: ✅ Pass                                 ║  │
│ ║ Remarks: Normal operation observed             ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📊 Reading #2                    ✏️ Edit 🗑️ Delete║  │
│ ║ Time: 10:30 AM                                  ║  │
│ ║                                                 ║  │
│ ║ Voltage: 220V | Current: 5.2A                  ║  │
│ ║ Temperature: 52°C | Oil Level: Low ⚠️           ║  │
│ ║                                                 ║  │
│ ║ Status: ❌ Fail - Temperature too high         ║  │
│ ║ Remarks: Oil level dropping, needs attention   ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📊 Reading #3                    ✏️ Edit 🗑️ Delete║  │
│ ║ Time: 10:45 AM (after topping up oil)          ║  │
│ ║                                                 ║  │
│ ║ Voltage: 220V | Current: 4.9A                  ║  │
│ ║ Temperature: 46°C | Oil Level: Normal          ║  │
│ ║                                                 ║  │
│ ║ Status: ✅ Pass                                 ║  │
│ ║ Remarks: Temperature stabilized after refill   ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ Summary: 3 readings • 2 pass, 1 fail                 │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## 8. Editing & Deleting Readings

### 8.1 Editing a Reading (NEW FEATURE! ✨)

#### Step 1: Click Edit Button

Click **✏️ Edit** icon on any reading card.

#### Step 2: Modify Reading Data

```
┌───────────────────────────────────────────────┐
│ Edit Reading #2              [✕ Close]        │
├───────────────────────────────────────────────┤
│                                               │
│ Reading Data (JSON):                          │
│ ┌───────────────────────────────────────────┐ │
│ │ {                                         │ │
│ │   "voltage": 220,                         │ │
│ │   "current": 5.2,      ← Edit values     │ │
│ │   "temperature": 52,                      │ │
│ │   "oil_level": "Low"                      │ │
│ │ }                                         │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│ Result Status: [Fail ▼]  ← Change if needed │
│                                               │
│ Remarks:                                      │
│ ┌───────────────────────────────────────────┐ │
│ │ Temperature exceeded threshold.           │ │
│ │ Oil level low - topped up oil.            │ │
│ │ ← Updated remarks                         │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│    [Cancel]         [💾 Save Changes]         │
└───────────────────────────────────────────────┘
```

#### Step 3: Confirmation

```
┌───────────────────────────────────────────────┐
│ ✅ Reading #2 Updated Successfully!           │
│                                               │
│ Changes saved to database.                    │
│                                               │
│    [OK]                                       │
└───────────────────────────────────────────────┘
```

**What You Can Edit**:
- ✅ Reading data (all measurement values)
- ✅ Result status (Pass/Fail/Conditional/Warning)
- ✅ Remarks and notes
- ❌ Reading number (auto-assigned)
- ❌ Session ID (locked to session)

### 8.2 Deleting a Reading

#### Step 1: Click Delete Button

Click **🗑️ Delete** icon on reading card.

#### Step 2: Confirm Deletion

```
┌───────────────────────────────────────────────┐
│ ⚠️ Delete Reading #2?                         │
├───────────────────────────────────────────────┤
│                                               │
│ Are you sure you want to delete this reading?│
│                                               │
│ This action cannot be undone.                 │
│                                               │
│ Reading Details:                              │
│ • Time: 10:30 AM                              │
│ • Status: Fail                                │
│ • Remarks: Temperature too high               │
│                                               │
│    [Cancel]         [🗑️ Delete]               │
└───────────────────────────────────────────────┘
```

#### Step 3: Deletion Confirmed

```
┌───────────────────────────────────────────────┐
│ ✅ Reading Deleted                            │
│                                               │
│ Reading #2 has been removed from Session 1    │
│                                               │
│    [OK]                                       │
└───────────────────────────────────────────────┘
```

**Important Notes**:
- ⚠️ Deletion is permanent
- 📝 Remaining readings are NOT renumbered
- 📊 Statistics automatically recalculated

---

## 9. Submitting Session Results

### 9.1 Entering Test Results

After adding all readings, enter the overall session result:

#### Step 1: Click "Enter Results"

From session page, click **[Enter Results]** button.

#### Step 2: Fill Test Result Form

```
┌───────────────────────────────────────────────────────┐
│ Test Results - Session 1            [✕ Close]         │
├───────────────────────────────────────────────────────┤
│                                                       │
│ Template: Power Transformer Major Maintenance        │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ Section 1: Pre-Test Inspection                  │  │
│ │                                                 │  │
│ │   Visual Condition:     [Good ▼]               │  │
│ │   Oil Level:            [Normal ▼]             │  │
│ │   Cable Integrity:      [No damage ▼]          │  │
│ │   Mounting:             [Secure ▼]             │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ Section 2: Electrical Tests                     │  │
│ │                                                 │  │
│ │   Insulation Resistance: [500 MΩ]              │  │
│ │   Winding Resistance:    [0.52 Ω]              │  │
│ │   Turns Ratio:           [1:10.5]              │  │
│ │   Capacitance:           [2500 pF]             │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ Section 3: Oil Analysis                         │  │
│ │                                                 │  │
│ │   Breakdown Voltage:     [55 kV]               │  │
│ │   Moisture Content:      [15 ppm]              │  │
│ │   Acidity:               [0.05 mg KOH/g]       │  │
│ │   Tan Delta:             [0.5%]                │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ Section 4: Overall Assessment                   │  │
│ │                                                 │  │
│ │   Overall Result: [⚠️ Conditional ▼]            │  │
│ │                   • Pass ✅                      │  │
│ │                   • Fail ❌                      │  │
│ │                   • Conditional ⚠️               │  │
│ │                                                 │  │
│ │   Remarks:                                      │  │
│ │   ┌───────────────────────────────────────┐    │  │
│ │   │ Transformer in serviceable condition  │    │  │
│ │   │ but oil quality needs improvement.    │    │  │
│ │   │ Recommend oil filtration before       │    │  │
│ │   │ Session 2.                            │    │  │
│ │   └───────────────────────────────────────┘    │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ 🔧 Replacement Parts Needed                      │  │
│ │                                                 │  │
│ │ ➕ Add Part                                      │  │
│ │                                                 │  │
│ │ [Oil Filter] Qty: [1] Category: [Consumables]  │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ 🔗 Session: Session 1 (Apr 21, 2026)                 │
│    ↑ This result will be linked to Session 1        │
│                                                       │
│    [💾 Save Draft]         [✅ Submit Final]          │
└───────────────────────────────────────────────────────┘
```

**KEY POINT**: The result is automatically linked to the current session (Session 1). This ensures proper per-session tracking.

#### Step 3: Save Draft or Submit

- **💾 Save Draft**: Save progress, can edit later (session remains "In Progress")
- **✅ Submit Final**: Lock result, move to completing session

### 9.2 Result Saved Confirmation

```
┌───────────────────────────────────────────────┐
│ ✅ Result Saved for Session 1                 │
│                                               │
│ Overall Result: Conditional ⚠️                │
│                                               │
│ Result has been linked to Session 1.          │
│ You can still edit readings before completing │
│ the session.                                  │
│                                               │
│    [Edit Result]    [Complete Session]        │
└───────────────────────────────────────────────┘
```

---

## 10. Completing Sessions

### 10.1 Completing a Session

When all readings and results are submitted:

#### Step 1: Click "Complete Session"

From session page or timeline, click **[✅ Complete Session]**.

#### Step 2: Review & Confirm

```
┌───────────────────────────────────────────────┐
│ Complete Session 1?                           │
├───────────────────────────────────────────────┤
│                                               │
│ You are about to mark Session 1 as completed. │
│                                               │
│ Session Summary:                              │
│ • Start Time:    10:05 AM                     │
│ • Current Time:  12:30 PM                     │
│ • Duration:      2h 25m                       │
│                                               │
│ • Total Readings: 3                           │
│ • Readings Pass:  2                           │
│ • Readings Fail:  1                           │
│                                               │
│ • Test Result:    Conditional ⚠️              │
│ • Parts Needed:   Oil Filter x1               │
│                                               │
│ ⚠️ Once completed:                             │
│ • You cannot add more readings                │
│ • You CAN still edit existing readings        │
│ • Session 2 will be unlocked                  │
│                                               │
│    [Cancel]         [✅ Complete]              │
└───────────────────────────────────────────────┘
```

#### Step 3: Session Completed

```
┌───────────────────────────────────────────────┐
│ ✅ Session 1 Completed!                       │
├───────────────────────────────────────────────┤
│                                               │
│ Statistics (from backend):                    │
│ • Reading Count:  3                           │
│ • Pass Count:     2 ✅                        │
│ • Fail Count:     1 ❌                        │
│ • Duration:       2h 25m ⏱️                   │
│ • Status:         Conditional ⚠️              │
│                                               │
│ Session 2 is now available to start.          │
│                                               │
│ Scheduled: Apr 28, 2026 10:00 AM (in 7 days) │
│                                               │
│    [View Timeline]    [Start Session 2 Now]   │
└───────────────────────────────────────────────┘
```

**What Happens**:
1. ✅ Session status changed to "Completed"
2. 📊 Statistics fetched from backend (authoritative counts)
3. 🔒 Session locked from new readings (can still edit existing)
4. 🔓 Next session (Session 2) becomes available
5. 📧 Notification sent to relevant users

---

## 11. Session Statistics & Timeline

### 11.1 Viewing Statistics

After completing a session, accurate statistics are displayed:

```
╔═════════════════════════════════════════════════╗
║ 📅 1  Session 1 - Initial Inspection            ║
║                                                 ║
║ 📆 Apr 21, 2026 10:05 AM - 12:30 PM            ║
║ 🟢 Status: Completed                            ║
║                                                 ║
║ 📊 Statistics (Backend):                        ║
║    • Total Readings:    3                       ║
║    • ✅ Passed:         2 (66.7%)               ║
║    • ❌ Failed:         1 (33.3%)               ║
║    • ⏱️ Duration:       2h 25m                  ║
║    • ⚠️ Overall Result: Conditional             ║
║                                                 ║
║ 🔧 Parts Used:                                  ║
║    • Oil Filter x1                              ║
║                                                 ║
║ 💬 2 comments                                    ║
║                                                 ║
║    [View Details]  [View Report]  [Edit Readings]║
╚═════════════════════════════════════════════════╝
```

**Statistics Features**:
- 📊 **Reading Count**: Total readings in session
- ✅ **Pass Count**: Readings with "Pass" status
- ❌ **Fail Count**: Readings with "Fail" status
- ⏱️ **Duration**: Time from start to completion
- 📈 **Percentage**: Pass/fail percentages
- 🔧 **Parts**: Replacement parts used

### 11.2 Updated Timeline (All Sessions)

After completing all 3 sessions:

```
┌───────────────────────────────────────────────────────┐
│ TR-2026-001 - Power Transformer Maintenance           │
│ Session Timeline                    [📄 Final Report] │
├───────────────────────────────────────────────────────┤
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ 📊 Testing Sessions          3 of 3 completed   │  │
│ │                                                 │  │
│ │ Progress: ████████████████████████████  100%   │  │
│ │                                                 │  │
│ │ 🕐 Last tested: May 5, 2026                     │  │
│ │ 📅 Total Duration: 14 days                      │  │
│ │ 📊 Total Readings: 12                           │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📅 1  Session 1 - Initial Inspection            ║  │
│ ║ 📆 Apr 21 • 🟢 Completed • 2h 25m               ║  │
│ ║ 📊 3 readings • ✅ 2 pass, ❌ 1 fail            ║  │
│ ║ ⚠️ Result: Conditional                          ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📅 2  Session 2 - Mid-term Check                ║  │
│ ║ 📆 Apr 28 • 🟢 Completed • 1h 50m               ║  │
│ ║ 📊 5 readings • ✅ All pass                     ║  │
│ ║ ✅ Result: Pass (After oil filtration)          ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ╔═════════════════════════════════════════════════╗  │
│ ║ 📅 3  Session 3 - Final Inspection              ║  │
│ ║ 📆 May 5 • 🟢 Completed • 2h 10m                ║  │
│ ║ 📊 4 readings • ✅ All pass                     ║  │
│ ║ ✅ Result: Pass                                  ║  │
│ ╚═════════════════════════════════════════════════╝  │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ 📝 Overall Summary                              │  │
│ │                                                 │  │
│ │ Trend: 📈 Improving                             │  │
│ │ • Session 1: Conditional → Oil issue found      │  │
│ │ • Session 2: Pass → After maintenance           │  │
│ │ • Session 3: Pass → Stable performance          │  │
│ │                                                 │  │
│ │ Recommendation: Equipment suitable for          │  │
│ │                 continued operation             │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│         [📄 Generate Report]  [Submit for Approval]   │
└───────────────────────────────────────────────────────┘
```

---

## 12. Approving Multi-Session Tests

### 12.1 Approver View (SEE W&M / CEE Zone)

#### Step 1: Navigate to Pending Approvals

1. Login as **SEE W&M** or **CEE Zone**
2. Navigate to **Testing** → **Pending Approvals**
3. Multi-session requests show **📅 Multi-Session** badge

#### Step 2: Review Session-by-Session

```
┌───────────────────────────────────────────────────────┐
│ TR-2026-001 - Power Transformer Maintenance           │
│ Approval Review                                       │
├───────────────────────────────────────────────────────┤
│                                                       │
│ Equipment:    Power Transformer PT-001                │
│ Tested by:    Jane Tester (Field Tester)            │
│ Submitted:    May 5, 2026                             │
│ Duration:     14 days (3 sessions)                    │
│                                                       │
│ ┌─────────────────────────────────────────────────┐  │
│ │ Session Results Summary                         │  │
│ │                                                 │  │
│ │ Session 1 (Apr 21): ⚠️ Conditional              │  │
│ │  • 3 readings (2 pass, 1 fail)                  │  │
│ │  • Oil quality issue identified                 │  │
│ │  • Parts used: Oil Filter x1                    │  │
│ │                                                 │  │
│ │ Session 2 (Apr 28): ✅ Pass                      │  │
│ │  • 5 readings (all pass)                        │  │
│ │  • After oil filtration                         │  │
│ │  • Improvement noted                            │  │
│ │                                                 │  │
│ │ Session 3 (May 5): ✅ Pass                       │  │
│ │  • 4 readings (all pass)                        │  │
│ │  • Stable performance                           │  │
│ │  • No issues found                              │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ Overall Assessment:                                   │
│ Equipment shows improvement after maintenance and     │
│ is suitable for continued operation.                  │
│                                                       │
│ Approver Comments:                                    │
│ ┌─────────────────────────────────────────────────┐  │
│ │ [Optional: Add your review comments]            │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│    [View Detailed Report]    [✅ Approve]  [❌ Reject]│
└───────────────────────────────────────────────────────┘
```

#### Step 3: View Detailed Report

Click **[View Detailed Report]** to see complete session breakdown:

```
┌───────────────────────────────────────────────────────┐
│ Detailed Multi-Session Report                         │
│ TR-2026-001 - Power Transformer Maintenance           │
├───────────────────────────────────────────────────────┤
│                                                       │
│ [Session 1 Details]                                   │
│ ├─ All 3 readings with data                          │
│ ├─ Test result form (complete)                       │
│ ├─ Comments history                                   │
│ └─ Timestamp audit trail                             │
│                                                       │
│ [Session 2 Details]                                   │
│ ├─ All 5 readings with data                          │
│ ├─ Test result form (complete)                       │
│ ├─ Comments history                                   │
│ └─ Timestamp audit trail                             │
│                                                       │
│ [Session 3 Details]                                   │
│ ├─ All 4 readings with data                          │
│ ├─ Test result form (complete)                       │
│ ├─ Comments history                                   │
│ └─ Timestamp audit trail                             │
│                                                       │
│ [Audit Trail]                                         │
│ • Apr 15: Request created by EE TLSS                 │
│ • Apr 16: Approved by SEE W&M                        │
│ • Apr 16: Assigned to Jane Tester                    │
│ • Apr 21: Session 1 started                          │
│ • Apr 21: Session 1 completed                        │
│ • Apr 28: Session 2 started                          │
│ • Apr 28: Session 2 completed                        │
│ • May 5: Session 3 started                           │
│ • May 5: Session 3 completed                         │
│ • May 5: Submitted for approval                      │
│                                                       │
│         [📥 Download PDF]    [📊 Download Excel]      │
└───────────────────────────────────────────────────────┘
```

#### Step 4: Approve or Reject

**Approve**:
```
┌───────────────────────────────────────────────┐
│ ✅ Approve Testing Results?                   │
├───────────────────────────────────────────────┤
│                                               │
│ By approving, you confirm that:               │
│ • All 3 sessions were conducted properly      │
│ • Results are acceptable                      │
│ • Equipment meets operational standards       │
│                                               │
│ Approval Comments (Optional):                 │
│ ┌───────────────────────────────────────────┐ │
│ │ Transformer suitable for continued        │ │
│ │ operation. Good work on identifying       │ │
│ │ and resolving oil issue.                  │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│    [Cancel]         [✅ Approve]               │
└───────────────────────────────────────────────┘
```

**Reject**:
```
┌───────────────────────────────────────────────┐
│ ❌ Reject Testing Results?                    │
├───────────────────────────────────────────────┤
│                                               │
│ Rejection Reason (Required):                  │
│ ┌───────────────────────────────────────────┐ │
│ │ Session 1 oil quality issue not           │ │
│ │ adequately documented. Need additional    │ │
│ │ oil analysis report before approval.      │ │
│ └───────────────────────────────────────────┘ │
│                                               │
│ ⚠️ Tester will be notified and can resubmit  │
│    after addressing the issues.               │
│                                               │
│    [Cancel]         [❌ Reject]                │
└───────────────────────────────────────────────┘
```

---

## 13. Reports & Analytics

### 13.1 Multi-Session Test Reports

#### Generating Reports

1. Navigate to **Reports** → **Testing Reports**
2. Select **Multi-Session Test Summary**
3. Filter by:
   - Date Range
   - Equipment Type
   - Tester
   - Status

#### Report Output (Excel)

```
┌─────────────────────────────────────────────────────────┐
│ Multi-Session Test Summary Report                      │
│ Generated: May 10, 2026 | Period: Apr 2026            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Request   │ Equipment │ Sessions│ Duration│ Result     │
│ ID        │           │ Complete│ (days)  │            │
├───────────┼───────────┼─────────┼─────────┼────────────┤
│ TR-2026-  │ PT-001    │ 3/3     │ 14      │ ✅ Pass    │
│ 001       │           │ (100%)  │         │            │
├───────────┼───────────┼─────────┼─────────┼────────────┤
│ TR-2026-  │ CB-045    │ 2/3     │ 7       │ 🟡 Pending │
│ 015       │           │ (66%)   │         │            │
├───────────┼───────────┼─────────┼─────────┼────────────┤
│ TR-2026-  │ CT-099    │ 5/5     │ 21      │ ✅ Pass    │
│ 028       │           │ (100%)  │         │            │
└─────────────────────────────────────────────────────────┘
```

### 13.2 Session Performance Analytics

```
┌─────────────────────────────────────────────────────────┐
│ Session Performance Dashboard                           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Total Multi-Session Requests:     45                   │
│ Sessions Completed:                112 / 135 (83%)     │
│ Average Duration per Session:      2h 15m              │
│ On-Time Completion Rate:           92%                 │
│                                                         │
│ Top Equipment Types (Multi-Session):                    │
│ 1. Power Transformers:  25 requests                    │
│ 2. Circuit Breakers:    12 requests                    │
│ 3. Protection Relays:   8 requests                     │
│                                                         │
│ Average Readings per Session:      4.2                 │
│ Pass Rate (All Sessions):          87%                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 14. Troubleshooting

### 14.1 Common Issues

#### Issue 1: Cannot Start Next Session

**Symptom**: "Session 2" button is grayed out

**Causes & Solutions**:
1. **Previous session not complete**
   - ✅ Complete Session 1 first
   - Click **[✅ Complete Session]** on Session 1

2. **Test result not submitted**
   - ✅ Submit result for previous session
   - Go to Session 1 → **[Enter Results]** → **[Submit Final]**

3. **Permission issue**
   - ✅ Check you're assigned as tester
   - Contact **EE TLSS** if not assigned

#### Issue 2: Cannot Edit Reading

**Symptom**: Edit button not showing or disabled

**Causes & Solutions**:
1. **Session completed**
   - ✅ Readings can still be edited after completion
   - Click **✏️ Edit** button (should be visible)

2. **Not your session**
   - ✅ Only assigned tester can edit
   - Check assignment in request detail

3. **Browser cache issue**
   - ✅ Refresh page (Ctrl+F5)
   - Clear browser cache and reload

#### Issue 3: Statistics Not Showing

**Symptom**: Session shows "0 readings" after adding readings

**Causes & Solutions**:
1. **Page not refreshed**
   - ✅ Click **[🔄 Refresh]** button
   - Reload page

2. **Backend sync delay**
   - ✅ Wait 10-15 seconds
   - Statistics are fetched from backend after completion

3. **Connection issue**
   - ✅ Check internet connection
   - Refresh page when online

#### Issue 4: Cannot Delete Reading

**Symptom**: Delete button not working

**Causes & Solutions**:
1. **Last reading in session**
   - ✅ Session must have at least 1 reading
   - Add another reading before deleting

2. **Result already submitted**
   - ✅ You can still delete readings after result submission
   - Session must be "In Progress" or "Completed"

### 14.2 Error Messages

| Error Message | Meaning | Solution |
|---------------|---------|----------|
| "Session not found" | Session ID invalid | Check URL, refresh page |
| "Cannot start session yet" | Previous session incomplete | Complete previous session first |
| "Reading data invalid" | JSON format error | Check JSON syntax in reading data |
| "Unauthorized" | Permission denied | Contact admin for access |
| "Session already completed" | Trying to add reading to complete session | Cannot add new readings to completed sessions |

### 14.3 Getting Help

1. **Documentation**
   - This user manual
   - SEACMS Main User Manual
   - Quick Reference (Section 15)

2. **Support Contacts**
   - IT Support: `support@kptcl.com`
   - System Admin: Org Admin user
   - Training: Contact your supervisor

3. **Reporting Bugs**
   - Email: `seacms.bugs@kptcl.com`
   - Include: Screenshot, error message, steps to reproduce

---

## 15. Quick Reference

### 15.1 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Ctrl + N** | New testing request |
| **Ctrl + R** | Refresh page/timeline |
| **Ctrl + S** | Save draft |
| **Ctrl + Enter** | Submit/Complete |
| **Esc** | Close dialog |

### 15.2 Status Icons

| Icon | Meaning |
|:----:|---------|
| ⚪ | Scheduled |
| 🟡 | In Progress |
| 🟢 | Completed |
| 🔴 | Failed |
| ⚫ | Skipped |
| ✅ | Pass |
| ❌ | Fail |
| ⚠️ | Conditional |
| ℹ️ | Warning |

### 15.3 Quick Actions

| Task | Path |
|------|------|
| **Create Multi-Session Request** | Testing → New Request → ☑ Enable Multi-Session |
| **View Timeline** | My Assignments → Click Request → View Sessions |
| **Start Session** | Timeline → Click Session → [Start Session] |
| **Add Reading** | Session Page → [➕ Add Reading] |
| **Edit Reading** | Session Page → Reading Card → [✏️ Edit] |
| **Submit Result** | Session Page → [Enter Results] → [Submit] |
| **Complete Session** | Session Page → [✅ Complete Session] |
| **View Statistics** | Timeline → Completed Session Card |
| **Approve Request** | Pending Approvals → Request → [Approve] |

### 15.4 API Endpoints (For Reference)

| Action | Method | Endpoint |
|--------|--------|----------|
| Get Sessions | GET | `/testing_requests/{id}/sessions` |
| Create Session | POST | `/testing_requests/{id}/sessions` |
| Start Session | POST | `/sessions/{id}/start` |
| Complete Session | POST | `/sessions/{id}/complete` |
| Add Reading | POST | `/sessions/{id}/readings` |
| Edit Reading | PUT | `/sessions/{id}/readings/{rid}` |
| Delete Reading | DELETE | `/sessions/{id}/readings/{rid}` |
| Get Statistics | GET | `/sessions/{id}/statistics` |
| Submit Result | POST | `/testing/{id}/results/structured` |

### 15.5 Best Practices

1. **Planning**
   - Determine number of sessions needed before starting
   - Set realistic intervals between sessions
   - Coordinate with lab/field scheduling

2. **During Testing**
   - Record readings immediately (don't wait)
   - Add detailed remarks for context
   - Use Edit feature to correct mistakes promptly
   - Save drafts frequently

3. **After Testing**
   - Review all readings before completing session
   - Ensure result form is complete
   - Add comprehensive summary in remarks
   - Complete session promptly

4. **Approval**
   - Review session-by-session progression
   - Check for consistent documentation
   - Verify equipment improvement/degradation trends
   - Provide clear approval/rejection comments

---

## Appendix A: Sample Scenarios

### Scenario 1: Power Transformer 3-Week Maintenance

**Equipment**: Power Transformer PT-001 (220kV)  
**Sessions**: 3 (Weekly intervals)  
**Purpose**: Progressive oil quality monitoring

**Timeline**:
- **Week 1 (Session 1)**: Initial assessment
  - Found: Oil quality degrading
  - Action: Oil filtration ordered
  - Result: Conditional

- **Week 2 (Session 2)**: Post-maintenance check
  - Found: Oil quality improved
  - Action: Continue monitoring
  - Result: Pass

- **Week 3 (Session 3)**: Final verification
  - Found: Stable performance
  - Action: Return to service
  - Result: Pass

**Outcome**: Equipment approved for continued operation

### Scenario 2: Circuit Breaker 10-Stage Repair

**Equipment**: Circuit Breaker CB-045 (132kV)  
**Sessions**: 10 (As per repair stages)  
**Purpose**: Complete repair lifecycle tracking

**Stages**:
1. Failure Report
2. Repair Committee Inspection
3. Allotment to Repairer
4. Lifting by Repairer
5. Joint Inspection at Vendor
6. Estimate & Revised Work Award
7. Stage Inspections (multiple)
8. Final Inspection
9. Dispatch
10. Erection Testing & Commissioning

**Duration**: 45 days total

**Outcome**: Equipment repaired and commissioned successfully

---

## Appendix B: Screenshots

*(Note: In actual documentation, include screenshots of each screen)*

1. Multi-Session Configuration Screen
2. Session Timeline View
3. Session Detail Page
4. Add Reading Form
5. Edit Reading Dialog
6. Test Result Form (with session link indicator)
7. Complete Session Confirmation
8. Session Statistics Display
9. Approver View
10. Multi-Session Report

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Multi-Session** | Testing process spanning multiple days/sessions |
| **Session** | Single testing instance within multi-session request |
| **Reading** | Individual measurement taken during session |
| **Session Timeline** | Visual display of all sessions and their status |
| **Statistics** | Pass/fail counts and metrics per session |
| **Per-Session Result** | Test result linked to specific session |
| **Progressive Testing** | Testing over time to observe trends |
| **Session Link** | Database connection between result and session |

---

## Document Information

**Document**: SEACMS-AI Multi-Session Testing User Manual  
**Version**: 2.0  
**Date**: April 2026  
**Prepared by**: SEACMS Development Team  
**Approved by**: CEE RT&R&D  
**Classification**: Internal Use  
**Next Review**: October 2026  

---

## Revision History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | Mar 2026 | Initial draft | Dev Team |
| 2.0 | Apr 2026 | Added Edit/Delete reading features, Statistics display | Dev Team |

---

**For technical support or questions about this manual, contact:**  
📧 Email: `seacms.support@kptcl.com`  
📞 Phone: +91-80-XXXX-XXXX  
🌐 Portal: `https://seacms.kptcl.com/support`

---

**© 2026 Karnataka Power Transmission Corporation Limited. All rights reserved.**
