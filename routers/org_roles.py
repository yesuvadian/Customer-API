"""
Organization role management endpoints.
Provides CRUD operations for roles and permissions within organizations.
"""

from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from middleware.org_auth import require_org_member, require_org_admin
from models import User
from schemas import (
    OrgRoleCreate,
    OrgRoleUpdate,
    OrgRoleOut,
    OrgRolePermissionOut,
    PermissionSet,
    BulkPermissionUpdate
)
from services.org_role_service import OrgRoleService


router = APIRouter(
    prefix="/organizations/{org_id}/roles",
    tags=["org-roles"]
)


@router.post("/", response_model=OrgRoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    org_id: UUID,
    role_data: OrgRoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Create a custom role for the organization.
    Only org admins can create roles.
    """
    # Ensure role is created in the correct org
    if role_data.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role organization_id must match the URL org_id"
        )

    service = OrgRoleService(db)
    return service.create_role(role_data, created_by=current_user.id)

@router.delete(
    "/organizations/{org_id}/users/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_user_role(
    org_id: UUID,
    user_id: UUID,
    role_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin),
):
    service = OrgRoleService(db)

    service.remove_role_from_user(
        organization_id=org_id,
        user_id=user_id,
        role_id=role_id,
        removed_by=current_user.id,
    )

    return None

@router.get("/", response_model=List[OrgRoleOut])
def list_roles(
    org_id: UUID,
    skip: int = 0,
    limit: Optional[int] = None,
    is_active: Optional[bool] = None,
    is_org_admin: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    List all roles in the organization.
    Any organization member can list roles.
    """
    service = OrgRoleService(db)
    return service.list_roles(
        organization_id=org_id,
        skip=skip,
        limit=limit,
        is_active=is_active,
        is_org_admin=is_org_admin
    )


@router.get("/{role_id}", response_model=OrgRoleOut)
def get_role(
    org_id: UUID,
    role_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get role details.
    Any organization member can view role details.
    """
    service = OrgRoleService(db)
    role = service.get_role(role_id)

    # Verify role belongs to the organization
    if role.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization"
        )

    return role


@router.put("/{role_id}", response_model=OrgRoleOut)
def update_role(
    org_id: UUID,
    role_id: UUID,
    role_data: OrgRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Update a role.
    Only org admins can update roles.
    """
    service = OrgRoleService(db)
    role = service.get_role(role_id)

    # Verify role belongs to the organization
    if role.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization"
        )

    return service.update_role(role_id, role_data, modified_by=current_user.id)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    org_id: UUID,
    role_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Soft delete a role.
    Only org admins can delete roles.
    Cannot delete default roles.
    """
    service = OrgRoleService(db)
    role = service.get_role(role_id)

    # Verify role belongs to the organization
    if role.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization"
        )

    service.delete_role(role_id)
    return None


@router.post("/{role_id}/permissions", response_model=List[OrgRolePermissionOut])
def set_role_permissions(
    org_id: UUID,
    role_id: UUID,
    permission_data: BulkPermissionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Set permissions for a role (replaces existing permissions).
    Only org admins can set permissions.
    """
    service = OrgRoleService(db)
    role = service.get_role(role_id)

    # Verify role belongs to the organization
    if role.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization"
        )

    return service.set_role_permissions(
        role_id=role_id,
        permissions=permission_data.permissions,
        created_by=current_user.id
    )


@router.get("/{role_id}/permissions", response_model=List[OrgRolePermissionOut])
def get_role_permissions(
    org_id: UUID,
    role_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get all permissions for a role.
    Any organization member can view role permissions.
    """
    service = OrgRoleService(db)
    role = service.get_role(role_id)

    # Verify role belongs to the organization
    if role.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization"
        )

    return service.get_role_permissions(role_id)


@router.put("/{role_id}/permissions/{module_id}", response_model=OrgRolePermissionOut)
def update_role_permission(
    org_id: UUID,
    role_id: UUID,
    module_id: int,
    permission_data: PermissionSet,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Update a specific module permission for a role.
    Only org admins can update permissions.
    """
    service = OrgRoleService(db)
    role = service.get_role(role_id)

    # Verify role belongs to the organization
    if role.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization"
        )

    permission_dict = {
        "can_view": permission_data.can_view,
        "can_add": permission_data.can_add,
        "can_edit": permission_data.can_edit,
        "can_delete": permission_data.can_delete,
        "can_approve": permission_data.can_approve,
        "can_assign": permission_data.can_assign,
        "can_export": permission_data.can_export,
        "can_import": permission_data.can_import
    }

    return service.update_role_permission(
        role_id=role_id,
        module_id=module_id,
        permission_data=permission_dict,
        modified_by=current_user.id
    )


@router.get("/name/{role_name}", response_model=OrgRoleOut)
def get_role_by_name(
    org_id: UUID,
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get role by name within the organization.
    Any organization member can search roles by name.
    """
    service = OrgRoleService(db)
    role = service.get_role_by_name(org_id, role_name)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role with name '{role_name}' not found in this organization"
        )

    return role


@router.get("/check-permission/{user_id}/{module_id}/{permission_type}", response_model=dict)
def check_user_permission(
    org_id: UUID,
    user_id: UUID,
    module_id: int,
    permission_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Check if a user has a specific permission.
    permission_type: can_view, can_add, can_edit, can_delete, can_approve, etc.
    """
    service = OrgRoleService(db)
    has_permission = service.check_user_permission(user_id, module_id, permission_type)

    return {
        "user_id": str(user_id),
        "module_id": module_id,
        "permission_type": permission_type,
        "has_permission": has_permission
    }


@router.get("/user-permissions/{user_id}", response_model=Dict[int, Dict[str, bool]])
def get_user_permissions(
    org_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get all permissions for a user across all their roles.
    Returns: {module_id: {permission_type: bool}}
    """
    service = OrgRoleService(db)
    return service.get_user_permissions(user_id)
