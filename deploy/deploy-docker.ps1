param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev"
)

# ---------------------------------
# Docker Compose deployment to the real VM (Linux) — a separate path from
# deploy.ps1, which does a bare-metal tar+scp+systemctl deploy under
# /apps/customer. This script ships both repos to the VM instead and runs
# `docker compose up --build -d` there. It does NOT touch deploy.ps1,
# docker-compose.yml, or the bare-metal /apps/customer path — this runs
# side by side with it, under /apps/customer-docker.
#
# Remote directory layout mirrors the local sibling layout that
# docker-compose.yml's own relative build contexts already assume:
#   /apps/customer-docker/CustomerAPI/Customer-API   (this repo)
#   /apps/customer-docker/coginiwattcustomer         (UI repo, sibling)
#
# DB_USER/DB_PASSWORD/DB_NAME/APP_NAME are identical between dev and prod
# per deploy.ps1, so whatever is in the shipped .env for those is already
# correct either way — only DB_HOST/DB_PORT/BASE_URL differ, and those are
# already forced by docker-compose.yml's environment: block (via
# deploy/dev.env or deploy/prod.env), so no sed patching is needed here.
#
# A second --env-file (dev.remote.env / prod.remote.env) is layered on top
# to remap the API's host port and the UI's API_BASE_URL — dev.env/prod.env
# alone assume local Windows testing, where the browser and the published
# API port share the same machine. On the actual VM that's not true (the
# end user's browser is elsewhere, and port 8000 may already be taken by
# the existing bare-metal service) — see dev.remote.env's own comments.
#
# Assumes Docker + Docker Compose are already installed on the target VM.
# ---------------------------------

if ($Environment -eq "main") {
    $Server = "erp@192.168.0.105"
    $ServerDR = "erp@192.168.0.100"
    $EnvFile = "prod.env"
    $RemoteEnvFile = "prod.remote.env"
} else {
    $Server = "erp@192.168.0.109"
    $ServerDR = $null
    $EnvFile = "dev.env"
    $RemoteEnvFile = "dev.remote.env"
}

$RemoteBase = "/apps/customer-docker"
$RemoteApiPath = "$RemoteBase/CustomerAPI/Customer-API"
$RemoteUiPath  = "$RemoteBase/coginiwattcustomer"

$ApiRepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$UiRepoRoot  = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\coginiwattcustomer")

$ApiArchive = "api_docker_deploy.tar.gz"
$UiArchive  = "ui_docker_deploy.tar.gz"

Write-Host "====================================="
Write-Host "Docker Compose Deployment"
Write-Host "Environment   : $Environment"
Write-Host "Primary Server: $Server"
if ($ServerDR) { Write-Host "DR Server     : $ServerDR" }
Write-Host "Env files     : deploy/$EnvFile + deploy/$RemoteEnvFile"
Write-Host "====================================="

if ($Environment -eq "main") {
    $confirm = Read-Host "Deploy containers to PRODUCTION (Primary + DR)? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Deployment cancelled."
        exit 1
    }
}

# ---------------------------------
# Checkout branch locally, both repos — matches deploy.ps1's own pattern,
# so -Environment actually controls which branch's code ships, not just
# which server/DB it ships to. Safe to switch the API repo's own branch
# mid-script: PowerShell has already parsed this whole file into memory,
# and dev/main both carry this deploy/ folder (see the commit that added
# it there), so the script keeps finding itself and its own config files
# after the checkout.
# ---------------------------------
Write-Host "Checking out branch: $Environment"
Push-Location $ApiRepoRoot
git checkout $Environment
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
git pull origin $Environment
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Push-Location $UiRepoRoot
git checkout $Environment
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
git pull origin $Environment
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

# ---------------------------------
# Archive both repos — written directly to a system temp staging dir, NOT
# to $PSScriptRoot (deploy/), since deploy/ lives INSIDE $ApiRepoRoot.
# Creating the archive there and moving it afterward meant a leftover
# archive from any prior interrupted run (Ctrl-C, closed terminal, etc.)
# sat inside the very tree being archived — tar's `*` glob would pick it
# up and refuse ("Can't add archive to itself"), and the archive step had
# no exit-code check, so that failure was silently swallowed and a
# broken/empty archive got shipped to production instead of stopping.
# ---------------------------------
$StagingDir = Join-Path $env:TEMP "customer-docker-deploy"
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
$ApiArchivePath = Join-Path $StagingDir $ApiArchive
$UiArchivePath  = Join-Path $StagingDir $UiArchive
Remove-Item -Force $ApiArchivePath, $UiArchivePath -ErrorAction SilentlyContinue

Write-Host "Archiving API repo..."
Push-Location $ApiRepoRoot
tar --exclude="venv" --exclude="__pycache__" --exclude=".git" --exclude=".github" `
    --exclude=".vscode" --exclude="uploads" -czf $ApiArchivePath *
if ($LASTEXITCODE -ne 0) { Write-Host "Archiving API repo failed."; Pop-Location; exit 1 }
Pop-Location

Write-Host "Archiving UI repo..."
Push-Location $UiRepoRoot
tar --exclude=".git" --exclude="build" --exclude=".dart_tool" --exclude=".claude" `
    --exclude=".codex_work" --exclude="artifacts" --exclude="outputs" --exclude="test_driver" `
    -czf $UiArchivePath *
if ($LASTEXITCODE -ne 0) { Write-Host "Archiving UI repo failed."; Pop-Location; exit 1 }
Pop-Location

function Deploy-ToServer {
    param($TargetServer)

    Write-Host ""
    Write-Host "====================================="
    Write-Host "Deploying to $TargetServer"
    Write-Host "====================================="

    Write-Host "Ensuring remote directories exist..."
    ssh $TargetServer "mkdir -p $RemoteApiPath $RemoteUiPath"

    Write-Host "Uploading API archive..."
    scp $ApiArchivePath "${TargetServer}:${RemoteApiPath}/"

    Write-Host "Uploading UI archive..."
    scp $UiArchivePath "${TargetServer}:${RemoteUiPath}/"

    $remoteCommand = @"
cd $RemoteApiPath && tar -xzf $ApiArchive && rm -f $ApiArchive &&
cd $RemoteUiPath && tar -xzf $UiArchive && rm -f $UiArchive &&
cd $RemoteApiPath/deploy && docker compose -f docker-compose.yml -f docker-compose.remote.yml --env-file $EnvFile --env-file $RemoteEnvFile up --build -d
"@
    $remoteCommand = $remoteCommand -replace "`r", ""

    ssh -tt $TargetServer $remoteCommand

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Deployment to $TargetServer successful."
        return $true
    } else {
        Write-Host "Deployment to $TargetServer failed."
        return $false
    }
}

$primaryOk = Deploy-ToServer $Server
if (-not $primaryOk) {
    Remove-Item -Force $ApiArchivePath, $UiArchivePath -ErrorAction SilentlyContinue
    exit 1
}

if ($ServerDR) {
    $drOk = Deploy-ToServer $ServerDR
    if (-not $drOk) {
        Write-Host "Primary is still running; DR deployment failed."
    }
}

Remove-Item -Force $ApiArchivePath, $UiArchivePath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "====================================="
Write-Host "Docker Compose Deployment Completed"
Write-Host "Primary: $Server"
if ($ServerDR) {
    Write-Host "DR: $ServerDR"
}
Write-Host "====================================="
