from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc


from models import CategoryMaster, CategoryDetails


class CategoryDetailsService:

    @classmethod
    def get_category_detail(cls, db: Session, detail_id: int):
        return db.query(CategoryDetails).filter(CategoryDetails.id == detail_id).first()

    @classmethod
    def get_category_details(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None, master_id: int | None = None):
        query = db.query(CategoryDetails)
        
        # Filter by Master ID if provided (common use case)
        if master_id:
            query = query.filter(CategoryDetails.category_master_id == master_id)

        if search:
            query = query.filter(CategoryDetails.name.ilike(f"%{search}%"))
            
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_category_detail(cls, db: Session, master_id: int, name: str, description: str | None = None, created_by: UUID | None = None):
        # 1. Validate Master Category exists
        master_exists = db.query(CategoryMaster).filter(CategoryMaster.id == master_id).first()
        if not master_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Master ID not found")

        # 2. Check for duplicate name (Optional: remove if duplicates are allowed across different masters)
        existing = db.query(CategoryDetails).filter(CategoryDetails.name == name).first()
        if existing:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category Detail with this name already exists")

        detail = CategoryDetails(
            category_master_id=master_id,
            name=name, 
            description=description,
            created_by=created_by,
            modified_by=created_by
        )
        db.add(detail)
        db.commit()
        db.refresh(detail)
        return detail

    @classmethod
    def update_category_detail(cls, db: Session, detail_id: int, updates: dict):
        detail = cls.get_category_detail(db, detail_id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Detail not found")
        
        # If updating the master_id, verify the new master exists
        if 'category_master_id' in updates:
             new_master_id = updates['category_master_id']
             master_exists = db.query(CategoryMaster).filter(CategoryMaster.id == new_master_id).first()
             if not master_exists:
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="New Category Master ID not found")

        for key, value in updates.items():
            setattr(detail, key, value)
            
        db.commit()
        db.refresh(detail)
        return detail

    @classmethod
    def delete_category_detail(cls, db: Session, detail_id: int):
        detail = cls.get_category_detail(db, detail_id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Detail not found")
            
        db.delete(detail)
        db.commit()
        return detail