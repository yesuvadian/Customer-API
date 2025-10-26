# ----------------- UserRole Endpoints -----------------
from collections import defaultdict
from typing import List, Set
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from auth_utils import get_current_user
from database import get_db
from models import UserRole
from schemas import UserRoleCreate, UserRoleResponse, UserRoleUpdate, UserRolesBulkCreate
from services.userrole_service import UserRoleService

user_role_router = APIRouter(
    prefix="/user_roles",
    tags=["user_roles"],
    dependencies=[Depends(get_current_user)]
)

@user_role_router.post("/bulk", response_model=List[UserRoleResponse])
def assign_roles_bulk(
    bulk_data: UserRolesBulkCreate,
    db: Session = Depends(get_db),
):
    service = UserRoleService(db)
    results: List[UserRoleResponse] = []

    # Group users by role
    role_users_map = defaultdict(list)
    for assignment in bulk_data.assignments:
        role_users_map[assignment.role_id].append(assignment.user_id)

    # Update each role
    for role_id, user_ids in role_users_map.items():
        updated_roles = service.update_users_for_role(role_id, user_ids)
        results.extend(updated_roles)

    return results

# Create / Assign Role to User
@user_role_router.post("/", response_model=UserRoleResponse)
def assign_role(user_role: UserRoleCreate, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        return service.assign_role_to_user(user_id=user_role.user_id, role_id=user_role.role_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# Get a specific UserRole assignment
@user_role_router.get("/{user_role_id}", response_model=UserRoleResponse)
def get_user_role(user_role_id: int, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        return service.get_user_role(user_role_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# List roles by a specific user
@user_role_router.get("/user/{user_id}", response_model=List[UserRoleResponse])
def list_roles_by_user(user_id: UUID, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    return service.get_roles_by_user(user_id)

# List users by a specific role
@user_role_router.get("/role/{role_id}", response_model=List[UserRoleResponse])
def list_users_by_role(role_id: int, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    return service.get_users_by_role(role_id)

# Update a UserRole assignment
@user_role_router.put("/{user_role_id}", response_model=UserRoleResponse)
def update_user_role(user_role_id: int, user_role: UserRoleUpdate, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        return service.update_user_role(user_role_id, new_role_id=user_role.role_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# Delete / Unassign a UserRole
@user_role_router.delete("/{user_role_id}", response_model=dict)
def delete_user_role(user_role_id: int, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        service.unassign_role_from_user(user_role_id)
        return {"message": "User role unassigned successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@user_role_router.get("/", response_model=list)
def fetch_user_role_mappings(db: Session = Depends(get_db)):
    service = UserRoleService(db)
    return service.fetch_user_role_mappings()
