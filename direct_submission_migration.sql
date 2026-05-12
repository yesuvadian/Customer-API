-- ============================================================
-- Migration: Direct Submission Modules
-- Failure Registry (Stage 2) & TA&QC Inspection (Stage 10)
-- ============================================================

-- 1. Extend RequestCategory enum with new values
--    PostgreSQL requires ALTER TYPE; values are added if not already present.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'failure_registry'
          AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'requestcategory'
          )
    ) THEN
        ALTER TYPE requestcategory ADD VALUE 'failure_registry';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'taqc_inspection'
          AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'requestcategory'
          )
    ) THEN
        ALTER TYPE requestcategory ADD VALUE 'taqc_inspection';
    END IF;
END
$$;

-- 2. Add is_direct_submission column to testing_requests
ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS is_direct_submission BOOLEAN NOT NULL DEFAULT FALSE;

-- 3. Index for fast lookup by category + direct_submission flag
CREATE INDEX IF NOT EXISTS idx_tr_category_direct
    ON public.testing_requests (request_category, is_direct_submission);

-- 4. Index by originator for "my submissions" queries
CREATE INDEX IF NOT EXISTS idx_tr_originator_direct
    ON public.testing_requests (originator_id, is_direct_submission)
    WHERE is_direct_submission = TRUE;
