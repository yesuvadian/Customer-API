from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.category_service import CategoryService
from schemas import ProductCategorySchema  # <-- use the Pydantic model
from pydantic import BaseModel

class ProductCategoryCreate(BaseModel):
    name: str
    description: str | None = None


router = APIRouter(prefix="/categories", tags=["categories"],dependencies=[Depends(get_current_user)])

@router.get("/", response_model=list[ProductCategorySchema])
def list_categories(skip: int = 0, limit: int = 10000, search: str | None = None, db: Session = Depends(get_db)):
    return CategoryService.get_categories(db, skip, limit, search)

@router.get("/{category_id}", response_model=ProductCategorySchema)
def get_category(category_id: int, db: Session = Depends(get_db)):
    category = CategoryService.get_category(db, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category

@router.post("/", response_model=ProductCategorySchema)
def create_category(category_in: ProductCategoryCreate, db: Session = Depends(get_db)):
    return CategoryService.create_category(
        db,
        name=category_in.name,
        description=category_in.description
    )


@router.put("/{category_id}", response_model=ProductCategorySchema)
def update_category(category_id: int, updates: dict, db: Session = Depends(get_db)):
    return CategoryService.update_category(db, category_id, updates)

@router.delete("/{category_id}", response_model=ProductCategorySchema)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    return CategoryService.delete_category(db, category_id)
