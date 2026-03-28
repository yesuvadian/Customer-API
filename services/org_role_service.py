from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from typing import List, Optional, Dict
from fastapi import HTTPException, status

from models import OrgRole, Organization, Module, OrgRolePermission
from schemas import OrgRoleCreate, OrgRoleUpdate, PermissionSet
from utils.common_service import UTCDateTimeMixin


class OrgRoleService(UTCDateTimeMixin):
    def __init__(self, db: Session):
        self.db = db

    def create_role(
        self,
        role_data: OrgRoleCreate,
        created_by: Optional[UUID] = None
    ) -> OrgRole:
        """Create a new role within an organization."""
        # Verify org exists
        org = self.db.query(Organization).filter(
            Organization.id == role_data.organization_id
        ).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization with id '{role_data.organization_id}' not found"
            )

        try:
            role = OrgRole(
                organization_id=role_data.organization_id,
                name=role_data.name,
                description=role_data.description,
                role_type=role_data.role_type,
                is_org_admin=role_data.is_org_admin,
                is_dept_admin=role_data.is_dept_admin,
                is_active=role_data.is_active,
                created_by=created_by,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(role)
            self.db.commit()
            self.db.refresh(role)
            return role
        except IntegrityError as e:
            self.db.rollback()
            if "uq_org_role_name" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Role with name '{role_data.name}' already exists in this organization"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create role"
            )

    def get_role(self, role_id: UUID) -> OrgRole:
        """Get role by ID."""
        role = self.db.query(OrgRole).filter(OrgRole.id == role_id).first()
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with id '{role_id}' not found"
            )
        return role

    def get_role_by_name(
        self,
        organization_id: UUID,
        name: str
    ) -> Optional[OrgRole]:
        """Get role by name within an organization."""
        return self.db.query(OrgRole).filter(
            OrgRole.organization_id == organization_id,
            OrgRole.name == name
        ).first()

    def list_roles(
        self,
        organization_id: UUID,
        skip: int = 0,
        limit: Optional[int] = None,
        is_active: Optional[bool] = None,
        is_org_admin: Optional[bool] = None
    ) -> List[OrgRole]:
        """List roles in an organization."""
        query = self.db.query(OrgRole).filter(
            OrgRole.organization_id == organization_id
        )

        if is_active is not None:
            query = query.filter(OrgRole.is_active == is_active)

        if is_org_admin is not None:
            query = query.filter(OrgRole.is_org_admin == is_org_admin)

        query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def update_role(
        self,
        role_id: UUID,
        role_data: OrgRoleUpdate,
        modified_by: Optional[UUID] = None
    ) -> OrgRole:
        """Update role."""
        role = self.get_role(role_id)

        # Prevent modification of default roles' admin flags
        if role.role_type == "default":
            if role_data.is_org_admin is not None and role_data.is_org_admin != role.is_org_admin:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot modify admin flags of default roles"
                )

        update_data = role_data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(role, key, value)

        role.modified_by = modified_by
        role.mts = self._utc_now()

        try:
            self.db.commit()
            self.db.refresh(role)
            return role
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update role"
            )

    def delete_role(self, role_id: UUID) -> bool:
        """Soft delete role."""
        role = self.get_role(role_id)

        # Prevent deletion of default roles
        if role.role_type == "default":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete default roles"
            )

        role.is_active = False
        role.mts = self._utc_now()
        self.db.commit()
        return True

    def set_role_permissions(
        self,
        role_id: UUID,
        permissions: List[PermissionSet],
        created_by: Optional[UUID] = None
    ) -> List[OrgRolePermission]:
        """Set permissions for a role (replaces existing permissions)."""
        role = self.get_role(role_id)

        # Delete existing permissions
        self.db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id == role_id
        ).delete()

        # Create new permissions
        result_permissions = []
        for perm in permissions:
            # Verify module exists
            module = self.db.query(Module).filter(Module.id == perm.module_id).first()
            if not module:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Module with id '{perm.module_id}' not found"
                )

            role_perm = OrgRolePermission(
                org_role_id=role_id,
                module_id=perm.module_id,
                can_view=perm.can_view,
                can_add=perm.can_add,
                can_edit=perm.can_edit,
                can_delete=perm.can_delete,
                can_approve=perm.can_approve,
                can_assign=perm.can_assign,
                can_export=perm.can_export,
                can_import=perm.can_import,
                created_by=created_by,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(role_perm)
            result_permissions.append(role_perm)

        self.db.commit()
        return result_permissions

    def get_role_permissions(self, role_id: UUID) -> List[OrgRolePermission]:
        """Get all permissions for a role."""
        role = self.get_role(role_id)

        return self.db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id == role_id
        ).all()

    def update_role_permission(
        self,
        role_id: UUID,
        module_id: int,
        permission_data: Dict[str, bool],
        modified_by: Optional[UUID] = None
    ) -> OrgRolePermission:
        """Update a specific module permission for a role."""
        role = self.get_role(role_id)

        # Check if permission exists
        perm = self.db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id == role_id,
            OrgRolePermission.module_id == module_id
        ).first()

        if not perm:
            # Create new permission
            module = self.db.query(Module).filter(Module.id == module_id).first()
            if not module:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Module with id '{module_id}' not found"
                )

            perm = OrgRolePermission(
                org_role_id=role_id,
                module_id=module_id,
                created_by=modified_by,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(perm)

        # Update permission flags
        for key, value in permission_data.items():
            if hasattr(perm, key):
                setattr(perm, key, value)

        perm.modified_by = modified_by
        perm.mts = self._utc_now()

        self.db.commit()
        self.db.refresh(perm)
        return perm

    def check_user_permission(
        self,
        user_id: UUID,
        module_id: int,
        permission_type: str
    ) -> bool:
        """
        Check if user has a specific permission through their roles.
        permission_type: 'can_view', 'can_add', 'can_edit', 'can_delete', etc.
        """
        from models import OrgUserRole

        # Get user's active roles
        user_roles = self.db.query(OrgUserRole).filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active == True
        ).all()

        role_ids = [ur.org_role_id for ur in user_roles]

        if not role_ids:
            return False

        # Check if any role has the permission
        permission = self.db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id.in_(role_ids),
            OrgRolePermission.module_id == module_id
        ).first()

        if not permission:
            return False

        return getattr(permission, permission_type, False)

    def get_user_permissions(self, user_id: UUID) -> Dict[int, Dict[str, bool]]:
        """
        Get all permissions for a user across all their roles.
        Returns: {module_id: {permission_type: bool}}
        """
        from models import OrgUserRole

        # Get user's active roles
        user_roles = self.db.query(OrgUserRole).filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active == True
        ).all()

        role_ids = [ur.org_role_id for ur in user_roles]

        if not role_ids:
            return {}

        # Get all permissions for these roles
        permissions = self.db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id.in_(role_ids)
        ).all()

        # Aggregate permissions (OR logic - if any role has permission, user has it)
        result = {}
        for perm in permissions:
            if perm.module_id not in result:
                result[perm.module_id] = {
                    "can_view": False,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": False,
                    "can_import": False
                }

            # OR logic
            result[perm.module_id]["can_view"] |= perm.can_view
            result[perm.module_id]["can_add"] |= perm.can_add
            result[perm.module_id]["can_edit"] |= perm.can_edit
            result[perm.module_id]["can_delete"] |= perm.can_delete
            result[perm.module_id]["can_approve"] |= perm.can_approve
            result[perm.module_id]["can_assign"] |= perm.can_assign
            result[perm.module_id]["can_export"] |= perm.can_export
            result[perm.module_id]["can_import"] |= perm.can_import

        return result
