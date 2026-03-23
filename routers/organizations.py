"""
Organization management endpoints.
Provides CRUD operations for organizations.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from auth_utils import get_current_user
from middleware.org_auth import require_super_admin, require_org_admin, require_org_member
from models import User
from schemas import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationOut,
    OrganizationWithAdmin
)
from services.organization_service import OrganizationService


router = APIRouter(
    prefix="/organizations",
    tags=["organizations"]
)


@router.post("/", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    org_data: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Create a new organization.
    Only super admins can create organizations.
    """
    service = OrganizationService(db)
    return service.create_organization(org_data, created_by=current_user.id)


@router.post("/with-admin", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization_with_admin(
    data: OrganizationWithAdmin,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Create a new organization with an admin user.
    Auto-provisions default roles and assigns admin role to the user.
    Only super admins can create organizations.
    """
    service = OrganizationService(db)

    org, admin_user = service.create_organization_with_admin(
        name=data.organization.name,
        code=data.organization.code,
        admin_email=data.admin_email,
        admin_password=data.admin_password,
        admin_firstname=data.admin_firstname,
        admin_lastname=data.admin_lastname,
        admin_phone=data.admin_phone,
        display_name=data.organization.display_name,
        organization_type=data.organization.organization_type,
        industry=data.organization.industry,
        website=data.organization.website,
        primary_email=data.organization.primary_email,
        primary_phone=data.organization.primary_phone,
        plan_id=data.organization.plan_id,
        is_active=data.organization.is_active,
        settings=data.organization.settings or {}
    )

    return org


@router.get("/my-organization", response_model=OrganizationOut)
def get_my_organization(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the current user's organization.
    Returns the organization the user belongs to.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not assigned to any organization"
        )

    service = OrganizationService(db)
    org = service.get_organization(current_user.organization_id)

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return org


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get organization by ID.
    Users can only access their own organization unless they're super admin.
    """
    service = OrganizationService(db)
    return service.get_organization(org_id)


@router.get("/", response_model=List[OrganizationOut])
def list_organizations(
    skip: int = 0,
    limit: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List organizations.
    - Super admins: See all organizations
    - Org admins: See only their organization
    - UPDATED: Now allows org admins to view their own organization
    """
    # Debug logging
    with open("C:/Yesu/CustomerAPI/Customer-API/debug_org_list.txt", "a") as f:
        f.write(f"list_organizations called by {current_user.email}\n")
        f.write(f"organization_id: {current_user.organization_id}\n\n")
    service = OrganizationService(db)

    # Check if user is super admin (no organization_id)
    if current_user.organization_id is None:
        # Super admin - return all organizations
        return service.list_organizations(skip=skip, limit=limit, is_active=is_active)
    else:
        # Org admin - return only their organization
        org = service.get_organization(current_user.organization_id)
        if org:
            return [org]
        return []


@router.put("/{org_id}", response_model=OrganizationOut)
def update_organization(
    org_id: UUID,
    org_data: OrganizationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Update organization.
    Only org admins can update their organization.
    """
    service = OrganizationService(db)
    return service.update_organization(org_id, org_data, modified_by=current_user.id)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Soft delete organization.
    Only super admins can delete organizations.
    """
    service = OrganizationService(db)
    service.delete_organization(org_id)
    return None


@router.post("/{org_id}/verify", response_model=OrganizationOut)
def verify_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Verify an organization.
    Only super admins can verify organizations.
    """
    service = OrganizationService(db)
    return service.verify_organization(org_id, verified_by=current_user.id)


@router.get("/code/{code}", response_model=OrganizationOut)
def get_organization_by_code(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Get organization by code.
    Only super admins can search by code.
    """
    service = OrganizationService(db)
    org = service.get_organization_by_code(code)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization with code '{code}' not found"
        )
    return org
