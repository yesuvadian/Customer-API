from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import ProductSubCategory


class SubCategoryService:

    @classmethod
    def get_subcategory(cls, db: Session, subcategory_id: int):
        return db.query(ProductSubCategory).filter(ProductSubCategory.id == subcategory_id).first()

    @classmethod
    def get_subcategories(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None):
        query = db.query(ProductSubCategory)
        if search:
            query = query.filter(ProductSubCategory.name.ilike(f"%{search}%"))
        return query.offset(skip).limit(limit).all()

    @classmethod
    def get_by_category(cls, db: Session, category_id: int):
        return db.query(ProductSubCategory).filter(ProductSubCategory.category_id == category_id).all()

    @classmethod
    def create_subcategory(cls, db: Session, name: str, category_id: int, description: str | None = None):
        existing = db.query(ProductSubCategory).filter(
            ProductSubCategory.name == name, ProductSubCategory.category_id == category_id
        ).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subcategory already exists in this category")

        sub = ProductSubCategory(name=name, description=description, category_id=category_id)
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    @classmethod
    def update_subcategory(cls, db: Session, subcategory_id: int, updates: dict):
        sub = cls.get_subcategory(db, subcategory_id)
        if not sub:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found")
        for key, value in updates.items():
            setattr(sub, key, value)
        db.commit()
        db.refresh(sub)
        return sub

    @classmethod
    def delete_subcategory(cls, db: Session, subcategory_id: int):
        sub = cls.get_subcategory(db, subcategory_id)
        if sub:
            db.delete(sub)
            db.commit()
        return sub
