from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import CategoryMaster, CategoryDetails

class CategoryMasterService:

    @classmethod
    def get_master_category(cls, db: Session, category_id: int):
        """Fetch a single master category by ID."""
        return db.query(CategoryMaster).filter(CategoryMaster.id == category_id).first()

    @classmethod
    def get_master_categories(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None):
        """Fetch master categories with optional search and pagination."""
        query = db.query(CategoryMaster)
        if search:
            query = query.filter(CategoryMaster.name.ilike(f"%{search}%"))
        return query.order_by(desc(CategoryMaster.id)).offset(skip).limit(limit).all()

    @classmethod
    def create_master_category(
        cls,
        db: Session,
        name: str,
        description: str | None = None,
        is_active: bool = True,          # ✅ ADD
        created_by: UUID | None = None
    ):
        """Create a new master category with duplicate check."""

        existing = (
            db.query(CategoryMaster)
            .filter(CategoryMaster.name == name)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category Master with this name already exists"
            )

        category = CategoryMaster(
            name=name,
            description=description,
            is_active=is_active,          # ✅ ADD
            created_by=created_by,
            modified_by=created_by
        )

        try:
            db.add(category)
            db.commit()
            db.refresh(category)
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating category: {str(e)}"
            )

        return category


    @classmethod
    def update_master_category(
        cls,
        db: Session,
        category_id: int,
        updates: dict
    ):
        category = cls.get_master_category(db, category_id)
        if not category:
            raise HTTPException(
                status_code=404,
                detail="Category Master not found"
            )

        # ─────────────────────────────────────────────
        # ❌ RULE: Cannot disable master if any child is active
        # ─────────────────────────────────────────────
        if updates.get("is_active") is False:
            active_children_count = (
                db.query(CategoryDetails)
                .filter(
                    CategoryDetails.category_master_id == category_id,
                    CategoryDetails.is_active == True
                )
                .count()
            )

            if active_children_count > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot disable category master while active child categories exist"
                )

        # ─────────────────────────────────────────────
        # Duplicate name check (unchanged logic)
        # ─────────────────────────────────────────────
        new_name = updates.get("name")
        if new_name and new_name != category.name:
            existing = (
                db.query(CategoryMaster)
                .filter(
                    CategoryMaster.name == new_name,
                    CategoryMaster.id != category_id
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail="Category Master with this name already exists"
                )

        # ─────────────────────────────────────────────
        # Apply updates
        # ─────────────────────────────────────────────
        for key, value in updates.items():
            setattr(category, key, value)

        try:
            db.commit()
            db.refresh(category)
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error updating category: {str(e)}"
            )

        return category



    @classmethod
    def delete_master_category(cls, db: Session, category_id: int):
        """
        Deletes a Category Master if it has no child categories.
        If it has child categories, raises a warning.
        Returns a JSON-compatible dict for Flutter response.
        """
        category = cls.get_master_category(db, category_id)
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category Master not found"
            )

        # Check for child categories
        has_children = db.query(CategoryDetails).filter(CategoryDetails.master_id == category_id).first()
        if has_children:
            return {"status": "warning", "message": "Cannot delete Category Master: it has child categories"}

        # Safe to delete
        deleted_info = {"id": category.id, "name": category.name}
        try:
            db.delete(category)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Error deleting category: {str(e)}")
        
        return {"status": "success", "message": f"Category '{category.name}' deleted successfully", "data": deleted_info}
