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

            # 2b. Clone PermissionMatrix entries so new org gets workflow permissions
            self._provision_workflow_permissions(org.id, default_roles)

            # 2c. Provision all stage workflows for new org
            self._provision_all_workflows(org.id)

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
        Provision default roles for a new org from RoleTemplate (auto_provision=True).
        All canonical roles live in role_templates — KPTCL is a customer org, not a template.
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
            if template.permissions_template:
                for perm_data in template.permissions_template:
                    self.db.add(OrgRolePermission(
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
                    ))
            roles.append(role)
        return roles

    def _provision_workflow_permissions(self, org_id: UUID, new_roles: list) -> None:
        """
        For each newly created OrgRole, copy PermissionMatrix entries from
        any existing role with the same name (seeded by seed_tr_workflows).
        This ensures new orgs get workflow transition permissions matching
        their role names without needing to re-run the global seed.
        """
        try:
            from models import Workflow, WorkflowTransition, PermissionMatrix, OrgRole

            # Build name → new_role_id map for roles just created
            name_to_new_role = {r.name: r.id for r in new_roles}

            # Find existing PermissionMatrix entries for roles with matching names
            # (from other orgs that were seeded already)
            existing_roles = (
                self.db.query(OrgRole)
                .filter(
                    OrgRole.name.in_(list(name_to_new_role.keys())),
                    OrgRole.organization_id != org_id,
                    OrgRole.is_active.is_(True),
                )
                .all()
            )
            if not existing_roles:
                return

            # For each existing role, clone its PermissionMatrix rows to the new role
            seen = set()
            for existing_role in existing_roles:
                new_role_id = name_to_new_role.get(existing_role.name)
                if not new_role_id:
                    continue

                pm_rows = (
                    self.db.query(PermissionMatrix)
                    .filter(
                        PermissionMatrix.role_id == existing_role.id,
                        PermissionMatrix.is_active.is_(True),
                    )
                    .all()
                )
                for pm in pm_rows:
                    key = (pm.transition_id, new_role_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    # Check not already exists
                    exists = (
                        self.db.query(PermissionMatrix)
                        .filter_by(transition_id=pm.transition_id, role_id=new_role_id)
                        .first()
                    )
                    if not exists:
                        self.db.add(PermissionMatrix(
                            workflow_id=pm.workflow_id,
                            transition_id=pm.transition_id,
                            role_id=new_role_id,
                            scope_type=pm.scope_type,
                            department_type_id=pm.department_type_id,
                            can_execute=pm.can_execute,
                            can_reject=pm.can_reject,
                            can_comment=pm.can_comment,
                            priority=pm.priority,
                            is_active=True,
                        ))
        except Exception as e:
            print(f"[WARN] _provision_workflow_permissions failed: {e}")

    def _provision_all_workflows(self, org_id: UUID) -> None:
        """
        Provision all stage workflows for a new org.
        Each seed function is org-aware and idempotent.
        """
        import traceback
        from models import Organization as OrgModel

        org = self.db.query(OrgModel).filter_by(id=org_id).first()

        def _run(label, fn, *args, **kwargs):
            try:
                fn(*args, **kwargs)
                print(f"[INFO] {label} provisioned for org {org_id}")
            except Exception as e:
                print(f"[WARN] {label} failed (non-fatal): {e}\n{traceback.format_exc()}")

        from seed_tr_wf_workflow import seed_tr_wf_workflow
        _run("TR workflow", seed_tr_wf_workflow, self.db, org=org)

        from seed_overhaul_workflow import seed_overhaul_role_mappings
        _run("Overhaul role mappings", seed_overhaul_role_mappings, self.db, org_id)

        from seed_calibration_workflow import seed_calibration_role_mappings
        _run("Calibration role mappings", seed_calibration_role_mappings, self.db, org_id)

        from seed_surveillance_workflow import seed_surveillance_role_mappings
        _run("Surveillance role mappings", seed_surveillance_role_mappings, self.db, org_id)

        from seed_precommission_workflow import seed_precommission_role_mappings
        _run("Pre-commission role mappings", seed_precommission_role_mappings, self.db, org_id)

        from seed_annual_audit import seed_annual_audit_role_mappings
        _run("Annual audit role mappings", seed_annual_audit_role_mappings, self.db, org_id)

        from seed_doc_support_workflow import seed_doc_support_workflow
        _run("Doc support workflow", seed_doc_support_workflow, self.db, org=org)

        from seed_repair_workflow import seed_repair_role_mappings
        _run("Repair role mappings", seed_repair_role_mappings, self.db, org_id)

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
        limit: Optional[int] = None,
        is_active: Optional[bool] = None
    ) -> List[Organization]:
        """List all organizations with optional filtering."""
        query = self.db.query(Organization)

        if is_active is not None:
            query = query.filter(Organization.is_active == is_active)

        query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

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
