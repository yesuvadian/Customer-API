from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models import Module, RoleModulePrivilege, UserRole, OrgUserRole, OrgRolePermission


class ModuleService:

    # ---------------------------------------------------------
    # GET SINGLE MODULE
    # ---------------------------------------------------------
    @classmethod
    def get_module(cls, db: Session, module_id: int):
        return db.query(Module).filter(Module.id == module_id).first()

    # ---------------------------------------------------------
    # GET ALL MODULES (Admin)
    # ---------------------------------------------------------
    @classmethod
    def get_modules(
        cls,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        active_only: bool = True
    ):
        query = db.query(Module)

        if search:
            query = query.filter(Module.name.ilike(f"%{search}%"))

        if active_only:
            query = query.filter(Module.is_active.is_(True))

        return query.offset(skip).limit(limit).all()

    # ---------------------------------------------------------
    # GET MODULES BASED ON USER PRIVILEGES
    # ---------------------------------------------------------
    @classmethod
    def get_modules_for_user(cls, db: Session, user_id: int):
        """
        Returns ONLY active modules where user has can_view permission.
        Supports both old role system and new organization role system.
        """

        module_ids = set()

        # 1️⃣ OLD ROLE SYSTEM: Get user roles
        old_role_ids = (
            db.query(UserRole.role_id)
            .filter(UserRole.user_id == user_id)
            .all()
        )
        old_role_ids = [r[0] for r in old_role_ids]

        if old_role_ids:
            # Get privileges for old roles
            old_privileges = (
                db.query(RoleModulePrivilege)
                .filter(
                    RoleModulePrivilege.role_id.in_(old_role_ids),
                    RoleModulePrivilege.can_view.is_(True)
                )
                .all()
            )
            module_ids.update([p.module_id for p in old_privileges])

        # 2️⃣ NEW ORGANIZATION ROLE SYSTEM: Get org user roles
        org_user_roles = (
            db.query(OrgUserRole)
            .filter(
                OrgUserRole.user_id == user_id,
                OrgUserRole.is_active == True
            )
            .all()
        )
        org_role_ids = [ur.org_role_id for ur in org_user_roles]

        if org_role_ids:
            # Get privileges for org roles
            org_privileges = (
                db.query(OrgRolePermission)
                .filter(
                    OrgRolePermission.org_role_id.in_(org_role_ids),
                    OrgRolePermission.can_view.is_(True)
                )
                .all()
            )
            module_ids.update([p.module_id for p in org_privileges])

        if not module_ids:
            return []

        # 3️⃣ Return active modules
        return (
            db.query(Module)
            .filter(
                Module.id.in_(module_ids),
                Module.is_active.is_(True)
            )
            .all()
        )

    # ---------------------------------------------------------
    # CREATE MODULE
    # ---------------------------------------------------------
    @classmethod
    def create_module(cls, db: Session, data: dict):
        try:
            module = Module(**data)
            db.add(module)
            db.commit()
            db.refresh(module)
            return module
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Module name already exists"
            )

    # ---------------------------------------------------------
    # UPDATE MODULE
    # ---------------------------------------------------------
    @classmethod
    def update_module(cls, db: Session, module_id: int, updates: dict):
        module = cls.get_module(db, module_id)

        if not module:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Module not found"
            )

        for key, value in updates.items():
            if hasattr(module, key):
                setattr(module, key, value)

        db.commit()
        db.refresh(module)
        return module

    # ---------------------------------------------------------
    # DEACTIVATE MODULE (SOFT DELETE)
    # ---------------------------------------------------------
    @classmethod
    def deactivate_module(cls, db: Session, module_id: int):
        module = cls.get_module(db, module_id)

        if not module:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Module not found"
            )

        module.is_active = False
        db.commit()
        db.refresh(module)
        return module

    # ---------------------------------------------------------
    # DELETE MODULE (HARD DELETE)
    # ---------------------------------------------------------
    @classmethod
    def delete_module(cls, db: Session, module_id: int):
        module = cls.get_module(db, module_id)

        if not module:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Module not found"
            )

        db.delete(module)
        db.commit()
        return {"detail": f"Module '{module.name}' deleted successfully"}
