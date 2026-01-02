from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models import Product


class ProductService:

    @classmethod
    def get_product(cls, db: Session, product_id: int):
        return db.query(Product).filter(Product.id == product_id).first()

    @classmethod
    def get_products(
        cls,
        db: Session,
        skip: int = 0,
        limit: int = 600,
        search: str | None = None
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

    @classmethod
    def create_product(
        cls,
        db: Session,
        name: str,
        sku: str,
        category_id: int | None = None,
        subcategory_id: int | None = None,
        description: str | None = None,

        # 🔹 Newly added fields
        hsn_code: str | None = None,
        gst_percentage: float | None = None,
        material_code: str | None = None,
        selling_price: float | None = None,
        cost_price: float | None = None,

        created_by: str | None = None,
        modified_by: str | None = None,
        cts: datetime | None = None,
        mts: datetime | None = None,
    ):
        # 🔥 Duplicate name check
        if db.query(Product).filter(Product.name == name).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "name_duplicate", "message": "Product name already exists"}
            )

        # 🔥 Duplicate SKU check
        if db.query(Product).filter(Product.sku == sku).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "sku_duplicate", "message": "SKU already exists"}
            )

        product = Product(
            name=name,
            sku=sku,
            description=description,
            category_id=category_id,
            subcategory_id=subcategory_id,

            hsn_code=hsn_code,
            gst_percentage=gst_percentage,
            material_code=material_code,
            selling_price=selling_price,
            cost_price=cost_price,

            created_by=created_by,
            modified_by=modified_by,
            cts=cts,
            mts=mts,
        )

        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    @classmethod
    def update_product(cls, db: Session, product_id: int, updates: dict):
        product = cls.get_product(db, product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )

        # 🔥 Duplicate NAME check
        if "name" in updates:
            if (
                db.query(Product)
                .filter(Product.name == updates["name"], Product.id != product_id)
                .first()
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product name already exists"
                )

        # 🔥 Duplicate SKU check
        if "sku" in updates:
            if (
                db.query(Product)
                .filter(Product.sku == updates["sku"], Product.id != product_id)
                .first()
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SKU already exists"
                )

        for key, value in updates.items():
            setattr(product, key, value)

        db.commit()
        db.refresh(product)
        return product

    @classmethod
    def delete_product(cls, db: Session, product_id: int):
        product = cls.get_product(db, product_id)
        if product:
            db.delete(product)
            db.commit()
        return product

    @staticmethod
    def get_products_by_ids(db: Session, ids: list[int]):
        return db.query(Product).filter(Product.id.in_(ids)).all()
