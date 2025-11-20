from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

# Assuming your models are in a file named 'models.py'
from models import CategoryMaster, CategoryDetails


class CategoryMasterService:

    @classmethod
    def get_master_category(cls, db: Session, category_id: int):
        return db.query(CategoryMaster).filter(CategoryMaster.id == category_id).first()

    @classmethod
    def get_master_categories(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None):
        query = db.query(CategoryMaster)
        
        if search:
            # Search case-insensitive in name
            query = query.filter(CategoryMaster.name.ilike(f"%{search}%"))
            
        # Optional: Order by ID descending to see newest first
        return query.order_by(desc(CategoryMaster.id)).offset(skip).limit(limit).all()

    @classmethod
    def create_master_category(cls, db: Session, name: str, description: str | None = None, created_by: UUID | None = None):
        # Check for duplicate name
        existing = db.query(CategoryMaster).filter(CategoryMaster.name == name).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category Master with this name already exists")
        
        category = CategoryMaster(
            name=name, 
            description=description,
            created_by=created_by,
            modified_by=created_by # Initial modified_by is same as creator
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        return category

    @classmethod
    def update_master_category(cls, db: Session, category_id: int, updates: dict):
        category = cls.get_master_category(db, category_id)
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Master not found")
        
        for key, value in updates.items():
            setattr(category, key, value)
            
        db.commit()
        db.refresh(category)
        return category
    

    @classmethod
    def delete_master_category(cls, db: Session, category_id: int):
        category = cls.get_master_category(db, category_id)
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Master not found")
            
        db.delete(category)
        db.commit()
        return category


