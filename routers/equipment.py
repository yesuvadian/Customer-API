"""
Equipment Asset Register Router
CRUD for equipment units with UEIC auto-generation, linked to OrgDepartment hierarchy.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from auth_utils import get_current_user
from models import Equipment
from schemas import (
    EquipmentCreate,
    EquipmentUpdate,
    EquipmentResponse,
    EquipmentRetireRequest,
    EquipmentReplaceRequest,
    EquipmentCountResponse,
)
from services.equipment_service import EquipmentService

router = APIRouter(
    prefix="/equipment",
    tags=["equipment"],
    dependencies=[Depends(get_current_user)]
)


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
    current_user=Depends(get_current_user),
):
    """Register a new equipment unit. UEIC is auto-generated."""
    equipment = EquipmentService.create_equipment(
        db=db,
        organization_id=data.organization_id,
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
    return _to_response(equipment)


# ============================================================
# LIST EQUIPMENT (with filters)
# ============================================================
@router.get("/", response_model=List[EquipmentResponse])
def list_equipment(
    organization_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    equipment_type_id: Optional[int] = None,
    status: Optional[str] = None,
    voltage_class: Optional[str] = None,
    manufacturer: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List equipment with optional filters. Use department_id to get equipment at a substation."""
    items = EquipmentService.list_equipment(
        db=db,
        organization_id=organization_id,
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
    current_user=Depends(get_current_user),
):
    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return _to_response(equipment)


# ============================================================
# GET EQUIPMENT BY UEIC
# ============================================================
@router.get("/by-ueic/{ueic}", response_model=EquipmentResponse)
def get_equipment_by_ueic(
    ueic: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    equipment = EquipmentService.get_equipment_by_ueic(db, ueic)
    if not equipment:
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
    current_user=Depends(get_current_user),
):
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
    current_user=Depends(get_current_user),
):
    """Retire equipment (soft-delete). UEIC and historical data remain."""
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
    current_user=Depends(get_current_user),
):
    """Retire old equipment and register a replacement. Returns both old and new."""
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
    current_user=Depends(get_current_user),
):
    """Get test types applicable to this equipment's type — for test request form dropdown."""
    tests = EquipmentService.get_applicable_tests(db, equipment_id)
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
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
    current_user=Depends(get_current_user),
):
    """Get the full department hierarchy for an equipment's location — auto-fills zone, circle, division etc."""
    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment:
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
    organization_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get equipment counts by status — for dashboard widgets."""
    return EquipmentService.get_equipment_count(db, organization_id, department_id)
