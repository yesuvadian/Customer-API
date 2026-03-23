"""
Admin API for managing tester role module requirements.
Allows admins to configure which modules are required for tester role selection.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel

from database import get_db
from models import User, TesterRoleModuleRequirement, Organization, Module
from auth_utils import get_current_user

router = APIRouter(
    prefix="/admin/tester-role-config",
    tags=["Admin - Tester Configuration"],
    dependencies=[Depends(get_current_user)]
)


class TesterRoleConfigCreate(BaseModel):
    organization_id: Optional[UUID] = None
    required_module_ids: List[int]
    description: Optional[str] = None


class TesterRoleConfigUpdate(BaseModel):
    required_module_ids: Optional[List[int]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TesterRoleConfigResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID]
    organization_name: Optional[str]
    required_module_ids: List[int]
    module_names: List[str]
    description: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[TesterRoleConfigResponse])
def list_tester_role_configs(
    organization_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all tester role module requirement configurations.

    Query params:
    - organization_id: Filter by specific organization (omit to see all including global)
    """
    query = db.query(TesterRoleModuleRequirement)

    if organization_id is not None:
        query = query.filter(TesterRoleModuleRequirement.organization_id == organization_id)

    configs = query.order_by(
        TesterRoleModuleRequirement.organization_id.asc().nullsfirst()
    ).all()

    # Enrich with organization and module names
    result = []
    for config in configs:
        # Get organization name
        org_name = None
        if config.organization_id:
            org = db.query(Organization).filter(Organization.id == config.organization_id).first()
            org_name = org.name if org else "Unknown"
        else:
            org_name = "Global Default"

        # Get module names
        modules = db.query(Module).filter(Module.id.in_(config.required_module_ids)).all()
        module_names = [m.name for m in modules]

        result.append(TesterRoleConfigResponse(
            id=config.id,
            organization_id=config.organization_id,
            organization_name=org_name,
            required_module_ids=config.required_module_ids,
            module_names=module_names,
            description=config.description,
            is_active=config.is_active
        ))

    return result


@router.get("/{config_id}", response_model=TesterRoleConfigResponse)
def get_tester_role_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get specific tester role configuration by ID."""
    config = db.query(TesterRoleModuleRequirement).filter(
        TesterRoleModuleRequirement.id == config_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration not found"
        )

    # Get organization name
    org_name = None
    if config.organization_id:
        org = db.query(Organization).filter(Organization.id == config.organization_id).first()
        org_name = org.name if org else "Unknown"
    else:
        org_name = "Global Default"

    # Get module names
    modules = db.query(Module).filter(Module.id.in_(config.required_module_ids)).all()
    module_names = [m.name for m in modules]

    return TesterRoleConfigResponse(
        id=config.id,
        organization_id=config.organization_id,
        organization_name=org_name,
        required_module_ids=config.required_module_ids,
        module_names=module_names,
        description=config.description,
        is_active=config.is_active
    )


@router.post("/", response_model=TesterRoleConfigResponse, status_code=status.HTTP_201_CREATED)
def create_tester_role_config(
    data: TesterRoleConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create new tester role module requirement configuration.

    Body:
    - organization_id: NULL for global default, or specific org UUID
    - required_module_ids: Array of module IDs (e.g., [45, 46, 49, 51])
    - description: Optional description
    """
    # Check if config already exists for this organization
    existing = db.query(TesterRoleModuleRequirement).filter(
        TesterRoleModuleRequirement.organization_id == data.organization_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Configuration already exists for this organization (ID: {existing.id})"
        )

    # Validate module IDs exist
    modules = db.query(Module).filter(Module.id.in_(data.required_module_ids)).all()
    if len(modules) != len(data.required_module_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more module IDs are invalid"
        )

    # Create configuration
    config = TesterRoleModuleRequirement(
        organization_id=data.organization_id,
        required_module_ids=data.required_module_ids,
        description=data.description,
        is_active=True,
        created_by=current_user.id
    )

    db.add(config)
    db.commit()
    db.refresh(config)

    # Build response
    org_name = "Global Default"
    if config.organization_id:
        org = db.query(Organization).filter(Organization.id == config.organization_id).first()
        org_name = org.name if org else "Unknown"

    module_names = [m.name for m in modules]

    return TesterRoleConfigResponse(
        id=config.id,
        organization_id=config.organization_id,
        organization_name=org_name,
        required_module_ids=config.required_module_ids,
        module_names=module_names,
        description=config.description,
        is_active=config.is_active
    )


@router.put("/{config_id}", response_model=TesterRoleConfigResponse)
def update_tester_role_config(
    config_id: UUID,
    data: TesterRoleConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update tester role module requirements.
    Use this to change which modules are required for tester role selection.
    """
    config = db.query(TesterRoleModuleRequirement).filter(
        TesterRoleModuleRequirement.id == config_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration not found"
        )

    # Update fields
    if data.required_module_ids is not None:
        # Validate module IDs
        modules = db.query(Module).filter(Module.id.in_(data.required_module_ids)).all()
        if len(modules) != len(data.required_module_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more module IDs are invalid"
            )
        config.required_module_ids = data.required_module_ids

    if data.description is not None:
        config.description = data.description

    if data.is_active is not None:
        config.is_active = data.is_active

    config.modified_by = current_user.id

    db.commit()
    db.refresh(config)

    # Build response
    org_name = "Global Default"
    if config.organization_id:
        org = db.query(Organization).filter(Organization.id == config.organization_id).first()
        org_name = org.name if org else "Unknown"

    modules = db.query(Module).filter(Module.id.in_(config.required_module_ids)).all()
    module_names = [m.name for m in modules]

    return TesterRoleConfigResponse(
        id=config.id,
        organization_id=config.organization_id,
        organization_name=org_name,
        required_module_ids=config.required_module_ids,
        module_names=module_names,
        description=config.description,
        is_active=config.is_active
    )


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tester_role_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Soft delete (deactivate) tester role configuration.
    """
    config = db.query(TesterRoleModuleRequirement).filter(
        TesterRoleModuleRequirement.id == config_id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration not found"
        )

    config.is_active = False
    config.modified_by = current_user.id

    db.commit()
    return None
