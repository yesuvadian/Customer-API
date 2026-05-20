-- Migration: add category_detail_id to repair_stage_templates
-- and convert stage_id primary key to surrogate UUID id.
--
-- Safe to run multiple times (all steps are idempotent).

BEGIN;

-- 1. Add surrogate id column (if not already present)
ALTER TABLE repair_stage_templates
    ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid();

-- 2. Populate id for existing rows that have no id yet
UPDATE repair_stage_templates SET id = gen_random_uuid() WHERE id IS NULL;

-- 3. Add category_detail_id column (nullable, FK to CategoryDetails — Integer PK)
ALTER TABLE repair_stage_templates
    ADD COLUMN IF NOT EXISTS category_detail_id INTEGER
    REFERENCES public."CategoryDetails"(id) ON DELETE SET NULL;

-- 4. Drop the old single-column primary key on stage_id
--    (wrapped in DO block so it's safe to run again if already dropped)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'repair_stage_templates'
          AND constraint_type = 'PRIMARY KEY'
          AND constraint_name = 'repair_stage_templates_pkey'
    ) THEN
        -- Check if the PK is currently on stage_id (old schema)
        IF EXISTS (
            SELECT 1 FROM information_schema.key_column_usage
            WHERE constraint_name = 'repair_stage_templates_pkey'
              AND column_name = 'stage_id'
        ) THEN
            ALTER TABLE repair_stage_templates DROP CONSTRAINT repair_stage_templates_pkey;
        END IF;
    END IF;
END $$;

-- 5. Set id as NOT NULL and add new primary key
ALTER TABLE repair_stage_templates ALTER COLUMN id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'repair_stage_templates'
          AND constraint_type = 'PRIMARY KEY'
    ) THEN
        ALTER TABLE repair_stage_templates ADD PRIMARY KEY (id);
    END IF;
END $$;

-- 6. Unique index: one generic template per stage (category_detail_id IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS uix_stage_template_generic
    ON repair_stage_templates (stage_id)
    WHERE category_detail_id IS NULL;

-- 7. Unique index: one category-specific template per (stage, category)
CREATE UNIQUE INDEX IF NOT EXISTS uix_stage_template_category
    ON repair_stage_templates (stage_id, category_detail_id)
    WHERE category_detail_id IS NOT NULL;

COMMIT;
