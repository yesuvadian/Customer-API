-- ============================================================
-- Migration: Add Multi-Session Testing Support
-- Description: Adds support for scheduled tests, multi-day testing, and multiple readings per session
-- Date: 2026-04-08
-- ============================================================

BEGIN;

-- ────────────────────────────────────────────────────────────
-- 1. Add new status to TestingRequestStatus enum
-- ────────────────────────────────────────────────────────────

-- Add 'scheduled' status to the enum
ALTER TYPE public.testingrequeststatus ADD VALUE IF NOT EXISTS 'scheduled';

-- ────────────────────────────────────────────────────────────
-- 2. Extend testing_requests table
-- ────────────────────────────────────────────────────────────

-- Add scheduled start date
ALTER TABLE public.testing_requests
ADD COLUMN IF NOT EXISTS scheduled_start_date TIMESTAMP WITH TIME ZONE;

-- Add multi-session support fields
ALTER TABLE public.testing_requests
ADD COLUMN IF NOT EXISTS is_multi_session BOOLEAN DEFAULT FALSE;

ALTER TABLE public.testing_requests
ADD COLUMN IF NOT EXISTS total_sessions_planned INTEGER;

ALTER TABLE public.testing_requests
ADD COLUMN IF NOT EXISTS session_interval_days INTEGER;

-- Add comments
COMMENT ON COLUMN public.testing_requests.scheduled_start_date IS 'Scheduled start date for future tests';
COMMENT ON COLUMN public.testing_requests.is_multi_session IS 'Indicates if this is a multi-day/multi-session test';
COMMENT ON COLUMN public.testing_requests.total_sessions_planned IS 'Total number of test sessions planned';
COMMENT ON COLUMN public.testing_requests.session_interval_days IS 'Number of days between each session';

