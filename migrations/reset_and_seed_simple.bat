@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo DATABASE RESET AND SEED SCRIPT
echo ============================================================
echo.
echo WARNING: This will DELETE ALL DATA in the database!
echo.

set /p confirm="Are you sure you want to continue? (yes/no): "
if /i not "%confirm%"=="yes" (
    echo Operation cancelled.
    pause
    exit /b 0
)

echo.
echo Starting database reset...
echo.

REM Read database config from .env file in parent directory
cd ..
if exist .env (
    for /f "tokens=1,2 delims==" %%a in ('type .env ^| findstr /r "^DB_"') do (
        set %%a=%%b
    )
)
cd migrations

REM Default values if not found in .env
if not defined DB_NAME set DB_NAME=Relu_Vendor2
if not defined DB_USER set DB_USER=relu_user
if not defined DB_HOST set DB_HOST=localhost
if not defined DB_PORT set DB_PORT=5432

echo Using Database: %DB_NAME%
echo Using User: %DB_USER%
echo Using Host: %DB_HOST%
echo Using Port: %DB_PORT%
echo.

REM Prompt for password
set /p DB_PASSWORD="Enter PostgreSQL password for %DB_USER%: "
set PGPASSWORD=%DB_PASSWORD%

REM Find psql.exe
set PSQL_PATH=
for %%P in (
    "C:\Program Files\PostgreSQL\18\bin\psql.exe"
    "C:\Program Files\PostgreSQL\17\bin\psql.exe"
    "C:\Program Files\PostgreSQL\16\bin\psql.exe"
    "C:\Program Files\PostgreSQL\15\bin\psql.exe"
    "C:\Program Files\PostgreSQL\14\bin\psql.exe"
    "C:\Program Files\PostgreSQL\13\bin\psql.exe"
) do (
    if exist %%P (
        set PSQL_PATH=%%P
        goto :found_psql
    )
)

:found_psql
if not defined PSQL_PATH (
    echo ERROR: Could not find psql.exe. Please install PostgreSQL or add it to PATH.
    pause
    exit /b 1
)

echo Found psql at: %PSQL_PATH%
echo.

REM Step 1: Drop all tables
echo ============================================================
echo Step 1: Dropping all existing tables...
echo ============================================================
"%PSQL_PATH%" -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f 000_drop_all_tables.sql
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to drop tables.
    echo Please check your database credentials and try again.
    pause
    exit /b 1
)
echo [SUCCESS] All tables dropped successfully
echo.

REM Step 2: Run all migrations
echo ============================================================
echo Step 2: Running all migrations...
echo ============================================================
"%PSQL_PATH%" -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f run_all_migrations.sql
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to run migrations.
    pause
    exit /b 1
)
echo [SUCCESS] All migrations completed successfully
echo.

REM Step 3: Seed complete system
echo ============================================================
echo Step 3: Seeding complete system...
echo ============================================================
"%PSQL_PATH%" -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f seed_complete_system.sql
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to seed database.
    pause
    exit /b 1
)
echo [SUCCESS] System seeded successfully
echo.

echo ============================================================
echo DATABASE RESET AND SEED COMPLETED!
echo ============================================================
echo.
echo Sample Login Credentials (password: admin123 for all):
echo.
echo   Organization Admin: orgadmin@kptcl.com
echo   Department Head:    depthead@kptcl.com
echo   Tester 1:           tester1@kptcl.com
echo   Tester 2:           tester2@kptcl.com
echo   Engineer:           engineer@kptcl.com
echo.
echo Ready to test!
echo.
pause
