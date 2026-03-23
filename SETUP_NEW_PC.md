# CogniWatt Customer API - Fresh Installation Guide

Complete step-by-step guide to set up the CogniWatt Customer API on a new PC.

---

## Prerequisites

### 1. Install Required Software

#### Python 3.11 or higher
- Download: https://www.python.org/downloads/
- **IMPORTANT:** Check "Add Python to PATH" during installation
- Verify installation: `python --version`

#### PostgreSQL 16 or higher
- Download: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
- Note down during installation:
  - Password for `postgres` user
  - Port (default: 5432)
- Add to PATH: `C:\Program Files\PostgreSQL\16\bin`
- Verify: `psql --version`

#### Git
- Download: https://git-scm.com/downloads
- Use default settings
- Verify: `git --version`

#### Redis (Optional - for caching)
- Windows: https://github.com/microsoftarchive/redis/releases
- Or Docker: `docker run -d -p 6379:6379 redis`

---

## Installation Steps

### Step 1: Clone Repository

```bash
# Create project directory
mkdir C:\Projects
cd C:\Projects

# Clone the repository
git clone https://github.com/yesuvadian/Customer-API.git
cd Customer-API

# Switch to your working branch
git checkout feature/testing-request-department-hierarchy
```

---

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it (Windows CMD)
venv\Scripts\activate

# Or PowerShell
venv\Scripts\Activate.ps1

# Or Git Bash
source venv/Scripts/activate

# You should see (venv) in your prompt
```

---

### Step 3: Install Dependencies

```bash
# Upgrade pip
python -m pip install --upgrade pip

# Install all packages
pip install -r requirements.txt
```

**Installed packages include:**
- FastAPI, Uvicorn (Web framework)
- SQLAlchemy, psycopg2 (Database)
- PyJWT, passlib (Authentication)
- pandas, openpyxl (Excel processing)

---

### Step 4: Create Database

```bash
# Open PostgreSQL shell
psql -U postgres

# Create database
CREATE DATABASE cogniwatt_db;

# Optional: Create dedicated user
CREATE USER cogniwatt_user WITH PASSWORD 'YourStrongPassword123!';
GRANT ALL PRIVILEGES ON DATABASE cogniwatt_db TO cogniwatt_user;

# Exit
\q
```

---

### Step 5: Configure Environment

```bash
# Copy example file
copy .env.example .env

# Edit with your values
notepad .env
```

**Required settings:**

```env
# Database
DB_HOST=localhost
DB_USER=postgres
DB_PASSWORD=YOUR_POSTGRES_PASSWORD
DB_PORT=5432
DB_NAME=cogniwatt_db

# Security (generate new key)
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">

# Application
BASE_URL=http://localhost:8000
ENV=development
```

**Generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### Step 6: Initialize Database

#### Option A: Automated (Recommended)

```bash
cd migrations
reset_and_seed.bat
```

This will:
1. Drop existing tables
2. Create all tables
3. Seed sample data

#### Option B: Manual

```bash
# 1. Drop tables (if needed)
psql -U postgres -d cogniwatt_db -f migrations/000_drop_all_tables.sql

# 2. Create tables
psql -U postgres -d cogniwatt_db -f migrations/run_all_migrations.sql

# 3. Seed data
psql -U postgres -d cogniwatt_db -f migrations/seed_complete_system.sql

# 4. Additional seed (optional)
python seed.py
```

---

### Step 7: Verify Installation

```bash
# Connect to database
psql -U postgres -d cogniwatt_db

# Check tables exist
\dt

# Check sample data
SELECT email, firstname FROM users LIMIT 5;
SELECT * FROM organizations;

# Exit
\q
```

---

### Step 8: Start Server

```bash
# Ensure virtual environment is active (venv)
python main.py
```

**Expected output:**
```
[OK] ERP PostgreSQL connected successfully.
[OK] Vendor PostgreSQL connected successfully.
INFO: Uvicorn running on http://0.0.0.0:8000
```

**Access points:**
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

### Step 9: Test Installation

#### 1. Open Swagger UI
- Browser: http://localhost:8000/docs

#### 2. Test Login
Using curl:
```bash
curl -X POST http://localhost:8000/token ^
  -H "Content-Type: application/x-www-form-urlencoded" ^
  -d "username=engineer@kptcl.com&password=admin123"
