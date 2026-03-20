param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev",

    [switch]$CreateDB,
    [switch]$CreateTables,
    [switch]$Seed,
    [switch]$All
)

# ---------------------------------
# Server config
# ---------------------------------
if ($Environment -eq "main") {
    $Server = "erp@192.168.0.105"
    $DbName = "Relu_Vendor2"
}
else {
    $Server = "erp@192.168.0.109"
    $DbName = "Relu_Vendor2"
}

$RemoteApiPath = "/apps/customer/api"
$DbUser = "relu_user"

Write-Host "====================================="
Write-Host "Database Setup - $Environment"
Write-Host "Server: $Server"
Write-Host "Database: $DbName"
Write-Host "====================================="

# If -All, enable all steps
if ($All) {
    $CreateDB = $true
    $CreateTables = $true
    $Seed = $true
}

# Show what will run
if (-not $CreateDB -and -not $CreateTables -and -not $Seed) {
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\db_setup.ps1 -Environment dev -All              # Run all steps"
    Write-Host "  .\db_setup.ps1 -Environment dev -CreateDB         # Create database only"
    Write-Host "  .\db_setup.ps1 -Environment dev -CreateTables     # Create tables only"
    Write-Host "  .\db_setup.ps1 -Environment dev -Seed             # Run seed only"
    Write-Host "  .\db_setup.ps1 -Environment dev -CreateTables -Seed  # Tables + seed"
    Write-Host ""
    exit 0
}

# Production safety
if ($Environment -eq "main") {
    $confirm = Read-Host "Run DB setup on PRODUCTION? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Cancelled."
        exit 1
    }
}

# ---------------------------------
# Step 1: Create Database
# ---------------------------------
if ($CreateDB) {
    Write-Host ""
    Write-Host "Creating database '$DbName'..."

    $scriptContent = @"
#!/bin/bash
if sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DbName'" | grep -q 1; then
    echo "Database already exists"
else
    sudo -u postgres psql -c "CREATE DATABASE \"$DbName\" OWNER $DbUser;"
    echo "Database created successfully"
fi
"@
    $scriptContent = $scriptContent -replace "`r",""
    $scriptContent | ssh $Server "cat > /tmp/db_setup.sh && chmod +x /tmp/db_setup.sh && bash /tmp/db_setup.sh && rm /tmp/db_setup.sh"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: DB creation returned non-zero exit. Check output above."
    }
}

# ---------------------------------
# Step 2: Create Tables
# ---------------------------------
if ($CreateTables) {
    Write-Host ""
    Write-Host "Creating tables..."

    $scriptContent = @"
#!/bin/bash
cd $RemoteApiPath
source venv/bin/activate
python -c "from database import engine; from models import Base; Base.metadata.create_all(bind=engine); print('Tables created successfully')"
"@
    $scriptContent = $scriptContent -replace "`r",""
    $scriptContent | ssh $Server "cat > /tmp/db_setup.sh && chmod +x /tmp/db_setup.sh && bash /tmp/db_setup.sh && rm /tmp/db_setup.sh"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: Table creation returned non-zero exit. Check output above."
    }
}

# ---------------------------------
# Step 3: Run Seed
# ---------------------------------
if ($Seed) {
    Write-Host ""
    Write-Host "Running seed..."

    $scriptContent = @"
#!/bin/bash
cd $RemoteApiPath
source venv/bin/activate
python seed.py
"@
    $scriptContent = $scriptContent -replace "`r",""
    $scriptContent | ssh $Server "cat > /tmp/db_setup.sh && chmod +x /tmp/db_setup.sh && bash /tmp/db_setup.sh && rm /tmp/db_setup.sh"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: Seed returned non-zero exit. Check output above."
    }
}

Write-Host ""
Write-Host "====================================="
Write-Host "DB Setup Completed!"
Write-Host "====================================="
