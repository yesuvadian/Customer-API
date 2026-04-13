# Manual Testing Guide - Multi-Session Features

**Quick Reference for testing multi-session functionality via Swagger UI**

## Prerequisites
- ✅ Database seeded
- ✅ Server running on http://localhost:8001
- ✅ Open Swagger UI: http://localhost:8001/docs

---

## Test Users

| Role | Email | Password |
|------|-------|----------|
| Requester | originator@sampleorg.com | Originator123! |
| Approver | testassigner@sampleorg.com | Assigner123! |
| Tester | fieldtester1@sampleorg.com | Tester123! |
| Admin | orgadmin@sampleorg.com | OrgAdmin123! |

---

## Step-by-Step Test Flow

### 1. Login (Get Auth Token)
**Endpoint:** `POST /auth/login`

```json
{
  "email": "fieldtester1@sampleorg.com",
  "password": "Tester123!"
}
```

**Response:** Copy the `access_token`  
**Action:** Click "Authorize" button in Swagger, paste token

---

### 2. Get Organization and Department IDs

**Get Organizations:** `GET /organizations`  
→ Copy first organization `id` (e.g., `36c72c1e-0f99-48c3-ad87-8322552ccee2`)

**Get Departments:** `GET /organizations/{org_id}/departments/`  
→ Copy first department `id` (e.g., `f669cd16-41f1-4d27-9bb6-cf655b4b61cc`)

**Get Equipment Types:** `GET /testing_requests/equipment_types`  
→ Copy first equipment type `id` (e.g., `19`)

---

### 3. Create Multi-Session Request
**Endpoint:** `POST /testing_requests/`

```json
{
  "title": "Weekly Transformer Test - 5 Sessions",
  "description": "Monitor transformer performance over 5 weeks",
  "equipment_type_id": 19,
  "organization_id": "36c72c1e-0f99-48c3-ad87-8322552ccee2",
  "department_id": "f669cd16-41f1-4d27-9bb6-cf655b4b61cc",
  "priority": "high",
  "scheduled_start_date": "2026-04-09T10:00:00",
  "is_multi_session": true,
  "total_sessions_planned": 5,
  "session_interval_days": 7
}
```

**Response:** Copy the request `id`

---

### 4. Auto-Generate Sessions
**Endpoint:** `POST /testing_requests/{request_id}/sessions/auto-generate`

**Response:** Returns array of 5 sessions  
→ Copy session IDs for use in next steps

---

### 5. Start Session
**Endpoint:** `POST /testing_requests/{request_id}/sessions/{session_id}/start`

**Response:** Session status changes to `in_progress`

---

### 6. Add Readings (Repeat 3 times)
**Endpoint:** `POST /testing_requests/{request_id}/sessions/{session_id}/readings`

**Reading 1:**
```json
{
  "reading_number": 1,
  "reading_time": "2026-04-09T10:15:00",
  "reading_data": {
    "voltage": 11.6,
    "current": 150.0,
    "temperature": 61,
    "power_factor": 0.92
  },
  "equipment_serial": "METER-2024-001",
  "result_status": "pass",
  "remarks": "All parameters normal"
}
```

**Reading 2:** (Change values slightly)
```json
{
  "reading_number": 2,
  "reading_time": "2026-04-09T10:30:00",
  "reading_data": {
    "voltage": 11.7,
    "current": 155.0,
    "temperature": 62,
    "power_factor": 0.93
  },
  "equipment_serial": "METER-2024-001",
  "result_status": "pass",
  "remarks": "Readings stable"
}
```

**Reading 3:**
```json
{
  "reading_number": 3,
  "reading_time": "2026-04-09T10:45:00",
  "reading_data": {
    "voltage": 11.8,
    "current": 160.0,
    "temperature": 63,
    "power_factor": 0.91
  },
  "equipment_serial": "METER-2024-001",
  "result_status": "warning",
  "remarks": "Temperature slightly elevated"
}
```

---

### 7. Complete Session
**Endpoint:** `POST /testing_requests/{request_id}/sessions/{session_id}/complete`

**Response:** Session status changes to `completed`

---

### 8. View Session Report
**Endpoint:** `GET /testing_requests/{request_id}/sessions/{session_id}`

**Response:** Shows:
- Session metadata
- All readings
- Status, timestamps
- Statistics

---

### 9. Get All Readings
**Endpoint:** `GET /testing_requests/{request_id}/sessions/{session_id}/readings`

**Response:** Array of all 3 readings with full details

---

### 10. Add Approver Comment
**Endpoint:** `POST /testing_requests/{request_id}/sessions/{session_id}/comments/`

