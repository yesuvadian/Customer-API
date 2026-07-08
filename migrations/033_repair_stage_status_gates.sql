ALTER TABLE repair_stage_definitions
    ADD COLUMN IF NOT EXISTS assign_statuses  JSONB NOT NULL DEFAULT '["pending","not_started"]',
    ADD COLUMN IF NOT EXISTS edit_statuses    JSONB NOT NULL DEFAULT '["assigned","in_progress"]',
    ADD COLUMN IF NOT EXISTS approve_statuses JSONB NOT NULL DEFAULT '["submitted"]';
