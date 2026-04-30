"""
Equipment Asset Register Router
CRUD for equipment units with UEIC auto-generation, linked to OrgDepartment hierarchy.
Enforces org-scoping and module-level RBAC via OrgRolePermission.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from auth_utils import get_current_user
from models import Equipment, Module, User
from middleware.org_auth import check_org_permission
from schemas import (
    EquipmentCreate,
    EquipmentUpdate,
    EquipmentResponse,
    EquipmentRetireRequest,
    EquipmentReplaceRequest,
    EquipmentCountResponse,
)
from services.equipment_service import EquipmentService
from services.test_register_service import TestRegisterService

router = APIRouter(
    prefix="/equipment",
    tags=["equipment"],
    dependencies=[Depends(get_current_user)]
)


# ── Permission helpers ──────────────────────────────────────────────────────
def _get_equipment_module_id(db: Session) -> int:
    """Resolve the Equipment module row; raises 500 if not seeded."""
    mod = db.query(Module).filter_by(path="equipment", is_active=True).first()
    if not mod:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Equipment module not configured. Run seed first.",
        )
    return mod.id


def _require_permission(db: Session, user: User, action: str) -> None:
    """
    Check that *user* has *action* (can_view / can_add / can_edit / can_delete)
    on the Equipment module.  Org admins are automatically allowed by
    check_org_permission → the OrgRole.is_org_admin bypass in org_auth.
    """
    from models import OrgUserRole, OrgRole

    # Org admins bypass all module checks
    is_org_admin = (
        db.query(OrgUserRole)
        .join(OrgRole)
        .filter(
            OrgUserRole.user_id == user.id,
            OrgRole.is_org_admin == True,
            OrgUserRole.is_active == True,
            OrgRole.is_active == True,
        )
        .first()
    )
    if is_org_admin:
        return

    module_id = _get_equipment_module_id(db)
    if not check_org_permission(user.id, module_id, action, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission '{action}' required on Equipment module",
        )


def _enforce_org_scope(user: User) -> UUID:
    """Return the user's organization_id or raise 403."""
    if not user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization to access equipment",
        )
    return user.organization_id


def _to_response(eq: Equipment) -> dict:
    """Convert Equipment ORM object to response dict with computed fields."""
    return {
        "id": eq.id,
        "ueic": eq.ueic,
        "organization_id": eq.organization_id,
        "department_id": eq.department_id,
        "equipment_type_id": eq.equipment_type_id,
        "equipment_type_name": eq.equipment_type.name if eq.equipment_type else None,
        "department_name": eq.department.name if eq.department else None,
        "voltage_class": eq.voltage_class,
        "bay_number": eq.bay_number,
        "serial_in_bay": eq.serial_in_bay,
        "nameplate_data": eq.nameplate_data,
        "status": eq.status.value if eq.status else None,
        "replaces_equipment_id": eq.replaces_equipment_id,
        "commissioned_date": eq.commissioned_date,
        "retired_date": eq.retired_date,
        "retirement_reason": eq.retirement_reason,
        "manufacturer": eq.manufacturer,
        "model_number": eq.model_number,
        "factory_serial_number": eq.factory_serial_number,
        "year_of_manufacture": eq.year_of_manufacture,
        "created_by": eq.created_by,
        "modified_by": eq.modified_by,
        "cts": eq.cts,
        "mts": eq.mts,
    }


# ============================================================
# CREATE EQUIPMENT
# ============================================================
@router.post("/", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
def create_equipment(
    data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new equipment unit. UEIC is auto-generated."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_add")

    # Org-scope: force equipment into the user's own organization
    if data.organization_id and data.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create equipment in another organization",
        )

    equipment = EquipmentService.create_equipment(
        db=db,
        organization_id=org_id,
        department_id=data.department_id,
        equipment_type_id=data.equipment_type_id,
        voltage_class=data.voltage_class,
        bay_number=data.bay_number,
        nameplate_data=data.nameplate_data,
        commissioned_date=data.commissioned_date,
        manufacturer=data.manufacturer,
        model_number=data.model_number,
        factory_serial_number=data.factory_serial_number,
        year_of_manufacture=data.year_of_manufacture,
        created_by=current_user.id,
    )
    db.commit()
    db.refresh(equipment)

    # ── Commissioning hook: auto-clone Test Register templates ────────────────
    try:
        reg_svc = TestRegisterService(db)
        commission_result = reg_svc.commission_equipment(equipment.id, current_user)
        if commission_result["requests_created"] > 0:
            print(
                f"[Test Register] Commissioned {commission_result['requests_created']} "
                f"schedule(s) for UEIC {equipment.ueic}"
            )
    except Exception as exc:
        # Non-fatal: commissioning failure must not block equipment creation
        print(f"[WARN] Test Register commissioning failed for {equipment.id}: {exc}")

    return _to_response(equipment)


