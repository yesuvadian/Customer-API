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

# ==========================================
#  CATEGORY MASTER ENDPOINTS
# ==========================================

@router.post("/", response_model=CategoryMasterResponse, status_code=status.HTTP_201_CREATED)
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

@router.get("/", response_model=List[CategoryMasterResponse])
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

@router.get("/{master_id}", response_model=CategoryMasterResponse)
def get_category_master(master_id: int, db: Session = Depends(get_db)):
    """Get a specific Master Category by ID"""
    master = CategoryMasterService.get_master_category(db, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Category Master not found")
    return master

@router.patch("/{master_id}", response_model=CategoryMasterResponse)
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
@router.get("/{master_name}/details", response_model=List[CategoryDetailsResponse])
def get_details_by_master_name(
    master_name: str = Query(..., description="The name of the Category Master (e.g., 'Company Documents')"),
    db: Session = Depends(get_db)
):
    """
    Retrieves all Category Details associated with a specific Category Master name.
    """
    details = CategoryMasterService.get_details_by_master_name(db, master_name)
    
    if details is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category Master '{master_name}' not found."
        )
    
    # Check if the master was found but had no details
    if not details:
         return [] # Return an empty list if no details found but master exists

    return details

# --- Existing endpoints follow ---
# @router.post("/details", ...)
# @router.get("/details", ...)
# ...
@router.delete("/{master_id}", status_code=status.HTTP_200_OK)
def delete_category_master(master_id: int, db: Session = Depends(get_db)):
    """Delete a Master Category"""
    CategoryMasterService.delete_master_category(db, master_id)
    return {"message": "Category Master deleted successfully"}