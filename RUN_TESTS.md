# 🚀 Quick Start: Running Multi-Session Tests

## Prerequisites
- ✅ PostgreSQL installed and running
- ✅ Python 3.8+ with dependencies installed (`pip install -r requirements.txt`)
- ✅ Database configured in `.env` file

---

## 🔧 Database Credentials (from .env)

```
DB_NAME=Relu_Vendor2
DB_USER=relu_user
DB_PASSWORD=StrongPassword123!
DB_HOST=localhost
DB_PORT=5432
```

---

## 🎯 Option 1: Automated Full Test (Windows)

**One-command solution that does everything:**

```cmd
cd C:\Yesu\CustomerAPI\Customer-API
run_full_test.bat
```

**What it does:**
1. Drops all tables
2. Runs migrations
3. Creates tables
4. Seeds test data
5. Starts backend server
6. Runs comprehensive tests

---

## 🎯 Option 2: Step-by-Step (Recommended for first time)

### **Step 1: Reset Database**

#### Using existing db_setup.sh (Linux/Mac):
```bash
cd /path/to/Customer-API
./db_setup.sh --env=dev --all
```

#### Using new reset script (Windows):
```cmd
cd C:\Yesu\CustomerAPI\Customer-API
reset_and_seed.bat
```

#### Manual database reset:
```bash
# Connect to PostgreSQL
psql -U relu_user -d Relu_Vendor2 -h localhost -p 5432

# Drop and recreate schema
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO relu_user;
\q

# Run migrations
psql -U relu_user -d Relu_Vendor2 -h localhost -p 5432 -f migrations/003_add_multi_session_testing.sql
psql -U relu_user -d Relu_Vendor2 -h localhost -p 5432 -f migrations/004_add_session_comments.sql

# Create tables via SQLAlchemy
python -c "from database import Base, engine; from models import *; Base.metadata.create_all(bind=engine)"

# Run seed
python seed.py
```

---

### **Step 2: Start Backend Server**

```bash
cd C:\Yesu\CustomerAPI\Customer-API
uvicorn main:app --reload --port 8000
```

**Verify server is running:**
- Open browser: http://localhost:8000/docs
- You should see Swagger API documentation

**Keep this terminal open!** The server must be running for tests to work.

---

### **Step 3: Run Tests (in new terminal)**

Open a **new** terminal/command prompt:

```bash
cd C:\Yesu\CustomerAPI\Customer-API
python test_multi_session_complete.py
```

---

## 📋 Test Users (from seed.py)

| Role | Email | Password | Description |
|------|-------|----------|-------------|
| Requester/Originator | operator@relu.com | utility@123 | Creates testing requests |
| Approver | approver@relu.com | utility@123 | Approves requests, assigns testers |
| Tester | tester@relu.com | utility@123 | Conducts tests, records readings |
| Result Approver | admin@relu.com | utility@123 | Approves final test results |

---

## 🧪 Test Scenarios Covered

The test script (`test_multi_session_complete.py`) validates:

1. ✅ **Create Multi-Session Request** (5 weekly sessions)
2. ✅ **Approve Request** (approver role)
3. ✅ **Assign Tester** (approver assigns tester)
4. ✅ **Tester Accept** (tester accepts assignment)
5. ✅ **Auto-Generate Sessions** (backend creates 5 sessions)
6. ✅ **Conduct Session 1-5** (start, add 3 readings each, complete)
7. ✅ **View Session Reports** (detailed report with all readings)
8. ✅ **Add Approver Comments** (comment on each session)
9. ✅ **Session Statistics** (reading counts, pass/fail, duration)
10. ✅ **Auto-Transition Check** (status → test_submitted after all sessions)
11. ✅ **Final Approval** (result approver approves the test)

---

## ✅ Expected Output

```
════════════════════════════════════════════════════════════════════════════════
              MULTI-SESSION TESTING - COMPREHENSIVE TEST SUITE
════════════════════════════════════════════════════════════════════════════════

Prerequisites:
  1. Database tables dropped and recreated
  2. Seed data loaded
  3. Backend running on http://localhost:8000

Press Enter to continue...

────────────────────────────────────────────────────────────────────────────────
STEP 1: Login All Users
────────────────────────────────────────────────────────────────────────────────
ℹ Logging in as requester...
✓ Logged in as requester
ℹ Logging in as approver...
✓ Logged in as approver
ℹ Logging in as tester...
✓ Logged in as tester
ℹ Logging in as result_approver...
✓ Logged in as result_approver

... (more test output)

════════════════════════════════════════════════════════════════════════════════
                                 TEST SUMMARY
════════════════════════════════════════════════════════════════════════════════

Total Tests: 16
Passed: 16
Failed: 0
Success Rate: 100.0%

🎉 ALL TESTS PASSED! 🎉
```

