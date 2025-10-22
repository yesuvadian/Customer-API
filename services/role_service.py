from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, NoResultFound
from uuid import UUID
from models import Role
from typing import List, Optional


class RoleService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE -----------------
    def create_role(self, name: str, description: Optional[str] = None, created_by: Optional[UUID] = None) -> Role:
        role = Role(name=name, description=description, created_by=created_by)
        self.db.add(role)
        try:
            self.db.commit()
            self.db.refresh(role)
            return role
        except IntegrityError:
            self.db.rollback()
            raise ValueError(f"Role with name '{name}' already exists.")

    # ----------------- READ -----------------
    def get_role(self, role_id: int) -> Role:
        role = self.db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise ValueError(f"Role with id '{role_id}' not found.")
        return role

    def get_role_by_name(self, name: str) -> Role:
        role = self.db.query(Role).filter(Role.name == name).first()
        if not role:
            raise ValueError(f"Role with name '{name}' not found.")
        return role

    # ----------------- LIST -----------------
    def list_roles(self, skip: int = 0, limit: int = 100) -> List[Role]:
        return self.db.query(Role).offset(skip).limit(limit).all()

    # ----------------- UPDATE -----------------
    def update_role(self, role_id: int, name: Optional[str] = None, description: Optional[str] = None, modified_by: Optional[UUID] = None) -> Role:
        role = self.get_role(role_id)
        if name:
            role.name = name
        if description is not None:
            role.description = description
        if modified_by:
            role.modified_by = modified_by
        try:
            self.db.commit()
            self.db.refresh(role)
            return role
        except IntegrityError:
            self.db.rollback()
            raise ValueError(f"Role with name '{name}' already exists.")

    # ----------------- DELETE -----------------
    def delete_role(self, role_id: int) -> bool:
        role = self.get_role(role_id)
        self.db.delete(role)
        self.db.commit()
        return True
