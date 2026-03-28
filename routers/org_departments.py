"""
Organization department management endpoints.
Provides CRUD operations for departments within organizations.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from middleware.org_auth import require_org_member, require_org_admin, require_org_admin_or_dept_admin
from models import User
from schemas import (
    OrgDepartmentCreate,
    OrgDepartmentUpdate,
    OrgDepartmentOut,
    User as UserSchema
)
from services.org_department_service import OrgDepartmentService


router = APIRouter(
    prefix="/organizations/{org_id}/departments",
    tags=["org-departments"]
)


@router.post("/", response_model=OrgDepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    org_id: UUID,
    dept_data: OrgDepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin_or_dept_admin)
):
    """
    Create a department within the organization.
    Only org admins or department admins can create departments.
    """
    # Ensure department is created in the correct org
    if dept_data.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department organization_id must match the URL org_id"
        )

    service = OrgDepartmentService(db)
    return service.create_department(dept_data, created_by=current_user.id)


@router.get("/", response_model=List[OrgDepartmentOut])
def list_departments(
    org_id: UUID,
    skip: int = 0,
    limit: Optional[int] = None,
    is_active: Optional[bool] = None,
    parent_department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    List all departments in the organization.
    Any organization member can list departments.
    """
    service = OrgDepartmentService(db)
    return service.list_departments(
        organization_id=org_id,
        skip=skip,
        limit=limit,
        is_active=is_active,
        parent_department_id=parent_department_id
    )


@router.get("/{dept_id}", response_model=OrgDepartmentOut)
def get_department(
    org_id: UUID,
    dept_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get department details.
    Any organization member can view department details.
    """
    service = OrgDepartmentService(db)
    dept = service.get_department(dept_id)

    # Verify department belongs to the organization
    if dept.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found in this organization"
        )

    return dept


@router.put("/{dept_id}", response_model=OrgDepartmentOut)
def update_department(
    org_id: UUID,
    dept_id: UUID,
    dept_data: OrgDepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin_or_dept_admin)
):
    """
    Update department.
    Only org admins or department admins can update departments.
    """
    service = OrgDepartmentService(db)
    dept = service.get_department(dept_id)

    # Verify department belongs to the organization
    if dept.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found in this organization"
        )

    return service.update_department(dept_id, dept_data, modified_by=current_user.id)


@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    org_id: UUID,
    dept_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Soft delete department.
    Only org admins can delete departments.
    """
    service = OrgDepartmentService(db)
    dept = service.get_department(dept_id)

    # Verify department belongs to the organization
    if dept.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found in this organization"
        )

    service.delete_department(dept_id)
    return None


@router.post("/{dept_id}/users", response_model=dict)
def assign_users_to_department(
    org_id: UUID,
    dept_id: UUID,
    user_ids: List[UUID] = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin_or_dept_admin)
):
    """
    Assign multiple users to a department.
    Only org admins or department admins can assign users.
    """
    service = OrgDepartmentService(db)
    dept = service.get_department(dept_id)

    # Verify department belongs to the organization
    if dept.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found in this organization"
        )

    count = service.assign_users_to_department(dept_id, user_ids)
    return {
        "message": f"Successfully assigned {count} user(s) to department",
        "count": count
    }


@router.get("/{dept_id}/users", response_model=List[UserSchema])
def get_department_users(
    org_id: UUID,
    dept_id: UUID,
    skip: int = 0,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get all users in a department.
    Any organization member can view department users.
    """
    service = OrgDepartmentService(db)
    dept = service.get_department(dept_id)

    # Verify department belongs to the organization
    if dept.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found in this organization"
        )

    return service.get_department_users(dept_id, skip=skip, limit=limit)
