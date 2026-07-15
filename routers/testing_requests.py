from uuid import UUID
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from models import RepairWorkflow, TrWfInstance
from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import (
    TestingRequestCreate,
    TestingRequestUpdate,
    TestingRequestAssign,
    TestingRequestResponse,
)
from services.testing_request_service import TestingRequestService
from utils.common_service import get_dept_subtree_ids, get_user_dept_scope

_DEFAULT_PAGE_SIZE = int(os.getenv("TR_PAGE_SIZE", "20"))

router = APIRouter(
    prefix="/testing_requests",
    tags=["testing_requests"],
    dependencies=[Depends(get_current_user)],
)


def _build_dept_path_map(reqs, db) -> dict:
    """
    Batch-build a {dept_id_str: [root_name, ..., leaf_name]} map for all
    department IDs seen in *reqs*. Uses one query to load all org departments,
    then walks ancestry in Python — avoids N+1 queries.
    """
    from models import OrgDepartment
    dept_ids = set()
    org_ids  = set()
    for r in reqs:
        if r.department_id:
            dept_ids.add(r.department_id)
        if r.organization_id:
            org_ids.add(r.organization_id)
    if not dept_ids or not org_ids:
        return {}

    all_depts = (
        db.query(OrgDepartment)
        .filter(OrgDepartment.organization_id.in_(list(org_ids)))
        .all()
    )
    name_map:   dict = {d.id: d.name for d in all_depts}
    parent_map: dict = {d.id: d.parent_department_id for d in all_depts if d.parent_department_id}

    result: dict = {}
    for did in dept_ids:
        path, visited = [], set()
        cur = did
        while cur and cur not in visited:
            visited.add(cur)
            if cur in name_map:
                path.append(name_map[cur])
            cur = parent_map.get(cur)
        path.reverse()
        result[str(did)] = path
    return result


