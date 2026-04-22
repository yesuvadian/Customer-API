# Multi-Session Testing Feature Guide

## Overview

The Multi-Session Testing feature allows tests to be:
1. **Scheduled** for future dates
2. **Span multiple days** with sessions at regular intervals
3. **Record multiple readings** per session

This is useful for tests that require:
- Monitoring equipment over time
- Environmental condition tracking
- Multiple data collection points
- Witness verification across sessions

---

## Key Concepts

### 1. **Scheduled Tests**
Tests can now be scheduled to start at a future date instead of starting immediately.

- New field: `scheduled_start_date`
- New status: `scheduled`
- Tests remain in "scheduled" status until the start date is reached

### 2. **Multi-Session Tests**
Tests that span multiple days with sessions at regular intervals.

- `is_multi_session`: Boolean flag
- `total_sessions_planned`: Number of planned sessions
- `session_interval_days`: Days between sessions

### 3. **Test Sessions**
Individual testing sessions within a multi-session test.

- Each session has a session number (1, 2, 3, etc.)
- Sessions track environmental conditions
- Sessions can be scheduled, in progress, completed, or skipped
- Each session can have a different conductor

### 4. **Session Readings**
Multiple readings within a single session.

- Structured data stored as JSONB
- Each reading has a timestamp
- Support for equipment serial numbers and calibration dates
- Pass/fail status per reading
- Images can be attached to specific readings

---

## Database Schema

### New Tables

#### `test_sessions`
```sql
- id (UUID)
- testing_request_id (UUID, FK)
- session_number (INTEGER)
- session_name (VARCHAR)
- session_date (TIMESTAMP)
- status (VARCHAR: scheduled, in_progress, completed, skipped)
- weather_conditions (VARCHAR)
- environmental_factors (TEXT)
- conducted_by (UUID, FK to users)
- witnessed_by (VARCHAR)
```

#### `test_session_readings`
```sql
- id (UUID)
- test_session_id (UUID, FK)
- reading_number (INTEGER)
- reading_time (TIMESTAMP)
- reading_data (JSONB) -- Structured test measurements
- result_status (VARCHAR: pass, fail, conditional, warning)
- equipment_serial (VARCHAR)
- calibration_date (TIMESTAMP)
```

#### `test_session_reading_images`
```sql
- id (UUID)
- reading_id (UUID, FK)
- file_name, file_data (image binary)
- caption, sort_order
```

---

## API Endpoints

### Testing Request Endpoints (Enhanced)

#### Create Test with Scheduling
```http
POST /testing_requests
{
    "title": "Transformer Monthly Test",
    "scheduled_start_date": "2026-04-15T09:00:00Z",
    "is_multi_session": true,
    "total_sessions_planned": 3,
    "session_interval_days": 7,
    ...
}
```

### Test Session Endpoints

Base path: `/testing_requests/{request_id}/sessions`

#### Create a Session
```http
POST /testing_requests/{request_id}/sessions
{
    "session_number": 1,
    "session_name": "Initial Reading",
    "session_date": "2026-04-15T09:00:00Z",
    "template_key": "relay_testing_report"
}
```

#### Auto-Generate Sessions
```http
POST /testing_requests/{request_id}/sessions/auto-generate
```
Automatically creates all sessions based on `total_sessions_planned` and `session_interval_days`.

#### List Sessions
```http
GET /testing_requests/{request_id}/sessions
```

#### Get Session
```http
GET /testing_requests/{request_id}/sessions/{session_id}
```

#### Update Session
```http
PUT /testing_requests/{request_id}/sessions/{session_id}
{
    "status": "in_progress",
    "weather_conditions": "Clear, 25°C",
    "conducted_by": "user-uuid",
    "witnessed_by": "John Doe, External Inspector"
}
```

#### Start Session
```http
POST /testing_requests/{request_id}/sessions/{session_id}/start
```
Marks session as in progress and records start time.

#### Complete Session
```http
POST /testing_requests/{request_id}/sessions/{session_id}/complete
```
Marks session as completed and records completion time.

#### Get Session Statistics
```http
GET /testing_requests/{request_id}/sessions/{session_id}/statistics
```
Returns reading count, pass/fail counts, and duration.

### Session Reading Endpoints

Base path: `/testing_requests/{request_id}/sessions/{session_id}/readings`

#### Create Reading
```http
POST /testing_requests/{request_id}/sessions/{session_id}/readings
{
    "reading_number": 1,
    "reading_time": "2026-04-15T09:15:00Z",
    "reading_data": {
        "voltage": 11.5,
        "current": 150.3,
        "power_factor": 0.92,
        "temperature": 65
    },
    "equipment_serial": "METER-2024-001",
    "result_status": "pass",
    "remarks": "All readings within normal range"
}
```

#### List Readings
```http
GET /testing_requests/{request_id}/sessions/{session_id}/readings
```

#### Get Reading
```http
GET /testing_requests/{request_id}/sessions/{session_id}/readings/{reading_id}
```

#### Update Reading
```http
PUT /testing_requests/{request_id}/sessions/{session_id}/readings/{reading_id}
{
    "reading_data": {...},
    "result_status": "fail",
    "remarks": "Temperature exceeded limit"
}
```

#### Delete Reading
```http
DELETE /testing_requests/{request_id}/sessions/{session_id}/readings/{reading_id}
```

---

## Usage Examples

### Example 1: Weekly Monitoring Test (3 weeks)

