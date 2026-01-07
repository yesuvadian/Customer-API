from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from models import CategoryMaster, CategoryDetails

class CategoryDetailsService:

    @classmethod
    def get_category_detail(cls, db: Session, detail_id: int):
        """Fetch a single Category Detail by ID"""
        return db.query(CategoryDetails).filter(CategoryDetails.id == detail_id).first()

    @classmethod
    def get_category_details(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None, master_id: int | None = None):
        """Fetch multiple Category Details with optional search and master filter"""
        query = db.query(CategoryDetails)
        
        if master_id:
            query = query.filter(CategoryDetails.category_master_id == master_id)

        if search:
            query = query.filter(CategoryDetails.name.ilike(f"%{search}%"))
            
        return query.offset(skip).limit(limit).all()

    @classmethod
    def get_category_details_by_master_name(cls, db: Session, master_name: str, skip: int = 0, limit: int = 100):
        """Fetch Category Details by Master Category name"""
        master = db.query(CategoryMaster).filter(CategoryMaster.name == master_name).first()
        if not master:
            return []

        return (
            db.query(CategoryDetails)
            .filter(CategoryDetails.category_master_id == master.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def create_category_detail(
        cls,
        db: Session,
        master_id: int,
        name: str,
        description: str | None = None,
        is_active: bool = True,              # ✅ ADD
        created_by: UUID | None = None
    ):
        """Create a new Category Detail under a Master Category"""

        master_exists = (
            db.query(CategoryMaster)
            .filter(CategoryMaster.id == master_id)
            .first()
        )
        if not master_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category Master ID not found"
            )

        existing = (
            db.query(CategoryDetails)
            .filter(
                CategoryDetails.name == name,
                CategoryDetails.category_master_id == master_id
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category Detail with this name already exists"
            )

        detail = CategoryDetails(
            category_master_id=master_id,
            name=name,
            description=description,
            is_active=is_active,              # ✅ ADD
            created_by=created_by,
            modified_by=created_by
        )

        db.add(detail)
        db.commit()
        db.refresh(detail)
        return detail


    @classmethod
    def update_category_detail(cls, db: Session, detail_id: int, updates: dict):
        """Update an existing Category Detail"""
        detail = cls.get_category_detail(db, detail_id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Detail not found")
        
        # Validate new master_id if provided
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
        """
        Safely delete a Category Detail.
        Raises 404 if not found, and handles database errors.
        """
        detail = cls.get_category_detail(db, detail_id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category Detail not found")

        try:
            # If there are related tables referencing this detail, handle them here
            # Example: db.query(RelatedTable).filter(RelatedTable.detail_id == detail_id).delete()

            db.delete(detail)
            db.commit()
            return {"message": "Category Detail deleted successfully"}
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
