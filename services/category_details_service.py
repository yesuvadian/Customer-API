from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

# Assuming your models are in a file named 'models.py'
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
    def get_category_details_by_master_name(
        cls,
        db: Session,
        master_name: str,
        skip: int = 0,
        limit: int = 100
    ):
        # 1️⃣ Get master id by name (exact match)
        master = db.query(CategoryMaster).filter(CategoryMaster.name == master_name).first()
        if not master:
            return []  # or raise HTTPException if needed

        # 2️⃣ Fetch category details using master_id
        return (
            db.query(CategoryDetails)
            .filter(CategoryDetails.category_master_id == master.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def create_category_detail(cls, db: Session, master_id: int, name: str, description: str | None = None, created_by: UUID | None = None):
        # 1. Validate Master Category exists
        master_exists = db.query(CategoryMaster).filter(CategoryMaster.id == master_id).first()
        if not master_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Master ID not found")

        # 2. Check for duplicate name (Optional: remove if duplicates are allowed across different masters)
        existing = db.query(CategoryDetails).filter(
         CategoryDetails.name == name,
         CategoryDetails.category_master_id == master_id # <--- Added filter
    ).first()
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
        
        # Verify new master exists if updating master_id
        if 'category_master_id' in updates:
            new_master_id = updates['category_master_id']
            master_exists = db.query(CategoryMaster).filter(CategoryMaster.id == new_master_id).first()
            if not master_exists:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="New Category Master ID not found")

        try:
            for key, value in updates.items():
                setattr(detail, key, value)
            
            db.commit()
            db.refresh(detail)
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
        
        return detail

    @classmethod
    def delete_category_detail(cls, db: Session, detail_id: int):
        detail = cls.get_category_detail(db, detail_id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Detail not found")

        try:
            db.delete(detail)
            db.commit()
        except Exception as e:
            db.rollback()  # Rollback to keep the session clean
            raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
        
        return detail
