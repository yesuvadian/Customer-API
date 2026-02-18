param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev"
)

$Server = "erp@192.168.0.109"
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

ssh $Server "
cd $RemoteBasePath && \
tar -xzf $ArchiveName -C api && \
rm $ArchiveName && \
sed -i 's|^DB_HOST=.*|DB_HOST=localhost|' $RemoteApiPath/.env && \
sed -i 's|^DB_USER=.*|DB_USER=relu_user|' $RemoteApiPath/.env && \
sed -i 's|^DB_PASSWORD=.*|DB_PASSWORD=StrongPassword123!|' $RemoteApiPath/.env && \
sed -i 's|^DB_PORT=.*|DB_PORT=5432|' $RemoteApiPath/.env && \
sed -i 's|^DB_NAME=.*|DB_NAME=Relu_Vendor2|' $RemoteApiPath/.env && \
sed -i 's|^APP_NAME=.*|APP_NAME=Relu-Vendor-API|' $RemoteApiPath/.env && \
sed -i 's|^BASE_URL=.*|BASE_URL=$BASE_URL|' $RemoteApiPath/.env && \
systemctl restart customer-api
"

Remove-Item $ArchiveName

Write-Host "====================================="
Write-Host "🚀 FastAPI Deployment Completed!"
Write-Host "====================================="
