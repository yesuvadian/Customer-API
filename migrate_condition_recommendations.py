"""
One-time migration: create condition_monitoring_recommendations and
condition_recommendation_activations tables.

Run once:
    python migrate_condition_recommendations.py
"""
import sys
from sqlalchemy import text
from database import engine


DDL = """
-- Recommendation configuration table
CREATE TABLE IF NOT EXISTS public.condition_monitoring_recommendations (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   UUID         REFERENCES public.organizations(id) ON DELETE CASCADE,
    equipment_type_id INTEGER      NOT NULL REFERENCES public."CategoryMaster"(id) ON DELETE CASCADE,
    score_from        NUMERIC(5,2) NOT NULL,
    score_to          NUMERIC(5,2) NOT NULL,
    test_type_id      INTEGER      NOT NULL REFERENCES public."CategoryDetails"(id) ON DELETE CASCADE,
    frequency         VARCHAR(20)  NOT NULL,
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    display_order     INTEGER      NOT NULL DEFAULT 0,
    created_by        UUID         REFERENCES public.users(id) ON DELETE SET NULL,
    cts               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    mts               TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_cmr_equipment_type
    ON public.condition_monitoring_recommendations (equipment_type_id);

-- Per-equipment activation tracking table
CREATE TABLE IF NOT EXISTS public.condition_recommendation_activations (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id UUID        NOT NULL REFERENCES public.condition_monitoring_recommendations(id) ON DELETE CASCADE,
    equipment_id      UUID        NOT NULL REFERENCES public.equipment(id) ON DELETE CASCADE,
    schedule_id       UUID        REFERENCES public.test_request_schedules(id) ON DELETE SET NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'recommended',
    activated_by      UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    activated_at      TIMESTAMPTZ,
    organization_id   UUID        REFERENCES public.organizations(id) ON DELETE CASCADE,
    cts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    mts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_rec_activation UNIQUE (recommendation_id, equipment_id)
);

CREATE INDEX IF NOT EXISTS ix_cra_equipment_id
    ON public.condition_recommendation_activations (equipment_id);
CREATE INDEX IF NOT EXISTS ix_cra_recommendation_id
    ON public.condition_recommendation_activations (recommendation_id);
"""

SEED_CONFIGS = """
-- Seed global recommendation configs for Power Transformer.
-- Uses subqueries so this is idempotent — skipped if equipment type or test type doesn't exist.

INSERT INTO public.condition_monitoring_recommendations
    (equipment_type_id, score_from, score_to, test_type_id, frequency, display_order)
SELECT
    cm.id,
    0, 20,
    cd.id,
    'monthly',
    1
FROM public."CategoryMaster" cm
JOIN public."CategoryDetails" cd
    ON cd.category_master_id = cm.id
   AND cd.name ILIKE '%insulation resistance%'
WHERE cm.name = 'Power Transformer'
  AND NOT EXISTS (
      SELECT 1 FROM public.condition_monitoring_recommendations r
      WHERE r.equipment_type_id = cm.id
        AND r.test_type_id      = cd.id
        AND r.score_from        = 0
        AND r.score_to          = 20
  )
ON CONFLICT DO NOTHING;

INSERT INTO public.condition_monitoring_recommendations
    (equipment_type_id, score_from, score_to, test_type_id, frequency, display_order)
SELECT
    cm.id,
    0, 20,
    cd.id,
    'monthly',
    2
FROM public."CategoryMaster" cm
JOIN public."CategoryDetails" cd
    ON cd.category_master_id = cm.id
   AND cd.name ILIKE '%contact resistance%'
WHERE cm.name = 'Power Transformer'
  AND NOT EXISTS (
      SELECT 1 FROM public.condition_monitoring_recommendations r
      WHERE r.equipment_type_id = cm.id
        AND r.test_type_id      = cd.id
        AND r.score_from        = 0
        AND r.score_to          = 20
  )
ON CONFLICT DO NOTHING;

INSERT INTO public.condition_monitoring_recommendations
    (equipment_type_id, score_from, score_to, test_type_id, frequency, display_order)
SELECT
    cm.id,
    21, 40,
    cd.id,
    'quarterly',
    1
FROM public."CategoryMaster" cm
JOIN public."CategoryDetails" cd
    ON cd.category_master_id = cm.id
   AND cd.name ILIKE '%oil%'
WHERE cm.name = 'Power Transformer'
  AND NOT EXISTS (
      SELECT 1 FROM public.condition_monitoring_recommendations r
      WHERE r.equipment_type_id = cm.id
        AND r.test_type_id      = cd.id
        AND r.score_from        = 21
        AND r.score_to          = 40
  )
ON CONFLICT DO NOTHING;

INSERT INTO public.condition_monitoring_recommendations
    (equipment_type_id, score_from, score_to, test_type_id, frequency, display_order)
SELECT
    cm.id,
    41, 60,
    cd.id,
    'semi_annual',
    1
FROM public."CategoryMaster" cm
JOIN public."CategoryDetails" cd
    ON cd.category_master_id = cm.id
   AND cd.name ILIKE '%visual inspection%'
WHERE cm.name = 'Power Transformer'
  AND NOT EXISTS (
      SELECT 1 FROM public.condition_monitoring_recommendations r
      WHERE r.equipment_type_id = cm.id
        AND r.test_type_id      = cd.id
        AND r.score_from        = 41
        AND r.score_to          = 60
  )
ON CONFLICT DO NOTHING;
"""


def run():
    print("Creating condition monitoring tables...")
    with engine.begin() as conn:
        conn.execute(text(DDL))
    print("[OK] Tables created")

    print("Seeding default recommendation configs...")
    with engine.begin() as conn:
        conn.execute(text(SEED_CONFIGS))
    print("[OK] Seed complete (skipped any duplicates)")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
