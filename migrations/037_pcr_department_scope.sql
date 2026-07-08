-- 037: Add dept_id to precommission_requests for department-scoped access control
ALTER TABLE public.precommission_requests
    ADD COLUMN IF NOT EXISTS dept_id UUID
        REFERENCES public.org_departments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_precommission_requests_dept_id
    ON public.precommission_requests(dept_id);
