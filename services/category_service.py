from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import ProductCategory



class CategoryService:

    @classmethod
    def get_category(cls, db: Session, category_id: int):
        return db.query(ProductCategory).filter(ProductCategory.id == category_id).first()

    @classmethod
    def get_categories(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None):
        query = db.query(ProductCategory)
        if search:
            query = query.filter(ProductCategory.name.ilike(f"%{search}%"))
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_category(cls, db: Session, name: str, description: str | None = None):
        existing = db.query(ProductCategory).filter(ProductCategory.name == name).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category already exists")
        category = ProductCategory(name=name, description=description)
        db.add(category)
        db.commit()
        db.refresh(category)
        return category

    @classmethod
    def update_category(cls, db: Session, category_id: int, updates: dict):
        category = cls.get_category(db, category_id)
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        for key, value in updates.items():
            setattr(category, key, value)
        db.commit()
        db.refresh(category)
        return category

    @classmethod
    def delete_category(cls, db: Session, category_id: int):
        category = cls.get_category(db, category_id)
        if category:
            db.delete(category)
            db.commit()
        return category
