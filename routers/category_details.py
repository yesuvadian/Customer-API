from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# Adjust imports based on your project structure
from database import get_db
from auth_utils import get_current_user
from schemas import (
    CategoryDetailsCreate, CategoryDetailsUpdate, CategoryDetailsResponse
)
from services.category_details_service import CategoryDetailsService

router = APIRouter(
    prefix="/category_details",
    tags=["category_details"],
    dependencies=[Depends(get_current_user)]
)

# ---------------------------
# GET DETAILS BY MASTER NAME
# ---------------------------
@router.get("/details/by-master/{master_name}", response_model=List[CategoryDetailsResponse])
def get_details_by_master_name(
    master_name: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Get Category Details using Master Name (exact match)
    master_name → master_id → details
    """
    details = CategoryDetailsService.get_category_details_by_master_name(
        db=db,
        master_name=master_name,
        skip=skip,
        limit=limit
    )

    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No details found for master name: {master_name}"
        )

    return details

# ---------------------------
# CREATE CATEGORY DETAIL
# ---------------------------
@router.post(
    "/details",
    response_model=CategoryDetailsResponse,
    status_code=status.HTTP_201_CREATED
)
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
        is_active=detail.is_active,   # ✅ ADD
        created_by=current_user.id
    )

# ---------------------------
# LIST CATEGORY DETAILS
# ---------------------------
@router.get("/details", response_model=List[CategoryDetailsResponse])
def list_category_details(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    master_id: Optional[int] = None,
    is_active: Optional[bool] = None,   # ✅ ADD
    db: Session = Depends(get_db)
):
    """List Category Details. Optional filter by Master ID & is_active"""
    return CategoryDetailsService.get_category_details(
        db=db,
        skip=skip,
        limit=limit,
        search=search,
        master_id=master_id,
        is_active=is_active               # ✅ PASS
    )

# ---------------------------
# GET SINGLE CATEGORY DETAIL
# ---------------------------
@router.get("/details/{detail_id}", response_model=CategoryDetailsResponse)
def get_category_detail(detail_id: int, db: Session = Depends(get_db)):
    """Get a specific Category Detail by ID"""
    detail = CategoryDetailsService.get_category_detail(db, detail_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Detail not found")
    return detail

# ---------------------------
# UPDATE CATEGORY DETAIL
# ---------------------------
@router.put("/details/{detail_id}", response_model=CategoryDetailsResponse)
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

# ---------------------------
# DELETE CATEGORY DETAIL
# ---------------------------
@router.delete("/details/{detail_id}", status_code=status.HTTP_200_OK)
def delete_category_detail(detail_id: int, db: Session = Depends(get_db)):
    """
    Delete a Category Detail by ID.
    Returns 404 if not found or 500 if deletion fails.
    """
    return CategoryDetailsService.delete_category_detail(db=db, detail_id=detail_id)
