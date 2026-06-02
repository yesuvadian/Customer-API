param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev"
)

# ---------------------------------
# Select server based on branch
# ---------------------------------
if ($Environment -eq "main") {
    $Server = "erp@192.168.0.105"
    $ServerDR = "erp@192.168.0.100"
    $BASE_URL = "https://api.procurement.cogniwatt.com"
}
else {
    $Server = "erp@192.168.0.103"
    $ServerDR = $null
    $BASE_URL = "https://devsupplier.cogniwatt.com"
}

$RemoteBasePath = "/apps/customer"
$RemoteApiPath  = "/apps/customer/api"
$ArchiveName    = "api_deploy.tar.gz"

Write-Host "====================================="
Write-Host "Starting Procurement API Deployment"
Write-Host "Environment: $Environment"
Write-Host "Primary Server: $Server"
if ($ServerDR) {
    Write-Host "DR Server: $ServerDR"
}
Write-Host "====================================="

# Optional production confirmation
if ($Environment -eq "main") {
    $confirm = Read-Host "Deploy to PRODUCTION (Primary + DR)? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Deployment cancelled."
        exit 1
    }
}

# ---------------------------------
# Checkout branch locally
# ---------------------------------
Write-Host "Checking out branch: $Environment"
git checkout $Environment
if ($LASTEXITCODE -ne 0) { exit 1 }
git pull origin $Environment
if ($LASTEXITCODE -ne 0) { exit 1 }

# ---------------------------------
# Create deployment archive
# ---------------------------------
Write-Host "Creating deployment archive..."
tar --exclude="venv" `
    --exclude="__pycache__" `
    --exclude=".git" `
    --exclude=".github" `
    --exclude=".vscode" `
    -czf $ArchiveName *

# ---------------------------------
# Remote command template
# ---------------------------------
function Get-RemoteCommand {
    param($RemotePath, $ApiPath, $BaseUrl)
    
    return @"
cd $RemotePath &&
tar -xzf $ArchiveName -C api &&
rm -f $ArchiveName &&
sed -i 's|^DB_HOST=.*|DB_HOST=localhost|' $ApiPath/.env &&
sed -i 's|^DB_USER=.*|DB_USER=relu_user|' $ApiPath/.env &&
sed -i 's|^DB_PASSWORD=.*|DB_PASSWORD=StrongPassword123!|' $ApiPath/.env &&
sed -i 's|^DB_PORT=.*|DB_PORT=5432|' $ApiPath/.env &&
sed -i 's|^DB_NAME=.*|DB_NAME=Relu_Vendor2|' $ApiPath/.env &&
sed -i 's|^APP_NAME=.*|APP_NAME=Relu-Vendor-API|' $ApiPath/.env &&
sed -i 's|^BASE_URL=.*|BASE_URL=$BaseUrl|' $ApiPath/.env &&
sudo /usr/bin/systemctl restart api-procurement
"@
}

# ---------------------------------
# Deploy to PRIMARY
# ---------------------------------
Write-Host ""
Write-Host "====================================="
Write-Host "Deploying to PRIMARY: $Server"
Write-Host "====================================="

Write-Host "Uploading archive to PRIMARY..."
scp $ArchiveName ${Server}:${RemoteBasePath}/

Write-Host "Deploying on PRIMARY..."
$primaryCommand = Get-RemoteCommand -RemotePath $RemoteBasePath -ApiPath $RemoteApiPath -BaseUrl $BASE_URL
$primaryCommand = $primaryCommand -replace "`r",""
ssh -tt $Server $primaryCommand

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ PRIMARY deployment successful!"
} else {
    Write-Host "❌ PRIMARY deployment failed!"
    Remove-Item $ArchiveName
    exit 1
}

# ---------------------------------
# Deploy to DR (production only)
# ---------------------------------
if ($ServerDR) {
    Write-Host ""
    Write-Host "====================================="
    Write-Host "Deploying to DR: $ServerDR"
    Write-Host "====================================="

    Write-Host "Uploading archive to DR..."
    scp $ArchiveName ${ServerDR}:${RemoteBasePath}/

    Write-Host "Deploying on DR..."
    $drCommand = Get-RemoteCommand -RemotePath $RemoteBasePath -ApiPath $RemoteApiPath -BaseUrl $BASE_URL
    $drCommand = $drCommand -replace "`r",""
    ssh -tt $ServerDR $drCommand

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ DR deployment successful!"
    } else {
        Write-Host "❌ DR deployment failed! Primary is still running."
    }
}

# ---------------------------------
# Cleanup
# ---------------------------------
Remove-Item $ArchiveName

Write-Host ""
Write-Host "====================================="
Write-Host "🚀 Procurement API Deployment Completed!"
Write-Host "Primary: $Server ✅"
if ($ServerDR) {
    Write-Host "DR: $ServerDR ✅"
}
Write-Host "====================================="