# Multi-Session Automatic Status Transition

## Overview

Automatic status transition system for multi-session testing requests. The system moves completed tests to the approver queue automatically based on two conditions:

1. **All sessions completed**: When tester completes all planned sessions
2. **End date elapsed**: When scheduled end date passes (even if not all sessions completed)

---

## ✨ Features Implemented

### 1. **Session Comments System**
- Approvers can comment on individual sessions
- Comments stored with author details and timestamps
- Edit/delete permissions (own comments only)
- Comment count displayed in session timeline

### 2. **Automatic Status Transition**
- Triggers on session completion
- Checks if all sessions are completed
- Auto-transitions `in_progress` → `test_submitted`
- Moves test to approver queue automatically

### 3. **End Date-Based Transition** (NEW REQUIREMENT)
- Scheduled job checks for elapsed end dates
- Auto-submits tests even if not all sessions complete
- Marks incomplete sessions as "skipped"
- Notifies approvers of partial completion

---

## 🔄 Auto-Transition Triggers

### **Trigger 1: Session Completion**

```python
# When tester completes a session:
POST /testing_requests/{id}/sessions/{session_id}/complete

Backend Logic:
1. Mark session as completed
2. Check if all sessions completed
3. If yes → Auto-transition to test_submitted
4. Notify approvers
```

**Example:**
```
Test has 5 sessions planned
- Session 1: ✅ completed
- Session 2: ✅ completed  
- Session 3: ✅ completed
- Session 4: ✅ completed
- Session 5: ✅ completed  ← Tester completes this

→ System auto-transitions status to "test_submitted"
→ Test appears in approver queue
```

### **Trigger 2: End Date Elapsed**

```python
# Scheduled job runs every hour:
check_elapsed_multi_session_tests()

Backend Logic:
1. Find all in_progress multi-session tests
2. Check if scheduled_end_date has passed
3. If yes:
   - Mark incomplete sessions as "skipped"
   - Auto-transition to test_submitted
   - Notify approvers (with warning about incomplete sessions)
```

**Example:**
```
Test scheduled: 15 Apr 2026 - 13 May 2026
Total sessions planned: 5

Current status (15 May 2026):
- Session 1: ✅ completed
- Session 2: ✅ completed  
- Session 3: ✅ completed
- Session 4: ⏭ scheduled (not started)
- Session 5: ⏭ scheduled (not started)

→ End date elapsed (13 May passed)
→ System marks Sessions 4-5 as "skipped"
→ Auto-transitions to "test_submitted"
→ Approver receives notification:
   "Test partially completed (3/5 sessions).
    Sessions 4-5 were skipped due to elapsed deadline."
```

---

## 📁 Files Modified/Created

### **Backend - New Files**
1. `routers/session_comments.py` - Session comment endpoints
2. `services/auto_status_transition_service.py` - Auto-transition logic
3. `migrations/004_add_session_comments.sql` - Database migration

### **Backend - Modified Files**
1. `models.py` - Added SessionComment model
2. `schemas.py` - Added SessionCommentCreate/Response schemas
3. `services/test_session_service.py` - Integrated auto-transition on session complete
4. `main.py` - Registered session_comments router

### **Frontend - New Files**
1. `lib/pages/zoho/multi_session_config_section.dart` - Multi-session config UI
2. `lib/pages/zoho/session_timeline_view.dart` - Visual session timeline
3. `lib/pages/zoho/session_report_view.dart` - Detailed session report
4. `lib/pages/zoho/session_comments_panel.dart` - Approver comments UI
5. `MULTI_SESSION_UI_INTEGRATION.md` - Complete integration guide

---

## 🔧 Backend Implementation Details

### **Service: AutoStatusTransitionService**

