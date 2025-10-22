from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from auth_utils import get_current_user
from database import get_db
from models import RoleModulePrivilege
from services.rolemoduleprivilege_service import RoleModulePrivilegeService
#from services.role_module_privilege_service import RoleModulePrivilegeService

router = APIRouter(
    prefix="/role_module_privileges",
    tags=["Role Module Privileges"],dependencies=[Depends(get_current_user)]
)

# ----------------- CREATE -----------------
@router.post("/", response_model=dict)
def create_privilege(
    role_id: int,
    module_id: int,
    can_add: bool = False,
    can_edit: bool = False,
    can_delete: bool = False,
    can_search: bool = False,
    can_import: bool = False,
    can_export: bool = False,
    can_view: bool = False,
    created_by: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    service = RoleModulePrivilegeService(db)
    try:
        privilege = service.create_privilege(
            role_id=role_id,
            module_id=module_id,
            can_add=can_add,
            can_edit=can_edit,
            can_delete=can_delete,
            can_search=can_search,
            can_import=can_import,
            can_export=can_export,
            can_view=can_view,
            created_by=created_by
        )
        return {"message": "Privilege created successfully", "id": privilege.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------------- READ -----------------
@router.get("/{privilege_id}", response_model=dict)
def get_privilege(privilege_id: int, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    try:
        privilege = service.get_privilege(privilege_id)
        return privilege.__dict__
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/", response_model=List[dict])
def list_privileges(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    privileges = service.list_privileges(skip=skip, limit=limit)
    return [p.__dict__ for p in privileges]


@router.get("/by-role/{role_id}", response_model=List[dict])
def get_privileges_by_role(role_id: int, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    privileges = service.get_privileges_by_role(role_id)
    return [p.__dict__ for p in privileges]


@router.get("/by-module/{module_id}", response_model=List[dict])
def get_privileges_by_module(module_id: int, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    privileges = service.get_privileges_by_module(module_id)
    return [p.__dict__ for p in privileges]


# ----------------- UPDATE -----------------
@router.put("/{privilege_id}", response_model=dict)
def update_privilege(
    privilege_id: int,
    can_add: Optional[bool] = None,
    can_edit: Optional[bool] = None,
    can_delete: Optional[bool] = None,
    can_search: Optional[bool] = None,
    can_import: Optional[bool] = None,
    can_export: Optional[bool] = None,
    can_view: Optional[bool] = None,
    modified_by: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    service = RoleModulePrivilegeService(db)
    try:
        privilege = service.update_privilege(
            privilege_id=privilege_id,
            can_add=can_add,
            can_edit=can_edit,
            can_delete=can_delete,
            can_search=can_search,
            can_import=can_import,
            can_export=can_export,
            can_view=can_view,
            modified_by=modified_by
        )
        return {"message": "Privilege updated successfully", "id": privilege.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ----------------- DELETE -----------------
@router.delete("/{privilege_id}", response_model=dict)
def delete_privilege(privilege_id: int, db: Session = Depends(get_db)):
    service = RoleModulePrivilegeService(db)
    try:
        service.delete_privilege(privilege_id)
        return {"message": "Privilege deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
