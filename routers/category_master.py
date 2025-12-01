from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from auth_utils import get_current_user

from schemas import (
    CategoryMasterCreate,
    CategoryMasterUpdate,
    CategoryMasterResponse,
)
from services.category_master_service import CategoryMasterService
from models import CategoryMaster, CategoryDetails

router = APIRouter(
    prefix="/category_master",
    tags=["category_master"],
    dependencies=[Depends(get_current_user)]
)

# ============================================================
# CREATE MASTER CATEGORY
# ============================================================
@router.post(
    "/masters",
    response_model=CategoryMasterResponse,
    status_code=status.HTTP_201_CREATED
)
def create_category_master(
    category: CategoryMasterCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return CategoryMasterService.create_master_category(
        db=db,
        name=category.name,
        description=category.description,
        created_by=current_user.id
    )

# ============================================================
# LIST MASTER CATEGORIES
# ============================================================
@router.get(
    "/masters",
    response_model=List[CategoryMasterResponse]
)
def list_category_masters(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return CategoryMasterService.get_master_categories(
        db=db,
        skip=skip,
        limit=limit,
        search=search
    )

# ============================================================
# GET SINGLE MASTER CATEGORY
# ============================================================
@router.get(
    "/masters/{master_id}",
    response_model=CategoryMasterResponse
)
def get_category_master(master_id: int, db: Session = Depends(get_db)):
    master = CategoryMasterService.get_master_category(db, master_id)
    if not master:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category Master not found"
        )
    return master

# ============================================================
# UPDATE MASTER CATEGORY
# ============================================================
@router.put(
    "/masters/{master_id}",
    response_model=CategoryMasterResponse
)
def update_category_master(
    master_id: int,
    category_update: CategoryMasterUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    updates = category_update.dict(exclude_unset=True)
    updates["modified_by"] = current_user.id

    return CategoryMasterService.update_master_category(
        db=db,
        category_id=master_id,
        updates=updates
    )

# ============================================================
# DELETE MASTER CATEGORY
# ============================================================
@router.delete(
    "/masters/{master_id}",
    status_code=status.HTTP_200_OK
)
def delete_category_master(
    master_id: int,
    db: Session = Depends(get_db)
):
    # Check if master category has children
    has_children = db.query(CategoryDetails).filter(CategoryDetails.master.has(id=master_id)).first()
    if has_children:
        return {"status": "warning", "message": "Cannot delete category master: it has child categories"}

    # Proceed to delete
    master = db.query(CategoryMaster).filter(CategoryMaster.id == master_id).first()
    if not master:
        raise HTTPException(status_code=404, detail="Category master not found")

    db.delete(master)
    db.commit()
    return {"status": "success", "message": "Category deleted successfully"}
