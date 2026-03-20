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

# Helper: write script to temp file with LF line endings, scp to server, execute, cleanup
function Invoke-RemoteScript {
    param([string]$ScriptBody)

    $localTmp = [System.IO.Path]::GetTempFileName()
    # Write with explicit LF (no CRLF)
    [System.IO.File]::WriteAllText($localTmp, $ScriptBody.Replace("`r",""))

    scp $localTmp ${Server}:/tmp/db_setup.sh
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to upload script to server."
        Remove-Item $localTmp -ErrorAction SilentlyContinue
        return $false
    }

    ssh $Server "chmod +x /tmp/db_setup.sh && bash /tmp/db_setup.sh && rm -f /tmp/db_setup.sh"
    $result = $LASTEXITCODE

    Remove-Item $localTmp -ErrorAction SilentlyContinue
    return ($result -eq 0)
}

# ---------------------------------
# Step 1: Create Database
# ---------------------------------
if ($CreateDB) {
    Write-Host ""
    Write-Host "Creating database '$DbName'..."

    $script = "#!/bin/bash`nif sudo -u postgres psql -tc ""SELECT 1 FROM pg_database WHERE datname = '$DbName'"" | grep -q 1; then`n  echo 'Database already exists'`nelse`n  sudo -u postgres psql -c ""CREATE DATABASE \""$DbName\"" OWNER $DbUser;""`n  echo 'Database created successfully'`nfi`n"

    $ok = Invoke-RemoteScript -ScriptBody $script
    if (-not $ok) {
        Write-Host "Warning: DB creation may have failed. Check output above."
    }
}

# ---------------------------------
# Step 2: Create Tables
# ---------------------------------
if ($CreateTables) {
    Write-Host ""
    Write-Host "Creating tables..."

    $script = "#!/bin/bash`ncd $RemoteApiPath`nsource venv/bin/activate`npython -c ""from database import engine; from models import Base; Base.metadata.create_all(bind=engine); print('Tables created successfully')""`n"

    $ok = Invoke-RemoteScript -ScriptBody $script
    if (-not $ok) {
        Write-Host "Warning: Table creation may have failed. Check output above."
    }
}

# ---------------------------------
# Step 3: Run Seed
# ---------------------------------
if ($Seed) {
    Write-Host ""
    Write-Host "Running seed..."

    $script = "#!/bin/bash`ncd $RemoteApiPath`nsource venv/bin/activate`npython seed.py`n"

    $ok = Invoke-RemoteScript -ScriptBody $script
    if (-not $ok) {
        Write-Host "Warning: Seed may have failed. Check output above."
    }
}

Write-Host ""
Write-Host "====================================="
Write-Host "DB Setup Completed!"
Write-Host "====================================="
