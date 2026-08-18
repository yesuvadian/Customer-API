-- 044_license_server_integration.sql
-- Adds License Server integration columns to the organizations table.
-- Run once per environment. Safe to re-run (uses IF NOT EXISTS / DO NOTHING guards).

-- license_server_org_id: the org's ID in the external CogniWatt License Server
-- upgrade_token:         per-org bearer token used to call the License Server API

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS license_server_org_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS upgrade_token          VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_organizations_license_server_org_id
    ON organizations (license_server_org_id)
    WHERE license_server_org_id IS NOT NULL;
