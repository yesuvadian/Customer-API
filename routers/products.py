from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.product_service import ProductService
from schemas import ProductSchema  # <-- Pydantic schema

router = APIRouter(prefix="/products", tags=["products"],dependencies=[Depends(get_current_user)])

@router.get("/", response_model=list[ProductSchema])
def list_products(skip: int = 0, limit: int = 100, search: str | None = None, db: Session = Depends(get_db)):
    return ProductService.get_products(db, skip, limit, search)

@router.get("/{product_id}", response_model=ProductSchema)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = ProductService.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.post("/", response_model=ProductSchema)
def create_product(
    name: str,
    sku: str,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    description: str | None = None,
    created_by: str | None = None,
    db: Session = Depends(get_db)
):
    return ProductService.create_product(db, name, sku, category_id, subcategory_id, description, created_by)

@router.put("/{product_id}", response_model=ProductSchema)
def update_product(product_id: int, updates: dict, db: Session = Depends(get_db)):
    return ProductService.update_product(db, product_id, updates)

@router.delete("/{product_id}", response_model=ProductSchema)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    return ProductService.delete_product(db, product_id)
