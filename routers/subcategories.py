from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.subcategory_service import SubCategoryService
from schemas import ProductSubCategorySchema
from pydantic import BaseModel

# ----------------- Pydantic Schemas -----------------
class ProductSubCategoryCreate(BaseModel):
    name: str
    category_id: int
    description: str | None = None

class ProductSubCategoryUpdate(BaseModel):
    name: str | None = None
    category_id: int | None = None
    description: str | None = None

# ----------------- Router -----------------
router = APIRouter(
    prefix="/subcategories",
    tags=["subcategories"],
    dependencies=[Depends(get_current_user)]
)

# ----------------- List Subcategories -----------------
@router.get("/", response_model=list[ProductSubCategorySchema])
def list_subcategories(
    skip: int = 0,
    limit: int = 10000,
    search: str | None = None,
    db: Session = Depends(get_db)
):
    return SubCategoryService.get_subcategories(db, skip, limit, search)

# ----------------- Get Subcategory by ID -----------------
@router.get("/{subcategory_id}", response_model=ProductSubCategorySchema)
def get_subcategory(subcategory_id: int, db: Session = Depends(get_db)):
    return SubCategoryService.get_subcategory(db, subcategory_id)

# ----------------- Get Subcategories by Category -----------------
@router.get("/by_category/{category_id}", response_model=list[ProductSubCategorySchema])
def get_by_category(category_id: int, db: Session = Depends(get_db)):
    return SubCategoryService.get_by_category(db, category_id)

# ----------------- Create Subcategory -----------------
@router.post("/", response_model=ProductSubCategorySchema)
def create_subcategory(
    subcategory_in: ProductSubCategoryCreate,
    db: Session = Depends(get_db)
):
    return SubCategoryService.create_subcategory(
        db,
        name=subcategory_in.name,
        category_id=subcategory_in.category_id,
        description=subcategory_in.description
    )

# ----------------- Update Subcategory -----------------
@router.put("/{subcategory_id}", response_model=ProductSubCategorySchema)
def update_subcategory(
    subcategory_id: int,
    updates: ProductSubCategoryUpdate,
    db: Session = Depends(get_db)
):
    return SubCategoryService.update_subcategory(
        db,
        subcategory_id,
        updates.dict(exclude_unset=True)
    )

# ----------------- Delete Subcategory (safe) -----------------
@router.delete("/{subcategory_id}", response_model=ProductSubCategorySchema)
def delete_subcategory(subcategory_id: int, db: Session = Depends(get_db)):
    try:
        return SubCategoryService.delete_subcategory(db, subcategory_id)
    except HTTPException as e:
        if e.status_code == status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete subcategory: it has linked products"
            )
        raise e
