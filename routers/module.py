from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Module
from services.module_service import ModuleService
from auth_utils import get_current_user
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/modules", tags=["modules"])

class ModuleCreateRequest(BaseModel):
    name: str
    description: Optional[str]
    path: Optional[str]
    group_name: Optional[str]

class ModuleUpdateRequest(BaseModel):
    description: Optional[str]
    path: Optional[str]
    group_name: Optional[str]

@router.get("/", response_model=List[dict])
async def list_modules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    is_active: Optional[str] = Query(None, description="Fetch all if false/0/no, otherwise only active"),
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None
):
    """
    List modules with optional search and active-only filtering.
    """
    try:
        # Determine if only active modules should be returned
        active_only = True
        if is_active is not None and is_active.lower() in ["false", "0", "no"]:
            active_only = False

        modules = ModuleService.get_modules(
            db=db,
            skip=skip,
            limit=limit,
            search=search,
            active_only=active_only
        )

        return [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
                "path": m.path,
                "group_name": m.group_name,
                "is_active": m.is_active
            }
            for m in modules
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def create_module(
    body: ModuleCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        return ModuleService.create_module(db, body.dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{module_id}")
async def update_module(
    module_id: int,
    body: ModuleUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        updated = ModuleService.update_module(db, module_id, body.dict(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Module not found")
        return updated
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{module_id}")
async def delete_module(
    module_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        deleted = ModuleService.delete_module(db, module_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Module not found")
        return {"detail": "Module deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))