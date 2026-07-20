"""
Dept-Level Billing — Phase 1 DB Migration
==========================================
Creates new tables and adds new columns needed for department-level billing.
Safe to run multiple times (all statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).

Execution order:
  1. Create billing_scopes (no deps)
  2. Create org_plan_pricing (refs billing_scopes, organizations, plans)
  3. Create billing_audit_logs (refs organizations, users, billing_orders)
  4. ALTER organizations  — add billing_* columns
  5. ALTER org_departments — add subscription_end_date, is_billing_unit
  6. ALTER users           — add billing_unit_id
  7. ALTER billing_orders  — add dept billing columns
  8. ALTER notification_log — add idempotency_key
  9. Seed SystemConfig rows
 10. Backfill organizations.billing_scope_id = org_level
"""

import uuid
from sqlalchemy import text


# ── helpers ──────────────────────────────────────────────────────────────────

def _exec(session, sql: str, label: str):
    """Execute one statement, skip gracefully on already-exists / does-not-exist."""
    try:
        session.execute(text(sql.strip()))
        session.commit()
        print(f"  [OK] {label}")
    except Exception as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "does not exist" in msg or "duplicate" in msg:
            session.rollback()
            print(f"  [SKIP] {label} (already applied)")
        else:
            session.rollback()
            print(f"  [ERROR] {label}: {exc}")
            raise


# ── Step 1: billing_scopes ────────────────────────────────────────────────────

def _create_billing_scopes(session):
    _exec(session, """
        CREATE TABLE IF NOT EXISTS public.billing_scopes (
            id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(50)  NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL
        )
    """, "CREATE TABLE billing_scopes")


# ── Step 2: org_plan_pricing ──────────────────────────────────────────────────

def _create_org_plan_pricing(session):
    _exec(session, """
        CREATE TABLE IF NOT EXISTS public.org_plan_pricing (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id           UUID NOT NULL REFERENCES public.organizations(id)   ON DELETE CASCADE,
            plan_id          UUID NOT NULL REFERENCES public.plans(id)            ON DELETE CASCADE,
            billing_scope_id UUID NOT NULL REFERENCES public.billing_scopes(id)  ON DELETE RESTRICT,
            price_paise      INTEGER NOT NULL,
            duration_days    INTEGER,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_org_plan_pricing UNIQUE (org_id, plan_id, billing_scope_id)
        )
    """, "CREATE TABLE org_plan_pricing")


# ── Step 3: billing_audit_logs ────────────────────────────────────────────────

def _create_billing_audit_logs(session):
    _exec(session, """
        CREATE TABLE IF NOT EXISTS public.billing_audit_logs (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                 UUID NOT NULL REFERENCES public.organizations(id)  ON DELETE CASCADE,
            actor_user_id          UUID NOT NULL REFERENCES public.users(id),
            actor_name             VARCHAR(255) NOT NULL,
            actor_usertype         VARCHAR(50)  NOT NULL,
            action                 VARCHAR(100) NOT NULL,
            entity_type            VARCHAR(100),
            entity_id              UUID,
            before_json            JSONB,
            after_json             JSONB,
            billing_order_id       UUID REFERENCES public.billing_orders(id) ON DELETE SET NULL,
            billing_units_affected INTEGER,
            notes                  VARCHAR(1000),
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """, "CREATE TABLE billing_audit_logs")

    _exec(session, """
        CREATE INDEX IF NOT EXISTS ix_billing_audit_logs_org_id
            ON public.billing_audit_logs (org_id)
    """, "INDEX billing_audit_logs(org_id)")

    _exec(session, """
        CREATE INDEX IF NOT EXISTS ix_billing_audit_logs_action
            ON public.billing_audit_logs (action)
    """, "INDEX billing_audit_logs(action)")


# ── Step 4: ALTER organizations ───────────────────────────────────────────────