```python
# 1. Create multi-session testing request
POST /testing_requests
{
    "title": "Transformer Load Monitoring",
    "description": "Monitor transformer under varying loads over 3 weeks",
    "equipment_type_id": 1,
    "test_type_id": 5,
    "scheduled_start_date": "2026-04-15T08:00:00Z",
    "is_multi_session": true,
    "total_sessions_planned": 3,
    "session_interval_days": 7,
    "organization_id": "org-uuid",
    "priority": "high"
}

# Response: { "id": "request-uuid", ...}

# 2. Auto-generate sessions
POST /testing_requests/request-uuid/sessions/auto-generate
# Creates 3 sessions:
# - Session 1: 2026-04-15
# - Session 2: 2026-04-22
# - Session 3: 2026-04-29

# 3. On test day, start session
POST /testing_requests/request-uuid/sessions/session-1-uuid/start

# 4. Record multiple readings throughout the day
POST /testing_requests/request-uuid/sessions/session-1-uuid/readings
{
    "reading_number": 1,
    "reading_time": "2026-04-15T08:00:00Z",
    "reading_data": {
        "load_current": 145.2,
        "voltage": 11.3,
        "temperature_top_oil": 62,
        "temperature_winding": 58
    },
    "result_status": "pass"
}

POST /testing_requests/request-uuid/sessions/session-1-uuid/readings
{
    "reading_number": 2,
    "reading_time": "2026-04-15T12:00:00Z",
    "reading_data": {
        "load_current": 178.5,
        "voltage": 11.2,
        "temperature_top_oil": 68,
        "temperature_winding": 64
    },
    "result_status": "pass"
}

POST /testing_requests/request-uuid/sessions/session-1-uuid/readings
{
    "reading_number": 3,
    "reading_time": "2026-04-15T18:00:00Z",
    "reading_data": {
        "load_current": 195.8,
        "voltage": 11.1,
        "temperature_top_oil": 72,
        "temperature_winding": 69
    },
    "result_status": "warning",
    "remarks": "Temperature approaching upper limit"
}

# 5. Complete session
POST /testing_requests/request-uuid/sessions/session-1-uuid/complete

# 6. Repeat for sessions 2 and 3 on their scheduled dates
```

### Example 2: Daily Environmental Monitoring (30 days)

```python
# Create 30-day monitoring test
POST /testing_requests
{
    "title": "Substation Environmental Monitoring",
    "scheduled_start_date": "2026-05-01T07:00:00Z",
    "is_multi_session": true,
    "total_sessions_planned": 30,
    "session_interval_days": 1,
    ...
}

# Auto-generate 30 daily sessions
POST /testing_requests/{id}/sessions/auto-generate

# Each day:
# 1. Start session
# 2. Record morning, noon, evening readings
# 3. Complete session
```

### Example 3: Single-Day Multiple Reading Test

```python
# Create test (not multi-session, but multiple readings in one session)
POST /testing_requests
{
    "title": "Power Quality Analysis",
    "scheduled_start_date": "2026-04-20T09:00:00Z",
    "is_multi_session": false,
    ...
}

# Create single session
POST /testing_requests/{id}/sessions
{
    "session_number": 1,
    "session_name": "Full Day Analysis",
    "session_date": "2026-04-20T09:00:00Z"
}

# Record readings every 15 minutes
# reading_number: 1, 2, 3, ... n
```

---

## Migration

Run the migration script:

```bash
psql -U postgres -d your_database -f migrations/003_add_multi_session_testing.sql
```

The migration adds:
- `scheduled` status to TestingRequestStatus enum
- New columns to `testing_requests` table
- Three new tables: `test_sessions`, `test_session_readings`, `test_session_reading_images`
- Indexes for performance
- Triggers for automatic timestamp updates

---

## Benefits

### For Single-Day Tests
- **Multiple readings**: Record data at different times throughout the test
- **Equipment tracking**: Track which equipment was used for each reading
- **Progressive documentation**: Add readings as the test progresses

### For Multi-Day Tests
- **Scheduled sessions**: Plan all sessions in advance
- **Environmental tracking**: Record conditions for each session
- **Witness verification**: Different witnesses for different sessions
- **Progress monitoring**: Track which sessions are completed vs pending

### For Long-Term Monitoring
- **Trend analysis**: Compare readings across sessions
- **Automated scheduling**: Auto-generate recurring sessions
- **Historical record**: Complete audit trail of all sessions and readings

---

## Frontend Integration

### Display Test Sessions
```javascript
// Get all sessions for a test
GET /testing_requests/{id}/sessions

// Show timeline:
// Session 1 (Completed) - Apr 15
// Session 2 (In Progress) - Apr 22
// Session 3 (Scheduled) - Apr 29
```

### Record Readings During Test
```javascript
// Mobile app flow:
// 1. Start session
// 2. For each measurement:
//    - Record reading_data
//    - Take photos (attach to reading)
//    - Mark pass/fail
// 3. Complete session
```

### View Session History
```javascript
// Show table of readings:
// Reading # | Time | Status | Values | Actions
// 1 | 08:00 | Pass | V:11.5kV, I:145A | [View][Edit]
// 2 | 12:00 | Pass | V:11.2kV, I:178A | [View][Edit]
// 3 | 18:00 | Warning | V:11.1kV, I:195A | [View][Edit]
```

---

## Next Steps

1. **Run migration** to create new tables
2. **Test API endpoints** using Postman/Swagger
3. **Update frontend** to support multi-session workflow
4. **Create test templates** that indicate multi-session support
5. **Train users** on new workflow

---

## Support

For questions or issues:
- Check API documentation: `/docs`
- Review test examples in this guide
- Contact development team

---

**Last Updated:** 2026-04-08
**Version:** 1.0.0