def _enrich(req, dept_path_map: dict | None = None):
    """Attach computed display names to ORM object."""

    req.equipment_type_name = (
        req.equipment_type.name
        if req.equipment_type
        else None
    )

    if req.test_type:
        req.test_type_name = req.test_type.name
    else:
        fd_types = (req.form_data or {}).get("test_types") or []
        names = [t["name"] for t in fd_types if t.get("name")]
        req.test_type_name = ", ".join(names) if names else None

    req.department_name = (
        req.department.name
        if req.department
        else None
    )

    # Full department hierarchy path: ["Zone", "Circle", ..., "Substation"]
    if dept_path_map is not None and req.department_id:
        req.department_path = dept_path_map.get(str(req.department_id), [])
    elif req.department:
        req.department_path = [req.department.name]
    else:
        req.department_path = []

    # Equipment asset register fields
    if req.equipment:
        eq = req.equipment
        req.equipment_ueic    = eq.ueic
        req.equipment_name    = eq.ueic
        req.bay_number        = eq.bay_number
        req.serial_in_bay     = eq.serial_in_bay
        req.voltage_class     = eq.voltage_class or None
        req.equipment_make    = eq.manufacturer or None
        req.commissioned_year = (
            str(eq.commissioned_date.year) if eq.commissioned_date else None
        )
        rated = getattr(eq, "rated_mva", None) or getattr(eq, "capacity_mva", None)
        req.capacity_mva = str(rated) if rated else None
    else:
        req.equipment_ueic    = None
        req.equipment_name    = None
        req.bay_number        = None
        req.serial_in_bay     = None
        req.voltage_class     = None
        req.equipment_make    = None
        req.commissioned_year = None
        req.capacity_mva      = None

    # Originator
    if req.originator:
        req.originator_name = (
            f"{req.originator.firstname or ''} "
            f"{req.originator.lastname or ''}"
        ).strip() or req.originator.email
    else:
        req.originator_name = None

    # Assigned tester
    if req.assigned_tester:
        req.assigned_tester_name = (
            f"{req.assigned_tester.firstname or ''} "
            f"{req.assigned_tester.lastname or ''}"
        ).strip() or req.assigned_tester.email
    else:
        req.assigned_tester_name = None

    # Completed by (who actually submitted test results)
    if req.completed_by:
        req.completed_by_name = (
            f"{req.completed_by.firstname or ''} "
            f"{req.completed_by.lastname or ''}"
        ).strip() or req.completed_by.email
    else:
        req.completed_by_name = None

    # ─────────────────────────────────────────────
    # Repair Workflow Enrichment
    # ─────────────────────────────────────────────

    req.repair_workflow_id = None
    req.repair_current_stage = None
    req.repair_status = None
    req.repair_progress = None

    try:

        next_action = getattr(
            req,
            "next_action",
            None,
        )

        if next_action and str(next_action) == "repair_cycle":

            workflow = (
                req._sa_instance_state.session
                .query(RepairWorkflow)
                .filter(
                    RepairWorkflow.source_failure_id
                    == req.id
                )
                .first()
            )

            if workflow:

                req.repair_workflow_id = str(
                    workflow.id
                )

                req.repair_status = workflow.status

                req.repair_progress = (
                    workflow.progress
                )

                if workflow.current_stage:
                    req.repair_current_stage = (
                        workflow.current_stage.name
                    )

    except Exception:
        pass

    # ─────────────────────────────────────────────
    # is_closed — supports both legacy and TR workflow requests
    # Legacy: status in known closed enum values
    # TR workflow: active TrWfInstance is completed or terminated
    # ─────────────────────────────────────────────
    _LEGACY_CLOSED = {
        "approved", "completed", "closed", "rejected",
        "pass", "fail", "cancelled",
    }
    try:
        _status_val = req.status.value if hasattr(req.status, "value") else str(req.status)
        if _status_val in _LEGACY_CLOSED:
            req.is_closed = True
        elif req.wf_instance_id:
            _inst = (
                req._sa_instance_state.session
                .query(TrWfInstance)
                .filter(TrWfInstance.id == req.wf_instance_id)
                .first()
            )
            req.is_closed = bool(_inst and _inst.status in ("completed", "terminated"))
        else:
            req.is_closed = False
    except Exception:
        req.is_closed = False

    # wf_status_name / wf_status_color — current workflow stage status (dynamic)
    req.wf_status_name  = None
    req.wf_status_color = None
    req.wf_stage_name   = None
    req.wf_stage_roles  = []
    try:
        if req.wf_instance_id:
            from models import TrWfStage, TrWfStatus as _TrWfStatus
            _inst2 = (
                req._sa_instance_state.session
                .query(TrWfInstance)
                .filter(TrWfInstance.id == req.wf_instance_id)
                .first()
            )
            if _inst2:
                if _inst2.status in ("completed", "terminated"):

                    if req.current_status_code:
                        _st = (
                            req._sa_instance_state.session
                            .query(_TrWfStatus)
                            .filter(_TrWfStatus.status_code == req.current_status_code)
                            .first()
                        )

                        if _st:
                            req.wf_status_name = _st.status_name
                            req.wf_status_color = _st.color
                        else:
                            req.wf_status_name = "Completed"
                            req.wf_status_color = "#16A34A"

                    else:
                        req.wf_status_name = "Completed"
                        req.wf_status_color = "#16A34A"
                elif _inst2.current_stage_id:
                    _stage = (
                        req._sa_instance_state.session
                        .query(TrWfStage)
                        .filter(TrWfStage.id == _inst2.current_stage_id)
                        .first()
                    )
                    if _stage and _stage.status_id:
                        _st = (
                            req._sa_instance_state.session
                            .query(_TrWfStatus)
                            .filter(_TrWfStatus.id == _stage.status_id)
                            .first()
                        )
                        if _st:
                            req.wf_status_name  = _st.status_name
                            req.wf_status_color = _st.color
                    if not req.wf_status_name and _stage:
                        req.wf_status_name = _stage.name
                    if _stage:
                        req.wf_stage_name = _stage.name
                        req.wf_stage_roles = [
                            r.role.name for r in _stage.roles
                            if r.role_id and r.role
                        ]
    except Exception:
        pass

    # session_types — resolved from template for multi-session requests
    req.session_types = None
    try:
        if req.is_multi_session and req.test_type_id:
            from models import OrgTestTemplate
            _tpl = (
                req._sa_instance_state.session
                .query(OrgTestTemplate)
                .filter(OrgTestTemplate.test_type_id == req.test_type_id)
                .order_by(OrgTestTemplate.version.desc())
                .first()
            )
            if _tpl:
                _types = (_tpl.template_data or {}).get("session_types")
                if _types:
                    req.session_types = _types
    except Exception as _e:
        import logging as _log
        _log.getLogger(__name__).debug(f"session_types enrichment failed: {_e}")

    return req


