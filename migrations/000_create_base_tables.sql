-- ============================================================
-- CREATE BASE TABLES
-- ============================================================
-- Description: Creates base tables required by the application
-- Date: 2026-03-22
-- ============================================================

\echo 'Creating base tables...'

-- ============================================================
-- 1. USERS TABLE (if not exists)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    firstname VARCHAR(100),
    lastname VARCHAR(100),
    phone_number VARCHAR(20) NOT NULL,
    isactive BOOLEAN DEFAULT TRUE,
    is_quick_registered BOOLEAN DEFAULT FALSE,
    email_confirmed BOOLEAN DEFAULT FALSE,
    phone_confirmed BOOLEAN DEFAULT FALSE,
    usertype VARCHAR(50),
    zoho_erp_id VARCHAR(255),
    employee_id VARCHAR(50),

    erp_sync_status VARCHAR(10) DEFAULT 'pending',
    erp_last_sync_at TIMESTAMP WITH TIME ZONE,
    erp_error_message TEXT,
    erp_external_id VARCHAR(255),

    created_by UUID,
    modified_by UUID,
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_isactive ON public.users(isactive);

-- ============================================================
-- 2. PLANS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planname VARCHAR(255) NOT NULL UNIQUE,
    plan_description TEXT,
    plan_limit INTEGER DEFAULT 0,
    isactive BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================
-- 3. MODULES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.modules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255),
    path VARCHAR(255),
    group_name VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================
-- 4. ROLES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.roles (
    id SERIAL PRIMARY KEY,
    rolename VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================
-- 5. USER_ROLES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES public.roles(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, role_id)
);

-- ============================================================
-- 6. CATEGORY MASTER (Equipment Types)
-- ============================================================
CREATE TABLE IF NOT EXISTS public."CategoryMaster" (
    id SERIAL PRIMARY KEY,
    categoryname VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================
-- 7. CATEGORY DETAILS (Test Types)
-- ============================================================
CREATE TABLE IF NOT EXISTS public."CategoryDetails" (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES public."CategoryMaster"(id),
    detailname VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================
-- 8. TESTING_REQUESTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.testing_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_number VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,

    -- Transformer details
    transformer_type VARCHAR(100),
    transformer_rating VARCHAR(100),
    manufacturer VARCHAR(255),
    serial_number VARCHAR(100),

    -- Equipment & Test type
    equipment_type_id INTEGER REFERENCES public."CategoryMaster"(id),
    test_type_id INTEGER REFERENCES public."CategoryDetails"(id),

    -- Legacy organizational hierarchy (string-based)
    zone VARCHAR(255),
    ce_circle VARCHAR(255),
    se_division VARCHAR(255),
    ee_subdivision VARCHAR(255),
    aee_section VARCHAR(255),
    ae_je VARCHAR(255),

    -- Workflow
    status VARCHAR(50) DEFAULT 'draft' NOT NULL,
    priority VARCHAR(20) DEFAULT 'normal',

    -- Assignments
    originator_id UUID NOT NULL REFERENCES public.users(id),
    assigned_tester_id UUID REFERENCES public.users(id),
    assigned_at TIMESTAMP WITH TIME ZONE,
    accepted_at TIMESTAMP WITH TIME ZONE,

    -- Dates
    requested_date TIMESTAMP WITH TIME ZONE,
    due_date TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Notes
    notes TEXT,
    rejection_reason TEXT,

    -- Audit
    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_testing_requests_status ON public.testing_requests(status);
CREATE INDEX IF NOT EXISTS idx_testing_requests_originator ON public.testing_requests(originator_id);
CREATE INDEX IF NOT EXISTS idx_testing_requests_tester ON public.testing_requests(assigned_tester_id);

-- ============================================================
-- 9. TESTER_LOCATIONS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.tester_locations (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Legacy string-based locations
    zone VARCHAR(255),
    ce_circle VARCHAR(255),
    se_division VARCHAR(255),
    ee_subdivision VARCHAR(255),

    is_active BOOLEAN DEFAULT TRUE,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tester_locations_user ON public.tester_locations(user_id);

-- ============================================================
-- 10. TEST_RESULTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.test_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    testing_request_id UUID NOT NULL REFERENCES public.testing_requests(id) ON DELETE CASCADE,

    test_date TIMESTAMP WITH TIME ZONE,
    test_location VARCHAR(255),
    test_equipment VARCHAR(255),

    test_data JSONB,
    attachments JSONB,

    notes TEXT,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_test_results_request ON public.test_results(testing_request_id);

-- ============================================================
-- 11. RECOMMENDATIONS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    testing_request_id UUID NOT NULL REFERENCES public.testing_requests(id) ON DELETE CASCADE,

    recommendation_type VARCHAR(50),
    recommendation_text TEXT,

    requires_procurement BOOLEAN DEFAULT FALSE,

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recommendations_request ON public.recommendations(testing_request_id);

-- ============================================================
-- 12. PROCUREMENT_REQUESTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS public.procurement_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    testing_request_id UUID REFERENCES public.testing_requests(id) ON DELETE SET NULL,

    request_number VARCHAR(50) UNIQUE,
    title VARCHAR(255) NOT NULL,
    description TEXT,

    status VARCHAR(50) DEFAULT 'draft',
    priority VARCHAR(20) DEFAULT 'normal',

    estimated_cost DECIMAL(15, 2),

    created_by UUID REFERENCES public.users(id),
    modified_by UUID REFERENCES public.users(id),
    cts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mts TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_procurement_requests_testing ON public.procurement_requests(testing_request_id);

\echo 'Base tables created successfully'
