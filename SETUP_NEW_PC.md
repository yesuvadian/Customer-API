# CogniWatt Customer API - Fresh Installation Guide

Simple 3-step setup guide for the CogniWatt Customer API on a new PC.

---

## Prerequisites

### Required Software

1. **Python 3.11+**
   - Download: https://www.python.org/downloads/
   - ✅ Check "Add Python to PATH" during installation
   - Verify: `python --version`

2. **PostgreSQL 16+**
   - Download: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
   - Note the `postgres` user password
   - Add to PATH: `C:\Program Files\PostgreSQL\16\bin`
   - Verify: `psql --version`

3. **Git**
   - Download: https://git-scm.com/downloads
   - Verify: `git --version`

---

## Quick Setup (3 Steps)

### Step 1: Clone and Setup Environment

```bash
# Clone repository
git clone https://github.com/yesuvadian/Customer-API.git
cd Customer-API
git checkout feature/testing-request-department-hierarchy

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Create database
psql -U postgres
CREATE DATABASE cogniwatt_db;
\q

# Configure environment
copy .env.example .env
notepad .env  # Update DB_PASSWORD and SECRET_KEY
```

**Generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

---

### Step 3: Create Tables and Seed Data

```bash
# Create all database tables
python create_tables.py

# Seed initial data
python seed.py
```

**That's it!** Your API is ready.

---

### Step 4: Start Server

```bash
python main.py
```

**Access the API:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Test Login

Open http://localhost:8000/docs and test with:

**Test accounts:**
- `admin@relu.com` / `Admin@123` (Super Admin)
- `engineer@kptcl.com` / `admin123` (Engineer - if using migrations)

Or use curl:
```bash
curl -X POST http://localhost:8000/token ^
  -H "Content-Type: application/x-www-form-urlencoded" ^
  -d "username=admin@relu.com&password=Admin@123"
```

---

## What Gets Created

**Users:**
- `admin@relu.com` / `Admin@123` (Super Admin)
- `viewer@relu.com` / `Viewer@123`
- `operator@relu.com` / `Operator@123`
- `tester@relu.com` / `Tester@123`

**Roles:**
- Admin, Viewer, Operator, Auditor, Vendor
- Originator, Tester, Approver (for testing system)

**Modules:**
- 45+ modules including Testing Requests, Organizations, Workflows, etc.

**Data:**
- Indian states and cities
- Product categories and test types
- Role templates for organizations
- Sample organization

---

## Optional: Seed KPTCL Departments

If you need KPTCL's 6-level department hierarchy:

```bash
python seed.py --kptcl <organization_id>
```

Or use the Excel-based seeder:
```bash
python seed_departments.py engineer@kptcl.com admin123 <org_id>
```

---

## Troubleshooting

**Python not found:** Reinstall with "Add to PATH" checked

**psql not found:** Add `C:\Program Files\PostgreSQL\16\bin` to PATH

**Port 8000 in use:**
```bash
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

**Database connection failed:** Check PostgreSQL is running and .env credentials

**Module not found:**
```bash
venv\Scripts\activate
pip install -r requirements.txt --upgrade
```

---

## Summary

```bash
# 1. Clone and setup
git clone https://github.com/yesuvadian/Customer-API.git
cd Customer-API
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup database and data
python create_tables.py
python seed.py

# 4. Start server
python main.py
```

**Done! API running at http://localhost:8000/docs** 🚀
