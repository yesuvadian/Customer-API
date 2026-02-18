param(
    [ValidateSet("dev", "main")]
    [string]$Environment = "dev"
)

$Server = "erp@192.168.0.109"
$RemoteBasePath = "/apps/customer"
$RemoteApiPath = "/apps/customer/api"
$EnvFile = "/apps/customer/api/.env"
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

# Set environment-specific BASE_URL
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

ssh $Server @"
cd $RemoteBasePath &&
tar -xzf $ArchiveName -C api &&
rm $ArchiveName &&

# Update only selected .env values
sed -i 's|^DB_HOST=.*|DB_HOST=localhost|' $EnvFile
sed -i 's|^DB_USER=.*|DB_USER=relu_user|' $EnvFile
sed -i 's|^DB_PASSWORD=.*|DB_PASSWORD=StrongPassword123!|' $EnvFile
sed -i 's|^DB_PORT=.*|DB_PORT=5432|' $EnvFile
sed -i 's|^DB_NAME=.*|DB_NAME=Relu_Vendor2|' $EnvFile
sed -i 's|^APP_NAME=.*|APP_NAME=Relu-Vendor-API|' $EnvFile
sed -i 's|^BASE_URL=.*|BASE_URL=$BASE_URL|' $EnvFile &&

sudo systemctl restart customer-api
"@

Remove-Item $ArchiveName

Write-Host "====================================="
Write-Host "🚀 FastAPI Deployment Completed!"
Write-Host "====================================="
