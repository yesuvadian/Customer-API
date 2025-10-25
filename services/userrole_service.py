from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List
from uuid import UUID
from models import UserRole, User, Role


class UserRoleService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE / ASSIGN -----------------
    def assign_role_to_user(self, user_id: UUID, role_id: int) -> UserRole:
        existing = self.db.query(UserRole).filter_by(user_id=user_id, role_id=role_id).first()
        if existing:
            raise ValueError(f"User {user_id} already has role {role_id} assigned.")
        user_role = UserRole(user_id=user_id, role_id=role_id)
        self.db.add(user_role)
        self.db.commit()
        self.db.refresh(user_role)
        return user_role

    # ----------------- READ -----------------
    def get_user_role(self, user_role_id: int) -> UserRole:
        user_role = self.db.query(UserRole).filter(UserRole.id == user_role_id).first()
        if not user_role:
            raise ValueError(f"UserRole with id {user_role_id} not found.")
        return user_role

    def get_roles_by_user(self, user_id: UUID) -> List[UserRole]:
        return self.db.query(UserRole).filter(UserRole.user_id == user_id).all()

    def get_users_by_role(self, role_id: int) -> List[UserRole]:
        return self.db.query(UserRole).filter(UserRole.role_id == role_id).all()

    # ----------------- UPDATE -----------------
    def update_user_role(self, user_role_id: int, new_role_id: int) -> UserRole:
        user_role = self.get_user_role(user_role_id)
        # Check if the new role is already assigned to the user
        existing = self.db.query(UserRole).filter_by(user_id=user_role.user_id, role_id=new_role_id).first()
        if existing:
            raise ValueError(f"User {user_role.user_id} already has role {new_role_id} assigned.")
        user_role.role_id = new_role_id
        self.db.commit()
        self.db.refresh(user_role)
        return user_role

    # ----------------- DELETE / UNASSIGN -----------------
    def unassign_role_from_user(self, user_role_id: int) -> bool:
        user_role = self.get_user_role(user_role_id)
        self.db.delete(user_role)
        self.db.commit()
        return True

    # ----------------- LIST -----------------
    def list_user_roles(self, skip: int = 0, limit: int = 100) -> List[UserRole]:
        return self.db.query(UserRole).offset(skip).limit(limit).all()
# Fetch user-role mappings for UI
    def fetch_user_role_mappings(self):
        rows = self.db.query(UserRole).join(UserRole.user).join(UserRole.role).all()
        role_users_map = defaultdict(list)

        for ur in rows:
            email = ur.user.email
            role_name = ur.role.name
            if role_name not in role_users_map[email]:
                role_users_map[email].append(role_name)

        return [{"email": email, "roles": roles} for email, roles in role_users_map.items()]