```python
class AutoStatusTransitionService:
    def check_and_transition_if_all_sessions_complete(self, request_id):
        """
        Called after every session completion.
        Checks if all sessions done → auto-submit.
        """
        # Get testing request
        test = db.get(TestingRequest, request_id)
        
        # Only for multi-session, in_progress status
        if not test.is_multi_session or test.status != "in_progress":
            return False
        
        # Get all sessions
        sessions = db.query(TestSession).filter_by(
            testing_request_id=request_id
        ).all()
        
        # Check if all completed
        if all(s.status == "completed" for s in sessions):
            test.status = "test_submitted"
            test.submitted_at = now()
            db.commit()
            notify_approvers(test)
            return True
        
        return False

    def check_elapsed_end_dates(self):
        """
        Scheduled job (runs hourly).
        Finds tests with elapsed end dates → auto-submit.
        """
        # Find in_progress multi-session tests
        tests = db.query(TestingRequest).filter(
            TestingRequest.status == "in_progress",
            TestingRequest.is_multi_session == True,
        ).all()
        
        transitioned_count = 0
        now = datetime.utcnow()
        
        for test in tests:
            # Calculate end date from start + sessions + interval
            if test.scheduled_start_date:
                days_needed = (test.total_sessions_planned - 1) * test.session_interval_days
                end_date = test.scheduled_start_date + timedelta(days=days_needed)
                
                if now > end_date:
                    # Mark incomplete sessions as skipped
                    sessions = db.query(TestSession).filter_by(
                        testing_request_id=test.id
                    ).all()
                    
                    for session in sessions:
                        if session.status == "scheduled":
                            session.status = "skipped"
                    
                    # Auto-submit
                    test.status = "test_submitted"
                    test.submitted_at = now
                    db.commit()
                    
                    # Notify with warning
                    completed_count = sum(1 for s in sessions if s.status == "completed")
                    notify_approvers_with_warning(
                        test,
                        f"Partially completed: {completed_count}/{len(sessions)} sessions"
                    )
                    
                    transitioned_count += 1
        
        return transitioned_count
```

### **Integration into complete_session**

```python
# services/test_session_service.py

def complete_session(self, session_id: UUID) -> TestSession:
    """Mark session as completed and check for auto-transition."""
    session = self.update_session(
        session_id=session_id,
        status="completed",
        completed_at=datetime.utcnow(),
    )

    # ✅ AUTO-TRANSITION CHECK
    from services.auto_status_transition_service import AutoStatusTransitionService
    auto_svc = AutoStatusTransitionService(self.db)
    auto_svc.check_and_transition_if_all_sessions_complete(
        session.testing_request_id
    )

    return session
```

### **Scheduled Job Setup**

```python
# main.py

from apscheduler.schedulers.background import BackgroundScheduler
from services.auto_status_transition_service import AutoStatusTransitionService

scheduler = BackgroundScheduler()

# Check every hour for elapsed end dates
@scheduler.scheduled_job('interval', hours=1)
def check_elapsed_tests():
    db = SessionLocal()
    try:
        svc = AutoStatusTransitionService(db)
        count = svc.check_elapsed_end_dates()
        if count > 0:
            logger.info(f"Auto-submitted {count} tests due to elapsed end dates")
    finally:
        db.close()

scheduler.start()
```

---

## 🗄️ Database Schema

### **New Table: session_comments**

```sql
CREATE TABLE public.session_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.test_sessions(id) ON DELETE CASCADE,
    
    comment TEXT NOT NULL,
    author_id UUID NOT NULL REFERENCES public.users(id),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_session_comments_session_id ON public.session_comments(session_id);
CREATE INDEX idx_session_comments_author_id ON public.session_comments(author_id);
```

### **Session Status Values**

- `scheduled` - Session is planned for future
- `in_progress` - Session currently being conducted
- `completed` - Session finished with all readings
- `skipped` - Session was not conducted (auto-set on end date elapsed)

---

## 🎯 Complete Workflow Example

### **Scenario: Weekly Monitoring Test (5 Weeks)**

**Phase 1: Create Test**
```
User creates test:
  - Start: 15 Apr 2026, 08:00 AM
  - Sessions: 5
  - Interval: Weekly (7 days)
  - End date: 13 May 2026 (calculated automatically)

→ Status: draft
```

**Phase 2: Submit & Approve**
```
User submits → Status: submitted
Admin approves → Status: assigned
Tester accepts → Status: in_progress
Backend auto-generates 5 sessions
```

**Phase 3: Conduct Tests (Happy Path)**
```
15 Apr: Complete Session 1 ✅
22 Apr: Complete Session 2 ✅
29 Apr: Complete Session 3 ✅
06 May: Complete Session 4 ✅
13 May: Complete Session 5 ✅

→ Trigger: All sessions complete
→ Auto-transition: Status = test_submitted
→ Notification: Approvers notified
```

**Phase 4: Approver Review**
```
Approver opens test:
  - Views session timeline (all 5 completed)
  - Clicks each session → Sees detailed report
  - Adds comments on specific sessions
  - Makes final decision: Approve/Reject

→ Status: approved
```

### **Scenario: Test with Elapsed End Date**

