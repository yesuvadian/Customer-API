from collections import defaultdict
from typing import List, Set
from uuid import UUID
from sqlalchemy.orm import Session
from models import UserRole, User, Role


class UserRoleService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE / ASSIGN -----------------
    def assign_role_to_user(self, user_id: UUID, role_id: int) -> UserRole:
        # Remove any previous role assigned to this user
        existing_user_roles = self.db.query(UserRole).filter_by(user_id=user_id).all()
        for ur in existing_user_roles:
            self.db.delete(ur)

        # Assign the new role
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

    def get_roles_by_user(self, user_id: UUID) -> Set[int]:
        """Return set of role IDs assigned to user."""
        return {ur.role_id for ur in self.db.query(UserRole).filter(UserRole.user_id == user_id).all()}

    def get_users_by_role(self, role_id: int) -> List[UserRole]:
        return self.db.query(UserRole).filter(UserRole.role_id == role_id).all()

    # ----------------- DELETE / UNASSIGN -----------------
    def unassign_role_from_user_by_role(self, user_id: UUID, role_id: int) -> bool:
        """Remove a specific role from a user."""
        user_role = self.db.query(UserRole).filter_by(user_id=user_id, role_id=role_id).first()
        if user_role:
            self.db.delete(user_role)
            self.db.commit()
        return True

    def unassign_role_from_user_by_id(self, user_role_id: int) -> bool:
        """Remove a role mapping by UserRole ID."""
        user_role = self.get_user_role(user_role_id)
        self.db.delete(user_role)
        self.db.commit()
        return True
    
    def update_users_for_role(self, role_id: int, updated_user_ids: List[UUID]) -> List[UserRole]:
        """
        Fully update a role's users:
        1. Remove any existing users.
        2. Assign only the users in updated_user_ids.
        """
        # Step 1: Remove existing users
        self.db.query(UserRole).filter_by(role_id=role_id).delete()
        self.db.commit()

        # Step 2: Assign updated users
        results = []
        for user_id in updated_user_ids:
            user_role = UserRole(user_id=user_id, role_id=role_id)
            self.db.add(user_role)
            self.db.commit()
            self.db.refresh(user_role)
            results.append(user_role)

        return results
    # ----------------- SYNC / BULK -----------------
    def sync_roles_for_user(self, user_id: UUID, new_role_ids: Set[int]):
        """
        Synchronize roles for a user:
        - Add roles in new_role_ids not currently assigned
        - Remove roles currently assigned but not in new_role_ids
        """
        current_role_ids = self.get_roles_by_user(user_id)

        # Add new roles
        for role_id in new_role_ids - current_role_ids:
            self.assign_role_to_user(user_id, role_id)

        # Remove roles no longer assigned
        for role_id in current_role_ids - new_role_ids:
            self.unassign_role_from_user_by_role(user_id, role_id)

    # ----------------- LIST -----------------
    def list_user_roles(self, skip: int = 0, limit: int = 100) -> List[UserRole]:
        return self.db.query(UserRole).offset(skip).limit(limit).all()

    # ----------------- FETCH FOR UI -----------------
    def fetch_user_role_mappings(self):
        rows = self.db.query(UserRole).join(UserRole.user).join(UserRole.role).all()
        role_users_map = defaultdict(list)

        for ur in rows:
            email = ur.user.email
            role_name = ur.role.name
            if role_name not in role_users_map[email]:
                role_users_map[email].append(role_name)

        return [{"email": email, "roles": roles} for email, roles in role_users_map.items()]
