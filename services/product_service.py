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
    def get_products(cls, db: Session, skip: int = 0, limit: int = 600, search: str | None = None):
        query = db.query(Product)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Product.name.ilike(search_pattern),
                    Product.sku.ilike(search_pattern)
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
        created_by: str | None = None,
        modified_by: str | None = None,
        cts: datetime | None = None,
        mts: datetime | None = None,
    ):
    # Check duplicate name
        existing_name = db.query(Product).filter(Product.name == name).first()
        if existing_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "name_duplicate", "message": "Product name already exists"}
            )

        # Check duplicate SKU
        existing_sku = db.query(Product).filter(Product.sku == sku).first()
        if existing_sku:
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
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )

        # 🔥 Duplicate NAME check (ignore current product)
        if "name" in updates:
            existing_name = (
                db.query(Product)
                .filter(Product.name == updates["name"], Product.id != product_id)
                .first()
            )
            if existing_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product name already exists"
                )

        # 🔥 Duplicate SKU check (ignore current product)
        if "sku" in updates:
            existing_sku = (
                db.query(Product)
                .filter(Product.sku == updates["sku"], Product.id != product_id)
                .first()
            )
            if existing_sku:
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
