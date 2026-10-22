"""
Workflow-role access to result / report records and the stage assignee
(middleware/auth_privilege.py _record_access_via_workflow, _find_stage_gate),
and own-org scoping of the shared department lookups
(routers/testing_requests.py department_hierarchy / _search / _ancestors).

Integration tests against the dev vendor DB, like the rest of this folder:
every session is rolled back, and a test skips when the data it needs isn't
there.

    python -m pytest tests/test_workflow_record_access.py -v
"""
import inspect
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import or_

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import VendorSessionLocal  # noqa: E402
from models import (  # noqa: E402
    OrgDepartment, OrgRole, Organization, TestResult, TestResultImage, TrWfInstance,
    TrWfStage, TrWfStageInstance, TrWfStageRole, User,
)
from middleware.auth_privilege import (  # noqa: E402
    _find_stage_gate, _record_access_via_workflow,
)
from routers import testing_requests as TR  # noqa: E402

NOBODY = [uuid.uuid4()]  # an org role id that holds nothing


def call(fn, **kw):
    """Call a FastAPI endpoint function directly, filling Query() defaults."""
    args = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name in kw:
            args[name] = kw[name]
        elif p.default is not inspect.Parameter.empty:
            args[name] = getattr(p.default, "default", p.default)
    return fn(**args)


@pytest.fixture()
def db():
    s = VendorSessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def wf_result(db):
    """(result, instance, viewer role id) - a result whose request has a
    workflow with at least one stage role."""
    rows = (
        db.query(TestResult, TrWfInstance, TrWfStageRole.role_id)
        .join(TrWfInstance, TrWfInstance.testing_request_id == TestResult.testing_request_id)
        .join(TrWfStage, TrWfStage.wf_definition_id == TrWfInstance.wf_definition_id)
        .join(TrWfStageRole, TrWfStageRole.stage_id == TrWfStage.id)
        .filter(TrWfStageRole.role_id != None)  # noqa: E711 (not a @token row)
        .filter(or_(TrWfStageRole.can_view == True,  # noqa: E712
                    TrWfStageRole.can_edit == True,  # noqa: E712
                    TrWfStageRole.can_approve == True,  # noqa: E712
                    TrWfStageRole.can_assign == True,  # noqa: E712
                    TrWfStageRole.can_act_as_tester == True))  # noqa: E712
        .limit(1).all()
    )
    if not rows:
        pytest.skip("no test result on a workflow with stage roles")
    return rows[0]


@pytest.fixture()
def active_instance(db):
    """(instance, current stage instance) of an active workflow."""
    row = (
        db.query(TrWfInstance, TrWfStageInstance)
        .join(TrWfStageInstance, (TrWfStageInstance.wf_instance_id == TrWfInstance.id)
              & (TrWfStageInstance.stage_id == TrWfInstance.current_stage_id))
        .filter(TrWfInstance.status == "active",
                TrWfStageInstance.status == "in_progress")
        .first()
    )
    if not row:
        pytest.skip("no active workflow with an in-progress stage")
    return row


# ── Result / report records ─────────────────────────────────────────────────

@pytest.mark.parametrize("tail", ["preview", "pdf"])
def test_result_preview_any_stage_role(db, wf_result, tail):
    result, _, role_id = wf_result
    parts = ["testing", "results", str(result.id), tail]
    assert _record_access_via_workflow(db, "GET", parts, [role_id], None)
    assert not _record_access_via_workflow(db, "GET", parts, NOBODY, None)


@pytest.mark.parametrize("tail", ["preview", "pdf"])
def test_request_report_any_stage_role(db, wf_result, tail):
    result, _, role_id = wf_result
    parts = ["testing_requests", str(result.testing_request_id), "report", tail]
    assert _record_access_via_workflow(db, "GET", parts, [role_id], None)
    assert not _record_access_via_workflow(db, "GET", parts, NOBODY, None)


def test_result_image_view_any_stage_role(db, wf_result):
    result, _, role_id = wf_result
    img = TestResultImage(test_result_id=result.id, file_name="t.png", file_data=b"x")
    db.add(img)
    db.flush()
    parts = ["testing", "results", "images", str(img.id)]
    assert _record_access_via_workflow(db, "GET", parts, [role_id], None)
    assert not _record_access_via_workflow(db, "GET", parts, NOBODY, None)