# ============================================================
# LIST EQUIPMENT (with filters)
# ============================================================
@router.get("/", response_model=List[EquipmentResponse])
def list_equipment(
    department_id: Optional[UUID] = None,
    equipment_type_id: Optional[int] = None,
    status: Optional[str] = None,
    voltage_class: Optional[str] = None,
    manufacturer: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List equipment with optional filters. Automatically scoped to user's organization."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    items = EquipmentService.list_equipment(
        db=db,
        organization_id=org_id,
        department_id=department_id,
        equipment_type_id=equipment_type_id,
        status=status,
        voltage_class=voltage_class,
        manufacturer=manufacturer,
        search=search,
        skip=skip,
        limit=limit,
    )
    return [_to_response(eq) for eq in items]


# ============================================================
# GET SINGLE EQUIPMENT
# ============================================================
@router.get("/{equipment_id}", response_model=EquipmentResponse)
def get_equipment(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Org-scope: ensure the equipment belongs to the user's org
    if equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    return _to_response(equipment)


# ============================================================
# GET EQUIPMENT BY UEIC
# ============================================================
@router.get("/by-ueic/{ueic}", response_model=EquipmentResponse)
def get_equipment_by_ueic(
    ueic: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment_by_ueic(db, ueic)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    if equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    return _to_response(equipment)


# ============================================================
# UPDATE EQUIPMENT
# ============================================================
@router.put("/{equipment_id}", response_model=EquipmentResponse)
def update_equipment(
    equipment_id: UUID,
    data: EquipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_edit")

    # Verify ownership before updating
    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    equipment = EquipmentService.update_equipment(
        db=db,
        equipment_id=equipment_id,
        modified_by=current_user.id,
        **data.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(equipment)
    return _to_response(equipment)


# ============================================================
# RETIRE EQUIPMENT
# ============================================================
@router.post("/{equipment_id}/retire", response_model=EquipmentResponse)
def retire_equipment(
    equipment_id: UUID,
    data: EquipmentRetireRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retire equipment (soft-delete). UEIC and historical data remain."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_edit")

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    equipment = EquipmentService.retire_equipment(
        db=db,
        equipment_id=equipment_id,
        reason=data.reason,
        modified_by=current_user.id,
    )
    db.commit()
    db.refresh(equipment)
    return _to_response(equipment)


# ============================================================
# REPLACE EQUIPMENT (retire old + register new)
# ============================================================
@router.post("/{equipment_id}/replace", status_code=status.HTTP_201_CREATED)
def replace_equipment(
    equipment_id: UUID,
    data: EquipmentReplaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retire old equipment and register a replacement. Returns both old and new."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_add")  # creating new equipment

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    old, new = EquipmentService.replace_equipment(
        db=db,
        old_equipment_id=equipment_id,
        reason=data.reason,
        created_by=current_user.id,
        nameplate_data=data.nameplate_data,
        commissioned_date=data.commissioned_date,
        manufacturer=data.manufacturer,
        model_number=data.model_number,
        factory_serial_number=data.factory_serial_number,
        year_of_manufacture=data.year_of_manufacture,
    )
    db.commit()
    db.refresh(old)
    db.refresh(new)
    return {
        "retired_equipment": _to_response(old),
        "new_equipment": _to_response(new),
    }


# ============================================================
# GET APPLICABLE TESTS FOR EQUIPMENT
# ============================================================
@router.get("/{equipment_id}/applicable-tests")
def get_applicable_tests(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get test types applicable to this equipment's type — for test request form dropdown."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    tests = EquipmentService.get_applicable_tests(db, equipment_id)
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category_type": t.category_type,
            "is_active": t.is_active,
        }
        for t in tests
    ]


# ============================================================
# GET DEPARTMENT ANCESTRY (auto-fill hierarchy for test request)
# ============================================================
@router.get("/{equipment_id}/location-hierarchy")
def get_equipment_location_hierarchy(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the full department hierarchy for an equipment's location — auto-fills zone, circle, division etc."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    if equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    ancestry = EquipmentService._get_department_ancestry_names(db, equipment.department_id)
    return {
        "equipment_id": str(equipment.id),
        "ueic": equipment.ueic,
        "department_id": str(equipment.department_id),
        "department_name": equipment.department.name if equipment.department else None,
        "hierarchy": ancestry,
    }


# ============================================================
# EQUIPMENT COUNTS (for dashboard)
# ============================================================
@router.get("/stats/counts", response_model=EquipmentCountResponse)
def get_equipment_counts(
    department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get equipment counts by status — for dashboard widgets. Scoped to user's organization."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    return EquipmentService.get_equipment_count(db, org_id, department_id)
