"""
Organization-level authorization middleware and dependencies.
Provides functions to verify organization membership, admin roles, and department admin roles.
"""

from fastapi import Depends, HTTPException, status, Path
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from database import get_db
from auth_utils import get_current_user, check_active_billing, has_org_admin_role
from models import User, OrgUserRole, OrgRole, Organization


async def require_org_member(
    org_id: UUID = Path(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify that the current user belongs to the specified organization.
    Also runs the mid-session dept-level billing guard.
    Raises 403 if user doesn't belong to the organization or billing has lapsed.
    """
    if current_user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )
    org = db.query(Organization).filter_by(id=org_id).first()
    check_active_billing(current_user, org, db)
    return current_user


async def require_org_admin(
    org_id: UUID = Path(..., description="Organization ID"),
    current_user: User = Depends(require_org_member),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify that the current user has organization admin role.
    Must first verify org membership via require_org_member.
    """
    # Check if user has any org admin role
    if not has_org_admin_role(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin privileges required"
        )

    return current_user


async def require_dept_admin(
    org_id: UUID = Path(..., description="Organization ID"),
    dept_id: UUID = Path(..., description="Department ID"),
    current_user: User = Depends(require_org_member),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify that the current user has department admin role for the specified department.
    Also allows org admins to manage any department.
    """
    # Check if user is org admin (can manage any department)
    if has_org_admin_role(current_user, db):
        return current_user

    # Check if user has dept admin role for this specific department
    has_dept_admin = db.query(OrgUserRole)\
        .join(OrgRole)\
        .filter(
            OrgUserRole.user_id == current_user.id,
            OrgUserRole.department_id == dept_id,
            OrgRole.is_dept_admin == True,
            OrgUserRole.is_active == True,
            OrgRole.is_active == True
        )\
        .first()

    if not has_dept_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Department admin privileges required for this department"
        )

    return current_user


async def require_org_admin_or_dept_admin(
    org_id: UUID = Path(..., description="Organization ID"),
    current_user: User = Depends(require_org_member),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify that the current user has either org admin or dept admin role.
    """
    # Check if user has org admin or dept admin role
    has_admin_role = db.query(OrgUserRole)\
        .join(OrgRole)\
        .filter(
            OrgUserRole.user_id == current_user.id,
            (OrgRole.is_org_admin == True) | (OrgRole.is_dept_admin == True),
            OrgUserRole.is_active == True,
            OrgRole.is_active == True
        )\
        .first()

    if not has_admin_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin or department admin privileges required"
        )

    return current_user


async def require_super_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify that the current user is a super admin (system-level admin).
    This is typically for managing organizations themselves.

    Implementation note: You may want to add a is_super_admin flag to User model
    or check against a specific usertype.
    """
    # Check if user has super admin privileges
    # For now, checking if usertype is 'super_admin' or 'system_admin'
    if current_user.usertype not in ['super_admin', 'system_admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin privileges required"
        )

    return current_user


def check_org_permission(
    user_id: UUID,
    module_id: int,
    permission_type: str,
    db: Session
) -> bool:
    """
    Helper function to check if a user has a specific permission.
    permission_type: 'can_view', 'can_add', 'can_edit', 'can_delete', etc.
    """
    from models import OrgRolePermission

    # Get user's active roles
    user_roles = db.query(OrgUserRole).filter(
        OrgUserRole.user_id == user_id,
        OrgUserRole.is_active == True
    ).all()

    role_ids = [ur.org_role_id for ur in user_roles]

    if not role_ids:
        return False

    # Check if any role has the permission
    permissions = db.query(OrgRolePermission).filter(
        OrgRolePermission.org_role_id.in_(role_ids),
        OrgRolePermission.module_id == module_id
    ).all()

    # OR logic - if any role has permission, user has it
    for permission in permissions:
        if getattr(permission, permission_type, False):
            return True

    return False


def require_module_permission(module_id: int, permission_type: str):
    """
    Dependency factory to check module-level permissions.

    Usage:
        @router.get("/products", dependencies=[Depends(require_module_permission(1, "can_view"))])
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        # First check if user is org admin (has all permissions)
        if has_org_admin_role(current_user, db):
            return current_user

        # Check specific permission
        has_permission = check_org_permission(
            current_user.id,
            module_id,
            permission_type,
            db
        )

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission_type}' required for this module"
            )

        return current_user

    return permission_checker


async def get_user_organization(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Optional[UUID]:
    """
    Get the organization ID for the current user.
    Returns None if user is not part of any organization.
    """
    return current_user.organization_id


async def verify_same_organization(
    target_user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> bool:
    """
    Verify that a target user belongs to the same organization as current user.
    """
    target_user = db.query(User).filter(User.id == target_user_id).first()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found"
        )

    if target_user.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not in same organization"
        )

    return True
