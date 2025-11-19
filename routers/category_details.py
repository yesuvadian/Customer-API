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
    CategoryDetailsCreate, CategoryDetailsUpdate, CategoryDetailsResponse
)
from services.category_service import CategoryMasterService, CategoryDetailsService

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(get_current_user)]
)


@router.post("/details", response_model=CategoryDetailsResponse, status_code=status.HTTP_201_CREATED)
def create_category_detail(
    detail: CategoryDetailsCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new Category Detail linked to a Master"""
    return CategoryDetailsService.create_category_detail(
        db=db,
        master_id=detail.category_master_id,
        name=detail.name,
        description=detail.description,
        created_by=current_user.id
    )

@router.get("/details", response_model=List[CategoryDetailsResponse])
def list_category_details(
    skip: int = 0, 
    limit: int = 100, 
    search: Optional[str] = None,
    master_id: Optional[int] = None, # Filter details by their parent master
    db: Session = Depends(get_db)
):
    """List details. Optional: Filter by Master ID"""
    return CategoryDetailsService.get_category_details(
        db=db, 
        skip=skip, 
        limit=limit, 
        search=search,
        master_id=master_id
    )

@router.get("/details/{detail_id}", response_model=CategoryDetailsResponse)
def get_category_detail(detail_id: int, db: Session = Depends(get_db)):
    """Get a specific Category Detail"""
    detail = CategoryDetailsService.get_category_detail(db, detail_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Category Detail not found")
    return detail

@router.patch("/details/{detail_id}", response_model=CategoryDetailsResponse)
def update_category_detail(
    detail_id: int, 
    detail_update: CategoryDetailsUpdate, 
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update a Category Detail"""
    updates = detail_update.dict(exclude_unset=True)
    updates['modified_by'] = current_user.id
    
    return CategoryDetailsService.update_category_detail(
        db=db, 
        detail_id=detail_id, 
        updates=updates
    )

@router.delete("/details/{detail_id}", status_code=status.HTTP_200_OK)
def delete_category_detail(detail_id: int, db: Session = Depends(get_db)):
    """Delete a Category Detail"""
    CategoryDetailsService.delete_category_detail(db, detail_id)
    return {"message": "Category Detail deleted successfully"}