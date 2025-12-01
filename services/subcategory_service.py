from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from models import ProductSubCategory


class SubCategoryService:

    # ---------------------------------------
    # GET SINGLE SUBCATEGORY (with 404)
    # ---------------------------------------
    @classmethod
    def get_subcategory(cls, db: Session, subcategory_id: int):
        sub = (
            db.query(ProductSubCategory)
              .options(joinedload(ProductSubCategory.category))
              .filter(ProductSubCategory.id == subcategory_id)
              .first()
        )

        if not sub:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subcategory not found"
            )
        return sub

    # ---------------------------------------
    # GET ALL SUBCATEGORIES
    # ---------------------------------------
    @classmethod
    def get_subcategories(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None):
        query = db.query(ProductSubCategory).options(joinedload(ProductSubCategory.category))

        if search:
            query = query.filter(ProductSubCategory.name.ilike(f"%{search}%"))

        return query.offset(skip).limit(limit).all()

    # ---------------------------------------
    # GET BY CATEGORY
    # ---------------------------------------
    @classmethod
    def get_by_category(cls, db: Session, category_id: int):
        return (
            db.query(ProductSubCategory)
              .options(joinedload(ProductSubCategory.category))
              .filter(ProductSubCategory.category_id == category_id)
              .all()
        )

    # ---------------------------------------
    # CREATE SUBCATEGORY (DUPLICATE CHECK)
    # ---------------------------------------
    @classmethod
    def create_subcategory(cls, db: Session, name: str, category_id: int, description: str | None = None):
        
        existing = (
            db.query(ProductSubCategory)
              .filter(
                  ProductSubCategory.name == name,
                  ProductSubCategory.category_id == category_id
              )
              .first()
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subcategory with this name already exists in this category"
            )

        sub = ProductSubCategory(
            name=name,
            description=description,
            category_id=category_id
        )

        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    # ---------------------------------------
    # UPDATE SUBCATEGORY (DUPLICATE CHECK)
    # ---------------------------------------
    @classmethod
    def update_subcategory(cls, db: Session, subcategory_id: int, updates: dict):
        sub = cls.get_subcategory(db, subcategory_id)

        # Extract updated fields
        new_name = updates.get("name", sub.name)
        new_category_id = updates.get("category_id", sub.category_id)

        # Duplicate validation
        duplicate = (
            db.query(ProductSubCategory)
                .filter(
                    ProductSubCategory.name == new_name,
                    ProductSubCategory.category_id == new_category_id,
                    ProductSubCategory.id != subcategory_id
                )
                .first()
        )

        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subcategory with this name already exists in this category"
            )

        # Apply updates
        for key, value in updates.items():
            if hasattr(sub, key):
                setattr(sub, key, value)

        db.commit()
        db.refresh(sub)
        return sub

    # ---------------------------------------
    # DELETE SUBCATEGORY
    # ---------------------------------------
    @classmethod
    def delete_subcategory(cls, db: Session, subcategory_id: int):
        sub = cls.get_subcategory(db, subcategory_id)
        db.delete(sub)
        db.commit()
        return sub