**Phase 3: Conduct Tests (Incomplete)**
```
15 Apr: Complete Session 1 ✅
22 Apr: Complete Session 2 ✅
29 Apr: Complete Session 3 ✅
06 May: Session 4 not conducted ⏱
13 May: Session 5 not conducted ⏱

→ Trigger: End date elapsed (13 May passed)
→ Scheduled job runs (next hour check)
→ Auto-marks Sessions 4-5 as "skipped"
→ Auto-transition: Status = test_submitted
→ Notification: Approvers notified with warning
   "Test partially completed (3/5 sessions).
    Remaining sessions skipped due to elapsed deadline."
```

**Phase 4: Approver Review (Partial)**
```
Approver sees:
  - Session 1: ✅ Completed (5 readings, all pass)
  - Session 2: ✅ Completed (5 readings, all pass)
  - Session 3: ✅ Completed (4 readings, 1 fail)
  - Session 4: ⏭ Skipped (deadline elapsed)
  - Session 5: ⏭ Skipped (deadline elapsed)

Approver decisions:
  - Option 1: Reject → Request retest for skipped sessions
  - Option 2: Approve conditionally → Accept 3/5 sessions as sufficient
  - Option 3: Approve → Mark as pass based on available data
```

---

## 🔔 Notification Messages

### **All Sessions Completed**
```
Subject: Test Ready for Approval
Body:
"Multi-session test '{title}' (ID: {id}) has been completed.

All {count} sessions have been successfully conducted and are ready for your review.

View details: {link}
```

### **End Date Elapsed (Partial Completion)**
```
Subject: Test Submitted (Partial Completion)
Body:
"Multi-session test '{title}' (ID: {id}) has been automatically submitted.

⚠️ Warning: Test deadline elapsed
- Completed sessions: {completed_count}/{total_count}
- Skipped sessions: {skipped_count}

Reason: Scheduled end date ({end_date}) has passed.

Please review available data and decide on approval.

View details: {link}
```

---

## 📊 Session Statistics Enhanced

```json
GET /testing_requests/{id}/sessions/{session_id}/statistics

Response:
{
  "session_id": "uuid",
  "session_number": 1,
  "status": "completed",
  "reading_count": 5,
  "pass_count": 4,
  "fail_count": 1,
  "comment_count": 2,  // ← NEW
  "duration_minutes": 420
}
```

---

## ✅ Implementation Checklist

### Backend
- [x] SessionComment model created
- [x] Session comments API endpoints (GET, POST, PUT, DELETE)
- [x] AutoStatusTransitionService implemented
- [x] Integration into complete_session method
- [x] Database migration script
- [x] Session statistics enhanced with comment_count
- [ ] Scheduled job for end date checks (add to main.py)
- [ ] Notification system integration

### Frontend
- [x] MultiSessionConfigSection component
- [x] SessionTimelineView component
- [x] SessionReportView component
- [x] SessionCommentsPanel component
- [x] Integration guide created
- [ ] Update CreateTestingRequestForm to use new components
- [ ] Update TestingRequestDetail to show timeline
- [ ] Test with real data

### Database
- [ ] Run migration 004_add_session_comments.sql
- [ ] Verify session_comments table created
- [ ] Test comment CRUD operations

### Testing
- [ ] Create multi-session test (5 sessions)
- [ ] Complete all sessions → verify auto-transition
- [ ] Complete 3/5 sessions, wait for end date → verify auto-transition
- [ ] Add approver comments → verify saved
- [ ] Check approver queue → verify test appears
- [ ] Final approval → verify workflow complete

---

## 🚀 Deployment Steps

1. **Database Migration**
   ```bash
   psql -U postgres -d database_name -f migrations/004_add_session_comments.sql
   ```

2. **Backend Deployment**
   ```bash
   # Pull latest code
   git pull origin dev
   
   # Restart backend
   systemctl restart fastapi-app
   ```

3. **Schedule Job Activation**
   ```python
   # Verify scheduler is running in main.py
   # Check logs for: "Scheduler started"
   ```

4. **Frontend Deployment**
   ```bash
   cd coginiwattcustomer
   git pull origin feature/org-test-templates
   flutter build web
   # Deploy to hosting
   ```

---

## 📝 Notes

- Auto-transition only works for `is_multi_session = true` tests
- Only tests in `in_progress` status are checked
- End date is calculated as: `start_date + ((total_sessions - 1) * interval_days)`
- Skipped sessions cannot be reopened (final state)
- Approvers can still approve/reject partially completed tests
- Comment count displayed in session timeline for quick reference

---

**Status**: ✅ Core implementation complete, ready for testing
**Last Updated**: 2026-04-08
