from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from fastapi import HTTPException, status

from models import Organization, OrgRole, User, OrgUserRole, RoleTemplate, OrgRolePermission, Module
from schemas import OrganizationCreate, OrganizationUpdate
from security_utils import get_password_hash
from utils.common_service import UTCDateTimeMixin


class OrganizationService(UTCDateTimeMixin):
    def __init__(self, db: Session):
        self.db = db

    def create_organization(
        self,
        org_data: OrganizationCreate,
        created_by: Optional[UUID] = None
    ) -> Organization:
        """Create a new organization."""
        try:
            org = Organization(
                name=org_data.name,
                code=org_data.code,
                display_name=org_data.display_name,
                organization_type=org_data.organization_type,
                industry=org_data.industry,
                website=org_data.website,
                primary_email=org_data.primary_email,
                primary_phone=org_data.primary_phone,
                plan_id=org_data.plan_id,
                is_active=org_data.is_active,
                settings=org_data.settings or {},
                created_by=created_by,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(org)
            self.db.commit()
            self.db.refresh(org)
            return org
        except IntegrityError as e:
            self.db.rollback()
            if "uq" in str(e) or "unique" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Organization with code '{org_data.code}' already exists"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create organization"
            )

    def create_organization_with_admin(
        self,
        name: str,
        code: str,
        admin_email: str,
        admin_password: str,
        admin_firstname: str,
        admin_lastname: str,
        admin_phone: str,
        **org_kwargs
    ) -> tuple[Organization, User]:
        """
        Create organization with default roles and admin user.
        Returns (organization, admin_user)
        """
        try:
            # 1. Create organization
            org = Organization(
                name=name,
                code=code,
                **org_kwargs,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(org)
            self.db.flush()

            # 2. Provision default roles from templates
            default_roles = self._provision_default_roles(org.id)
            self.db.flush()

            # 3. Create admin user
            admin_user = User(
                email=admin_email,
                password_hash=get_password_hash(admin_password),
                firstname=admin_firstname,
                lastname=admin_lastname,
                phone_number=admin_phone,
                organization_id=org.id,
                isactive=True,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(admin_user)
            self.db.flush()

            # 4. Assign Admin role to admin user
            admin_role = next((r for r in default_roles if r.is_org_admin), None)
            if admin_role:
                user_role = OrgUserRole(
                    user_id=admin_user.id,
                    org_role_id=admin_role.id,
                    assigned_by=admin_user.id,
                    is_active=True
                )
                self.db.add(user_role)

            self.db.commit()
            self.db.refresh(org)
            self.db.refresh(admin_user)
            return org, admin_user

        except IntegrityError as e:
            self.db.rollback()
            if "email" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Email '{admin_email}' already exists"
                )
            if "code" in str(e).lower() or "organizations_code" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Organization code '{code}' already exists"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create organization with admin"
            )

    def _provision_default_roles(self, org_id: UUID) -> List[OrgRole]:
        """
        Provision default roles from templates for a new organization.
        """
        templates = self.db.query(RoleTemplate)\
            .filter(RoleTemplate.auto_provision == True)\
            .all()

        roles = []
        for template in templates:
            role = OrgRole(
                organization_id=org_id,
                name=template.name,
                description=template.description,
                role_type="default",
                is_org_admin=template.is_org_admin,
                is_dept_admin=template.is_dept_admin,
                is_active=True,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(role)
            self.db.flush()

            # Create permissions from template
            if template.permissions_template:
                for perm_data in template.permissions_template:
                    permission = OrgRolePermission(
                        org_role_id=role.id,
                        module_id=perm_data.get("module_id"),
                        can_view=perm_data.get("can_view", False),
                        can_add=perm_data.get("can_add", False),
                        can_edit=perm_data.get("can_edit", False),
                        can_delete=perm_data.get("can_delete", False),
                        can_approve=perm_data.get("can_approve", False),
                        can_assign=perm_data.get("can_assign", False),
                        can_export=perm_data.get("can_export", False),
                        can_import=perm_data.get("can_import", False),
                        cts=self._utc_now(),
                        mts=self._utc_now()
                    )
                    self.db.add(permission)

            roles.append(role)

        return roles

    def get_organization(self, org_id: UUID) -> Optional[Organization]:
        """Get organization by ID."""
        org = self.db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization with id '{org_id}' not found"
            )
        return org

    def get_organization_by_code(self, code: str) -> Optional[Organization]:
        """Get organization by code."""
        return self.db.query(Organization).filter(Organization.code == code).first()

    def list_organizations(
        self,
        skip: int = 0,
        limit: int = 100,
        is_active: Optional[bool] = None
    ) -> List[Organization]:
        """List all organizations with optional filtering."""
        query = self.db.query(Organization)

        if is_active is not None:
            query = query.filter(Organization.is_active == is_active)

        return query.offset(skip).limit(limit).all()

    def update_organization(
        self,
        org_id: UUID,
        org_data: OrganizationUpdate,
        modified_by: Optional[UUID] = None
    ) -> Organization:
        """Update organization."""
        org = self.get_organization(org_id)

        update_data = org_data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(org, key, value)

        org.modified_by = modified_by
        org.mts = self._utc_now()

        try:
            self.db.commit()
            self.db.refresh(org)
            return org
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update organization"
            )

    def delete_organization(self, org_id: UUID) -> bool:
        """Soft delete organization by setting is_active to False."""
        org = self.get_organization(org_id)
        org.is_active = False
        org.mts = self._utc_now()
        self.db.commit()
        return True

    def verify_organization(
        self,
        org_id: UUID,
        verified_by: UUID
    ) -> Organization:
        """Verify an organization."""
        org = self.get_organization(org_id)
        org.is_verified = True
        org.modified_by = verified_by
        org.mts = self._utc_now()
        self.db.commit()
        self.db.refresh(org)
        return org
