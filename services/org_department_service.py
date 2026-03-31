from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from typing import List, Optional
from fastapi import HTTPException, status

from models import OrgDepartment, Organization, User
from schemas import OrgDepartmentCreate, OrgDepartmentUpdate
from utils.common_service import UTCDateTimeMixin


class OrgDepartmentService(UTCDateTimeMixin):
    def __init__(self, db: Session):
        self.db = db

    def create_department(
        self,
        dept_data: OrgDepartmentCreate,
        created_by: Optional[UUID] = None
    ) -> OrgDepartment:
        """Create a new department within an organization."""
        # Verify org exists
        org = self.db.query(Organization).filter(
            Organization.id == dept_data.organization_id
        ).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization with id '{dept_data.organization_id}' not found"
            )

        # Verify parent department exists if provided
        if dept_data.parent_department_id:
            parent = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == dept_data.parent_department_id,
                OrgDepartment.organization_id == dept_data.organization_id
            ).first()
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent department not found in this organization"
                )

        # Verify manager exists if provided
        if dept_data.manager_id:
            manager = self.db.query(User).filter(
                User.id == dept_data.manager_id,
                User.organization_id == dept_data.organization_id
            ).first()
            if not manager:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Manager not found in this organization"
                )

        # Duplicate name check: same name under same parent within the org
        duplicate_query = self.db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == dept_data.organization_id,
            OrgDepartment.name.ilike(dept_data.name),
            OrgDepartment.is_active == True
        )
        if dept_data.parent_department_id:
            duplicate_query = duplicate_query.filter(
                OrgDepartment.parent_department_id == dept_data.parent_department_id
            )
        else:
            duplicate_query = duplicate_query.filter(
                OrgDepartment.parent_department_id == None
            )
        existing = duplicate_query.first()
        if existing:
            if dept_data.parent_department_id:
                parent = self.db.query(OrgDepartment).filter(
                    OrgDepartment.id == dept_data.parent_department_id
                ).first()
                parent_label = f"under '{parent.name}'" if parent else "under the same parent"
            else:
                parent_label = "at the root level"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A department named '{dept_data.name}' already exists {parent_label}"
            )

        try:
            dept = OrgDepartment(
                organization_id=dept_data.organization_id,
                name=dept_data.name,
                code=dept_data.code,
                description=dept_data.description,
                parent_department_id=dept_data.parent_department_id,
                manager_id=dept_data.manager_id,
                is_active=dept_data.is_active,
                created_by=created_by,
                cts=self._utc_now(),
                mts=self._utc_now()
            )
            self.db.add(dept)
            self.db.commit()
            self.db.refresh(dept)
            return dept
        except IntegrityError as e:
            self.db.rollback()
            if "uq_org_dept_name_per_parent" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"A department named '{dept_data.name}' already exists under the same parent"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create department"
            )

    def get_department(self, dept_id: UUID) -> OrgDepartment:
        """Get department by ID."""
        dept = self.db.query(OrgDepartment).filter(OrgDepartment.id == dept_id).first()
        if not dept:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with id '{dept_id}' not found"
            )
        return dept

    def list_departments(
        self,
        organization_id: UUID,
        skip: int = 0,
        limit: Optional[int] = None,
        is_active: Optional[bool] = None,
        parent_department_id: Optional[UUID] = None
    ) -> List[OrgDepartment]:
        """List departments in an organization."""
        query = self.db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == organization_id
        )

        if is_active is not None:
            query = query.filter(OrgDepartment.is_active == is_active)

        if parent_department_id is not None:
            query = query.filter(OrgDepartment.parent_department_id == parent_department_id)

        query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)

        return query.all()

    def update_department(
        self,
        dept_id: UUID,
        dept_data: OrgDepartmentUpdate,
        modified_by: Optional[UUID] = None
    ) -> OrgDepartment:
        """Update department."""
        dept = self.get_department(dept_id)

        # Verify manager exists in same org if provided
        if dept_data.manager_id:
            manager = self.db.query(User).filter(
                User.id == dept_data.manager_id,
                User.organization_id == dept.organization_id
            ).first()
            if not manager:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Manager not found in this organization"
                )

        # Duplicate name check on update: same name, same parent level, same org, different dept
        new_name = dept_data.name if dept_data.name is not None else dept.name
        new_parent_id = dept_data.parent_department_id if hasattr(dept_data, 'parent_department_id') and 'parent_department_id' in dept_data.dict(exclude_unset=True) else dept.parent_department_id
        dup_query = self.db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == dept.organization_id,
            OrgDepartment.name.ilike(new_name),
            OrgDepartment.id != dept_id,
            OrgDepartment.is_active == True
        )
        if new_parent_id:
            dup_query = dup_query.filter(OrgDepartment.parent_department_id == new_parent_id)
        else:
            dup_query = dup_query.filter(OrgDepartment.parent_department_id == None)
        if dup_query.first():
            if new_parent_id:
                parent_obj = self.db.query(OrgDepartment).filter(
                    OrgDepartment.id == new_parent_id
                ).first()
                parent_label = f"under '{parent_obj.name}'" if parent_obj else "under the same parent"
            else:
                parent_label = "at the root level"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A department named '{new_name}' already exists {parent_label}"
            )

        # Verify parent department if provided
        if dept_data.parent_department_id:
            # Prevent circular reference
            if dept_data.parent_department_id == dept_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Department cannot be its own parent"
                )

            parent = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == dept_data.parent_department_id,
                OrgDepartment.organization_id == dept.organization_id
            ).first()
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent department not found in this organization"
                )

        update_data = dept_data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(dept, key, value)

        dept.modified_by = modified_by
        dept.mts = self._utc_now()

        try:
            self.db.commit()
            self.db.refresh(dept)
            return dept
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update department"
            )

    def delete_department(self, dept_id: UUID) -> bool:
        """Soft delete department."""
        dept = self.get_department(dept_id)

        # Check if department has sub-departments
        has_children = self.db.query(OrgDepartment).filter(
            OrgDepartment.parent_department_id == dept_id,
            OrgDepartment.is_active == True
        ).first()

        if has_children:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete department with active sub-departments"
            )

        dept.is_active = False
        dept.mts = self._utc_now()
        self.db.commit()
        return True

    def assign_users_to_department(
        self,
        dept_id: UUID,
        user_ids: List[UUID]
    ) -> int:
        """Assign multiple users to a department."""
        dept = self.get_department(dept_id)

        # Verify all users exist and belong to same org
        users = self.db.query(User).filter(
            User.id.in_(user_ids),
            User.organization_id == dept.organization_id
        ).all()

        if len(users) != len(user_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Some users not found in this organization"
            )

        # Update users
        for user in users:
            user.department_id = dept_id
            user.mts = self._utc_now()

        self.db.commit()
        return len(users)

    def get_department_users(
        self,
        dept_id: UUID,
        skip: int = 0,
        limit: int = 100
    ) -> List[User]:
        """Get all users in a department."""
        dept = self.get_department(dept_id)

        return self.db.query(User).filter(
            User.department_id == dept_id,
            User.isactive == True
        ).offset(skip).limit(limit).all()