# ─── Department Hierarchy (for location dropdowns) ───────────────────
@router.get("/department_hierarchy")
def get_department_hierarchy(
    org_id: Optional[UUID] = None,
    parent_id: Optional[UUID] = None,
    category: Optional[str] = Query(None, description="failure_registry | taqc_inspection — count only that category"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns department hierarchy for location selection.

    - Get root depts for an org:       /department_hierarchy?org_id=<uuid>
    - Get children of a department:    /department_hierarchy?org_id=<uuid>&parent_id=<uuid>

    When fetching root depts (no parent_id), org-admin sees all zones;
    dept-scoped users see only their root ancestor zone.
    """
    svc = TestingRequestService(db)

    # When drilling into children, never restrict — parent_id is explicit
    if parent_id is not None:
        return svc.get_department_hierarchy(org_id, parent_id, category=category)

    # For root-level fetch, scope to user's zone if dept-scoped
    if org_id is not None:
        is_admin, user_dept_id = get_user_dept_scope(db, current_user.id, org_id)
        if not is_admin and user_dept_id:
            return svc.get_department_hierarchy(org_id, parent_id=None, root_id=user_dept_id, category=category)

    return svc.get_department_hierarchy(org_id, parent_id, category=category)


@router.get("/department_root/{dept_id}")
def get_department_root(dept_id: UUID, db: Session = Depends(get_db)):
    """Walk up the hierarchy and return the root ancestor of the given department."""
    from models import OrgDepartment
    current = db.query(OrgDepartment).filter_by(id=dept_id).first()
    if not current:
        raise HTTPException(status_code=404, detail="Department not found")
    while current.parent_department_id:
        parent = db.query(OrgDepartment).filter_by(id=current.parent_department_id).first()
        if not parent:
            break
        current = parent
    return {"id": str(current.id), "name": current.name}


@router.get("/department_ancestors/{dept_id}")
def get_department_ancestors(dept_id: UUID, db: Session = Depends(get_db)):
    """Return the chain from the root down to the given dept (exclusive of dept itself).
    e.g. [KPTCL, Bangalore Zone, BMAZ South, Hoody] for dept=400kV Hoody"""
    from models import OrgDepartment
    chain = []
    current = db.query(OrgDepartment).filter_by(id=dept_id).first()
    if not current:
        raise HTTPException(status_code=404, detail="Department not found")
    # walk up, collect ancestors (not the dept itself)
    node = current
    while node.parent_department_id:
        parent = db.query(OrgDepartment).filter_by(id=node.parent_department_id).first()
        if not parent:
            break
        chain.append({"id": str(parent.id), "name": parent.name})
        node = parent
    chain.reverse()  # root first
    return chain


# ─── Equipment Types (for form dropdowns) ───────────────────
@router.get("/equipment_types")
def list_equipment_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns equipment types grouped by request category."""
    return TestingRequestService(db).list_equipment_types(org_id=current_user.organization_id)


# ─── Kit Sub-Types (Testing Kit CategoryDetails) ────────────
@router.get("/kit-subtypes")
def list_kit_subtypes(db: Session = Depends(get_db)):
    """Returns Testing Kit sub-categories for the kit-type dropdown."""
    from models import CategoryMaster, CategoryDetails
    kit_master = db.query(CategoryMaster).filter(
        CategoryMaster.name == "Testing Kit",
        CategoryMaster.is_active.is_(True),
    ).first()
    if not kit_master:
        return []
    subs = (
        db.query(CategoryDetails)
        .filter(
            CategoryDetails.category_master_id == kit_master.id,
            CategoryDetails.is_active.is_(True),
        )
        .order_by(CategoryDetails.name)
        .all()
    )
    return [{"id": s.id, "name": s.name} for s in subs]


# ─── Lifecycle Types (calibration + cumulative, separate masters) ────────────
@router.get("/lifecycle-types")
def list_lifecycle_types(db: Session = Depends(get_db)):
    """Returns calibration and cumulative test types from their dedicated masters.

    Response:
      {
        "calibration": [{"id", "name", "enable_calibration": true, ...}],
        "cumulative":  [{"id", "name", "enable_cumulative":  true, ...}]
      }

    Flutter uses this to reload the test-type dropdown when a lifecycle flag
    is detected on a selected test type.
    """
    return TestingRequestService(db).list_lifecycle_types()


# ─── All test types by category (no equipment filter) ───────────────────────
@router.get("/all-test-types")
def list_all_test_types(
    category: str = None,
    db: Session = Depends(get_db),
):
    """Return all CategoryDetails (test types) grouped by category_type, with
    lifecycle flags resolved from their OrgTestTemplate.

    Optional ?category=test|maintenance|inspection|repair_lifecycle to filter.

    Flutter uses this to populate the test-type dropdown when no equipment
    type is selected — so calibration/cumulative maintenance types (Protection
    Relay Calibration, Circuit Breaker Operations Count, etc.) are accessible
    without first picking a specific registered equipment.
    """
    return TestingRequestService(db).list_all_test_types(category=category)


# ─── Generic dropdown by master description ─────────────
@router.get("/dropdown/{master_desc}")
def get_dropdown_values(master_desc: str, db: Session = Depends(get_db)):
    """Returns CategoryDetails for a CategoryMaster identified by description.
    E.g. /dropdown/Testing Priority → [{id, name}, ...]
    """
    return TestingRequestService(db).get_dropdown_values(master_desc)


# ─── List testers (users with Tester role, optionally filtered by location) ───
@router.get("/by-equipment")
def get_by_equipment(
    org_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    request_category: Optional[str] = None,
    is_closed: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return testing requests grouped by equipment with alert bar status."""
    eff_org_id = org_id or current_user.organization_id
    if not eff_org_id:
        raise HTTPException(status_code=400, detail="org_id required")
    dept_ids = None
    if department_id:
        dept_ids = get_dept_subtree_ids(db, department_id, eff_org_id)
    return TestingRequestService(db).get_by_equipment(
        org_id=eff_org_id,
        department_ids=dept_ids,
        request_category=request_category,
        is_closed=is_closed,
    )


@router.get("/testers")
def list_testers(
    zone: Optional[str] = None,
    ce_circle: Optional[str] = None,
    se_division: Optional[str] = None,
    ee_subdivision: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Returns active users with the 'Tester' role, optionally filtered by location."""
    return TestingRequestService(db).list_testers(
        zone=zone, ce_circle=ce_circle, se_division=se_division, ee_subdivision=ee_subdivision
    )


@router.get("/stats")
def get_testing_request_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return testing request counts by status for the organization."""
    service = TestingRequestService(db)
    # Filter by organization if user belongs to one
    organization_id = current_user.organization_id
    return service.get_stats(organization_id=organization_id)


@router.post("/", response_model=TestingRequestResponse, status_code=status.HTTP_201_CREATED)
def create_testing_request(
    data: TestingRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    payload = data.dict()
    # Auto-set organization_id from current user if not provided
    if not payload.get("organization_id") and current_user.organization_id:
        payload["organization_id"] = str(current_user.organization_id)
    req = service.create_request(payload, originator_id=current_user.id)
    return _enrich(req)


@router.get("/request-categories")
def list_request_categories():
    """Return all valid request categories with labels for Flutter dropdowns."""
    return [
        {"value": "test",             "label": "Testing",          "icon": "science",        "description": "Routine or scheduled equipment testing"},
        {"value": "maintenance",      "label": "Maintenance",      "icon": "build",          "description": "Preventive or corrective maintenance"},
        {"value": "inspection",       "label": "Inspection",       "icon": "search",         "description": "Visual or functional inspection"},
        {"value": "repair_lifecycle", "label": "Repair / Lifecycle","icon": "engineering",   "description": "Repair work or lifecycle assessment"},
        {"value": "failure_registry", "label": "Failure Registry", "icon": "report_problem", "description": "Equipment failure registration and tracking"},
        {"value": "taqc_inspection",  "label": "TA&QC Inspection", "icon": "verified",       "description": "Type approval and quality control inspection"},
    ]


@router.get("/")
def list_testing_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(None, ge=1, le=2000),
    search: Optional[str] = Query(None, description="Search by UEIC or bay number"),
    status: Optional[str] = None,
    category: Optional[str] = None,
    originator_id: Optional[UUID] = None,
    tester_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    equipment_id: Optional[UUID] = None,
    voltage_class: Optional[str] = Query(None, description="Asset-dashboard filter: voltage class"),
    equipment_type: Optional[str] = Query(None, description="Asset-dashboard filter: equipment type name"),
    make: Optional[str] = Query(None, description="Asset-dashboard filter: equipment manufacturer"),
    commissioned_year: Optional[str] = Query(None, description="Asset-dashboard filter: commissioning year"),
    failure_year: Optional[str] = Query(None, description="Asset-dashboard filter: retirement/failure year"),
    capacity_mva: Optional[str] = Query(None, description="Asset-dashboard filter: capacity label"),
    date_from: Optional[str] = Query(None, description="Filter completed_at >= YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="Filter completed_at <= YYYY-MM-DD"),
    is_closed: Optional[bool] = Query(None, description="True = legacy-closed or wf-completed; False = still active"),
    wf_active: Optional[bool] = Query(None, description="True = only TRs with an active workflow instance (Kanban use)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    ps = page_size or _DEFAULT_PAGE_SIZE
    skip = (page - 1) * ps

    organization_id = current_user.organization_id
    service = TestingRequestService(db)

    if department_id is None and organization_id:
        is_admin, scoped_dept = service.get_user_scope(current_user.id, organization_id)
        if not is_admin and scoped_dept:
            # Don't narrow by dept for users who have approver roles in any TR workflow stage
            user_is_approver = service.user_has_tr_wf_approver_role(current_user.id, organization_id)
            if not user_is_approver:
                department_id = scoped_dept

    dept_ids = None
    if department_id:
        subtree = get_dept_subtree_ids(db, department_id)
        if len(subtree) >= 1:
            dept_ids = subtree

    from datetime import date as _date
    def _parse_date(s):
        try:
            return _date.fromisoformat(s) if s else None
        except ValueError:
            return None

    common = dict(
        status_filter=status,
        is_closed=is_closed,
        wf_active=wf_active,
        category_filter=category,
        originator_id=originator_id,
        tester_id=tester_id,
        organization_id=organization_id,
        department_id=department_id if dept_ids is None else None,
        department_ids=dept_ids,
        equipment_id=equipment_id,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        search=search,
        voltage_class=voltage_class,
        equipment_type=equipment_type,
        make=make,
        commissioned_year=commissioned_year,
        failure_year=failure_year,
        capacity_mva=capacity_mva,
    )

    total = service.count_requests(**common)
    items = service.get_requests(skip=skip, limit=ps, **common)
    dept_path_map = _build_dept_path_map(items, db)
    serialized = [
        TestingRequestResponse.model_validate(_enrich(r, dept_path_map), from_attributes=True).model_dump(mode='json')
        for r in items
    ]

    return {
        "items": serialized,
        "total": total,
        "page": page,
        "page_size": ps,
        "has_more": (skip + len(serialized)) < total,
    }


@router.get("/breakdown")
def get_testing_request_breakdown(
    search: Optional[str] = Query(None, description="Search by UEIC, bay number, request number, or title"),
    status: Optional[str] = None,
    category: Optional[str] = None,
    originator_id: Optional[UUID] = None,
    tester_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    equipment_id: Optional[UUID] = None,
    date_from: Optional[str] = Query(None, description="Filter completed_at >= YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="Filter completed_at <= YYYY-MM-DD"),
    is_closed: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    organization_id = current_user.organization_id
    service = TestingRequestService(db)

    if department_id is None and organization_id:
        is_admin, scoped_dept = service.get_user_scope(current_user.id, organization_id)
        if not is_admin and scoped_dept:
            department_id = scoped_dept

    dept_ids = None
    if department_id:
        subtree = get_dept_subtree_ids(db, department_id)
        if len(subtree) >= 1:
            dept_ids = subtree

    from datetime import date as _date
    def _parse_date(s):
        try:
            return _date.fromisoformat(s) if s else None
        except ValueError:
            return None

    return service.get_breakdown(
        status_filter=status,
        is_closed=is_closed,
        category_filter=category,
        originator_id=originator_id,
        tester_id=tester_id,
        organization_id=organization_id,
        department_id=department_id if dept_ids is None else None,
        department_ids=dept_ids,
        equipment_id=equipment_id,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        search=search,
    )


@router.get("/{request_id}", response_model=TestingRequestResponse)
def get_testing_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    req = _enrich(service.get_request(request_id))

    # Attach current TR workflow stage flags
    instance = (
        db.query(TrWfInstance)
        .filter(
            TrWfInstance.testing_request_id == request_id,
            TrWfInstance.status == "active",
        )
        .first()
    )
    req.current_stage_show_recommendation = bool(
        instance and instance.current_stage and instance.current_stage.show_recommendation
    )
    return req


@router.put("/{request_id}", response_model=TestingRequestResponse)
def update_testing_request(
    request_id: UUID,
    data: TestingRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    req = service.update_request(request_id, data.dict(exclude_unset=True), modified_by=current_user.id)
    return _enrich(req)


@router.delete("/{request_id}")
def delete_testing_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    return service.delete_request(request_id)


@router.put("/{request_id}/submit", response_model=TestingRequestResponse)
def submit_testing_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    return _enrich(service.submit_request(request_id, modified_by=current_user.id))


@router.put("/{request_id}/assign", response_model=TestingRequestResponse)
def assign_tester(
    request_id: UUID,
    data: TestingRequestAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    return _enrich(service.assign_tester(request_id, tester_id=data.tester_id, assigned_by=current_user.id))


@router.put("/{request_id}/approve", response_model=TestingRequestResponse)
def approve_testing_results(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve test results after testing is complete."""
    from services.testing_request_workflow_service import TestingRequestWorkflowService

    service = TestingRequestService(db)
    request = service.get_request(request_id)

    workflow_service = TestingRequestWorkflowService(db)
    success, message = workflow_service.approve_results(
        testing_request=request,
        user=current_user,
        comment=None
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    db.refresh(request)
    return _enrich(request)


# NOTE: Tester workflow endpoints (accept, start, submit_results)

@router.get("/{request_id}/report/preview", response_class=HTMLResponse)
def request_report_preview(request_id: UUID, db: Session = Depends(get_db)):
    """HTML report for a test request — uses latest session if present, else TestResult directly."""
    from models import TestSession
    from services.testing_request_html_service import TestingRequestHTMLService

    req = db.query(__import__('models').TestingRequest).filter(
        __import__('models').TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Not found")

    session = (
        db.query(TestSession)
        .filter(TestSession.testing_request_id == request_id)
        .order_by(TestSession.session_number.desc())
        .first()
    )
    if session:
        from routers.test_sessions import preview_session
        return preview_session(request_id=request_id, session_id=session.id, db=db)

    html = TestingRequestHTMLService(db).generate_html(str(request_id))
    return HTMLResponse(content=html)
@router.get("/{request_id}/report/pdf")
def request_report_pdf(request_id: UUID, db: Session = Depends(get_db)):
    """PDF report for a test request — uses latest session if present, else TestResult directly."""
    from fastapi.responses import Response
    from models import TestSession, TestResult as TR

    req = db.query(__import__('models').TestingRequest).filter(
        __import__('models').TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Not found")

    # Prefer session-based PDF
    session = (
        db.query(TestSession)
        .filter(TestSession.testing_request_id == request_id)
        .order_by(TestSession.session_number.desc())
        .first()
    )
    if session:
        from routers.test_sessions import download_session_pdf
        return download_session_pdf(request_id=request_id, session_id=session.id, db=db)

    # Fallback: use the existing TestingRequestPDFService (now extended with test_data)
    from fastapi.responses import Response
    from services.testing_request_pdf_service import TestingRequestPDFService

    req_num = getattr(req, "request_number", str(request_id))
    buf = TestingRequestPDFService(db).generate_pdf(str(request_id))
    safe_name = f"report_{req_num}.pdf".replace(" ", "_")
    return Response(content=buf.read(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})
