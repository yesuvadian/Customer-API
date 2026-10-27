"""
Shared TR workflow access rules, used by the TR Approval Queue
(routers/testing_request_approvals.py), the stage gate
(middleware/auth_privilege.py) and submit_test_results
(services/testing_service.py), so who may see and who may act on a request
can't drift apart again.
"""
from sqlalchemy.orm import Session

from models import (
    OrgUserRole, TestingRequest, TrWfInstance, TrWfStage, TrWfStageInstance,
    TrWfStageRole,
)
from utils.common_service import get_dept_subtree_ids


def caller_dept_ids(db: Session, user) -> list:
    """
    Return the department subtree IDs visible to this user.

    Strategy: use the department_id from the caller's OrgUserRole assignments
    (role scoped at a specific department). Falls back to user.department_id.
    All matching departments and their descendants are included so that a
    manager at dept X can see all requests / testers under X.
    """
    dept_ids_raw = (
        db.query(OrgUserRole.department_id)
        .filter(
            OrgUserRole.user_id == user.id,
            OrgUserRole.is_active.is_(True),
            OrgUserRole.department_id.isnot(None),
        )
        .distinct()
        .all()
    )
    root_ids = [r[0] for r in dept_ids_raw]
    if not root_ids and user.department_id:
        root_ids = [user.department_id]
    if not root_ids:
        return []
    # Expand each root to its full subtree
    result = []
    seen = set()
    for root in root_ids:
        for did in get_dept_subtree_ids(db, root):
            if did not in seen:
                seen.add(did)
                result.append(did)
    return result


def is_tester_delegate(db: Session, instance, testing_request, org_role_ids,
                       dept_ids) -> bool:
    """
    True if the caller may execute the current stage on behalf of the
    request's assigned tester:

    - the current stage is the one assigned to the request's tester
      (its open stage instance's assigned_user_id == assigned_tester_id),
      so this never opens approval / review / originator stages that also
      happen to carry an assigned user;
    - one of org_role_ids has can_act_as_tester on ANY stage of the
      instance's workflow definition;
    - the request is inside the caller's department subtree (dept_ids, from
      caller_dept_ids). An empty dept_ids means the caller is not
      department-scoped, the same as the approval queue's filter.
    """
    if not org_role_ids or not instance.wf_definition_id or not instance.current_stage_id:
        return False
    if not testing_request or not testing_request.assigned_tester_id:
        return False
    if dept_ids and testing_request.department_id not in set(dept_ids):
        return False
    on_tester_stage = (
        db.query(TrWfStageInstance.id)
        .filter(
            TrWfStageInstance.wf_instance_id == instance.id,
            TrWfStageInstance.stage_id == instance.current_stage_id,
            TrWfStageInstance.status.notin_(("completed", "rejected")),
            TrWfStageInstance.assigned_user_id == testing_request.assigned_tester_id,
        )
        .first()
        is not None
    )
    if not on_tester_stage:
        return False
    return (
        db.query(TrWfStageRole.id)
        .join(TrWfStage, TrWfStage.id == TrWfStageRole.stage_id)
        .filter(
            TrWfStage.wf_definition_id == instance.wf_definition_id,
            TrWfStageRole.role_id.in_(org_role_ids),
            TrWfStageRole.can_act_as_tester.is_(True),
        )
        .first()
        is not None
    )


def user_is_tester_delegate(db: Session, testing_request, user) -> bool:
    """is_tester_delegate for a user, resolving their active org roles,
    department scope and the request's active workflow instance."""
    instance = (
        db.query(TrWfInstance)
        .filter(
            TrWfInstance.testing_request_id == testing_request.id,
            TrWfInstance.status == "active",
        )
        .first()
    )
    if not instance:
        return False
    org_role_ids = [
        r.org_role_id for r in
        db.query(OrgUserRole).filter_by(user_id=user.id, is_active=True).all()
    ]
    return is_tester_delegate(db, instance, testing_request, org_role_ids,
                              caller_dept_ids(db, user))
