-- ============================================================
-- ENABLE POSTGRESQL EXTENSIONS
-- ============================================================
-- Description: Enable required PostgreSQL extensions
-- Date: 2026-03-22
-- ============================================================

\echo 'Enabling PostgreSQL extensions...'

-- Enable UUID generation functions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable UUID generation (PostgreSQL 13+)
-- Note: gen_random_uuid() is built-in, but uuid_generate_v4() needs uuid-ossp

\echo 'Extensions enabled successfully'
