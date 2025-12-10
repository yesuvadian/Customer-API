from collections import defaultdict
from typing import List, Set
from uuid import UUID
from sqlalchemy.orm import Session
from models import UserRole, User, Role


class UserRoleService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE / ASSIGN SINGLE -----------------
    def assign_role_to_user(self, user_id: UUID, role_id: int) -> UserRole:
        # Remove user from any other roles
        self.db.query(UserRole).filter(UserRole.user_id == user_id, UserRole.role_id != role_id).delete()
        self.db.commit()

        # Assign to the new role
        user_role = self.db.query(UserRole).filter_by(user_id=user_id, role_id=role_id).first()
        if not user_role:
            user_role = UserRole(user_id=user_id, role_id=role_id)
            self.db.add(user_role)
            self.db.commit()
            self.db.refresh(user_role)
        return user_role

    # ----------------- CREATE / ASSIGN BULK -----------------
    def update_users_for_role(self, role_id: int, updated_user_ids: List[UUID]) -> List[UserRole]:
        results = []

        for user_id in updated_user_ids:
            # Remove from other roles
            self.db.query(UserRole).filter(UserRole.user_id == user_id, UserRole.role_id != role_id).delete()

            # Assign to this role if not already
            exists = self.db.query(UserRole).filter_by(user_id=user_id, role_id=role_id).first()
            if not exists:
                user_role = UserRole(user_id=user_id, role_id=role_id)
                self.db.add(user_role)
                self.db.commit()
                self.db.refresh(user_role)
                results.append(user_role)

        return results

    # ----------------- READ -----------------
    def get_user_role(self, user_role_id: int) -> UserRole:
        user_role = self.db.query(UserRole).filter(UserRole.id == user_role_id).first()
        if not user_role:
            raise ValueError(f"UserRole with id {user_role_id} not found.")
        return user_role

    def get_roles_by_user(self, user_id: UUID) -> Set[int]:
        return {ur.role_id for ur in self.db.query(UserRole).filter(UserRole.user_id == user_id).all()}

    def get_users_by_role(self, role_id: int) -> List[UserRole]:
        return self.db.query(UserRole).filter(UserRole.role_id == role_id).all()

    # ----------------- UPDATE -----------------
    def update_user_role(self, user_role_id: int, new_role_id: int) -> UserRole:
        assignment = self.get_user_role(user_role_id)

        # Remove from other roles
        self.db.query(UserRole).filter(UserRole.user_id == assignment.user_id, UserRole.role_id != new_role_id).delete()
        self.db.commit()

        # Update role
        assignment.role_id = new_role_id
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    # ----------------- DELETE / UNASSIGN -----------------
    def unassign_role_from_user_by_role(self, user_id: UUID, role_id: int) -> bool:
        user_role = self.db.query(UserRole).filter_by(user_id=user_id, role_id=role_id).first()
        if user_role:
            self.db.delete(user_role)
            self.db.commit()
        return True

    def unassign_role_from_user_by_id(self, user_role_id: int) -> bool:
        assignment = self.get_user_role(user_role_id)
        self.db.delete(assignment)
        self.db.commit()
        return True

    # ----------------- SYNC -----------------
    def sync_roles_for_user(self, user_id: UUID, new_role_ids: Set[int]):
        current_role_ids = self.get_roles_by_user(user_id)

        # Add new roles
        for role_id in new_role_ids - current_role_ids:
            self.assign_role_to_user(user_id, role_id)

        # Remove roles not in new_role_ids
        for role_id in current_role_ids - new_role_ids:
            self.unassign_role_from_user_by_role(user_id, role_id)

    # ----------------- LIST / FETCH -----------------
    def list_user_roles(self, skip: int = 0, limit: int = 100) -> List[UserRole]:
        return self.db.query(UserRole).offset(skip).limit(limit).all()

    def fetch_user_role_mappings(self):
        rows = self.db.query(UserRole).join(UserRole.user).join(UserRole.role).all()
        role_users_map = defaultdict(list)

        for ur in rows:
            email = ur.user.email
            role_name = ur.role.name
            if role_name not in role_users_map[email]:
                role_users_map[email].append(role_name)

        return [{"email": email, "roles": roles} for email, roles in role_users_map.items()]

    # ============================================================
    # ⭐ NEW: FETCH VENDOR ROLE ID (NO HARDCODE) ⭐
    # ============================================================
    def get_vendor_role_id(self) -> int:
        vendor = self.db.query(Role).filter(Role.name == "Vendor").first()
        if not vendor:
            raise ValueError("Vendor role not found in database.")
        return vendor.id
