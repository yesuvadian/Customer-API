from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import Product


class ProductService:

    @classmethod
    def get_product(cls, db: Session, product_id: int):
        return db.query(Product).filter(Product.id == product_id).first()

    @classmethod
    def get_products(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None):
        query = db.query(Product)
        if search:
            query = query.filter(Product.name.ilike(f"%{search}%"))
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_product(cls, db: Session, name: str, sku: str, category_id: int | None = None,
                       subcategory_id: int | None = None, description: str | None = None,
                       created_by: str | None = None):
        existing_sku = db.query(Product).filter(Product.sku == sku).first()
        if existing_sku:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKU already exists")

        product = Product(
            name=name,
            sku=sku,
            description=description,
            category_id=category_id,
            subcategory_id=subcategory_id,
            created_by=created_by
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    @classmethod
    def update_product(cls, db: Session, product_id: int, updates: dict):
        product = cls.get_product(db, product_id)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
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
