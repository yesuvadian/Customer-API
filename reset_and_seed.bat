@echo off
setlocal enabledelayedexpansion

REM Reset Database and Run Seed Script (Windows)
REM This script drops all tables, recreates schema, runs migrations, and seeds data

echo ========================================
echo   Database Reset ^& Seed Script
echo ========================================
echo.

REM Database configuration (from .env)
set DB_NAME=Relu_Vendor2
set DB_USER=relu_user
set DB_HOST=localhost
set DB_PORT=5432
set PGPASSWORD=StrongPassword123!

REM Ask for confirmation
echo WARNING: This will DROP ALL TABLES in database '%DB_NAME%'
set /p confirmation="Are you sure you want to continue? (yes/no): "

if /i not "%confirmation%"=="yes" (
    echo Aborted
    exit /b 1
)

echo.
echo Step 1: Dropping all tables in public schema...

REM Drop all tables
psql -U %DB_USER% -d %DB_NAME% -h %DB_HOST% -p %DB_PORT% -c "BEGIN; DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO %DB_USER%; GRANT ALL ON SCHEMA public TO public; COMMIT;"

if %errorlevel% neq 0 (
    echo Failed to drop tables
    exit /b 1
)

echo Tables dropped successfully
echo.

echo Step 2: Running migrations...

REM Run migration 003
echo   - Running migration 003_add_multi_session_testing.sql
psql -U %DB_USER% -d %DB_NAME% -h %DB_HOST% -p %DB_PORT% -f migrations\003_add_multi_session_testing.sql

if %errorlevel% neq 0 (
    echo Migration 003 failed
    exit /b 1
)

echo   Migration 003 completed

REM Run migration 004
echo   - Running migration 004_add_session_comments.sql
psql -U %DB_USER% -d %DB_NAME% -h %DB_HOST% -p %DB_PORT% -f migrations\004_add_session_comments.sql

if %errorlevel% neq 0 (
    echo Migration 004 failed
    exit /b 1
)

echo   Migration 004 completed
echo.

echo Step 3: Creating tables via SQLAlchemy...

REM Create temporary Python script
echo from database import Base, engine > _temp_create_tables.py
echo from models import * >> _temp_create_tables.py
echo try: >> _temp_create_tables.py
echo     Base.metadata.create_all(bind=engine) >> _temp_create_tables.py
echo     print("Tables created successfully") >> _temp_create_tables.py
echo except Exception as e: >> _temp_create_tables.py
echo     print(f"Failed to create tables: {e}") >> _temp_create_tables.py
echo     exit(1) >> _temp_create_tables.py

python _temp_create_tables.py

if %errorlevel% neq 0 (
    echo Failed to create SQLAlchemy tables
    del _temp_create_tables.py
    exit /b 1
)

del _temp_create_tables.py
echo SQLAlchemy tables created
echo.

echo Step 4: Running seed script...

if not exist seed.py (
    echo seed.py not found
    exit /b 1
)

python seed.py

if %errorlevel% neq 0 (
    echo Failed to load seed data
    exit /b 1
)

echo Seed data loaded successfully
echo.

echo ========================================
echo   Database reset and seed completed!
echo ========================================
echo.
echo Next steps:
echo   1. Start the backend server: uvicorn main:app --reload
echo   2. Run the test script: python test_multi_session_complete.py
echo.

pause
