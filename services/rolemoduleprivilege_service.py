from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from models import RoleModulePrivilege


class RoleModulePrivilegeService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE -----------------
    def create_privilege(
        self,
        role_id: int,
        module_id: int,
        can_add: bool = False,
        can_edit: bool = False,
        can_delete: bool = False,
        can_search: bool = False,
        can_import: bool = False,
        can_export: bool = False,
        can_view: bool = False,
        created_by: Optional[str] = None
    ) -> RoleModulePrivilege:
        """Create or update role-module privilege"""
        existing = (
            self.db.query(RoleModulePrivilege)
            .filter_by(role_id=role_id, module_id=module_id)
            .first()
        )
        if existing:
            raise ValueError(f"Privilege already exists for role_id={role_id} and module_id={module_id}")

        privilege = RoleModulePrivilege(
            role_id=role_id,
            module_id=module_id,
            can_add=can_add,
            can_edit=can_edit,
            can_delete=can_delete,
            can_search=can_search,
            can_import=can_import,
            can_export=can_export,
            can_view=can_view,
            created_by=created_by
        )
        self.db.add(privilege)
        try:
            self.db.commit()
            self.db.refresh(privilege)
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"Failed to create privilege: {str(e)}")
        return privilege

    # ----------------- READ -----------------
    def get_privilege(self, privilege_id: int) -> RoleModulePrivilege:
        privilege = self.db.query(RoleModulePrivilege).filter(RoleModulePrivilege.id == privilege_id).first()
        if not privilege:
            raise ValueError(f"Privilege with id={privilege_id} not found")
        return privilege

    def get_privileges_by_role(self, role_id: int) -> List[RoleModulePrivilege]:
        return self.db.query(RoleModulePrivilege).filter(RoleModulePrivilege.role_id == role_id).all()

    def get_privileges_by_module(self, module_id: int) -> List[RoleModulePrivilege]:
        return self.db.query(RoleModulePrivilege).filter(RoleModulePrivilege.module_id == module_id).all()

    def list_privileges(self, skip: int = 0, limit: int = 100) -> List[RoleModulePrivilege]:
        return self.db.query(RoleModulePrivilege).offset(skip).limit(limit).all()

    # ----------------- UPDATE -----------------
    def update_privilege(
        self,
        privilege_id: int,
        can_add: Optional[bool] = None,
        can_edit: Optional[bool] = None,
        can_delete: Optional[bool] = None,
        can_search: Optional[bool] = None,
        can_import: Optional[bool] = None,
        can_export: Optional[bool] = None,
        can_view: Optional[bool] = None,
        modified_by: Optional[str] = None
    ) -> RoleModulePrivilege:
        privilege = self.get_privilege(privilege_id)
        # Update only provided fields
        for field, value in {
            "can_add": can_add,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "can_search": can_search,
            "can_import": can_import,
            "can_export": can_export,
            "can_view": can_view,
        }.items():
            if value is not None:
                setattr(privilege, field, value)
        if modified_by:
            privilege.modified_by = modified_by

        self.db.commit()
        self.db.refresh(privilege)
        return privilege

    # ----------------- DELETE -----------------
    def delete_privilege(self, privilege_id: int) -> bool:
        privilege = self.get_privilege(privilege_id)
        self.db.delete(privilege)
        self.db.commit()
        return True
