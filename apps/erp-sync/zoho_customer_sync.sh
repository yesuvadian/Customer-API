#!/bin/bash

API_BASE="https://api.procurement.cogniwatt.com"
LOG_FILE="/apps/erp-sync/logs/zoho_customer_sync.log"

USERNAME="admin@relu.com"
PASSWORD="Admin@123"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "===== Zoho Customer Sync started ====="

# -------------------------------------------------
# Step 1: Get Auth Token
# -------------------------------------------------
TOKEN_RESPONSE=$(curl -s -X POST "$API_BASE/token" \
  -F "username=$USERNAME" \
  -F "password=$PASSWORD")

ERP_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token')

if [[ -z "$ERP_TOKEN" || "$ERP_TOKEN" == "null" ]]; then
  log "❌ Failed to obtain access token"
  log "$TOKEN_RESPONSE"
  exit 1
fi

HEADERS=(
  -H "Authorization: Bearer $ERP_TOKEN"
  -H "Content-Type: application/json"
)

# -------------------------------------------------
# Step 2: Call Zoho Sync API
# -------------------------------------------------
log "🚀 Calling ZOHO CUSTOMER SYNC"

HTTP_CODE=$(curl -s -o /tmp/resp.$$ -w "%{http_code}" \
  -X POST "$API_BASE/zoho-register/sync-customers" \
  "${HEADERS[@]}")

log "📡 ZOHO CUSTOMER SYNC HTTP $HTTP_CODE"
cat /tmp/resp.$$ >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
rm -f /tmp/resp.$$

log "===== Zoho Customer Sync finished ====="
