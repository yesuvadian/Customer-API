from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, CategoryMaster, CategoryDetails, Role, UserRole, TesterLocation, OrgDepartment, Organization
from sqlalchemy import or_
from schemas import (
    TestingRequestCreate,
    TestingRequestUpdate,
    TestingRequestAssign,
    TestingRequestResponse,
)
from services.testing_request_service import TestingRequestService

router = APIRouter(
    prefix="/testing_requests",
    tags=["testing_requests"],
    dependencies=[Depends(get_current_user)],
)


def _user_role_names(db: Session, user_id) -> set:
    """Return set of role names for a user."""
    roles = (
        db.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return {r[0] for r in roles}


def _enrich(req):
    """Attach computed display names to ORM object."""
    req.equipment_type_name = req.equipment_type.name if req.equipment_type else None
    req.test_type_name = req.test_type.name if req.test_type else None
    req.department_name = req.department.name if req.department else None

    # Equipment asset register fields
    if req.equipment:
        req.equipment_ueic = req.equipment.ueic
        req.equipment_name = req.equipment.ueic  # Alias for Flutter UI
    else:
        req.equipment_ueic = None
        req.equipment_name = None

    if req.originator:
        req.originator_name = f"{req.originator.firstname or ''} {req.originator.lastname or ''}".strip() or req.originator.email
    else:
        req.originator_name = None
    if req.assigned_tester:
        req.assigned_tester_name = f"{req.assigned_tester.firstname or ''} {req.assigned_tester.lastname or ''}".strip() or req.assigned_tester.email
    else:
        req.assigned_tester_name = None
    return req


# ─── Department Hierarchy (for location dropdowns) ───────────────────
@router.get("/department_hierarchy")
def get_department_hierarchy(
    org_id: Optional[UUID] = None,
    parent_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Returns department hierarchy for location selection.
    Can be filtered by organization_id and parent_department_id.

    Use cases:
    - Get all organizations: /department_hierarchy
    - Get root departments for an org: /department_hierarchy?org_id=<uuid>
    - Get children of a department: /department_hierarchy?org_id=<uuid>&parent_id=<uuid>
    """
    if org_id is None:
        # Return list of organizations
        orgs = db.query(Organization).filter(Organization.is_active == True).order_by(Organization.name).all()
        return [{
            "id": str(org.id),
            "name": org.name,
            "code": org.code,
            "type": "organization"
        } for org in orgs]

    # Return departments for the organization
    query = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == org_id,
        OrgDepartment.is_active == True
    )

    if parent_id is None:
        # Root level departments (no parent)
        query = query.filter(OrgDepartment.parent_department_id == None)
    else:
        # Children of specified parent
        query = query.filter(OrgDepartment.parent_department_id == parent_id)

    departments = query.order_by(OrgDepartment.name).all()

    return [{
        "id": str(dept.id),
        "name": dept.name,
        "code": dept.code,
        "parent_department_id": str(dept.parent_department_id) if dept.parent_department_id else None,
        "has_children": db.query(OrgDepartment).filter(
            OrgDepartment.parent_department_id == dept.id,
            OrgDepartment.is_active == True
        ).count() > 0,
        "type": "department"
    } for dept in departments]


# ─── Equipment Types (for form dropdowns) ───────────────────
@router.get("/equipment_types")
def list_equipment_types(db: Session = Depends(get_db)):
    """
    Returns equipment types (CategoryMaster where description='Testing Equipment')
    with their test types (CategoryDetails).
    """
    masters = (
        db.query(CategoryMaster)
        .filter(CategoryMaster.description == "Testing Equipment", CategoryMaster.is_active == True)
        .order_by(CategoryMaster.name)
        .all()
    )
    result = []
    for m in masters:
        tests = (
            db.query(CategoryDetails)
            .filter(CategoryDetails.category_master_id == m.id, CategoryDetails.is_active == True)
            .order_by(CategoryDetails.name)
            .all()
        )
        result.append({
            "id": m.id,
            "name": m.name,
            "tests": [{"id": t.id, "name": t.name} for t in tests],
        })
    return result


# ─── Generic dropdown by master description ─────────────
@router.get("/dropdown/{master_desc}")
def get_dropdown_values(master_desc: str, db: Session = Depends(get_db)):
    """
    Returns CategoryDetails for a CategoryMaster identified by description.
    E.g. /dropdown/Testing Priority → [{id, name}, ...]
    """
    master = (
        db.query(CategoryMaster)
        .filter(CategoryMaster.description == master_desc, CategoryMaster.is_active == True)
        .first()
    )
    if not master:
        return []
    details = (
        db.query(CategoryDetails)
        .filter(CategoryDetails.category_master_id == master.id, CategoryDetails.is_active == True)
        .order_by(CategoryDetails.id)
        .all()
    )
    return [{"id": d.id, "name": d.name} for d in details]


# ─── List testers (users with Tester role, optionally filtered by location) ───
@router.get("/testers")
def list_testers(
    zone: Optional[str] = None,
    ce_circle: Optional[str] = None,
    se_division: Optional[str] = None,
    ee_subdivision: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Returns active users with the 'Tester' role.
    Optionally filters by location via the tester_locations mapping table."""
    tester_role = db.query(Role).filter(Role.name == "Tester").first()
    if not tester_role:
        return []

    # Check if any location filter is provided
    has_location_filter = any([zone, ce_circle, se_division, ee_subdivision])

    if has_location_filter:
        query = (
            db.query(User, TesterLocation)
            .join(UserRole, UserRole.user_id == User.id)
            .join(TesterLocation, TesterLocation.user_id == User.id)
            .filter(UserRole.role_id == tester_role.id, User.isactive == True,
                    TesterLocation.is_active == True)
        )
        if zone:
            query = query.filter(TesterLocation.zone == zone)
        if ce_circle:
            query = query.filter(TesterLocation.ce_circle == ce_circle)
        if se_division:
            query = query.filter(TesterLocation.se_division == se_division)
        if ee_subdivision:
            query = query.filter(TesterLocation.ee_subdivision == ee_subdivision)

        results = query.order_by(User.firstname).all()
        return [
            {
                "id": str(u.id),
                "name": f"{u.firstname} {u.lastname}".strip(),
                "email": u.email,
                "zone": tl.zone,
                "ce_circle": tl.ce_circle,
                "se_division": tl.se_division,
                "ee_subdivision": tl.ee_subdivision,
            }
            for u, tl in results
        ]
    else:
        testers = (
            db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .filter(UserRole.role_id == tester_role.id, User.isactive == True)
            .order_by(User.firstname)
            .all()
        )
        # Attach location info if available
        result = []
        for t in testers:
            loc = db.query(TesterLocation).filter(
                TesterLocation.user_id == t.id, TesterLocation.is_active == True
            ).first()
            result.append({
                "id": str(t.id),
                "name": f"{t.firstname} {t.lastname}".strip(),
                "email": t.email,
                "zone": loc.zone if loc else None,
                "ce_circle": loc.ce_circle if loc else None,
                "se_division": loc.se_division if loc else None,
                "ee_subdivision": loc.ee_subdivision if loc else None,
            })
        return result


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
    ]


@router.get("/", response_model=List[TestingRequestResponse])
def list_testing_requests(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    category: Optional[str] = None,
    originator_id: Optional[UUID] = None,
    tester_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Filter by organization if user belongs to one
    organization_id = current_user.organization_id

    service = TestingRequestService(db)
    requests = service.get_requests(
        skip=skip,
        limit=limit,
        status_filter=status,
        category_filter=category,
        originator_id=originator_id,
        tester_id=tester_id,
        organization_id=organization_id,
    )
    return [_enrich(r) for r in requests]


@router.get("/{request_id}", response_model=TestingRequestResponse)
def get_testing_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingRequestService(db)
    return _enrich(service.get_request(request_id))


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
# are in routers/testing.py under the /testing prefix.
