"""
Organization user management endpoints.
Provides CRUD operations for users within organizations.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from middleware.org_auth import require_org_member, require_org_admin
from models import User
from schemas import (
    OrgUserCreate,
    OrgUserUpdate,
    User as UserOut,
    RoleAssignment,
    OrgUserRoleOut,
    OrgUserWithRoles
)
from services.org_user_service import OrgUserService


router = APIRouter(
    prefix="/organizations/{org_id}/users",
    tags=["org-users"]
)


@router.post("/", response_model=OrgUserWithRoles, status_code=status.HTTP_201_CREATED)
def create_org_user(
    org_id: UUID,
    user_data: OrgUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Create a new user within the organization.
    Only org admins can create users.
    Auto-assigns to specified department and roles if provided.
    """
    service = OrgUserService(db)
    user = service.create_org_user(
        organization_id=org_id,
        user_data=user_data,
        created_by=current_user.id
    )
    # Convert to OrgUserWithRoles
    users_with_roles = service.list_org_users_with_roles(
        organization_id=org_id,
        search=user.email
    )
    return users_with_roles[0] if users_with_roles else user


@router.get("/", response_model=List[OrgUserWithRoles])
def list_org_users(
    org_id: UUID,
    department_id: Optional[UUID] = None,
    skip: int = 0,
    limit: Optional[int] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    List users in the organization with their roles.
    Optionally filter by department, active status, or search term.
    """
    service = OrgUserService(db)
    return service.list_org_users_with_roles(
        organization_id=org_id,
        department_id=department_id,
        skip=skip,
        limit=limit,
        is_active=is_active,
        search=search
    )


@router.get("/{user_id}", response_model=OrgUserWithRoles)
def get_org_user(
    org_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get user details with roles.
    Any organization member can view other members.
    """
    service = OrgUserService(db)
    return service.get_org_user_with_roles(user_id, org_id)


@router.put("/{user_id}", response_model=OrgUserWithRoles)
def update_org_user(
    org_id: UUID,
    user_id: UUID,
    user_data: OrgUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Update user in organization.
    Only org admins can update users.
    """
    service = OrgUserService(db)
    service.update_org_user(
        user_id=user_id,
        organization_id=org_id,
        user_data=user_data,
        modified_by=current_user.id
    )
    # Return user with roles
    return service.get_org_user_with_roles(user_id, org_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_user(
    org_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Soft delete user in organization.
    Only org admins can delete users.
    """
    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    service = OrgUserService(db)
    service.delete_org_user(user_id, org_id)
    return None


@router.post("/{user_id}/roles", response_model=OrgUserRoleOut, status_code=status.HTTP_201_CREATED)
def assign_role_to_user(
    org_id: UUID,
    user_id: UUID,
    role_assignment: RoleAssignment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Assign a role to a user within the organization.
    Only org admins can assign roles.
    """
    service = OrgUserService(db)
    return service.assign_role_to_user(
        user_id=user_id,
        organization_id=org_id,
        org_role_id=role_assignment.org_role_id,
        department_id=role_assignment.department_id,
        assigned_by=current_user.id
    )


@router.delete("/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_role_from_user(
    org_id: UUID,
    user_id: UUID,
    role_id: UUID,
    department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Remove a role from a user.
    Only org admins can remove roles.
    """
    service = OrgUserService(db)
    service.remove_role_from_user(
        user_id=user_id,
        organization_id=org_id,
        org_role_id=role_id,
        department_id=department_id
    )
    return None


@router.get("/{user_id}/roles", response_model=List[OrgUserRoleOut])
def get_user_roles(
    org_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get all roles assigned to a user.
    Any organization member can view user roles.
    """
    service = OrgUserService(db)
    return service.get_user_roles(user_id, org_id)


@router.get("/me", response_model=OrgUserWithRoles)
def get_current_org_user(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get current user's information with roles.
    """
    service = OrgUserService(db)
    return service.get_org_user_with_roles(current_user.id, org_id)