def test_result_image_upload_needs_active_tester(db):
    row = (
        db.query(TrWfInstance, TestResult)
        .join(TestResult, TestResult.testing_request_id == TrWfInstance.testing_request_id)
        .filter(TrWfInstance.status == "active", TrWfInstance.current_stage_id != None)  # noqa: E711
        .first()
    )
    if not row:
        pytest.skip("no active workflow with a result")
    inst, result = row
    parts = ["testing", "results", str(result.id), "images"]
    taken = {r for (r,) in db.query(TrWfStageRole.role_id)
             .filter(TrWfStageRole.stage_id == inst.current_stage_id)}
    free = [r for (r,) in db.query(OrgRole.id).limit(500) if r not in taken][:2]
    if len(free) < 2:
        pytest.skip("need two org roles with no role on the current stage")
    tester = TrWfStageRole(stage_id=inst.current_stage_id, role_id=free[0],
                           can_edit=True)
    viewer = TrWfStageRole(stage_id=inst.current_stage_id, role_id=free[1],
                           can_view=True)
    db.add_all([tester, viewer])
    db.flush()
    assert _record_access_via_workflow(db, "POST", parts, [tester.role_id], None)
    assert not _record_access_via_workflow(db, "POST", parts, [viewer.role_id], None)


def test_other_paths_not_granted(db, wf_result):
    result, _, role_id = wf_result
    for method, parts in [
        ("DELETE", ["testing", "results", str(result.id), "images"]),
        ("GET", ["testing", "results", str(result.id)]),
        ("GET", ["testing_requests", str(result.testing_request_id)]),
        ("POST", ["testing_requests", str(result.testing_request_id), "report", "pdf"]),
    ]:
        assert not _record_access_via_workflow(db, method, parts, [role_id], None)


# ── Stage assignee ──────────────────────────────────────────────────────────

def test_assignee_reads_but_cannot_write(db, active_instance):
    inst, si = active_instance
    user = db.query(User).first()
    si.assigned_user_id = user.id
    db.flush()
    parts = ["testing_requests", str(inst.testing_request_id)]
    assert _find_stage_gate(db, parts, NOBODY, user.id, "GET") is True
    assert _find_stage_gate(db, parts, NOBODY, user.id, "PUT") is False
    assert _find_stage_gate(db, parts, NOBODY, uuid.uuid4(), "GET") is False
    # ... and sees the request's report / results
    report = ["testing_requests", str(inst.testing_request_id), "report", "preview"]
    assert _record_access_via_workflow(db, "GET", report, NOBODY, user.id)


# ── Department lookups ──────────────────────────────────────────────────────

@pytest.fixture()
def two_orgs(db):
    """(org user, a department of another org)."""
    for u in db.query(User).filter(User.organization_id != None).limit(500):  # noqa: E711
        other = (db.query(OrgDepartment)
                 .filter(OrgDepartment.organization_id != u.organization_id,
                         OrgDepartment.is_active == True)  # noqa: E712
                 .first())
        if other:
            return u, other
    pytest.skip("need an org user and another org's department")


def test_hierarchy_rejects_other_org(db, two_orgs):
    user, other = two_orgs
    with pytest.raises(HTTPException) as e:
        call(TR.get_department_hierarchy, org_id=other.organization_id,
             current_user=user, db=db)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        call(TR.get_department_hierarchy, org_id=other.organization_id,
             parent_id=other.id, current_user=user, db=db)


def test_hierarchy_without_org_lists_own_org_only(db, two_orgs):
    user, _ = two_orgs
    if not db.get(Organization, user.organization_id).is_active:
        pytest.skip("user's org is inactive")
    orgs = call(TR.get_department_hierarchy, current_user=user, db=db)
    assert [o["id"] for o in orgs] == [str(user.organization_id)]


def test_hierarchy_own_org_still_works(db, two_orgs):
    user, _ = two_orgs
    call(TR.get_department_hierarchy, org_id=user.organization_id,
         current_user=user, db=db)


def test_search_rejects_other_org(db, two_orgs):
    user, other = two_orgs
    with pytest.raises(HTTPException) as e:
        call(TR.search_departments, q="a", org_id=other.organization_id,
             current_user=user, db=db)
    assert e.value.status_code == 403


def test_ancestors_hide_other_org(db, two_orgs):
    user, other = two_orgs
    with pytest.raises(HTTPException) as e:
        call(TR.get_department_ancestors, dept_id=other.id, current_user=user, db=db)
    assert e.value.status_code == 404