**Login as approver first!** (testassigner@sampleorg.com)

```json
{
  "comment": "Session completed successfully. All readings within acceptable parameters. Equipment calibration verified."
}
```

---

### 11. Get Session Comments
**Endpoint:** `GET /testing_requests/{request_id}/sessions/{session_id}/comments/`

**Response:** Array of comments with author info

---

### 12. Get Session Statistics
**Endpoint:** `GET /testing_requests/{request_id}/sessions/{session_id}/statistics`

**Response:**
```json
{
  "reading_count": 3,
  "pass_count": 2,
  "fail_count": 0,
  "warning_count": 1,
  "comment_count": 1,
  "duration_minutes": 30
}
```

---

### 13. List All Sessions
**Endpoint:** `GET /testing_requests/{request_id}/sessions/`

**Response:** All 5 sessions with their current status

---

## Repeat for Remaining Sessions

Repeat steps 5-12 for sessions 2, 3, 4, and 5.

---

## Expected Results After All 5 Sessions

- ✅ 5 sessions created (all with unique dates)
- ✅ All sessions completed
- ✅ 15 total readings (3 per session)
- ✅ Comments on each session
- ✅ Individual session reports available
- ✅ Complete test history

---

## Database Verification Queries

```sql
-- View the multi-session request
SELECT id, title, is_multi_session, total_sessions_planned, 
       session_interval_days, scheduled_start_date, status
FROM testing_requests
WHERE is_multi_session = true
ORDER BY cts DESC
LIMIT 1;

-- View all sessions
SELECT session_number, session_date, status, 
       started_at, completed_at
FROM test_sessions
WHERE testing_request_id = '<your-request-id>'
ORDER BY session_number;

-- Count readings per session
SELECT ts.session_number, COUNT(r.id) as reading_count
FROM test_sessions ts
LEFT JOIN test_session_readings r ON ts.id = r.test_session_id
WHERE ts.testing_request_id = '<your-request-id>'
GROUP BY ts.session_number
ORDER BY ts.session_number;

-- View all comments
SELECT ts.session_number, c.comment, u.firstname, u.lastname, c.created_at
FROM session_comments c
JOIN test_sessions ts ON c.session_id = ts.id
JOIN users u ON c.author_id = u.id
WHERE ts.testing_request_id = '<your-request-id>'
ORDER BY ts.session_number, c.created_at;
```

---

## API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/testing_requests/` | POST | Create multi-session request |
| `/testing_requests/{id}/sessions/auto-generate` | POST | Generate all sessions |
| `/testing_requests/{id}/sessions/` | GET | List all sessions |
| `/testing_requests/{id}/sessions/{sid}` | GET | Get session details |
| `/testing_requests/{id}/sessions/{sid}/start` | POST | Start session |
| `/testing_requests/{id}/sessions/{sid}/complete` | POST | Complete session |
| `/testing_requests/{id}/sessions/{sid}/readings` | POST | Add reading |
| `/testing_requests/{id}/sessions/{sid}/readings` | GET | Get all readings |
| `/testing_requests/{id}/sessions/{sid}/comments/` | POST | Add comment |
| `/testing_requests/{id}/sessions/{sid}/comments/` | GET | Get comments |
| `/testing_requests/{id}/sessions/{sid}/statistics` | GET | Get statistics |

---

## ✅ Success Criteria

After completing all steps, you should have:

1. ✅ 1 multi-session testing request created
2. ✅ 5 sessions generated with weekly intervals
3. ✅ Each session started and completed
4. ✅ 3 readings per session (15 total)
5. ✅ Comments added by approver on each session
6. ✅ Session reports showing all details
7. ✅ Statistics available for each session

---

## 🎯 Tips for Testing

- **Use different users:** Login as different users to test role-based access
- **Check timestamps:** Verify session dates are 7 days apart
- **Test reading values:** Use realistic values for voltage, current, temperature
- **Add meaningful comments:** Use real feedback in approver comments
- **Monitor status changes:** Watch how session status changes from scheduled → in_progress → completed

---

## 🐛 Troubleshooting

**Error: 401 Unauthorized**  
→ Token expired, login again and update authorization

**Error: 404 Not Found**  
→ Check that you're using correct IDs (request_id, session_id)

**Error: 422 Validation Error**  
→ Check JSON format, ensure all required fields present

**Session won't start:**  
→ Verify session status is 'scheduled' before starting

**Can't add readings:**  
→ Session must be 'in_progress' to add readings

---

**Server:** http://localhost:8001  
**Swagger UI:** http://localhost:8001/docs  
**Database:** Relu_Vendor2 (PostgreSQL)
