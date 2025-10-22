# ----------------- Role Endpoints -----------------
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from pytest import Session
from auth_utils import get_current_user
from database import get_db
from models import RoleModulePrivilege
from schemas import RoleCreate, RoleResponse, RoleUpdate, UserRoleCreate, UserRoleResponse, UserRoleUpdate
from services.role_service import RoleService
from services.userrole_service import UserRoleService
from uuid import UUID


router = APIRouter(prefix="/roles", tags=["roles"],dependencies=[Depends(get_current_user)])

@router.post("/", response_model=RoleResponse)
def create_role(role: RoleCreate, db: Session = Depends(get_db)):
    service = RoleService(db)
    try:
        return service.create_role(name=role.name, description=role.description, created_by=role.created_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: int, db: Session = Depends(get_db)):
    service = RoleService(db)
    try:
        return service.get_role(role_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/", response_model=List[RoleResponse])
def list_roles(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    service = RoleService(db)
    return service.list_roles(skip=skip, limit=limit)

@router.put("/{role_id}", response_model=RoleResponse)
def update_role(role_id: int, role: RoleUpdate, db: Session = Depends(get_db)):
    service = RoleService(db)
    try:
        return service.update_role(role_id, name=role.name, description=role.description, modified_by=role.modified_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{role_id}", response_model=dict)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    service = RoleService(db)
    try:
        service.delete_role(role_id)
        return {"message": "Role deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# ----------------- UserRole Endpoints -----------------
@router.post("/user-roles/", response_model=UserRoleResponse)
def assign_role(user_role: UserRoleCreate, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        return service.assign_role_to_user(user_id=user_role.user_id, role_id=user_role.role_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/user-roles/{user_role_id}", response_model=UserRoleResponse)
def get_user_role(user_role_id: int, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        return service.get_user_role(user_role_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/user-roles/user/{user_id}", response_model=List[UserRoleResponse])
def list_roles_by_user(user_id: UUID, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    return service.get_roles_by_user(user_id)

@router.get("/user-roles/role/{role_id}", response_model=List[UserRoleResponse])
def list_users_by_role(role_id: int, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    return service.get_users_by_role(role_id)

@router.put("/user-roles/{user_role_id}", response_model=UserRoleResponse)
def update_user_role(user_role_id: int, user_role: UserRoleUpdate, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        return service.update_user_role(user_role_id, new_role_id=user_role.role_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/user-roles/{user_role_id}", response_model=dict)
def delete_user_role(user_role_id: int, db: Session = Depends(get_db)):
    service = UserRoleService(db)
    try:
        service.unassign_role_from_user(user_role_id)
        return {"message": "User role unassigned successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{role_id}/privileges")
def assign_privileges(
    role_id: int,
    privileges: Dict[str, Dict[str, Any]],  # dynamic JSON body { "1": {"can_add": true, ...}, ... }
    db: Session = Depends(get_db)
):
    """
    Assign module privileges to a role.
    Keys are module IDs as strings, values are permission objects.
    """
    if not privileges:
        raise HTTPException(status_code=400, detail="No data provided")

    for mod_id_str, perms in privileges.items():
        try:
            module_id = int(mod_id_str)
        except ValueError:
            # Skip invalid module IDs
            continue

        existing = (
            db.query(RoleModulePrivilege)
            .filter_by(role_id=role_id, module_id=module_id)
            .first()
        )

        if not existing:
            existing = RoleModulePrivilege(role_id=role_id, module_id=module_id)
            db.add(existing)

        for key in [
            "can_view",
            "can_add",
            "can_edit",
            "can_delete",
            "can_search",
            "can_import",
            "can_export",
        ]:
            if key in perms:
                setattr(existing, key, perms[key])

    db.commit()
    return {"message": "Privileges updated"}