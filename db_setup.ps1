param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev",

    [switch]$CreateDB,
    [switch]$DropTables,
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
    $DropTables = $true
    $CreateTables = $true
    $Seed = $true
}

# Show what will run
if (-not $CreateDB -and -not $CreateTables -and -not $Seed) {
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\db_setup.ps1 -Environment dev -All              # Run all steps"
    Write-Host "  .\db_setup.ps1 -Environment dev -CreateDB         # Create database only"
    Write-Host "  .\db_setup.ps1 -Environment dev -DropTables       # Drop all tables"
    Write-Host "  .\db_setup.ps1 -Environment dev -CreateTables     # Create tables only"
    Write-Host "  .\db_setup.ps1 -Environment dev -Seed             # Run seed only"
    Write-Host "  .\db_setup.ps1 -Environment dev -DropTables -CreateTables -Seed  # Fresh setup"
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

# Helper: write script to temp file with LF, scp to server, execute with -t for sudo, cleanup
function Invoke-RemoteScript {
    param(
        [string]$ScriptBody,
        [switch]$NeedsSudo
    )

    $localTmp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($localTmp, $ScriptBody.Replace("`r",""))

    scp $localTmp ${Server}:/tmp/db_setup.sh
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to upload script to server."
        Remove-Item $localTmp -ErrorAction SilentlyContinue
        return $false
    }

    if ($NeedsSudo) {
        ssh -t $Server "chmod +x /tmp/db_setup.sh && bash /tmp/db_setup.sh && rm -f /tmp/db_setup.sh"
    } else {
        ssh $Server "chmod +x /tmp/db_setup.sh && bash /tmp/db_setup.sh && rm -f /tmp/db_setup.sh"
    }
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

    $ok = Invoke-RemoteScript -ScriptBody $script -NeedsSudo
    if (-not $ok) {
        Write-Host "Warning: DB creation may have failed. Check output above."
    }
}

# ---------------------------------
# Step 2: Drop Tables
# ---------------------------------
if ($DropTables) {
    Write-Host ""

    if ($Environment -eq "main") {
        $confirm = Read-Host "DROP ALL TABLES on PRODUCTION? This cannot be undone! (yes/no)"
        if ($confirm -ne "yes") {
            Write-Host "Cancelled."
            exit 1
        }
    }

    Write-Host "Dropping all tables..."

    $script = "#!/bin/bash`ncd $RemoteApiPath`nsource venv/bin/activate`npython -c ""`nfrom database import engine`nfrom models import Base`nBase.metadata.drop_all(bind=engine)`nprint('All tables dropped successfully.')`n""`n"

    $ok = Invoke-RemoteScript -ScriptBody $script
    if (-not $ok) {
        Write-Host "Warning: Drop tables may have failed. Check output above."
    }
}

# ---------------------------------
# Step 3: Create Tables
# ---------------------------------
if ($CreateTables) {
    Write-Host ""
    Write-Host "Creating / updating tables..."

    $script = @"
#!/bin/bash
cd $RemoteApiPath
source venv/bin/activate
python -c "
from database import engine
from models import Base
from sqlalchemy import inspect, text

# Create any new tables
Base.metadata.create_all(bind=engine)
print('Tables created/verified.')

# Auto-add missing columns to existing tables
inspector = inspect(engine)
with engine.connect() as conn:
    for table_name, table in Base.metadata.tables.items():
        schema = table.schema or 'public'
        try:
            existing = {c['name'] for c in inspector.get_columns(table_name, schema=schema)}
        except Exception:
            continue
        for col in table.columns:
            if col.name not in existing:
                col_type = col.type.compile(engine.dialect)
                default = ''
                if col.default is not None:
                    default = ' DEFAULT ' + str(col.default.arg)
                elif col.nullable:
                    default = ' DEFAULT NULL'
                stmt = f'ALTER TABLE {schema}.{table_name} ADD COLUMN {col.name} {col_type}{default}'
                print(f'  Adding column: {schema}.{table_name}.{col.name} ({col_type})')
                conn.execute(text(stmt))
    conn.commit()
print('Migration complete.')
"
"@

    $ok = Invoke-RemoteScript -ScriptBody $script
    if (-not $ok) {
        Write-Host "Warning: Table creation may have failed. Check output above."
    }
}

# ---------------------------------
# Step 4: Run Seed
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
