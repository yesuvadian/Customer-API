from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from typing import List, Optional
from fastapi import HTTPException, status

from models import User, Organization, OrgDepartment, OrgRole, OrgUserRole
from schemas import OrgUserCreate, OrgUserUpdate, OrgUserWithRoles, OrgUserRoleInfo
from security_utils import get_password_hash
from utils.common_service import UTCDateTimeMixin


class OrgUserService(UTCDateTimeMixin):
    def __init__(self, db: Session):
        self.db = db

    def create_org_user(
        self,
        organization_id: UUID,
        user_data: OrgUserCreate,
        created_by: Optional[UUID] = None
    ) -> User:
        """
        Create a user within an organization.
        Optionally assign to department and roles.
        """
        # Verify org exists
        org = self.db.query(Organization).filter(
            Organization.id == organization_id
        ).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization with id '{organization_id}' not found"
            )

        # Check if email already exists
        existing_email = self.db.query(User).filter(User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{user_data.email}' already exists"
            )

        # Check if phone already exists
        existing_phone = self.db.query(User).filter(
            User.phone_number == user_data.phone_number
        ).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phone number '{user_data.phone_number}' already exists"
            )

        # Verify department exists in same org if provided
        if user_data.department_id:
            dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == user_data.department_id,
                OrgDepartment.organization_id == organization_id
            ).first()
            if not dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Department not found in this organization"
                )

        try:
            # Create user
            user = User(
                email=user_data.email,
                password_hash=get_password_hash(user_data.password),
                firstname=user_data.firstname,
                lastname=user_data.lastname,
                phone_number=user_data.phone_number,
                organization_id=organization_id,
                employee_id=user_data.employee_id,
                department_id=user_data.department_id,
                isactive=user_data.isactive,
                created_by=created_by,
                cts=self._utc_now(),
                mts=self._utc_now()
            )

            self.db.add(user)
            self.db.flush()

            # Assign roles if provided
            if user_data.role_ids:
                for role_id in user_data.role_ids:
                    # Verify role exists in same org
                    role = self.db.query(OrgRole).filter(
                        OrgRole.id == role_id,
                        OrgRole.organization_id == organization_id
                    ).first()
                    if not role:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Role '{role_id}' not found in this organization"
                        )

                    user_role = OrgUserRole(
                        user_id=user.id,
                        org_role_id=role_id,
                        department_id=user_data.department_id,
                        assigned_by=created_by,
                        is_active=True
                    )
                    self.db.add(user_role)

            self.db.commit()
            self.db.refresh(user)
            return user

        except IntegrityError as e:
            self.db.rollback()
            if "email" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Email '{user_data.email}' already exists"
                )
            if "phone" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Phone number already exists"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user"
            )

    def get_org_user(self, user_id: UUID, organization_id: UUID) -> User:
        """Get user by ID within an organization."""
        user = self.db.query(User).filter(
            User.id == user_id,
            User.organization_id == organization_id
        ).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in this organization"
            )
        return user

    def get_org_user_with_roles(self, user_id: UUID, organization_id: UUID) -> OrgUserWithRoles:
        """Get user by ID with role information."""
        user = self.get_org_user(user_id, organization_id)

        # Get user's roles
        user_roles = self.db.query(OrgUserRole).join(
            OrgRole, OrgUserRole.org_role_id == OrgRole.id
        ).filter(
            OrgUserRole.user_id == user.id,
            OrgUserRole.is_active == True
        ).all()

        # Build role info list
        role_infos = []
        for user_role in user_roles:
            role = self.db.query(OrgRole).filter(OrgRole.id == user_role.org_role_id).first()
            if role:
                role_infos.append(OrgUserRoleInfo(
                    role_id=role.id,
                    role_name=role.name,
                    is_org_admin=role.is_org_admin,
                    is_dept_admin=role.is_dept_admin,
                    department_id=user_role.department_id,
                    is_active=user_role.is_active
                ))

        # Create user with roles
        return OrgUserWithRoles(
            id=user.id,
            email=user.email,
            firstname=user.firstname,
            lastname=user.lastname,
            phone_number=user.phone_number,
            organization_id=user.organization_id,
            employee_id=user.employee_id,
            department_id=user.department_id,
            isactive=user.isactive,
            usertype=user.usertype,
            email_confirmed=user.email_confirmed,
            phone_confirmed=user.phone_confirmed,
            cts=user.cts,
            mts=user.mts,
            roles=role_infos
        )

    def list_org_users(
        self,
        organization_id: UUID,
        department_id: Optional[UUID] = None,
        skip: int = 0,
        limit: Optional[int] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> List[User]:
        """List users in an organization."""
        query = self.db.query(User).filter(User.organization_id == organization_id)

        if department_id:
            query = query.filter(User.department_id == department_id)

        if is_active is not None:
            query = query.filter(User.isactive == is_active)

        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (User.email.ilike(search_pattern)) |
                (User.firstname.ilike(search_pattern)) |
                (User.lastname.ilike(search_pattern)) |
                (User.employee_id.ilike(search_pattern))
            )

        query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)

        return query.all()

    def list_org_users_with_roles(
        self,
        organization_id: UUID,
        department_id: Optional[UUID] = None,
        skip: int = 0,
        limit: Optional[int] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> List[OrgUserWithRoles]:
        """List users in an organization with their role information."""
        # Get users
        users = self.list_org_users(
            organization_id=organization_id,
            department_id=department_id,
            skip=skip,
            limit=limit,
            is_active=is_active,
            search=search
        )

        # Build response with roles
        result = []
        for user in users:
            # Get user's roles
            user_roles = self.db.query(OrgUserRole).join(
                OrgRole, OrgUserRole.org_role_id == OrgRole.id
            ).filter(
                OrgUserRole.user_id == user.id,
                OrgUserRole.is_active == True
            ).all()

            # Build role info list
            role_infos = []
            for user_role in user_roles:
                role = self.db.query(OrgRole).filter(OrgRole.id == user_role.org_role_id).first()
                if role:
                    role_infos.append(OrgUserRoleInfo(
                        role_id=role.id,
                        role_name=role.name,
                        is_org_admin=role.is_org_admin,
                        is_dept_admin=role.is_dept_admin,
                        department_id=user_role.department_id,
                        is_active=user_role.is_active
                    ))

            # Create user with roles
            user_with_roles = OrgUserWithRoles(
                id=user.id,
                email=user.email,
                firstname=user.firstname,
                lastname=user.lastname,
                phone_number=user.phone_number,
                organization_id=user.organization_id,
                employee_id=user.employee_id,
                department_id=user.department_id,
                isactive=user.isactive,
                usertype=user.usertype,
                email_confirmed=user.email_confirmed,
                phone_confirmed=user.phone_confirmed,
                cts=user.cts,
                mts=user.mts,
                roles=role_infos
            )
            result.append(user_with_roles)

        return result

    def update_org_user(
        self,
        user_id: UUID,
        organization_id: UUID,
        user_data: OrgUserUpdate,
        modified_by: Optional[UUID] = None
    ) -> User:
        """Update user in organization."""
        user = self.get_org_user(user_id, organization_id)

        # Verify department if provided
        if user_data.department_id:
            dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == user_data.department_id,
                OrgDepartment.organization_id == organization_id
            ).first()
            if not dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Department not found in this organization"
                )

        update_data = user_data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(user, key, value)

        user.modified_by = modified_by
        user.mts = self._utc_now()

        try:
            self.db.commit()
            self.db.refresh(user)
            return user
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update user"
            )

    def delete_org_user(self, user_id: UUID, organization_id: UUID) -> bool:
        """Soft delete user in organization."""
        user = self.get_org_user(user_id, organization_id)
        user.isactive = False
        user.mts = self._utc_now()
        self.db.commit()
        return True

    def assign_role_to_user(
        self,
        user_id: UUID,
        organization_id: UUID,
        org_role_id: UUID,
        department_id: Optional[UUID] = None,
        assigned_by: Optional[UUID] = None
    ) -> OrgUserRole:
        """Assign a role to a user."""
        # Verify user exists in org
        user = self.get_org_user(user_id, organization_id)

        # Verify role exists in org
        role = self.db.query(OrgRole).filter(
            OrgRole.id == org_role_id,
            OrgRole.organization_id == organization_id
        ).first()
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found in this organization"
            )

        # Verify department if provided
        if department_id:
            dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == department_id,
                OrgDepartment.organization_id == organization_id
            ).first()
            if not dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Department not found in this organization"
                )

        # Check if assignment already exists
        existing = self.db.query(OrgUserRole).filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.org_role_id == org_role_id,
            OrgUserRole.department_id == department_id
        ).first()

        if existing:
            if existing.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User already has this role"
                )
            else:
                # Reactivate
                existing.is_active = True
                existing.assigned_by = assigned_by
                self.db.commit()
                self.db.refresh(existing)
                return existing

        try:
            user_role = OrgUserRole(
                user_id=user_id,
                org_role_id=org_role_id,
                department_id=department_id,
                assigned_by=assigned_by,
                is_active=True
            )
            self.db.add(user_role)
            self.db.commit()
            self.db.refresh(user_role)
            return user_role
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to assign role"
            )

    def remove_role_from_user(
        self,
        user_id: UUID,
        organization_id: UUID,
        org_role_id: UUID,
        department_id: Optional[UUID] = None
    ) -> bool:
        """Remove a role from a user."""
        # Verify user exists in org
        self.get_org_user(user_id, organization_id)

        user_role = self.db.query(OrgUserRole).filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.org_role_id == org_role_id,
            OrgUserRole.department_id == department_id
        ).first()

        if not user_role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role assignment not found"
            )

        user_role.is_active = False
        self.db.commit()
        return True

    def get_user_roles(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> List[OrgUserRole]:
        """Get all roles assigned to a user."""
        # Verify user exists in org
        self.get_org_user(user_id, organization_id)

        return self.db.query(OrgUserRole).filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active == True
        ).all()
