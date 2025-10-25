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