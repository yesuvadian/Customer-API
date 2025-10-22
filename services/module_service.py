from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models import Module


class ModuleService:

    @classmethod
    def get_module(cls, db: Session, module_id: int):
        """Fetch a single module by ID"""
        return db.query(Module).filter(Module.id == module_id).first()

    @classmethod
    def get_modules(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None, active_only: bool = True):
        """Fetch all modules, optionally filtered by name and active status"""
        query = db.query(Module)
        if search:
            query = query.filter(Module.name.ilike(f"%{search}%"))
        if active_only:
            query = query.filter(Module.is_active == True)
        return query.offset(skip).limit(limit).all()

    @classmethod
    # Correct for creating a Module
    def create_module(cls,db: Session, data: dict):
        module = Module(**data)  # Unpack dict into keyword arguments
        db.add(module)
        db.commit()
        db.refresh(module)
        return module

            

    @classmethod
    def update_module(cls, db: Session, module_id: int, updates: dict, modified_by: int | None = None):
        """Update a module’s details"""
        module = cls.get_module(db, module_id)
        if not module:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

        for key, value in updates.items():
            if hasattr(module, key):
                setattr(module, key, value)

        if modified_by:
            module.modified_by = modified_by

        db.commit()
        db.refresh(module)
        return module

    @classmethod
    def deactivate_module(cls, db: Session, module_id: int, modified_by: int | None = None):
        """Soft delete (deactivate) a module"""
        module = cls.get_module(db, module_id)
        if not module:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

        module.is_active = False
        if modified_by:
            module.modified_by = modified_by

        db.commit()
        db.refresh(module)
        return module

    @classmethod
    def delete_module(cls, db: Session, module_id: int):
        """Permanently delete a module"""
        module = cls.get_module(db, module_id)
        if not module:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

        db.delete(module)
        db.commit()
        return {"detail": f"Module '{module.name}' deleted successfully"}
