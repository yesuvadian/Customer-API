from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from services.module_service import ModuleService
from auth_utils import get_current_user
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(
    prefix="/modules",
    tags=["modules"],
    dependencies=[Depends(get_current_user)]
)

# ---------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------

class ModuleCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    path: Optional[str] = None
    group_name: Optional[str] = None


class ModuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    group_name: Optional[str] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True     # Pydantic v2 equivalent of orm_mode


# ---------------------------------------------------------
# GET MODULE LIST
# ---------------------------------------------------------
@router.get("/", response_model=List[dict])
async def list_modules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    is_active: Optional[str] = Query(None, description="false → fetch all modules"),
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None
):
    """
    - Vendor / Normal User → Only modules they are allowed to VIEW
    - Admin → is_active=false → full list (active + inactive)
              is_active=true  → only active
    """
    try:
        # Default: active only
        active_only = True
        if is_active is not None and is_active.lower() in ("false", "0", "no"):
            active_only = False

        # If active_only → filter by privileges (vendor or admin UI)
        if active_only:
            modules = ModuleService.get_modules_for_user(db, current_user.id)

        else:
            # Admin fetching full list
            modules = ModuleService.get_modules(
                db=db,
                skip=skip,
                limit=limit,
                search=search,
                active_only=False
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


# ---------------------------------------------------------
# CREATE MODULE
# ---------------------------------------------------------
@router.post("/")
async def create_module(
    body: ModuleCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        return ModuleService.create_module(db, body.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------
# UPDATE MODULE
# ---------------------------------------------------------
@router.put("/{module_id}")
async def update_module(
    module_id: int,
    body: ModuleUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        updated = ModuleService.update_module(
            db, module_id, body.model_dump(exclude_unset=True)
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Module not found")

        return updated

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------
# DELETE MODULE
# ---------------------------------------------------------
@router.delete("/{module_id}")
async def delete_module(
    module_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        deleted = ModuleService.delete_module(db, module_id)
        return {"detail": "Module deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------
# GET MODULES FOR USER (Sidebar Menu)
# ---------------------------------------------------------
@router.get("/user", response_model=List[dict])
async def list_user_modules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Returns ONLY modules where this user has can_view = True.
    Used for Vendor Sidebar.
    """
    modules = ModuleService.get_modules_for_user(db, current_user.id)

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
