from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, List

from auth_utils import get_current_user
from database import get_db
#from services.role_module_privilege_service import RoleModulePrivilegeService
from schemas import (
    RoleModulePrivilegeCreate,
    RoleModulePrivilegeUpdate,
    RoleModulePrivilegeResponse
)
from services.rolemoduleprivilege_service import RoleModulePrivilegeService

router = APIRouter(
    prefix="/role_module_privileges",
    tags=["Role Module Privileges"],dependencies=[Depends(get_current_user)]
)


@router.post("/", response_model=RoleModulePrivilegeResponse)
def create_privilege(
    payload: RoleModulePrivilegeCreate,
    db: Session = Depends(get_db)
):
    service = RoleModulePrivilegeService(db)
    try:
        privilege = service.create_privilege(**payload.model_dump())
        return privilege
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{privilege_id}", response_model=RoleModulePrivilegeResponse)
def get_privilege(privilege_id: int, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    privilege = service.get_privilege(privilege_id)
    if not privilege:
        raise HTTPException(status_code=404, detail="Privilege not found")
    return privilege


@router.get("/", response_model=List[RoleModulePrivilegeResponse])
def list_privileges(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    return service.list_privileges(skip=skip, limit=limit)


@router.put("/{privilege_id}", response_model=RoleModulePrivilegeResponse)
def update_privilege(
    privilege_id: int,
    payload: RoleModulePrivilegeUpdate,
    db: Session = Depends(get_db)
):
    service = RoleModulePrivilegeService(db)
    privilege = service.update_privilege(privilege_id, **payload.model_dump(exclude_unset=True))
    if not privilege:
        raise HTTPException(status_code=404, detail="Privilege not found")
    return privilege


@router.delete("/{privilege_id}", response_model=dict)
def delete_privilege(privilege_id: int, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    service.delete_privilege(privilege_id)
    return {"message": "Privilege deleted successfully"}

@router.post("/{role_id}/privileges", response_model=None)
def assign_role_privileges(
    role_id: int,
    payload: List[Dict] = Body(...),
    db: Session = Depends(get_db)
):
    service = RoleModulePrivilegeService(db)

    try:
        #db.begin()

        service.delete_privileges_by_role(role_id)

        for item in payload:
            item["role_id"] = role_id
            service.create_or_update_privilege(item)

        #db.commit()
        return {"message": "Privileges updated successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Failed to update privileges: {e}")
