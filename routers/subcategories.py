from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from services.subcategory_service import SubCategoryService
from schemas import ProductSubCategorySchema  # <-- use Pydantic schema

router = APIRouter(prefix="/subcategories", tags=["subcategories"])

@router.get("/", response_model=list[ProductSubCategorySchema])
def list_subcategories(skip: int = 0, limit: int = 100, search: str | None = None, db: Session = Depends(get_db)):
    return SubCategoryService.get_subcategories(db, skip, limit, search)

@router.get("/{subcategory_id}", response_model=ProductSubCategorySchema)
def get_subcategory(subcategory_id: int, db: Session = Depends(get_db)):
    sub = SubCategoryService.get_subcategory(db, subcategory_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subcategory not found")
    return sub

@router.get("/by_category/{category_id}", response_model=list[ProductSubCategorySchema])
def get_by_category(category_id: int, db: Session = Depends(get_db)):
    return SubCategoryService.get_by_category(db, category_id)

@router.post("/", response_model=ProductSubCategorySchema)
def create_subcategory(name: str, category_id: int, description: str | None = None, db: Session = Depends(get_db)):
    return SubCategoryService.create_subcategory(db, name, category_id, description)

@router.put("/{subcategory_id}", response_model=ProductSubCategorySchema)
def update_subcategory(subcategory_id: int, updates: dict, db: Session = Depends(get_db)):
    return SubCategoryService.update_subcategory(db, subcategory_id, updates)

@router.delete("/{subcategory_id}", response_model=ProductSubCategorySchema)
def delete_subcategory(subcategory_id: int, db: Session = Depends(get_db)):
    return SubCategoryService.delete_subcategory(db, subcategory_id)
