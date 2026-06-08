-- Migration 024: Pre-Commission QAP Request table
-- A PreCommissionRequest is created before a transformer arrives at site.
-- On approval, a RepairWorkflow (PRE_COMMISSION) is auto-created.
-- After equipment onboarding, equipment_id is backfilled.

BEGIN;

CREATE TABLE IF NOT EXISTS public.precommission_requests (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_number          VARCHAR(50)  NOT NULL UNIQUE,

    -- Organization
    organization_id         UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,

    -- Equipment type (must be Power Transformer category)
    equipment_type_id       INTEGER REFERENCES public."CategoryMaster"(id),

    -- Purchase / Vendor details
    vendor_name             VARCHAR(255) NOT NULL,
    purchase_order_number   VARCHAR(100) NOT NULL,
    po_date                 DATE,
    rated_mva               NUMERIC(10,3),
    voltage_class           VARCHAR(20),   -- '110kV', '66kV', '220kV'
    quantity                INTEGER DEFAULT 1,
    factory_location        VARCHAR(255),
    proposed_inspection_date DATE,
    remarks                 TEXT,

    -- Approval
    approval_status         VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    approved_by             UUID REFERENCES public.users(id),
    approved_at             TIMESTAMPTZ,
    approval_notes          TEXT,
    rejected_by             UUID REFERENCES public.users(id),
    rejected_at             TIMESTAMPTZ,

    -- Workflow link (set after approval)
    workflow_id             UUID REFERENCES repair_workflows(id) ON DELETE SET NULL,

    -- Equipment link (set after onboarding)
    equipment_id            UUID REFERENCES public.equipment(id) ON DELETE SET NULL,

    -- Audit
    created_by              UUID REFERENCES public.users(id),
    modified_by             UUID REFERENCES public.users(id),
    cts                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mts                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pcr_org      ON public.precommission_requests(organization_id);
CREATE INDEX IF NOT EXISTS idx_pcr_status   ON public.precommission_requests(approval_status);
CREATE INDEX IF NOT EXISTS idx_pcr_workflow ON public.precommission_requests(workflow_id);
CREATE INDEX IF NOT EXISTS idx_pcr_equip    ON public.precommission_requests(equipment_id);

COMMIT;
