param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev"
)



# ---------------------------------
# Select server based on branch
# ---------------------------------
if ($Environment -eq "main") {
    $Server = "erp@192.168.0.105"
    $ServiceName = "api-procurement"
}
else {
    $Server = "erp@192.168.0.109"
    $ServiceName = "customer-api"
}


$RemoteBasePath = "/apps/customer"
$RemoteApiPath = "/apps/customer/api"
$ArchiveName = "api_deploy.tar.gz"



Write-Host "====================================="
Write-Host "Starting FastAPI Deployment"
Write-Host "Environment: $Environment"
Write-Host "====================================="

# Optional production confirmation
if ($Environment -eq "main") {
    $confirm = Read-Host "Deploy to PRODUCTION? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Deployment cancelled."
        exit 1
    }
}

# -------------------------------
# 🔥 Branch Checkout (LOCAL)
# -------------------------------
Write-Host "Checking out branch: $Environment"

git checkout $Environment
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to checkout branch."
    exit 1
}

git pull origin $Environment
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to pull latest changes."
    exit 1
}

# Set BASE_URL
if ($Environment -eq "main") {
    $BASE_URL = "https://procurement.cogniwatt.com"
}
else {
    $BASE_URL = "https://devprocurement.cogniwatt.com"
}

Write-Host "Creating deployment archive..."

tar --exclude="venv" `
    --exclude="__pycache__" `
    --exclude=".git" `
    --exclude=".github" `
    --exclude=".vscode" `
    --exclude="*.xlsx" `
    --exclude="output_*.csv" `
    -czf $ArchiveName *

Write-Host "Uploading archive to server..."
scp $ArchiveName ${Server}:${RemoteBasePath}/

Write-Host "Extracting, updating .env and restarting service..."

$remoteCommand = @"
cd $RemoteBasePath &&
tar -xzf $ArchiveName -C api &&
rm $ArchiveName &&
sed -i 's|^DB_HOST=.*|DB_HOST=localhost|' $RemoteApiPath/.env &&
sed -i 's|^DB_USER=.*|DB_USER=relu_user|' $RemoteApiPath/.env &&
sed -i 's|^DB_PASSWORD=.*|DB_PASSWORD=StrongPassword123!|' $RemoteApiPath/.env &&
sed -i 's|^DB_PORT=.*|DB_PORT=5432|' $RemoteApiPath/.env &&
sed -i 's|^DB_NAME=.*|DB_NAME=Relu_Vendor2|' $RemoteApiPath/.env &&
sed -i 's|^APP_NAME=.*|APP_NAME=Relu-Vendor-API|' $RemoteApiPath/.env &&
sed -i 's|^BASE_URL=.*|BASE_URL=$BASE_URL|' $RemoteApiPath/.env &&
sudo /usr/bin/systemctl restart $ServiceName
"@

# Remove Windows CRLF before sending
$remoteCommand = $remoteCommand -replace "`r",""

ssh -tt $Server $remoteCommand


Remove-Item $ArchiveName

Write-Host "====================================="
Write-Host "🚀 FastAPI Deployment Completed!"
Write-Host "====================================="
