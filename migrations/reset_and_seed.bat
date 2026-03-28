@echo off
REM ============================================================
REM RESET AND SEED DATABASE SCRIPT (Windows)
REM ============================================================
REM Complete database reset with fresh seed data
REM ============================================================

echo ============================================================
echo DATABASE RESET AND SEED SCRIPT
echo ============================================================
echo.
echo WARNING: This will DELETE ALL DATA in the database!
echo.
set /p confirm="Are you sure you want to continue? (yes/no): "

if /i not "%confirm%"=="yes" (
    echo Operation cancelled.
    exit /b 0
)

echo.
echo Starting database reset...
echo.

REM Database connection parameters (update these if needed)
set DB_NAME=cogniwatt_db
set DB_USER=postgres
set DB_HOST=localhost
set DB_PORT=5432

REM Set PGPASSWORD environment variable if needed
REM set PGPASSWORD=your_password

REM Step 1: Drop all tables
echo Step 1: Dropping all existing tables...
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f 000_drop_all_tables.sql
if errorlevel 1 (
    echo Error dropping tables. Exiting.
    exit /b 1
)
echo [SUCCESS] All tables dropped successfully
echo.

REM Step 2: Run all migrations
echo Step 2: Running all migrations...
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f run_all_migrations.sql
if errorlevel 1 (
    echo Error running migrations. Exiting.
    exit /b 1
)
echo [SUCCESS] All migrations completed successfully
echo.

REM Step 3: Seed complete system
echo Step 3: Seeding complete system...
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f seed_complete_system.sql
if errorlevel 1 (
    echo Error seeding database. Exiting.
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
