"""
Router: /equipment-type-kit-mappings

Admin CRUD for mapping which testing kit types are required/optional
per equipment type. Used by Kit Manager role.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import CategoryDetails, CategoryMaster, EquipmentTypeKitMapping, User

router = APIRouter(
    prefix="/equipment-type-kit-mappings",
    tags=["equipment-type-kit-mappings"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class KitMappingCreate(BaseModel):
    equipment_type_id: int
    kit_type_id: int
    is_required: bool = True
    notes: Optional[str] = None


class KitMappingResponse(BaseModel):
    id: int
    equipment_type_id: int
    equipment_type_name: str
    kit_type_id: int
    kit_type_name: str
    is_required: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(m: EquipmentTypeKitMapping) -> KitMappingResponse:
    return KitMappingResponse(
        id=m.id,
        equipment_type_id=m.equipment_type_id,
        equipment_type_name=m.equipment_type.name if m.equipment_type else "",
        kit_type_id=m.kit_type_id,
        kit_type_name=m.kit_type.name if m.kit_type else "",
        is_required=m.is_required,
        notes=m.notes,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[KitMappingResponse])
def list_mappings(
    equipment_type_id: Optional[int] = Query(None, description="Filter by equipment type"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(EquipmentTypeKitMapping)
    if equipment_type_id:
        q = q.filter(EquipmentTypeKitMapping.equipment_type_id == equipment_type_id)
    return [_to_response(m) for m in q.all()]


@router.post("/", response_model=KitMappingResponse, status_code=status.HTTP_201_CREATED)
def create_mapping(
    payload: KitMappingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate equipment_type_id against CategoryMaster, kit_type_id against CategoryDetails
    if not db.query(CategoryMaster).filter(CategoryMaster.id == payload.equipment_type_id).first():
        raise HTTPException(status_code=404, detail="equipment_type_id not found")
    if not db.query(CategoryDetails).filter(CategoryDetails.id == payload.kit_type_id).first():
        raise HTTPException(status_code=404, detail="kit_type_id not found")

    existing = db.query(EquipmentTypeKitMapping).filter(
        EquipmentTypeKitMapping.equipment_type_id == payload.equipment_type_id,
        EquipmentTypeKitMapping.kit_type_id == payload.kit_type_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Mapping already exists")

    mapping = EquipmentTypeKitMapping(
        equipment_type_id=payload.equipment_type_id,
        kit_type_id=payload.kit_type_id,
        is_required=payload.is_required,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return _to_response(mapping)


@router.patch("/{mapping_id}", response_model=KitMappingResponse)
def update_mapping(
    mapping_id: int,
    is_required: Optional[bool] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    mapping = db.query(EquipmentTypeKitMapping).filter(
        EquipmentTypeKitMapping.id == mapping_id
    ).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    if is_required is not None:
        mapping.is_required = is_required
    if notes is not None:
        mapping.notes = notes
    db.commit()
    db.refresh(mapping)
    return _to_response(mapping)


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    mapping = db.query(EquipmentTypeKitMapping).filter(
        EquipmentTypeKitMapping.id == mapping_id
    ).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(mapping)
    db.commit()
