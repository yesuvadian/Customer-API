"""
Which results Recompute All rescores (routers/analytics._recompute_result_ids):
an active Doc Support workflow - a tr_wf_instances row with no
testing_request_id - must not empty the list (NOT IN (..., NULL) matches
nothing in SQL), and a request in an active workflow is still skipped.

DB-backed like the rest of this folder: every session is rolled back.

    python -m pytest tests/test_recompute_result_ids.py -v
"""
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import VendorSessionLocal  # noqa: E402
from models import TestResult, TestingRequestStatus, TrWfInstance  # noqa: E402
from routers import analytics as A  # noqa: E402

SKIP = {
    TestingRequestStatus.draft, TestingRequestStatus.submitted,
    TestingRequestStatus.assigned, TestingRequestStatus.accepted,
    TestingRequestStatus.in_progress,
}


@pytest.fixture()
def db():
    s = VendorSessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def baseline(db):
    ids = A._recompute_result_ids(db, None, SKIP)
    if not ids:
        pytest.skip("no result a recompute would rescore")
    return ids


def test_active_doc_support_workflow_does_not_empty_recompute(db, baseline):
    db.add(TrWfInstance(entity_type="document_request", entity_id=uuid.uuid4(),
                        status="active", testing_request_id=None))
    db.flush()
    assert sorted(A._recompute_result_ids(db, None, SKIP)) == sorted(baseline)


def test_request_in_an_active_workflow_is_skipped(db, baseline):
    rid = baseline[0]
    tr_id = db.get(TestResult, rid).testing_request_id
    inst = db.query(TrWfInstance).filter_by(testing_request_id=tr_id).first()
    if inst:  # one instance per request (unique): reopen it
        inst.status = "active"
    else:
        db.add(TrWfInstance(entity_type="testing_request", entity_id=tr_id,
                            status="active", testing_request_id=tr_id))
    db.add(TrWfInstance(entity_type="document_request", entity_id=uuid.uuid4(),
                        status="active", testing_request_id=None))
    db.flush()
    ids = A._recompute_result_ids(db, None, SKIP)
    assert rid not in ids
    assert ids  # the NULL row didn't empty it
