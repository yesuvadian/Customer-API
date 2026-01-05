from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.product_service import ProductService
from schemas import (
    IdList,
    ProductCreateSchema,
    ProductUpdateSchema,
    ProductSchema,
)

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(get_current_user)],
)

# ================================
# LIST PRODUCTS
# ================================
@router.get("/", response_model=list[ProductSchema])
def list_products(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    return ProductService.get_products(db, skip, limit, search)


# ================================
# GET SINGLE PRODUCT
# ================================
@router.get("/{product_id}", response_model=ProductSchema)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = ProductService.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ================================
# CREATE PRODUCT
# ================================
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
        gst_slab_id=payload.gst_slab_id,   # ✅ FIXED
        material_code=payload.material_code,
        selling_price=payload.selling_price,
        cost_price=payload.cost_price,

        created_by=current_user.id,
        modified_by=current_user.id,
    )


# ================================
# UPDATE PRODUCT
# ================================
@router.put("/{product_id}", response_model=ProductSchema)
def update_product(
    product_id: int,
    payload: ProductUpdateSchema,
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(exclude_unset=True)
    return ProductService.update_product(db, product_id, updates)


# ================================
# DELETE PRODUCT
# ================================
@router.delete("/{product_id}", response_model=ProductSchema)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    return ProductService.delete_product(db, product_id)


# ================================
# GET PRODUCTS BY IDS
# ================================
@router.post("/by_ids", response_model=list[ProductSchema])
def get_products_by_ids(ids: IdList, db: Session = Depends(get_db)):
    return ProductService.get_products_by_ids(db, ids.ids)
