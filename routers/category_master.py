from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID

# Adjust imports based on your project structure
from database import get_db
from auth_utils import get_current_user 
# Assuming your User model has an .id attribute. Adjust if it's a dict.

from schemas import (
    CategoryMasterCreate, CategoryMasterUpdate, CategoryMasterResponse,
)
from services.category_master_service import CategoryMasterService

router = APIRouter(
    prefix="/category_master",
    tags=["category_master"],
    dependencies=[Depends(get_current_user)]
)

# ==========================================
#  CATEGORY MASTER ENDPOINTS
# ==========================================

@router.post("/masters", response_model=CategoryMasterResponse, status_code=status.HTTP_201_CREATED)
def create_category_master(
    category: CategoryMasterCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new Master Category"""
    return CategoryMasterService.create_master_category(
        db=db,
        name=category.name,
        description=category.description,
        created_by=current_user.id  # Auto-assign logged-in user
    )

@router.get("/masters", response_model=List[CategoryMasterResponse])
def list_category_masters(
    skip: int = 0, 
    limit: int = 100, 
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all Master Categories with optional search"""
    return CategoryMasterService.get_master_categories(
        db=db, 
        skip=skip, 
        limit=limit, 
        search=search
    )

@router.get("/masters/{master_id}", response_model=CategoryMasterResponse)
def get_category_master(master_id: int, db: Session = Depends(get_db)):
    """Get a specific Master Category by ID"""
    master = CategoryMasterService.get_master_category(db, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Category Master not found")
    return master

@router.patch("/masters/{master_id}", response_model=CategoryMasterResponse)
def update_category_master(
    master_id: int, 
    category_update: CategoryMasterUpdate, 
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update a Master Category"""
    # Convert Pydantic model to dict, excluding None values
    updates = category_update.dict(exclude_unset=True)
    
    # Add the modifier
    updates['modified_by'] = current_user.id
    
    return CategoryMasterService.update_master_category(
        db=db, 
        category_id=master_id, 
        updates=updates
    )

@router.delete("/masters/{master_id}", status_code=status.HTTP_200_OK)
def delete_category_master(master_id: int, db: Session = Depends(get_db)):
    """Delete a Master Category"""
    CategoryMasterService.delete_master_category(db, master_id)
    return {"message": "Category Master deleted successfully"}

