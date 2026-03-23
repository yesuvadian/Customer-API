# ============================================================
# LOCAL DATABASE RESET AND SEED SCRIPT (PowerShell)
# ============================================================
# Complete database reset with fresh seed data for local development
# ============================================================

Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "DATABASE RESET AND SEED SCRIPT (Local)" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "WARNING: This will DELETE ALL DATA in the database!" -ForegroundColor Red
Write-Host ""

$confirm = Read-Host "Are you sure you want to continue? (yes/no)"
if ($confirm -ne "yes") {
    Write-Host "Operation cancelled." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Starting database reset..." -ForegroundColor Yellow
Write-Host ""

# Database connection parameters from .env
$envFile = Join-Path $PSScriptRoot ".." ".env"
if (Test-Path $envFile) {
    Write-Host "Reading database config from .env..." -ForegroundColor Cyan
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^DB_([^=]+)=(.+)$') {
            Set-Variable -Name "DB_$($matches[1])" -Value $matches[2] -Scope Script
        }
    }
} else {
    Write-Host ".env file not found, using default values" -ForegroundColor Yellow
}

# Default values if not found in .env
if (-not $DB_NAME) { $DB_NAME = "Relu_Vendor2" }
if (-not $DB_USER) { $DB_USER = "relu_user" }
if (-not $DB_HOST) { $DB_HOST = "localhost" }
if (-not $DB_PORT) { $DB_PORT = "5432" }

Write-Host "Database: $DB_NAME" -ForegroundColor Cyan
Write-Host "User: $DB_USER" -ForegroundColor Cyan
Write-Host "Host: $DB_HOST" -ForegroundColor Cyan
Write-Host "Port: $DB_PORT" -ForegroundColor Cyan
Write-Host ""

# Prompt for password
$securePassword = Read-Host "Enter PostgreSQL password for $DB_USER" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$DB_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

$env:PGPASSWORD = $DB_PASSWORD

# Find psql.exe
$psqlPath = $null
$psqlSearchPaths = @(
    "C:\Program Files\PostgreSQL\18\bin\psql.exe",
    "C:\Program Files\PostgreSQL\17\bin\psql.exe",
    "C:\Program Files\PostgreSQL\16\bin\psql.exe",
    "C:\Program Files\PostgreSQL\15\bin\psql.exe",
    "C:\Program Files\PostgreSQL\14\bin\psql.exe"
)

foreach ($path in $psqlSearchPaths) {
    if (Test-Path $path) {
        $psqlPath = $path
        break
    }
}

if (-not $psqlPath) {
    Write-Host "ERROR: Could not find psql.exe. Please install PostgreSQL or add it to PATH." -ForegroundColor Red
    exit 1
}

Write-Host "Found psql at: $psqlPath" -ForegroundColor Green
Write-Host ""

# Step 1: Drop all tables
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "Step 1: Dropping all existing tables..." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow

& $psqlPath -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f "000_drop_all_tables.sql"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to drop tables." -ForegroundColor Red
    Write-Host "Please check your database credentials and try again." -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] All tables dropped successfully" -ForegroundColor Green
Write-Host ""

# Step 2: Run all migrations
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "Step 2: Running all migrations..." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow

& $psqlPath -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f "run_all_migrations.sql"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to run migrations." -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] All migrations completed successfully" -ForegroundColor Green
Write-Host ""

# Step 3: Seed complete system
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "Step 3: Seeding complete system..." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow

& $psqlPath -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f "seed_complete_system.sql"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to seed database." -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] System seeded successfully" -ForegroundColor Green
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host "DATABASE RESET AND SEED COMPLETED!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Sample Login Credentials (password: admin123 for all):" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Organization Admin: orgadmin@kptcl.com"
Write-Host "  Department Head:    depthead@kptcl.com"
Write-Host "  Tester 1:           tester1@kptcl.com"
Write-Host "  Tester 2:           tester2@kptcl.com"
Write-Host "  Engineer:           engineer@kptcl.com"
Write-Host ""
Write-Host "Ready to test!" -ForegroundColor Green
Write-Host ""

# Clear password from environment
$env:PGPASSWORD = $null

Read-Host "Press Enter to exit"