def _alter_organizations(session):
    cols = [
        ("billing_scope_id",                "UUID REFERENCES public.billing_scopes(id) ON DELETE RESTRICT"),
        ("billing_hierarchy_level",         "INTEGER"),
        ("dept_level_labels",               "JSONB"),
        ("billing_reminder_days",           "JSONB"),
        ("billing_unit_recompute_pending",  "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("billing_unit_recompute_status",   "VARCHAR(50)"),
        ("billing_unit_recompute_started",  "TIMESTAMPTZ"),
        ("billing_unit_recompute_error",    "TEXT"),
        ("billing_unit_recompute_retries",  "INTEGER NOT NULL DEFAULT 0"),
        ("subscription_status",             "VARCHAR(20)"),
    ]
    for col_name, col_def in cols:
        _exec(session,
            f"ALTER TABLE public.organizations ADD COLUMN IF NOT EXISTS {col_name} {col_def}",
            f"organizations.{col_name}")


# ── Step 5: ALTER org_departments ─────────────────────────────────────────────

def _alter_org_departments(session):
    cols = [
        ("is_billing_unit",      "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("subscription_end_date", "TIMESTAMPTZ"),
    ]
    for col_name, col_def in cols:
        _exec(session,
            f"ALTER TABLE public.org_departments ADD COLUMN IF NOT EXISTS {col_name} {col_def}",
            f"org_departments.{col_name}")


# ── Step 6: ALTER users ───────────────────────────────────────────────────────

def _alter_users(session):
    _exec(session, """
        ALTER TABLE public.users
            ADD COLUMN IF NOT EXISTS billing_unit_id UUID
                REFERENCES public.org_departments(id) ON DELETE SET NULL
    """, "users.billing_unit_id")


# ── Step 7: ALTER billing_orders ──────────────────────────────────────────────

def _alter_billing_orders(session):
    cols = [
        ("department_id",        "UUID REFERENCES public.org_departments(id) ON DELETE SET NULL"),
        ("amount_paise",         "INTEGER"),
        ("verified_at",          "TIMESTAMPTZ"),
        ("plan_name",            "VARCHAR(100)"),
        ("paid_by_user_id",      "UUID REFERENCES public.users(id) ON DELETE SET NULL"),
        ("cancellation_reason",  "VARCHAR(255)"),
        ("anomaly_flag",         "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("anomaly_reason",       "VARCHAR(100)"),
        ("anomaly_resolution",   "VARCHAR(255)"),
        ("anomaly_resolved_at",  "TIMESTAMPTZ"),
        ("anomaly_resolved_by",  "UUID REFERENCES public.users(id) ON DELETE SET NULL"),
    ]
    for col_name, col_def in cols:
        _exec(session,
            f"ALTER TABLE public.billing_orders ADD COLUMN IF NOT EXISTS {col_name} {col_def}",
            f"billing_orders.{col_name}")

    # Ensure razorpay_payment_id exists (was in billing_v1.sql but confirm)
    _exec(session, """
        ALTER TABLE public.billing_orders
            ADD COLUMN IF NOT EXISTS razorpay_payment_id VARCHAR(100)
    """, "billing_orders.razorpay_payment_id (confirm)")

    # Partial UNIQUE index — DB-level idempotency guard for verify+webhook race
    _exec(session, """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_orders_payment_id
            ON public.billing_orders (razorpay_payment_id)
            WHERE razorpay_payment_id IS NOT NULL
    """, "UNIQUE INDEX billing_orders(razorpay_payment_id) WHERE NOT NULL")


# ── Step 8: ALTER notification_log ───────────────────────────────────────────

def _alter_notification_log(session):
    _exec(session, """
        ALTER TABLE public.notification_log
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255)
    """, "notification_log.idempotency_key")

    _exec(session, """
        CREATE INDEX IF NOT EXISTS ix_notification_log_idempotency_key
            ON public.notification_log (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """, "INDEX notification_log(idempotency_key)")


# ── Step 9: Seed SystemConfig rows ───────────────────────────────────────────

def _seed_system_config(session):
    rows = [
        (
            "billing_subscription_reminder_days",
            "[30, 7]",
            "json",
            "Global default reminder thresholds (days before expiry) for dept subscription expiry notifications. "
            "Override per-org via Organization.billing_reminder_days.",
        ),
        (
            "billing_payment_token_ttl_hours",
            "1",
            "int",
            "How long (hours) a Razorpay order/payment-link token is valid before the user must create a new order.",
        ),
        (
            "billing_notification_dedup_days",
            "3",
            "int",
            "Minimum days between duplicate billing notifications of the same type to the same dept.",
        ),
    ]
    for key, value, value_type, description in rows:
        try:
            result = session.execute(
                text("SELECT id FROM public.system_config WHERE key = :key"),
                {"key": key}
            ).fetchone()
            if not result:
                session.execute(text("""
                    INSERT INTO public.system_config (id, key, value, value_type, description)
                    VALUES (:id, :key, :value, :value_type, :description)
                """), {
                    "id": str(uuid.uuid4()),
                    "key": key,
                    "value": value,
                    "value_type": value_type,
                    "description": description,
                })
                session.commit()
                print(f"  [OK] SystemConfig: {key}")
            else:
                print(f"  [SKIP] SystemConfig: {key} (already exists)")
        except Exception as exc:
            session.rollback()
            print(f"  [ERROR] SystemConfig {key}: {exc}")
            raise


# ── Step 10: Seed BillingScope rows + backfill orgs ──────────────────────────

def _seed_billing_scope(session):
    scopes = [
        ("org_level",        "Organisation Level"),
        ("department_level", "Department Level"),
    ]
    for code, name in scopes:
        try:
            exists = session.execute(
                text("SELECT id FROM public.billing_scopes WHERE code = :code"),
                {"code": code}
            ).fetchone()
            if not exists:
                session.execute(text("""
                    INSERT INTO public.billing_scopes (id, code, name)
                    VALUES (:id, :code, :name)
                """), {"id": str(uuid.uuid4()), "code": code, "name": name})
                session.commit()
                print(f"  [OK] BillingScope: {code}")
            else:
                print(f"  [SKIP] BillingScope: {code} (already exists)")
        except Exception as exc:
            session.rollback()
            print(f"  [ERROR] BillingScope {code}: {exc}")
            raise

    # Backfill orgs that have no billing_scope_id yet
    try:
        org_level_id = session.execute(
            text("SELECT id FROM public.billing_scopes WHERE code = 'org_level'")
        ).scalar()

        result = session.execute(text("""
            UPDATE public.organizations
            SET billing_scope_id = :scope_id
            WHERE billing_scope_id IS NULL
        """), {"scope_id": str(org_level_id)})
        session.commit()
        print(f"  [OK] Backfilled {result.rowcount} org(s) → billing_scope_id = org_level")
    except Exception as exc:
        session.rollback()
        print(f"  [ERROR] Backfill orgs: {exc}")
        raise


# ── Public entry point ────────────────────────────────────────────────────────

def run(session):
    print("\n" + "=" * 70)
    print("  BILLING DEPT — PHASE 1 MIGRATION")
    print("=" * 70)

    print("\n[1/10] Create billing_scopes table")
    _create_billing_scopes(session)

    print("\n[2/10] Create org_plan_pricing table")
    _create_org_plan_pricing(session)

    print("\n[3/10] Create billing_audit_logs table")
    _create_billing_audit_logs(session)

    print("\n[4/10] ALTER organizations — billing columns")
    _alter_organizations(session)

    print("\n[5/10] ALTER org_departments — billing columns")
    _alter_org_departments(session)

    print("\n[6/10] ALTER users — billing_unit_id")
    _alter_users(session)

    print("\n[7/10] ALTER billing_orders — dept billing columns")
    _alter_billing_orders(session)

    print("\n[8/10] ALTER notification_log — idempotency_key")
    _alter_notification_log(session)

    print("\n[9/10] Seed SystemConfig rows")
    _seed_system_config(session)

    print("\n[10/10] Seed BillingScope + backfill orgs")
    _seed_billing_scope(session)

    print("\n" + "=" * 70)
    print("  [DONE] Billing Dept Phase 1 Migration Complete")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    from database import VendorSessionLocal
    _session = VendorSessionLocal()
    try:
        run(_session)
    finally:
        _session.close()
