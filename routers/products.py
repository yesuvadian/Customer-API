from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.product_service import ProductService
from schemas import IdList, ProductCreateSchema, ProductSchema  # <-- Pydantic schema

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
    payload: ProductCreateSchema,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return ProductService.create_product(
        db=db,
        name=payload.name,
        sku=payload.sku,
        category_id=payload.category_id,
        subcategory_id=payload.subcategory_id,
        description=payload.description,
        hsn_code=payload.hsn_code,
        gst_percentage=payload.gst_percentage,
        material_code=payload.material_code,
        selling_price=payload.selling_price,
        cost_price=payload.cost_price,
        created_by=current_user.id,     # ✅ UUID
        modified_by=current_user.id,    # ✅ UUID
    )

@router.put("/{product_id}", response_model=ProductSchema)
def update_product(product_id: int, updates: dict, db: Session = Depends(get_db)):
    return ProductService.update_product(db, product_id, updates)

@router.delete("/{product_id}", response_model=ProductSchema)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    return ProductService.delete_product(db, product_id)
from typing import List


@router.post("/by_ids", response_model=list[ProductSchema])
def get_products_by_ids(ids: IdList, db: Session = Depends(get_db)):
    products = ProductService.get_products_by_ids(db, ids.ids)
    return products