---

## 🔍 Manual Verification

After automated tests pass, verify manually:

### **1. Check Database**

```sql
-- Connect to database
psql -U relu_user -d Relu_Vendor2

-- Check testing requests
SELECT id, title, status, is_multi_session, total_sessions_planned 
FROM public.testing_requests;

-- Check sessions
SELECT session_number, session_date, status 
FROM public.test_sessions 
ORDER BY session_number;

-- Check readings
SELECT s.session_number, r.reading_number, r.result_status 
FROM public.test_session_readings r
JOIN public.test_sessions s ON r.test_session_id = s.id
ORDER BY s.session_number, r.reading_number;

-- Check comments
SELECT s.session_number, c.comment, u.firstname 
FROM public.session_comments c
JOIN public.test_sessions s ON c.session_id = s.id
JOIN public.users u ON c.author_id = u.id;
```

### **2. Test API Endpoints (Swagger)**

1. Open http://localhost:8000/docs
2. Click "Authorize" button
3. Login as `tester@relu.com` / `utility@123`
4. Try these endpoints:
   - `GET /testing_requests/{id}` - Get test details
   - `GET /testing_requests/{id}/sessions` - List sessions
   - `GET /testing_requests/{id}/sessions/{sid}/readings` - Get readings
   - `POST /testing_requests/{id}/sessions/{sid}/comments` - Add comment

### **3. Check Auto-Transition**

```sql
-- Verify status changed after all sessions complete
SELECT id, title, status, submitted_at 
FROM public.testing_requests 
WHERE is_multi_session = true;

-- Should see status = 'test_submitted' and submitted_at is set
```

---

## 🐛 Troubleshooting

### **Error: "Connection refused" to database**

**Check if PostgreSQL is running:**
```bash
# Windows
sc query postgresql-x64-15

# Linux
systemctl status postgresql
```

**Test connection manually:**
```bash
psql -U relu_user -d Relu_Vendor2 -h localhost -p 5432
# Password: StrongPassword123!
```

### **Error: "ModuleNotFoundError"**

```bash
pip install -r requirements.txt
```

### **Error: "Login failed" in tests**

**Verify seed data loaded:**
```sql
SELECT email, firstname, lastname FROM public.users;
```

Should show:
- admin@relu.com
- operator@relu.com
- tester@relu.com
- approver@relu.com

If not, run: `python seed.py`

### **Error: "No organizations found"**

**Check organizations:**
```sql
SELECT id, name FROM public.organizations;
```

If empty, seed didn't run properly. Run `python seed.py` again.

### **Tests hang or timeout**

1. Verify backend is running: http://localhost:8000/docs
2. Check backend logs for errors
3. Restart backend: `Ctrl+C` then `uvicorn main:app --reload`

---

## 📊 Performance Check

After tests complete, check backend performance:

```bash
# Check logs
tail -f api.log

# Look for:
# - Auto-transition messages
# - Session completion logs
# - Comment creation logs
```

---

## 🎯 Next Steps After Tests Pass

1. **Frontend Integration**
   ```bash
   cd C:\Yesu\coginiwattcustomer
   # See MULTI_SESSION_UI_INTEGRATION.md
   ```

2. **End Date Elapsed Test**
   - Create test with 2-day duration
   - Complete only 2 of 5 sessions
   - Wait for scheduled job to run (hourly)
   - Verify incomplete sessions marked as "skipped"

3. **Load Testing**
   - Use tools like Apache JMeter
   - Test with 10+ concurrent users
   - Measure response times

---

## 📚 Documentation Files

- `IMPLEMENTATION_COMPLETE.md` - Full implementation guide
- `MULTI_SESSION_AUTO_TRANSITION.md` - Auto-transition details
- `MULTI_SESSION_UI_INTEGRATION.md` - Frontend integration
- `test_multi_session_complete.py` - Test script source

---

## 🚀 CI/CD Integration

To run in CI/CD pipeline:

```yaml
# .github/workflows/test.yml
test-multi-session:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: postgres:15
      env:
        POSTGRES_DB: Relu_Vendor2
        POSTGRES_USER: relu_user
        POSTGRES_PASSWORD: StrongPassword123!
  steps:
    - uses: actions/checkout@v2
    - name: Setup Python
      uses: actions/setup-python@v2
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Setup database
      run: |
        psql -f migrations/003_add_multi_session_testing.sql
        psql -f migrations/004_add_session_comments.sql
        python -c "from database import Base, engine; Base.metadata.create_all(bind=engine)"
        python seed.py
    - name: Start backend
      run: uvicorn main:app &
    - name: Run tests
      run: python test_multi_session_complete.py
```

---

**Ready to test!** 🎉

Run the commands above and watch your multi-session testing system come to life!