-- ────────────────────────────────────────────────────────────
-- 3. Create test_sessions table
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.test_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    testing_request_id UUID NOT NULL REFERENCES public.testing_requests(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES public.organizations(id),

    session_number INTEGER NOT NULL,
    session_name VARCHAR(255),
    session_date TIMESTAMP WITH TIME ZONE NOT NULL,
    scheduled_date TIMESTAMP WITH TIME ZONE,

    status VARCHAR(20) DEFAULT 'scheduled',
    template_key VARCHAR(100),

    notes TEXT,
    weather_conditions VARCHAR(255),
    environmental_factors TEXT,

    conducted_by UUID REFERENCES public.users(id),
    witnessed_by VARCHAR(255),

    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_session_number_per_request UNIQUE(testing_request_id, session_number)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_test_sessions_request_id ON public.test_sessions(testing_request_id);
CREATE INDEX IF NOT EXISTS idx_test_sessions_org_id ON public.test_sessions(organization_id);
CREATE INDEX IF NOT EXISTS idx_test_sessions_status ON public.test_sessions(status);
CREATE INDEX IF NOT EXISTS idx_test_sessions_session_date ON public.test_sessions(session_date);

-- Add comments
COMMENT ON TABLE public.test_sessions IS 'Test sessions for multi-day/multi-session testing';
COMMENT ON COLUMN public.test_sessions.session_number IS 'Sequential session number (1, 2, 3, etc.)';
COMMENT ON COLUMN public.test_sessions.status IS 'Session status: scheduled, in_progress, completed, skipped';
COMMENT ON COLUMN public.test_sessions.weather_conditions IS 'Weather conditions during the test (for outdoor tests)';
COMMENT ON COLUMN public.test_sessions.environmental_factors IS 'Environmental conditions (temperature, humidity, etc.)';
COMMENT ON COLUMN public.test_sessions.witnessed_by IS 'Names of external witnesses';

-- ────────────────────────────────────────────────────────────
-- 4. Create test_session_readings table
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.test_session_readings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_session_id UUID NOT NULL REFERENCES public.test_sessions(id) ON DELETE CASCADE,

    reading_number INTEGER NOT NULL,
    reading_time TIMESTAMP WITH TIME ZONE NOT NULL,

    reading_data JSONB NOT NULL,

    equipment_serial VARCHAR(100),
    calibration_date TIMESTAMP WITH TIME ZONE,
    remarks TEXT,

    result_status VARCHAR(20),

    image_count INTEGER DEFAULT 0,

    recorded_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_reading_number_per_session UNIQUE(test_session_id, reading_number)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_test_session_readings_session_id ON public.test_session_readings(test_session_id);
CREATE INDEX IF NOT EXISTS idx_test_session_readings_time ON public.test_session_readings(reading_time);
CREATE INDEX IF NOT EXISTS idx_test_session_readings_status ON public.test_session_readings(result_status);

-- Add comments
COMMENT ON TABLE public.test_session_readings IS 'Multiple readings per test session';
COMMENT ON COLUMN public.test_session_readings.reading_number IS 'Sequential reading number within the session';
COMMENT ON COLUMN public.test_session_readings.reading_data IS 'Structured test measurement data (JSONB)';
COMMENT ON COLUMN public.test_session_readings.result_status IS 'Reading result: pass, fail, conditional, warning';

-- ────────────────────────────────────────────────────────────
-- 5. Create test_session_reading_images table
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.test_session_reading_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reading_id UUID NOT NULL REFERENCES public.test_session_readings(id) ON DELETE CASCADE,

    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(100),
    file_size INTEGER,
    file_data BYTEA NOT NULL,

    caption VARCHAR(500),
    sort_order INTEGER DEFAULT 0,

    created_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_session_reading_images_reading_id ON public.test_session_reading_images(reading_id);
CREATE INDEX IF NOT EXISTS idx_session_reading_images_sort ON public.test_session_reading_images(reading_id, sort_order);

-- Add comments
COMMENT ON TABLE public.test_session_reading_images IS 'Images/photos attached to specific readings';

-- ────────────────────────────────────────────────────────────
-- 6. Create trigger to update mts on test_sessions
-- ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_test_session_mts()
RETURNS TRIGGER AS $$
BEGIN
    NEW.mts = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_test_session_mts
    BEFORE UPDATE ON public.test_sessions
    FOR EACH ROW
    EXECUTE FUNCTION public.update_test_session_mts();

-- ────────────────────────────────────────────────────────────
-- 7. Create trigger to update mts on test_session_readings
-- ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_test_session_reading_mts()
RETURNS TRIGGER AS $$
BEGIN
    NEW.mts = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_test_session_reading_mts
    BEFORE UPDATE ON public.test_session_readings
    FOR EACH ROW
    EXECUTE FUNCTION public.update_test_session_reading_mts();

-- ────────────────────────────────────────────────────────────
-- 8. Grant permissions (adjust schema/user as needed)
-- ────────────────────────────────────────────────────────────

-- Grant permissions to application user (replace 'app_user' with your actual user)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON public.test_sessions TO app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON public.test_session_readings TO app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON public.test_session_reading_images TO app_user;

COMMIT;

-- ============================================================
-- Rollback instructions (if needed):
-- ============================================================
-- BEGIN;
-- DROP TABLE IF EXISTS public.test_session_reading_images CASCADE;
-- DROP TABLE IF EXISTS public.test_session_readings CASCADE;
-- DROP TABLE IF EXISTS public.test_sessions CASCADE;
-- ALTER TABLE public.testing_requests DROP COLUMN IF EXISTS scheduled_start_date;
-- ALTER TABLE public.testing_requests DROP COLUMN IF EXISTS is_multi_session;
-- ALTER TABLE public.testing_requests DROP COLUMN IF EXISTS total_sessions_planned;
-- ALTER TABLE public.testing_requests DROP COLUMN IF EXISTS session_interval_days;
-- COMMIT;