```

Or use Swagger UI:
1. Navigate to `/token` endpoint
2. Click "Try it out"
3. Enter: `engineer@kptcl.com` / `admin123`
4. Click "Execute"
5. Copy `access_token`

#### 3. Test Protected Endpoint
```bash
curl -X GET http://localhost:8000/organizations ^
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Test Accounts

After seeding, these accounts are available:

| Email                  | Password  | Role          | Organization |
|------------------------|-----------|---------------|--------------|
| admin@relu.com         | Admin@123 | Super Admin   | System       |
| orgadmin@kptcl.com     | admin123  | Org Admin     | KPTCL        |
| engineer@kptcl.com     | admin123  | Engineer      | KPTCL        |
| tester1@kptcl.com      | admin123  | Tester        | KPTCL        |
| depthead@kptcl.com     | admin123  | Dept Head     | KPTCL        |

---

## Troubleshooting

### Python not found

**Solution:**
- Reinstall Python with "Add to PATH" checked
- Or add manually: `C:\Users\YourUser\AppData\Local\Programs\Python\Python311`

### psql not found

**Solution:**
Add PostgreSQL to PATH:
- `C:\Program Files\PostgreSQL\16\bin`
- Restart terminal

### Port 8000 in use

**Solution:**
```bash
# Find process
netstat -ano | findstr :8000

# Kill it
taskkill /PID <pid> /F

# Or use different port
python main.py --port 8080
```

### Database connection failed

**Solutions:**
1. Check PostgreSQL service is running
2. Verify .env credentials
3. Test: `psql -U postgres -d cogniwatt_db`

### Module not found errors

**Solution:**
```bash
# Ensure venv is active
venv\Scripts\activate

# Reinstall
pip install -r requirements.txt --upgrade
```

### Migration fails

**Solution:**
```bash
# Drop all tables first
psql -U postgres -d cogniwatt_db -f migrations/000_drop_all_tables.sql

# Retry migrations
psql -U postgres -d cogniwatt_db -f migrations/run_all_migrations.sql
```

---

## Additional Scripts

### Seed KPTCL Departments (Excel)
```bash
python seed_departments.py engineer@kptcl.com admin123 <org_id>
```

### Grant Admin Permissions
```bash
python grant_org_admin_permissions.py
```

### Update Workflow Permissions
```bash
python update_org_workflows_permission.py
```

---

## File Structure

```
Customer-API/
├── main.py                      # API entry point
├── seed.py                      # Data seeding
├── requirements.txt             # Dependencies
├── .env                         # Config (create from .env.example)
├── .env.example                 # Config template
│
├── routers/                     # API endpoints
├── services/                    # Business logic
├── models.py                    # Database models
├── schemas.py                   # API schemas
├── database.py                  # DB connection
├── auth_utils.py                # Authentication
│
└── migrations/                  # Database migrations
    ├── reset_and_seed.bat       # One-click setup
    ├── 000_drop_all_tables.sql
    ├── run_all_migrations.sql
    └── seed_complete_system.sql
```

---

## Quick Commands

```bash
# Activate environment
venv\Scripts\activate

# Start server
python main.py

# Reset database
cd migrations && reset_and_seed.bat && cd ..

# Run tests
pytest

# Check database
psql -U postgres -d cogniwatt_db

# Update dependencies
pip install -r requirements.txt --upgrade
```

---

## Success Checklist

- [ ] Python 3.11+ installed
- [ ] PostgreSQL 16+ installed and running
- [ ] Git installed
- [ ] Repository cloned
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] Database created
- [ ] .env configured
- [ ] Migrations run
- [ ] Sample data seeded
- [ ] Server starts without errors
- [ ] Swagger UI accessible
- [ ] Can login with test accounts

---

## Next Steps

1. Start Flutter app (frontend)
2. Test creating testing requests
3. Configure email for password reset
4. Create your organization
5. Deploy to production server

---

## Documentation

- **API Docs:** http://localhost:8000/docs
- **User Manual:** USER_MANUAL.md
- **Organization Setup:** ORGANIZATION_SETUP.md
- **Testing Guide:** TESTING_GUIDE.md

---

**Installation Complete! Your API is ready to use! 🚀**
