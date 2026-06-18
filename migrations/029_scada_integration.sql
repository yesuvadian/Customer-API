-- ============================================================
-- 029: SCADA Integration Tables
-- ============================================================

-- -----------------------------------------------------------
-- 1. scada_tag_map — maps device tags to equipment records
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.scada_tag_map (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID        NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    scada_tag        VARCHAR(120) NOT NULL,
    equipment_id     UUID        NOT NULL REFERENCES public.equipment(id) ON DELETE CASCADE,
    parameter_name   VARCHAR(120),
    unit             VARCHAR(30),
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by       UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    cts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, scada_tag)
);

-- -----------------------------------------------------------
-- 2. scada_unresolved — staging for unmapped tags
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.scada_unresolved (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID        NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    scada_tag        VARCHAR(120) NOT NULL,
    sample_payload   JSONB,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved         BOOLEAN     NOT NULL DEFAULT FALSE,
    resolved_at      TIMESTAMPTZ,
    resolved_by      UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    UNIQUE (organization_id, scada_tag)
);

-- -----------------------------------------------------------
-- 3. scada_alert_rules — threshold configuration per tag
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.scada_alert_rules (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   UUID        NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    equipment_id      UUID        REFERENCES public.equipment(id) ON DELETE CASCADE,
    equipment_type_id INTEGER     REFERENCES public."CategoryMaster"(id) ON DELETE CASCADE,
    scada_tag         VARCHAR(120) NOT NULL,
    parameter_name    VARCHAR(120),
    unit              VARCHAR(30),
    warning_min       NUMERIC(18,6),
    warning_max       NUMERIC(18,6),
    alarm_min         NUMERIC(18,6),
    alarm_max         NUMERIC(18,6),
    critical_min      NUMERIC(18,6),
    critical_max      NUMERIC(18,6),
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by        UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    cts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    mts               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scada_alert_rules_equipment_tag
    ON public.scada_alert_rules (equipment_id, scada_tag) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_scada_alert_rules_type_tag
    ON public.scada_alert_rules (equipment_type_id, scada_tag) WHERE is_active = TRUE AND equipment_id IS NULL;

-- -----------------------------------------------------------
-- 4. scada_readings — time-series table (partitioned by month)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.scada_readings (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID        NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    equipment_id     UUID        REFERENCES public.equipment(id) ON DELETE SET NULL,
    scada_tag        VARCHAR(120) NOT NULL,
    parameter_name   VARCHAR(120),
    value            NUMERIC(18,6) NOT NULL,
    unit             VARCHAR(30),
    alarm_condition  VARCHAR(20)  NOT NULL DEFAULT 'NORMAL',
    recorded_at      TIMESTAMPTZ  NOT NULL,
    received_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scada_readings_equipment_tag_ts
    ON public.scada_readings (equipment_id, scada_tag, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_scada_readings_org_ts
    ON public.scada_readings (organization_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_scada_readings_alarm
    ON public.scada_readings (equipment_id, alarm_condition, recorded_at DESC)
    WHERE alarm_condition != 'NORMAL';

-- -----------------------------------------------------------
-- 5. scada_parameter_analytics — scheduled analytics output
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.scada_parameter_analytics (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id      UUID        NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    equipment_id         UUID        NOT NULL REFERENCES public.equipment(id) ON DELETE CASCADE,
    scada_tag            VARCHAR(120) NOT NULL,
    parameter_name       VARCHAR(120),
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    history_count        INTEGER,
    trend                VARCHAR(30),
    trend_slope          NUMERIC(18,8),
    trend_r_squared      NUMERIC(6,4),
    annual_change        NUMERIC(18,6),
    pct_change_annual    NUMERIC(8,2),
    is_anomaly           BOOLEAN     DEFAULT FALSE,
    anomaly_type         VARCHAR(50),
    anomaly_detail       TEXT,
    breach_threshold     NUMERIC(18,6),
    breach_predicted_at  TIMESTAMPTZ,
    days_to_breach       NUMERIC(8,2),
    UNIQUE (equipment_id, scada_tag)
);

-- -----------------------------------------------------------
-- 6. Extend testing_requests for SCADA-triggered tickets
-- -----------------------------------------------------------
ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS scada_reading_id UUID REFERENCES public.scada_readings(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS trigger_source   VARCHAR(20) DEFAULT 'manual';
-- trigger_source: 'manual' | 'scada' | 'schedule' | 'score'

-- -----------------------------------------------------------
-- 7. Extend condition_monitoring_recommendations for SCADA
-- -----------------------------------------------------------
ALTER TABLE public.condition_monitoring_recommendations
    ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) DEFAULT 'score';
-- trigger_source: 'score' (existing) | 'scada' (new)

ALTER TABLE public.condition_monitoring_recommendations
    ADD COLUMN IF NOT EXISTS scada_tag_pattern VARCHAR(120);
-- e.g. '%OIL_TEMP%' — matched against scada_tag to pick recommended test
