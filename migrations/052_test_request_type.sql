-- Migration 052: Test Request lineage type (design doc section 3)
--
-- ORIGINAL  - raised by a schedule, a user, or any other normal path
-- FOLLOW_UP - raised by services/car_service.py from a CAR Trigger Config
--             follow-up action of a different test type (maintenance,
--             inspection, another test)
-- RETEST    - raised by car_service.py to re-run the triggering test type
--
-- A separate column, not the existing testing_requests.request_type: that one
-- already holds normal / failure / special and drives workflow routing.
-- Values mirror the "Test Request Type" CategoryMaster seeded by
-- seed_test_request_type_master.py. parent_request_id (migration 029) already
-- carries the lineage itself.

BEGIN;

ALTER TABLE public.testing_requests
    ADD COLUMN IF NOT EXISTS test_request_type VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL';

ALTER TABLE public.testing_requests
    DROP CONSTRAINT IF EXISTS chk_tr_test_request_type;
ALTER TABLE public.testing_requests
    ADD CONSTRAINT chk_tr_test_request_type CHECK (test_request_type IN ('ORIGINAL', 'FOLLOW_UP', 'RETEST'));

-- Backfill the requests car_service.py already raised (titled
-- "CAR-YYYY-NNNN retest: ..." / "CAR-YYYY-NNNN follow-up: ...").
UPDATE public.testing_requests SET test_request_type = 'RETEST'
 WHERE title ~ '^CAR-[0-9]{4}-[0-9]+ retest:' AND test_request_type = 'ORIGINAL';
UPDATE public.testing_requests SET test_request_type = 'FOLLOW_UP'
 WHERE title ~ '^CAR-[0-9]{4}-[0-9]+ follow-up:' AND test_request_type = 'ORIGINAL';

COMMIT;
