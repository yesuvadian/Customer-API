from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import Product, CategoryDetails


class ProductService:

    # ================================
    # GET SINGLE PRODUCT
    # ================================
    @classmethod
    def get_product(cls, db: Session, product_id: int):
        return db.query(Product).filter(Product.id == product_id).first()

    # ================================
    # LIST PRODUCTS
    # ================================
    @classmethod
    def get_products(
        cls,
        db: Session,
        skip: int = 0,
        limit: int = 600,
        search: str | None = None,
    ):
        query = db.query(Product)

        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Product.name.ilike(search_pattern),
                    Product.sku.ilike(search_pattern),
                    Product.material_code.ilike(search_pattern),
                    Product.hsn_code.ilike(search_pattern),
                )
            )

        return query.offset(skip).limit(limit).all()

    # ================================
    # CREATE PRODUCT
    # ================================
    @classmethod
    def create_product(
        cls,
        db: Session,
        name: str,
        sku: str,
        category_id: int | None = None,
        subcategory_id: int | None = None,
        description: str | None = None,

        hsn_code: str | None = None,
        gst_slab_id: int | None = None,   # ✅ FIXED
        material_code: str | None = None,
        selling_price: float | None = None,
        cost_price: float | None = None,

        created_by: UUID | None = None,
        modified_by: UUID | None = None,
    ):
        # 🔒 Duplicate name check
        if db.query(Product).filter(Product.name == name).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "name_duplicate", "message": "Product name already exists"},
            )

        # 🔒 Duplicate SKU check
        if db.query(Product).filter(Product.sku == sku).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "sku_duplicate", "message": "SKU already exists"},
            )

        # 🔒 GST slab validation
        if gst_slab_id is not None:
            gst_slab = (
                db.query(CategoryDetails)
                .filter(
                    CategoryDetails.id == gst_slab_id,
                    CategoryDetails.is_active == True
                )
                .first()
            )
            if not gst_slab:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid GST slab selected",
                )

        # 🔒 Price validations
        if selling_price is not None and selling_price < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selling price cannot be negative",
            )

        if cost_price is not None and cost_price < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cost price cannot be negative",
            )

        product = Product(
            name=name,
            sku=sku,
            description=description,
            category_id=category_id,
            subcategory_id=subcategory_id,

            hsn_code=hsn_code,
            gst_slab_id=gst_slab_id,   # ✅ FIXED
            material_code=material_code,
            selling_price=selling_price,
            cost_price=cost_price,

            created_by=created_by,
            modified_by=modified_by,
        )

        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    # ================================
    # UPDATE PRODUCT
    # ================================
    @classmethod
    def update_product(cls, db: Session, product_id: int, updates: dict):
        product = cls.get_product(db, product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

        # 🔒 Prevent immutable updates
        forbidden_fields = {"id", "cts"}
        for field in forbidden_fields:
            updates.pop(field, None)

        # 🔒 Duplicate name check
        if "name" in updates:
            if (
                db.query(Product)
                .filter(Product.name == updates["name"], Product.id != product_id)
                .first()
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product name already exists",
                )

        # 🔒 Duplicate SKU check
        if "sku" in updates:
            if (
                db.query(Product)
                .filter(Product.sku == updates["sku"], Product.id != product_id)
                .first()
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SKU already exists",
                )

        # 🔒 GST slab validation
        if "gst_slab_id" in updates and updates["gst_slab_id"] is not None:
            gst_slab = (
                db.query(CategoryDetails)
                .filter(
                    CategoryDetails.id == updates["gst_slab_id"],
                    CategoryDetails.is_active == True
                )
                .first()
            )
            if not gst_slab:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid GST slab selected",
                )

        # 🔒 Apply updates
        for key, value in updates.items():
            if hasattr(product, key):
                setattr(product, key, value)

        db.commit()
        db.refresh(product)
        return product

    # ================================
    # DELETE PRODUCT
    # ================================
    @classmethod
    def delete_product(cls, db: Session, product_id: int):
        product = cls.get_product(db, product_id)
        if product:
            db.delete(product)
            db.commit()
        return product

    # ================================
    # GET PRODUCTS BY IDS
    # ================================
    @staticmethod
    def get_products_by_ids(db: Session, ids: list[int]):
        return db.query(Product).filter(Product.id.in_(ids)).all()
