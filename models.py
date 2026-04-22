
from enum import Enum as PyEnum
from sqlalchemy import Enum

import uuid
from sqlalchemy import (
    Column, Float, LargeBinary, Numeric, String, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint, func,Text
)
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB, ARRAY
from sqlalchemy.orm import relationship
from database import Base
from utils.common_service import UTCDateTimeMixin
import uuid
from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


#Base = declarative_base()

class AddressTypeEnum(PyEnum):
    office = "office"
    communication = "communication"
    registered = "registered"
    corporate = "corporate"
    billing = "billing"
    shipping = "shipping"
    factory = "factory"
    warehouse = "warehouse"
    other = "other"


class TaxStatusEnum(PyEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"

class BankStatusEnum(PyEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class ScheduleFrequency(PyEnum):
    daily = "daily"
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class ScheduleLogStatus(PyEnum):
    success = "success"
    failed = "failed"


class TestingRequestStatus(PyEnum):
    draft = "draft"
    submitted = "submitted"
    pending_approval = "pending_approval"
    assigned = "assigned"
    accepted = "accepted"
    scheduled = "scheduled"  # NEW: Test is scheduled for future date
    in_progress = "in_progress"
    test_submitted = "test_submitted"
    under_approval = "under_approval"
    approved = "approved"
    rejected = "rejected"
    procurement_initiated = "procurement_initiated"
    completed = "completed"

class RecommendationType(PyEnum):
    pass_test = "pass"
    fail = "fail"
    conditional = "conditional"
    retest = "retest"


class EquipmentStatus(PyEnum):
    active = "active"
    retired = "retired"
    scrapped = "scrapped"
    under_repair = "under_repair"


class RequestCategory(PyEnum):
    test = "test"
    maintenance = "maintenance"
    inspection = "inspection"
    repair_lifecycle = "repair_lifecycle"


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    planname = Column(String, nullable=False, unique=True)
    plan_description = Column(String)
    plan_limit = Column(Integer, nullable=False, default=0)
    isactive = Column(Boolean, default=True)

    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)

    # ✅ Relationship: one plan can have many users
    users = relationship(
        "User",
        back_populates="plan",
        foreign_keys=lambda: [User.plan_id]
    )
    # Relationship: one plan can have many organizations
    organizations = relationship(
        "Organization",
        back_populates="plan",
        foreign_keys=lambda: [Organization.plan_id]
    )


# ------------------------------
# Organization Model
# ------------------------------
class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(255))

    organization_type = Column(String(50))  # "vendor", "customer", "partner", "internal"
    industry = Column(String(100))
    website = Column(String(255))

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    plan_id = Column(UUID(as_uuid=True), ForeignKey("public.plans.id"), nullable=True)
    subscription_start_date = Column(DateTime(timezone=True))
    subscription_end_date = Column(DateTime(timezone=True))

    primary_email = Column(String(255))
    primary_phone = Column(String(50))

    # Address fields
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100))
    pincode = Column(String(20))

    settings = Column(JSONB, default={})

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True))
    erp_error_message = Column(Text)
    erp_external_id = Column(String(255))

    # Relationships
    plan = relationship("Plan", back_populates="organizations", foreign_keys=[plan_id])
    users = relationship("User", back_populates="organization", foreign_keys=lambda: [User.organization_id])
    department_types = relationship("OrgDepartmentType", back_populates="organization", cascade="all, delete-orphan")
    departments = relationship("OrgDepartment", back_populates="organization", cascade="all, delete-orphan")
    roles = relationship("OrgRole", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("OrgInvitation", back_populates="organization", cascade="all, delete-orphan")


# ------------------------------
# Organization Department Type Model
# ------------------------------
class OrgDepartmentType(Base):
    __tablename__ = "org_department_types"
    __table_args__ = (
        UniqueConstraint("organization_id", "type_code", name="uq_org_dept_type_code"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)

    type_name = Column(String(100), nullable=False)
    type_code = Column(String(50), nullable=False)
    description = Column(Text)
    icon = Column(String(100))
    color = Column(String(50))
    display_order = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organization = relationship("Organization", back_populates="department_types")


# ------------------------------
# Organization Department Model
# ------------------------------
class OrgDepartment(Base):
    __tablename__ = "org_departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "parent_department_id", "name", name="uq_org_dept_name_per_parent"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    code = Column(String(100))
    description = Column(Text)

    parent_department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id", ondelete="SET NULL"))
    manager_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))

    is_active = Column(Boolean, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True))
    erp_error_message = Column(Text)
    erp_external_id = Column(String(255))

    # Relationships
    organization = relationship("Organization", back_populates="departments")
    users = relationship("User", back_populates="department", foreign_keys=lambda: [User.department_id])
    manager = relationship("User", foreign_keys=[manager_id], post_update=True)
    parent_department = relationship("OrgDepartment", remote_side=[id], foreign_keys=[parent_department_id])
    sub_departments = relationship("OrgDepartment", back_populates="parent_department", foreign_keys=[parent_department_id], remote_side=[parent_department_id])
    user_roles = relationship("OrgUserRole", back_populates="department", cascade="all, delete-orphan")
    equipment = relationship("Equipment", back_populates="department", cascade="all, delete-orphan")


# ------------------------------
# Equipment Asset Register Model
# ------------------------------
class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (
        UniqueConstraint("ueic", name="uq_equipment_ueic"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ueic = Column(String(50), unique=True, nullable=False)  # Auto-generated: BZ-PNYA-220-01-CB-01

    # Location — linked to department hierarchy (substation level)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id", ondelete="CASCADE"), nullable=False)

    # Classification
    equipment_type_id = Column(Integer, ForeignKey("public.CategoryMaster.id"), nullable=False)

    # UEIC components
    voltage_class = Column(String(10), nullable=True)   # "400", "220", "110", "66"
    bay_number = Column(String(10), nullable=True)       # "01", "02"
    serial_in_bay = Column(String(10), nullable=True)    # "01"

    # Nameplate data — dynamic JSONB (template-driven, same pattern as OrgTestTemplate)
    nameplate_data = Column(JSONB, nullable=True)

    # Lifecycle
    status = Column(Enum(EquipmentStatus), default=EquipmentStatus.active, nullable=False)
    replaces_equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment.id"), nullable=True)
    commissioned_date = Column(DateTime(timezone=True), nullable=True)
    retired_date = Column(DateTime(timezone=True), nullable=True)
    retirement_reason = Column(Text, nullable=True)

    # Manufacturer / identity (quick-access fields from nameplate_data)
    manufacturer = Column(String(255), nullable=True)
    model_number = Column(String(255), nullable=True)
    factory_serial_number = Column(String(100), nullable=True)
    year_of_manufacture = Column(Integer, nullable=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organization = relationship("Organization", foreign_keys=[organization_id])
    department = relationship("OrgDepartment", back_populates="equipment", foreign_keys=[department_id])
    equipment_type = relationship("CategoryMaster", foreign_keys=[equipment_type_id])
    replaces_equipment = relationship("Equipment", remote_side=[id], foreign_keys=[replaces_equipment_id])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])


# ------------------------------
# Organization Role Model
# ------------------------------
class OrgRole(Base):
    __tablename__ = "org_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_org_role_name"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(100), nullable=False)
    description = Column(Text)
    role_type = Column(String(50), default="custom")  # "default", "custom", "system"

    is_org_admin = Column(Boolean, default=False)
    is_dept_admin = Column(Boolean, default=False)
    is_tester_assignable = Column(Boolean, default=False)  # Can this role be assigned as tester in testing requests
    is_active = Column(Boolean, default=True)
    default_module_id = Column(Integer, ForeignKey("public.modules.id"), nullable=True)  # Default module to navigate on login

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organization = relationship("Organization", back_populates="roles")
    user_roles = relationship("OrgUserRole", back_populates="org_role", cascade="all, delete-orphan")
    permissions = relationship("OrgRolePermission", back_populates="org_role", cascade="all, delete-orphan")
    default_module = relationship("Module", foreign_keys=[default_module_id])


# ------------------------------
# Organization User Role Model
# ------------------------------
class OrgUserRole(Base):
    __tablename__ = "org_user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "org_role_id", "department_id", name="uq_user_org_role"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    org_role_id = Column(UUID(as_uuid=True), ForeignKey("public.org_roles.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id", ondelete="CASCADE"))

    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="org_user_roles")
    org_role = relationship("OrgRole", back_populates="user_roles")
    department = relationship("OrgDepartment", back_populates="user_roles", foreign_keys=[department_id])
    assigner = relationship("User", foreign_keys=[assigned_by], post_update=True)


# ------------------------------
# Organization Role Permission Model
# ------------------------------
class OrgRolePermission(Base):
    __tablename__ = "org_role_permissions"
    __table_args__ = (
        UniqueConstraint("org_role_id", "module_id", name="uq_org_role_module"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_role_id = Column(UUID(as_uuid=True), ForeignKey("public.org_roles.id", ondelete="CASCADE"), nullable=False)
    module_id = Column(Integer, ForeignKey("public.modules.id", ondelete="CASCADE"), nullable=False)

    can_view = Column(Boolean, default=False)
    can_add = Column(Boolean, default=False)
    can_edit = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    can_approve = Column(Boolean, default=False)
    can_assign = Column(Boolean, default=False)
    can_export = Column(Boolean, default=False)
    can_import = Column(Boolean, default=False)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    org_role = relationship("OrgRole", back_populates="permissions")
    module = relationship("Module", foreign_keys=[module_id])


# ------------------------------
# Role Template Model (System-level)
# ------------------------------
class RoleTemplate(Base):
    __tablename__ = "role_templates"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)

    is_org_admin = Column(Boolean, default=False)
    is_dept_admin = Column(Boolean, default=False)
    auto_provision = Column(Boolean, default=False)
    default_module_id = Column(Integer, ForeignKey("public.modules.id"), nullable=True)  # Default landing module

    permissions_template = Column(JSONB, default=[])

    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ------------------------------
# Organization Invitation Model
# ------------------------------
class OrgInvitation(Base):
    __tablename__ = "org_invitations"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", "status", name="uq_org_invitation_email"),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)

    email = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))

    org_role_id = Column(UUID(as_uuid=True), ForeignKey("public.org_roles.id"), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id"), nullable=True)

    invitation_token = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    status = Column(String(20), default="pending")  # pending, accepted, expired, revoked
    accepted_at = Column(DateTime(timezone=True))
    accepted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))

    invited_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    cts = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    organization = relationship("Organization", back_populates="invitations")
    org_role = relationship("OrgRole", foreign_keys=[org_role_id])
    department = relationship("OrgDepartment", foreign_keys=[department_id])
    inviter = relationship("User", foreign_keys=[invited_by], post_update=True)
    accepted_by_user = relationship("User", foreign_keys=[accepted_by_user_id], post_update=True)


class UserAddress(Base):
    __tablename__ = "user_addresses"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "address_type", "is_primary",
            name="user_addresses_user_id_address_type_is_primary_key"
        ),
        {"schema": "public"}
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    address_type = Column(Enum(AddressTypeEnum), nullable=False)
    is_primary = Column(Boolean, default=False)
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255))
    city_id = Column(Integer, ForeignKey("public.cities.id", ondelete="SET NULL"))  # <-- changed
    state_id = Column(Integer, ForeignKey("public.states.id", ondelete="SET NULL"))
    country_id = Column(Integer, ForeignKey("public.countries.id", ondelete="SET NULL"))
    postal_code = Column(String(20))
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))

    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)
    mts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)

    # Relationships
    user = relationship("User", back_populates="addresses", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])
    state = relationship("State", foreign_keys=[state_id])
    country = relationship("Country", foreign_keys=[country_id])
    city = relationship("City", back_populates="addresses")  # <-- new relationship

# ------------------------------
# User Model
# ------------------------------
class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String)
    firstname = Column(String)
    lastname = Column(String)
    phone_number = Column(String, nullable=False)
    is_quick_registered = Column(Boolean, default=False)
    isactive = Column(Boolean, default=True)
    email_confirmed = Column(Boolean, default=False)
    phone_confirmed = Column(Boolean, default=False)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # inside User class
    erp_sync_status = Column(String(10), default="pending")      # pending | success | failed
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
        # ✅ Nullable usertype
    usertype = Column(String(50), nullable=True)
      # ✅ NEW COLUMN
    zoho_erp_id = Column(String(255), nullable=True)
    # ✅ Plan FK
    plan_id = Column(UUID(as_uuid=True), ForeignKey("public.plans.id"), nullable=True)

    # ✅ Organization Multi-Tenancy Columns
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=True)
    employee_id = Column(String(50), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id", ondelete="SET NULL"), nullable=True)

    # ✅ Relationship: Plan → Users
    plan = relationship(
        "Plan",
        back_populates="users",
        foreign_keys=lambda: [User.plan_id]
    )

    # ✅ Organization Relationships
    organization = relationship("Organization", back_populates="users", foreign_keys=[organization_id])
    department = relationship("OrgDepartment", back_populates="users", foreign_keys=[department_id])
    org_user_roles = relationship("OrgUserRole", back_populates="user", cascade="all, delete-orphan", foreign_keys="OrgUserRole.user_id")

    # === Existing Auth Relationships ===
    sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete",
        foreign_keys=lambda: [UserSession.user_id]
    )

    security = relationship(
        "UserSecurity",
        uselist=False,
        back_populates="user",
        cascade="all, delete"
    )

    user_roles = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete",
        foreign_keys="[UserRole.user_id]"
    )

    password_history = relationship(
        "PasswordHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="[PasswordHistory.user_id]"
    )

    # === ✅ Vendor Management Relationships Added ===
    addresses = relationship(
    "UserAddress",
    back_populates="user",
    cascade="all, delete-orphan",
    foreign_keys="[UserAddress.user_id]"
)


    tax_info = relationship(
        "CompanyTaxInfo",
        back_populates="company",
        cascade="all, delete-orphan",
        foreign_keys="[CompanyTaxInfo.company_id]"
    )

    bank_info = relationship(
        "CompanyBankInfo",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="[CompanyBankInfo.company_id]"
    )
    documents = relationship(
    "UserDocument",
    back_populates="user",
    cascade="all, delete-orphan",
    foreign_keys="[UserDocument.user_id]"
)





class PasswordHistory(Base):
    __tablename__ = "password_history"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    password_hash = Column(String, nullable=False)

    # Audit fields
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)

    # Relationships
    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="password_history"  # ✅ matches User.password_history
    )
class CompanyBankDocument(Base):
    __tablename__ = "company_bank_documents"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)

    company_bank_info_id = Column(
        Integer,
        ForeignKey("public.company_bank_info.id", ondelete="CASCADE"),
        nullable=False
    )

    file_name = Column(String(255), nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    file_type = Column(String(50))
    file_data = Column(LargeBinary, nullable=False) # BYTEA
    pending_kyc = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verified_by = Column(String)
    verified_at = Column(DateTime(timezone=True))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    category_detail_id = Column(
        Integer, 
        ForeignKey("public.CategoryDetails.id"), 
        nullable=True
    )
    company_bank_info = relationship(
        "CompanyBankInfo",
        back_populates="documents",
        foreign_keys=[company_bank_info_id]
    )

    category_detail = relationship(
    "CategoryDetails",
    back_populates="bank_document_types",
    foreign_keys=[category_detail_id],
    lazy="joined"
)

    

class CompanyBankInfo(Base):
    __tablename__ = "company_bank_info"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    account_holder_name = Column(String(255), nullable=False)
    bank_name = Column(String(255), nullable=False)
    account_number = Column(String(30), nullable=False)
    ifsc = Column(String(11), nullable=False)
    branch_name = Column(String(255), nullable=True)
    
    account_type_detail_id = Column(
        Integer, 
        ForeignKey("public.CategoryDetails.id"), 
        nullable=True
    )
    
    is_primary = Column(Boolean, server_default="false", nullable=False)
    status = Column(Enum(BankStatusEnum), server_default="pending")
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # ... (ERP columns)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
    
    # ✅ RELATIONSHIP: Account Type
    account_type_detail = relationship(
        "CategoryDetails",
        foreign_keys=[account_type_detail_id]
    )

    # ✅ Relationships
    user = relationship(
        "User",
        back_populates="bank_info",
        foreign_keys=[company_id]
    )

    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])

    documents = relationship(
        "CompanyBankDocument",
        back_populates="company_bank_info",
        cascade="all, delete-orphan",
        foreign_keys="[CompanyBankDocument.company_bank_info_id]"
    )

# ------------------------------
# UserRole Model
# ------------------------------
class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"))
    role_id = Column(Integer, ForeignKey("public.roles.id", ondelete="CASCADE"))
    is_active = Column(Boolean, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship(
        "User",
        back_populates="user_roles",
        foreign_keys=[user_id]
    )
    created_user = relationship(
        "User",
        foreign_keys=[created_by],
        lazy="joined"
    )
    modified_user = relationship(
        "User",
        foreign_keys=[modified_by],
        lazy="joined"
    )
    role = relationship(
        "Role",
        back_populates="user_roles",
        foreign_keys=[role_id]
    )
   


# ------------------------------
# Role Model
# ------------------------------
class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete")
    privileges = relationship("RoleModulePrivilege", back_populates="role", cascade="all, delete")


# ------------------------------
# UserSecurity Model
# ------------------------------
class UserSecurity(Base):
    __tablename__ = "user_security"
    __table_args__ = {"schema": "public"}

    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), primary_key=True)
    totp_secret = Column(String(32), nullable=True)
    otp_code = Column(String(10), nullable=True)
    otp_expiry = Column(TIMESTAMP(timezone=True), nullable=True)
    otp_attempts = Column(Integer, default=0, nullable=False)
    otp_locked_until = Column(TIMESTAMP(timezone=True), nullable=True)
    last_otp_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    otp_resend_count = Column(Integer, default=0, nullable=False)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    login_locked_until = Column(TIMESTAMP(timezone=True), nullable=True)
    otp_pending_verification = Column(Boolean, default=False, nullable=True)

    user = relationship("User", back_populates="security")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = {"schema": "public"}  # ✅ must be dict

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)

    access_token = Column(Text, nullable=False)       # ✅ no quotes
    refresh_token = Column(Text, nullable=False)      # ✅ no quotes

    cts = Column(TIMESTAMP(timezone=True), nullable=False, default=UTCDateTimeMixin._utc_now)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)

    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    user = relationship("User", back_populates="sessions", foreign_keys=[user_id])

    #user = relationship("User", back_populates="sessions")

    @property
    def is_active(self) -> bool:
        now = UTCDateTimeMixin._utc_now()
        return self.revoked_at is None and self.expires_at > now




# ------------------------------
# Module Model
# ------------------------------
class Module(Base):
    __tablename__ = "modules"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    path = Column(String(255))
    group_name = Column(String(50))
    is_active = Column(Boolean, default=True)
    is_menu = Column(Boolean, default=True, nullable=False, server_default="true")

    created_by = Column(ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    modified_by = Column(ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_user = relationship("User", foreign_keys=[created_by], lazy="joined")
    modified_user = relationship("User", foreign_keys=[modified_by], lazy="joined")

    privileges = relationship("RoleModulePrivilege", back_populates="module", cascade="all, delete")


# ------------------------------
# RoleModulePrivilege Model
# ------------------------------
class RoleModulePrivilege(Base):
    __tablename__ = "role_module_privileges"
    __table_args__ = (
        UniqueConstraint("role_id", "module_id", name="uq_role_module"),
        {"schema": "public"}  # include schema
    )

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(ForeignKey("public.roles.id", ondelete="CASCADE"), nullable=False)
    module_id = Column(ForeignKey("public.modules.id", ondelete="CASCADE"), nullable=False)

    can_add = Column(Boolean, default=False)
    can_edit = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    can_search = Column(Boolean, default=False)
    can_import = Column(Boolean, default=False)
    can_export = Column(Boolean, default=False)
    can_view = Column(Boolean, default=False)
    can_approve = Column(Boolean, default=False)
    can_assign = Column(Boolean, default=False)

    created_by = Column(ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    modified_by = Column(ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_user = relationship("User", foreign_keys=[created_by], lazy="joined")
    modified_user = relationship("User", foreign_keys=[modified_by], lazy="joined")
    role = relationship("Role", back_populates="privileges")
    module = relationship("Module", back_populates="privileges")

    









# ------------------------------
# CompanyProduct (Company ↔ Product)
# ------------------------------
class CompanyProduct(Base):

    __tablename__ = "company_products"

    __table_args__ = (

        UniqueConstraint("company_id", "product_id", name="uq_company_product"),

        {"schema": "public"},

    )



    id = Column(Integer, primary_key=True, autoincrement=True)

    company_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"))

    product_id = Column(Integer, ForeignKey("public.products.id", ondelete="CASCADE"))

    company_sku = Column(String(50))

    price = Column(Float)

    stock_quantity = Column(Integer, default=0)



    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))

    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))

    cts = Column(DateTime(timezone=True), server_default=func.now())

    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    pending_kyc = Column(Boolean, default=True)

   

   



    company = relationship("User", foreign_keys=[company_id])

    product = relationship("Product", back_populates="companies")

    created_user = relationship("User", foreign_keys=[created_by])

    modified_user = relationship("User", foreign_keys=[modified_by])

    certificates = relationship(

    "CompanyProductCertificate",

    back_populates="company_product",

    cascade="all, delete-orphan"

    )



    supply_references = relationship(

    "CompanyProductSupplyReference",

    back_populates="company_product",

    cascade="all, delete-orphan"

   )



    documents = relationship(

        "UserDocument",

        back_populates="company_product",

        cascade="all, delete-orphan"

    )

class Country(Base):
    __tablename__ = "countries"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(10), unique=True)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    # Relationships
    states = relationship("State", back_populates="country", cascade="all, delete")


class State(Base):
    __tablename__ = "states"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(10))
    country_id = Column(Integer, ForeignKey("public.countries.id", ondelete="CASCADE"), nullable=False)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    # Relationships
    country = relationship("Country", back_populates="states")
    cities = relationship("City", back_populates="state")



    #country = relationship("Country", back_populates="states")
    #company_tax_infos = relationship("CompanyTaxInfo", back_populates="state")
class City(Base):
    __tablename__ = "cities"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    state_id = Column(Integer, ForeignKey("public.states.id", ondelete="CASCADE"), nullable=False)
    
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    # Relationships
    state = relationship("State", back_populates="cities")
    addresses = relationship("UserAddress", back_populates="city")  # <-- new

    
class CompanyTaxInfo(Base):
    __tablename__ = "company_tax_info"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    pan = Column(String(10), nullable=False)
    gstin = Column(String(15), nullable=False)
    tan = Column(String(10),  nullable=False)
    financial_year = Column(String(9))

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))

    cts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)
    mts = Column(DateTime, default=UTCDateTimeMixin._utc_now, onupdate=UTCDateTimeMixin._utc_now, nullable=False)
        # inside CompanyTaxInfo class (after mts)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    # ✅ Single correct primary relationship to User
    company = relationship(
        "User",
        back_populates="tax_info",
        foreign_keys=[company_id]
    )

    # ✅ Audit relationships
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])

    documents = relationship(
        "CompanyTaxDocument",
        back_populates="company_tax_info",
        cascade="all, delete-orphan"
    )

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)
    cts = Column(DateTime, default=UTCDateTimeMixin._utc_now)
    expires_at = Column(DateTime, nullable=True)   # <-- new column
    used = Column(Boolean, default=False)


class CompanyTaxDocument(Base):
    __tablename__ = "company_tax_documents"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_tax_info_id = Column(Integer, ForeignKey("public.company_tax_info.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    pending_kyc = Column(Boolean, default=True)
    file_type = Column(String(50))
    
    category_detail_id = Column(
        Integer,
        ForeignKey("public.CategoryDetails.id"),   # 👈 this is required!
        nullable=True
    )

    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # inside CompanyBankDocument class (after modified_at)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
    # Relationships
    company_tax_info = relationship("CompanyTaxInfo", back_populates="documents")
    category_detail = relationship(
    "CategoryDetails",
    back_populates="tax_document_types"
)

class CompanyProductCertificate(Base):
    __tablename__ = "company_product_certificates"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)

    company_product_id = Column(
        Integer,
        ForeignKey("public.company_products.id", ondelete="CASCADE"),
        nullable=False
    )

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(100))   # MIME (e.g. application/pdf)
    file_size = Column(Integer)       # bytes
    file_data = Column(LargeBinary, nullable=False)
    pending_kyc = Column(Boolean, default=True)

    issued_date = Column(DateTime(timezone=True), nullable=True)
    expiry_date = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company_product = relationship(
        "CompanyProduct",
        back_populates="certificates",
        foreign_keys=[company_product_id]
    )
    creator = relationship("User", foreign_keys=[created_by])
class CategoryMaster(Base):
    __tablename__ = "CategoryMaster"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Audit Columns
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ✅ One-to-Many: Master → Details
    details = relationship(
        "CategoryDetails",
        back_populates="master",
        cascade="all, delete-orphan",
        foreign_keys="CategoryDetails.category_master_id"
    )


class CategoryDetails(Base):
    __tablename__ = "CategoryDetails"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_master_id = Column(
        Integer,
        ForeignKey("public.CategoryMaster.id", ondelete="CASCADE"),
        nullable=False
    )

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category_type = Column(String(50), nullable=True)  # test, maintenance, inspection, repair_lifecycle
    is_active = Column(Boolean, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    master = relationship("CategoryMaster", back_populates="details", foreign_keys=[category_master_id])

    user_documents = relationship(
        "UserDocument",
        back_populates="categorydetails",
        cascade="all, delete-orphan",
        foreign_keys="UserDocument.category_detail_id"
    )

    bank_info_accounts = relationship(
        "CompanyBankInfo",
        foreign_keys="[CompanyBankInfo.account_type_detail_id]",
        back_populates="account_type_detail"
    )

    bank_document_types = relationship(
        "CompanyBankDocument",
        foreign_keys="[CompanyBankDocument.category_detail_id]",
        back_populates="category_detail"
    )

    tax_document_types = relationship(
        "CompanyTaxDocument",
        foreign_keys="[CompanyTaxDocument.category_detail_id]",
        back_populates="category_detail",
        cascade="all, delete-orphan"
    )

    # ✅ Reverse relationship to Product
    products = relationship("Product", back_populates="gst_slab")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)

    category_id = Column(Integer, ForeignKey("public.product_categories.id", ondelete="SET NULL"))
    subcategory_id = Column(Integer, ForeignKey("public.product_subcategories.id", ondelete="SET NULL"))

    sku = Column(String(50), unique=True, nullable=False)
    description = Column(String(50000))
    is_active = Column(Boolean, default=True)

    # 🔹 Business fields
    hsn_code = Column(String(50), nullable=True)

    gst_slab_id = Column(
    Integer,
    ForeignKey("public.CategoryDetails.id", ondelete="SET NULL"),
    nullable=True
)

    gst_slab = relationship("CategoryDetails", back_populates="products")

    material_code = Column(String(50), nullable=True)
    selling_price = Column(Float, nullable=True)
    cost_price = Column(Float, nullable=True)

    # 🔹 Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 🔹 ERP fields
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    # 🔹 Relationships
    created_user = relationship("User", foreign_keys=[created_by])
    modified_user = relationship("User", foreign_keys=[modified_by])

    category_obj = relationship("ProductCategory", back_populates="products")
    subcategory_obj = relationship("ProductSubCategory", back_populates="products")
    companies = relationship("CompanyProduct", back_populates="product", cascade="all, delete")

  
    
# ------------------------------
# ProductCategory Model
# ------------------------------
class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255))
    is_active = Column(Boolean, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_user = relationship("User", foreign_keys=[created_by])
    modified_user = relationship("User", foreign_keys=[modified_by])
    
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    subcategories = relationship("ProductSubCategory", back_populates="category", cascade="all, delete")
    products = relationship("Product", back_populates="category_obj")


# ------------------------------
# ProductSubCategory Model
# ------------------------------
class ProductSubCategory(Base):
    __tablename__ = "product_subcategories"
    __table_args__ = (
        UniqueConstraint("category_id", "name", name="uq_category_subcategory"),
        {"schema": "public"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey("public.product_categories.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    description = Column(String(255))
    is_active = Column(Boolean, default=True)
    
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category = relationship("ProductCategory", back_populates="subcategories")
    created_user = relationship("User", foreign_keys=[created_by])
    modified_user = relationship("User", foreign_keys=[modified_by])
    products = relationship("Product", back_populates="subcategory_obj")

class UserDocument(Base):
    __tablename__ = "user_documents"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    division_id = Column(UUID(as_uuid=True), ForeignKey("public.divisions.id"), nullable=False)
    category_detail_id = Column(Integer, ForeignKey("public.CategoryDetails.id"), nullable=False)
    company_product_id = Column(Integer, ForeignKey("public.company_products.id", ondelete="CASCADE"), nullable=True)

    document_name = Column(String(255), nullable=False)
    document_type = Column(String(100))
    document_url = Column(Text)
    file_data = Column(LargeBinary)
    file_size = Column(Integer)
    content_type = Column(String(100))
    om_number = Column(String(100))
    expiry_date = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True))
    erp_error_message = Column(Text)
    erp_external_id = Column(String(255))
    pending_kyc = Column(Boolean, default=True)


    # Relationships
    user = relationship("User", back_populates="documents", foreign_keys=[user_id])
    uploader = relationship("User", foreign_keys=[uploaded_by], backref="uploaded_documents")
    division = relationship("Division", back_populates="documents", foreign_keys=[division_id])
    categorydetails = relationship("CategoryDetails", back_populates="user_documents", foreign_keys=[category_detail_id])
    company_product = relationship("CompanyProduct", back_populates="documents", foreign_keys=[company_product_id])

class Division(Base):
    __tablename__ = "divisions"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    division_name = Column(String(255), unique=True, nullable=False)
    description = Column(String(500))
    code = Column(String(100), unique=True)
    is_active = Column(Boolean, default=True)
    
    erp_sync_status = Column(String(10), default="pending")     # pending | success | failed
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)

    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship
    documents = relationship(
    "UserDocument",
    back_populates="division",
    foreign_keys="UserDocument.division_id"
)

class CompanyProductSupplyReference(Base):
    __tablename__ = "company_product_supply_references"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)

    company_product_id = Column(
        Integer,
        ForeignKey("public.company_products.id", ondelete="CASCADE"),
        nullable=False
    )

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(100))
    file_size = Column(Integer)
    file_data = Column(LargeBinary, nullable=False)
    pending_kyc = Column(Boolean, default=True)

    description = Column(Text)
    customer_name = Column(String(255))
    reference_date = Column(DateTime(timezone=True))

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company_product = relationship(
        "CompanyProduct",
        back_populates="supply_references",
        foreign_keys=[company_product_id]
    )
    creator = relationship("User", foreign_keys=[created_by])

class RFQ(Base):
    __tablename__ = "rfq_requests"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_id = Column(
        Integer,
        ForeignKey("public.products.id"),
        nullable=False
    )

    quantity = Column(Integer, nullable=False)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id")
    )

    created_at = Column(DateTime, server_default=func.now())

    product = relationship("Product")

class RFQVendor(Base):
    __tablename__ = "rfq_vendors"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)

    rfq_id = Column(
        Integer,
        ForeignKey("public.rfq_requests.id"),
        nullable=False
    )

    vendor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id"),
        nullable=False
    )

    status = Column(String, default="pending")

    created_at = Column(DateTime, server_default=func.now())

    rfq = relationship("RFQ")


# ------------------------------
# TestingRequest Model
# ------------------------------
class TestingRequest(Base):
    __tablename__ = "testing_requests"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_number = Column(String(50), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Transformer details
    transformer_type = Column(String(100), nullable=True)
    transformer_rating = Column(String(100), nullable=True)
    manufacturer = Column(String(255), nullable=True)
    serial_number = Column(String(100), nullable=True)

    # Equipment & Test type (FK → CategoryMaster / CategoryDetails)
    equipment_type_id = Column(Integer, ForeignKey("public.CategoryMaster.id"), nullable=True)
    test_type_id = Column(Integer, ForeignKey("public.CategoryDetails.id"), nullable=True)

    # Equipment Asset Register link (auto-fills equipment_type_id, nameplate fields, location)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment.id"), nullable=True)

    # Request category: test | maintenance | inspection | repair_lifecycle
    request_category = Column(Enum(RequestCategory), default=RequestCategory.test, nullable=False)

    # Organization & Department (new multi-tenancy approach)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id"), nullable=True)

    # Organizational hierarchy (legacy - kept for backward compatibility)
    zone = Column(String(255), nullable=True)
    ce_circle = Column(String(255), nullable=True)
    se_division = Column(String(255), nullable=True)
    ee_subdivision = Column(String(255), nullable=True)
    aee_section = Column(String(255), nullable=True)
    ae_je = Column(String(255), nullable=True)

    # Workflow
    status = Column(Enum(TestingRequestStatus), default=TestingRequestStatus.draft, nullable=False)
    priority = Column(String(20), default="normal")

    # Assignments
    originator_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    assigned_tester_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    # Dates
    requested_date = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    scheduled_start_date = Column(DateTime(timezone=True), nullable=True)  # NEW: For scheduled tests
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Multi-session support
    is_multi_session = Column(Boolean, default=False)  # NEW: Indicates multi-day/multi-session test
    total_sessions_planned = Column(Integer, nullable=True)  # NEW: Number of planned sessions
    session_interval_days = Column(Integer, nullable=True)  # NEW: Days between sessions

    # Notes
    notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    originator = relationship("User", foreign_keys=[originator_id])
    assigned_tester = relationship("User", foreign_keys=[assigned_tester_id])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])
    equipment_type = relationship("CategoryMaster", foreign_keys=[equipment_type_id])
    test_type = relationship("CategoryDetails", foreign_keys=[test_type_id])
    equipment = relationship("Equipment", foreign_keys=[equipment_id])
    organization = relationship("Organization", foreign_keys=[organization_id])
    department = relationship("OrgDepartment", foreign_keys=[department_id])
    test_results = relationship("TestResult", back_populates="testing_request", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="testing_request", cascade="all, delete-orphan")
    test_sessions = relationship("TestSession", back_populates="testing_request", cascade="all, delete-orphan")


# ------------------------------
# TestRequestSchedule Model
# ------------------------------
class TestRequestSchedule(Base):
    __tablename__ = "test_request_schedules"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_request_id = Column(UUID(as_uuid=True), ForeignKey("public.testing_requests.id", ondelete="CASCADE"), nullable=False, unique=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)

    frequency = Column(Enum(ScheduleFrequency), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)  # = first request's due_date
    end_date = Column(DateTime(timezone=True), nullable=True)
    next_run_date = Column(DateTime(timezone=True), nullable=False)  # first request due_date + frequency
    last_run_date = Column(DateTime(timezone=True), nullable=True)
    advance_days = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    test_request = relationship("TestingRequest", foreign_keys=[test_request_id])
    organization = relationship("Organization", foreign_keys=[organization_id])
    creator = relationship("User", foreign_keys=[created_by])
    logs = relationship("TestRequestScheduleLog", back_populates="schedule", cascade="all, delete-orphan")


# ------------------------------
# TestRequestScheduleLog Model
# ------------------------------
class TestRequestScheduleLog(Base):
    __tablename__ = "test_request_schedule_logs"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("public.test_request_schedules.id", ondelete="CASCADE"), nullable=False)
    generated_request_id = Column(UUID(as_uuid=True), ForeignKey("public.testing_requests.id", ondelete="SET NULL"), nullable=True)
    run_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(ScheduleLogStatus), nullable=False)
    error_message = Column(Text, nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    schedule = relationship("TestRequestSchedule", back_populates="logs")
    generated_request = relationship("TestingRequest", foreign_keys=[generated_request_id])


# ------------------------------
# TesterLocation Mapping (links tester users to org hierarchy without altering users table)
# ------------------------------
class TesterLocation(Base):
    __tablename__ = "tester_locations"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)

    # New department-based location
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id"), nullable=True)

    # Legacy string-based locations (kept for backward compatibility)
    zone = Column(String(255), nullable=True)
    ce_circle = Column(String(255), nullable=True)
    se_division = Column(String(255), nullable=True)
    ee_subdivision = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)

    user = relationship("User", foreign_keys=[user_id])
    organization = relationship("Organization", foreign_keys=[organization_id])
    department = relationship("OrgDepartment", foreign_keys=[department_id])


# ------------------------------
# TestResult Model
# ------------------------------
class TestResult(Base):
    __tablename__ = "test_results"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    testing_request_id = Column(UUID(as_uuid=True), ForeignKey("public.testing_requests.id", ondelete="CASCADE"), nullable=False)

    # Multi-session support: link result to specific test session
    test_session_id = Column(UUID(as_uuid=True), ForeignKey("public.test_sessions.id", ondelete="SET NULL"), nullable=True)

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)

    test_name = Column(String(255), nullable=False)
    test_category = Column(String(100), nullable=True)
    result_value = Column(String(255), nullable=True)
    result_unit = Column(String(50), nullable=True)
    pass_fail = Column(String(10), nullable=True)
    remarks = Column(Text, nullable=True)

    # File attachment
    file_name = Column(String(255), nullable=True)
    file_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_data = Column(LargeBinary, nullable=True)

    # Structured test data (JSONB)
    test_data = Column(JSONB, nullable=True)
    overall_result = Column(String(20), nullable=True)
    template_key = Column(String(100), nullable=True)
    replacement_products = Column(JSONB, nullable=True)  # [{item_id, item_name, category, quantity}, ...]

    # Auto-evaluation result (JSONB) — computed from template acceptance criteria
    # {overall: "NORMAL"|"ALERT"|"CRITICAL", evaluated_at, fields: [{key, label, value, unit, status, thresholds}]}
    evaluation_result = Column(JSONB, nullable=True)

    tested_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    tested_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    testing_request = relationship("TestingRequest", back_populates="test_results")
    test_session = relationship("TestSession", foreign_keys=[test_session_id])
    organization = relationship("Organization", foreign_keys=[organization_id])
    images = relationship("TestResultImage", back_populates="test_result", cascade="all, delete-orphan")
    tester = relationship("User", foreign_keys=[tested_by])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])


# ------------------------------
# Test Result Image Model
# ------------------------------
class TestResultImage(Base):
    __tablename__ = "test_result_images"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_result_id = Column(UUID(as_uuid=True), ForeignKey("public.test_results.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_data = Column(LargeBinary, nullable=False)
    caption = Column(String(500), nullable=True)
    sort_order = Column(Integer, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    test_result = relationship("TestResult", back_populates="images")


# ------------------------------
# Test Session Model (Multi-day/Multi-session Testing)
# ------------------------------
class TestSession(Base):
    __tablename__ = "test_sessions"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    testing_request_id = Column(UUID(as_uuid=True), ForeignKey("public.testing_requests.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)

    session_number = Column(Integer, nullable=False)  # 1, 2, 3, etc.
    session_name = Column(String(255), nullable=True)  # "Day 1 Morning", "Initial Reading", etc.
    session_date = Column(DateTime(timezone=True), nullable=False)
    scheduled_date = Column(DateTime(timezone=True), nullable=True)  # When it was planned

    # Session status
    status = Column(String(20), default="scheduled")  # scheduled, in_progress, completed, skipped

    # Template reference
    template_key = Column(String(100), nullable=True)  # Links to OrgTestTemplate

    # Session notes
    notes = Column(Text, nullable=True)
    weather_conditions = Column(String(255), nullable=True)  # For outdoor tests
    environmental_factors = Column(Text, nullable=True)  # Temperature, humidity, etc.

    # Session team
    conducted_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    witnessed_by = Column(String(255), nullable=True)  # External witness names

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    testing_request = relationship("TestingRequest", back_populates="test_sessions")
    organization = relationship("Organization", foreign_keys=[organization_id])
    conductor = relationship("User", foreign_keys=[conducted_by])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])
    readings = relationship("TestSessionReading", back_populates="test_session", cascade="all, delete-orphan")
    comments = relationship("SessionComment", back_populates="session", cascade="all, delete-orphan")


# ------------------------------
# Test Session Reading Model (Multiple readings per session)
# ------------------------------
class TestSessionReading(Base):
    __tablename__ = "test_session_readings"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_session_id = Column(UUID(as_uuid=True), ForeignKey("public.test_sessions.id", ondelete="CASCADE"), nullable=False)

    reading_number = Column(Integer, nullable=False)  # 1, 2, 3, etc. within the session
    reading_time = Column(DateTime(timezone=True), nullable=False)

    # Reading data (structured as JSONB for flexibility)
    reading_data = Column(JSONB, nullable=False)  # Actual test measurements

    # Additional metadata
    equipment_serial = Column(String(100), nullable=True)
    calibration_date = Column(DateTime(timezone=True), nullable=True)
    remarks = Column(Text, nullable=True)

    # Pass/fail for this specific reading
    result_status = Column(String(20), nullable=True)  # pass, fail, conditional, warning

    # Images/attachments for this specific reading
    image_count = Column(Integer, default=0)

    # Audit
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    test_session = relationship("TestSession", back_populates="readings")
    recorder = relationship("User", foreign_keys=[recorded_by])
    images = relationship("TestSessionReadingImage", back_populates="reading", cascade="all, delete-orphan")


# ------------------------------
# Test Session Reading Image Model
# ------------------------------
class TestSessionReadingImage(Base):
    __tablename__ = "test_session_reading_images"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reading_id = Column(UUID(as_uuid=True), ForeignKey("public.test_session_readings.id", ondelete="CASCADE"), nullable=False)

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_data = Column(LargeBinary, nullable=False)
    caption = Column(String(500), nullable=True)
    sort_order = Column(Integer, default=0)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    reading = relationship("TestSessionReading", back_populates="images")
    creator = relationship("User", foreign_keys=[created_by])


# ------------------------------
# Session Comment Model
# ------------------------------
class SessionComment(Base):
    """Comments on test sessions (typically by approvers)"""
    __tablename__ = "session_comments"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("public.test_sessions.id", ondelete="CASCADE"), nullable=False)

    comment = Column(Text, nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    modified_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    session = relationship("TestSession", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])


# ------------------------------
# Recommendation Model
# ------------------------------
class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    testing_request_id = Column(UUID(as_uuid=True), ForeignKey("public.testing_requests.id", ondelete="CASCADE"), nullable=False)

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)

    recommendation_type = Column(Enum(RecommendationType), nullable=False)
    summary = Column(Text, nullable=False)
    detailed_notes = Column(Text, nullable=True)
    replacement_products = Column(JSONB, nullable=True)  # [{item_id, item_name, category, quantity}, ...]

    # Approval
    approval_status = Column(String(20), default="pending")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_notes = Column(Text, nullable=True)

    submitted_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    testing_request = relationship("TestingRequest", back_populates="recommendations")
    organization = relationship("Organization", foreign_keys=[organization_id])
    submitter = relationship("User", foreign_keys=[submitted_by])
    approver = relationship("User", foreign_keys=[approved_by])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])


# ------------------------------
# ProcurementRequest Model
# ------------------------------
class ProcurementRequest(Base):
    __tablename__ = "procurement_requests"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procurement_number = Column(String(50), unique=True, nullable=False)
    testing_request_id = Column(UUID(as_uuid=True), ForeignKey("public.testing_requests.id"), nullable=False)
    recommendation_id = Column(UUID(as_uuid=True), ForeignKey("public.recommendations.id"), nullable=True)

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="initiated")

    estimated_cost = Column(Float, nullable=True)
    quantity = Column(Integer, nullable=True)
    specifications = Column(Text, nullable=True)

    raised_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    raised_at = Column(DateTime(timezone=True), server_default=func.now())

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    testing_request = relationship("TestingRequest", foreign_keys=[testing_request_id])
    recommendation = relationship("Recommendation", foreign_keys=[recommendation_id])
    organization = relationship("Organization", foreign_keys=[organization_id])
    raiser = relationship("User", foreign_keys=[raised_by])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])


# ------------------------------
# OrgTestTemplate Model
# ------------------------------
class OrgTestTemplate(Base):
    __tablename__ = "org_test_templates"
    __table_args__ = (
        UniqueConstraint("org_id", "template_key", name="uq_org_template_key"),
        {"schema": "public"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), nullable=True)   # NULL = global default
    template_key = Column(String(100), nullable=False)
    test_type_id = Column(Integer, nullable=True)            # soft ref to CategoryDetails.id
    template_data = Column(JSONB, nullable=False)            # full template JSON
    is_system = Column(Boolean, default=True)
    version = Column(Integer, default=1)


# ============================================================
# WORKFLOW ENGINE MODELS
# ============================================================

class Workflow(Base, UTCDateTimeMixin):
    """
    Workflow definition model - stores workflow configurations
    """
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint('organization_id', 'workflow_type', 'version', name='uq_workflow_org_type_version'),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic Info
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    workflow_type = Column(String(100), nullable=False)  # 'testing_request', 'approval', etc.

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organization = relationship("Organization", foreign_keys=[organization_id])
    creator = relationship("User", foreign_keys=[created_by])
    states = relationship("WorkflowState", back_populates="workflow", cascade="all, delete-orphan")
    transitions = relationship("WorkflowTransition", back_populates="workflow", cascade="all, delete-orphan")
    permission_entries = relationship("PermissionMatrix", back_populates="workflow", cascade="all, delete-orphan")
    audit_logs = relationship("WorkflowAuditLog", back_populates="workflow")


class WorkflowState(Base, UTCDateTimeMixin):
    """
    Workflow state model - represents individual states within a workflow
    """
    __tablename__ = "workflow_states"
    __table_args__ = (
        UniqueConstraint('workflow_id', 'state_code', name='uq_workflow_state_code'),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationship
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("public.workflows.id", ondelete="CASCADE"), nullable=False)

    # State Info
    state_code = Column(String(50), nullable=False)  # 'draft', 'submitted', 'approved'
    state_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # State Type
    state_type = Column(String(50), default='intermediate')  # 'initial', 'intermediate', 'final', 'cancelled'

    # Display
    color = Column(String(20), default='#3FA9F5')
    icon = Column(String(50), default='circle')
    display_order = Column(Integer, default=0)

    # Status
    is_active = Column(Boolean, default=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="states")
    creator = relationship("User", foreign_keys=[created_by])
    transitions_from = relationship("WorkflowTransition", foreign_keys="WorkflowTransition.from_state_id", back_populates="from_state")
    transitions_to = relationship("WorkflowTransition", foreign_keys="WorkflowTransition.to_state_id", back_populates="to_state")


class WorkflowTransition(Base, UTCDateTimeMixin):
    """
    Workflow transition model - defines allowed state changes
    """
    __tablename__ = "workflow_transitions"
    __table_args__ = (
        UniqueConstraint('workflow_id', 'from_state_id', 'to_state_id', 'action_code', name='uq_workflow_transition'),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationship
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("public.workflows.id", ondelete="CASCADE"), nullable=False)
    from_state_id = Column(UUID(as_uuid=True), ForeignKey("public.workflow_states.id", ondelete="CASCADE"), nullable=False)
    to_state_id = Column(UUID(as_uuid=True), ForeignKey("public.workflow_states.id", ondelete="CASCADE"), nullable=False)

    # Transition Info
    transition_name = Column(String(200), nullable=False)  # 'Submit', 'Approve', 'Reject'
    action_code = Column(String(50), nullable=False)  # 'submit', 'approve', 'reject'
    description = Column(Text, nullable=True)

    # Conditions
    conditions = Column(JSONB, nullable=True)

    # Display
    button_label = Column(String(100), nullable=True)
    button_color = Column(String(20), default='#3FA9F5')
    icon = Column(String(50), default='arrow_forward')
    requires_comment = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)

    # Status
    is_active = Column(Boolean, default=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="transitions")
    from_state = relationship("WorkflowState", foreign_keys=[from_state_id], back_populates="transitions_from")
    to_state = relationship("WorkflowState", foreign_keys=[to_state_id], back_populates="transitions_to")
    creator = relationship("User", foreign_keys=[created_by])
    permissions = relationship("PermissionMatrix", back_populates="transition", cascade="all, delete-orphan")


class PermissionMatrix(Base, UTCDateTimeMixin):
    """
    Permission matrix model - role-based permissions for transitions
    """
    __tablename__ = "permission_matrix"
    __table_args__ = (
        UniqueConstraint('transition_id', 'role_id', 'scope_type', name='uq_permission_transition_role_scope'),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationship
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("public.workflows.id", ondelete="CASCADE"), nullable=False)
    transition_id = Column(UUID(as_uuid=True), ForeignKey("public.workflow_transitions.id", ondelete="CASCADE"), nullable=False)

    # Role-Based Access
    role_id = Column(UUID(as_uuid=True), ForeignKey("public.org_roles.id", ondelete="CASCADE"), nullable=False)

    # Department Scope
    scope_type = Column(String(50), nullable=False, default='exact')  # 'exact', 'department_tree', 'organization', 'any'
    department_type_id = Column(UUID(as_uuid=True), ForeignKey("public.org_department_types.id", ondelete="SET NULL"), nullable=True)

    # Permission Level
    can_execute = Column(Boolean, default=True)
    can_view = Column(Boolean, default=True)
    requires_approval = Column(Boolean, default=False)

    # Additional Conditions
    conditions = Column(JSONB, nullable=True)

    # Priority
    priority = Column(Integer, default=0)

    # Status
    is_active = Column(Boolean, default=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="permission_entries")
    transition = relationship("WorkflowTransition", back_populates="permissions")
    role = relationship("OrgRole", foreign_keys=[role_id])
    department_type = relationship("OrgDepartmentType", foreign_keys=[department_type_id])
    creator = relationship("User", foreign_keys=[created_by])


class WorkflowAuditLog(Base, UTCDateTimeMixin):
    """
    Workflow audit log - tracks all state transitions
    """
    __tablename__ = "workflow_audit_log"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationship
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("public.workflows.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(100), nullable=False)  # 'testing_request', 'purchase_order'
    entity_id = Column(UUID(as_uuid=True), nullable=False)

    # Transition Details
    transition_id = Column(UUID(as_uuid=True), ForeignKey("public.workflow_transitions.id", ondelete="SET NULL"), nullable=True)
    from_state_id = Column(UUID(as_uuid=True), ForeignKey("public.workflow_states.id", ondelete="SET NULL"), nullable=True)
    to_state_id = Column(UUID(as_uuid=True), ForeignKey("public.workflow_states.id", ondelete="SET NULL"), nullable=True)
    action_code = Column(String(50), nullable=True)

    # User & Context
    performed_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    performed_at = Column(DateTime(timezone=True), server_default=func.now())
    user_role_id = Column(UUID(as_uuid=True), ForeignKey("public.org_roles.id", ondelete="SET NULL"), nullable=True)
    user_department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id", ondelete="SET NULL"), nullable=True)

    # Additional Data
    comment = Column(Text, nullable=True)
    audit_metadata = Column(JSONB, nullable=True)  # Renamed from 'metadata' to avoid SQLAlchemy conflict

    # Result
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    workflow = relationship("Workflow", back_populates="audit_logs")
    transition = relationship("WorkflowTransition", foreign_keys=[transition_id])
    from_state = relationship("WorkflowState", foreign_keys=[from_state_id])
    to_state = relationship("WorkflowState", foreign_keys=[to_state_id])
    performer = relationship("User", foreign_keys=[performed_by])
    user_role = relationship("OrgRole", foreign_keys=[user_role_id])
    user_department = relationship("OrgDepartment", foreign_keys=[user_department_id])

# ------------------------------
# WorkflowRoleConfig Model
# ------------------------------
class WorkflowRoleConfig(Base):
    """
    Configuration for role assignment in workflows.
    Defines which module permissions are required for a role to be assignable in a workflow.
    Only roles with FULL permissions on the specified module will appear in assignment dropdowns.
    """
    __tablename__ = "workflow_role_configs"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Workflow type (e.g., "testing_request", "inspection_request", "approval_workflow")
    workflow_type = Column(String(100), nullable=False, index=True)

    # Role assignment type (e.g., "tester", "inspector", "reviewer")
    assignment_type = Column(String(100), nullable=False)

    # Module that must have FULL permissions
    module_id = Column(Integer, ForeignKey("public.modules.id", ondelete="CASCADE"), nullable=False)

    # Required permissions on the module (role must have ALL of these set to TRUE)
    requires_can_view = Column(Boolean, default=True)
    requires_can_add = Column(Boolean, default=True)
    requires_can_edit = Column(Boolean, default=True)
    requires_can_delete = Column(Boolean, default=True)
    requires_can_approve = Column(Boolean, default=True)
    requires_can_assign = Column(Boolean, default=True)

    # Description
    description = Column(Text)

    # Active flag
    is_active = Column(Boolean, default=True)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    module = relationship("Module")


# ------------------------------
# Tester Role Configuration Model
# ------------------------------
class TesterRoleModuleRequirement(Base):
    """
    Configuration for tester role selection in testing request approvals.
    Defines which modules a role must have FULL permissions on to appear
    in the tester assignment dropdown.

    Role must have ALL 6 permissions (view, add, edit, delete, approve, assign)
    on EXACTLY the modules listed in required_module_ids.
    """
    __tablename__ = "tester_role_module_requirements"
    __table_args__ = (
        UniqueConstraint('organization_id', name='uq_tester_role_config_org'),
        {"schema": "public"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Organization (NULL = global default)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.organizations.id", ondelete="CASCADE"),
        nullable=True
    )

    # Required module IDs (EXACT match required)
    required_module_ids = Column(ARRAY(Integer), nullable=False)

    # Metadata
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    cts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    organization = relationship("Organization", foreign_keys=[organization_id])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])


# ------------------------------
# Zoho Import Mapping
# ------------------------------
class ZohoImportMapping(Base):
    __tablename__ = "zoho_import_mappings"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Zoho identifier (e.g. Zoho org id or a label like "default")
    zoho_org_id = Column(String(255), nullable=True)
    label = Column(String(255), nullable=True)  # friendly name for this mapping

    # Where imported users land
    organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id", ondelete="SET NULL"), nullable=True)
    org_role_id = Column(UUID(as_uuid=True), ForeignKey("public.org_roles.id", ondelete="SET NULL"), nullable=True)

    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])
    organization = relationship("Organization", foreign_keys=[organization_id])
    department = relationship("OrgDepartment", foreign_keys=[department_id])
    org_role = relationship("OrgRole", foreign_keys=[org_role_id])


# ══════════════════════════════════════════════════════════════════════════════
# Notification & Alert Engine
# ══════════════════════════════════════════════════════════════════════════════

class NotificationTemplate(Base):
    """
    Defines what to send (subject + body) and who to send it to (recipient_roles)
    for each event_type / channel combination.
    NULL organization_id = global default template.
    """
    __tablename__ = "notification_templates"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.organizations.id", ondelete="CASCADE"),
        nullable=True,  # NULL = global default
    )

    # e.g. "eval_critical", "eval_alert", "due_reminder", "overdue_alert",
    #       "recommendation_approved", "test_submitted"
    event_type = Column(String(100), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # "email" | "sms" | "inapp"

    subject_template = Column(String(500), nullable=True)   # Jinja2 / str.format
    body_template = Column(Text, nullable=False)             # Jinja2 / str.format

    # Role names whose members should receive this notification
    # e.g. ["Originator", "Department Head", "Tester"]
    recipient_roles = Column(JSONB, nullable=False, server_default="[]")

    is_active = Column(Boolean, default=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationLog(Base):
    """
    Audit log of every notification attempt.  status lifecycle:
      pending → sent | failed | digested | skipped
    Retry counter incremented on each attempt up to max_retries (default 3).
    """
    __tablename__ = "notification_log"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=True)

    event_type = Column(String(100), nullable=False, index=True)
    channel = Column(String(20), nullable=False)            # "email" | "sms" | "inapp"

    recipient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_email = Column(String(255), nullable=True)
    recipient_phone = Column(String(50), nullable=True)

    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)

    status = Column(String(20), default="pending", index=True)  # pending/sent/failed/digested/skipped
    error_message = Column(Text, nullable=True)

    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    sent_at = Column(DateTime(timezone=True), nullable=True)

    # Source object that triggered this notification
    source_id = Column(UUID(as_uuid=True), nullable=True)   # TestResult.id, TestingRequest.id, etc.
    source_type = Column(String(100), nullable=True)        # "test_result", "testing_request", etc.

    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    recipient = relationship("User", foreign_keys=[recipient_id])


class UserNotification(Base):
    """
    In-app (bell icon) notifications.  One row per user per event.
    Soft-deleted via is_read flag; hard-delete never needed.
    """
    __tablename__ = "user_notifications"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(UUID(as_uuid=True), nullable=True)

    event_type = Column(String(100), nullable=False)
    title = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    severity = Column(String(20), nullable=True)  # "critical" | "alert" | "info"

    # Source navigation payload (flutter can deep-link)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    source_type = Column(String(100), nullable=True)
    ueic = Column(String(100), nullable=True)  # Equipment UEIC for quick display

    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    cts = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])


# ── Reporting Suite ────────────────────────────────────────────────────────

class ReportDefinition(Base):
    """
    One row = one report.  The 14 SRS reports are seeded as system rows.
    Custom ad-hoc reports saved by users are additional rows.
    """
    __tablename__ = "report_definitions"
    __table_args__ = {"schema": "public"}

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True),
                             ForeignKey("public.organizations.id", ondelete="CASCADE"),
                             nullable=True, index=True)
    name            = Column(String(255), nullable=False)
    description     = Column(Text, nullable=True)
    query_key       = Column(String(100), nullable=False)
    # JSON schema of available filter parameters
    parameters      = Column(JSONB, nullable=False, server_default="{}")
    output_format   = Column(String(20), nullable=False, default="excel")   # excel | pdf | both
    frequency       = Column(String(20), nullable=False, default="on_demand")  # daily | weekly | monthly | on_demand
    recipient_roles = Column(JSONB, nullable=False, server_default="[]")
    is_active       = Column(Boolean, default=True)
    is_system       = Column(Boolean, default=False)   # True for the 14 built-in SRS reports
    last_generated_at = Column(DateTime(timezone=True), nullable=True)
    created_by      = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by     = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts             = Column(DateTime(timezone=True), server_default=func.now())
    mts             = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    logs = relationship("ReportLog", back_populates="definition",
                        cascade="all, delete-orphan")


class ReportLog(Base):
    """Tracks every execution of a ReportDefinition (scheduled or ad-hoc)."""
    __tablename__ = "report_logs"
    __table_args__ = {"schema": "public"}

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id   = Column(UUID(as_uuid=True),
                             ForeignKey("public.report_definitions.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=True)
    generated_by    = Column(UUID(as_uuid=True),
                             ForeignKey("public.users.id", ondelete="SET NULL"),
                             nullable=True)
    parameters_used = Column(JSONB, nullable=False, server_default="{}")
    output_format   = Column(String(20), nullable=False, default="excel")
    file_path       = Column(String(500), nullable=True)
    file_name       = Column(String(255), nullable=True)
    file_size       = Column(Integer, nullable=True)
    row_count       = Column(Integer, nullable=True)
    status          = Column(String(20), default="pending", index=True)
                           # pending | generating | completed | failed
    error_message   = Column(Text, nullable=True)
    started_at      = Column(DateTime(timezone=True), nullable=True)
    completed_at    = Column(DateTime(timezone=True), nullable=True)
    cts             = Column(DateTime(timezone=True), server_default=func.now())

    definition          = relationship("ReportDefinition", back_populates="logs")
    generated_by_user   = relationship("User", foreign_keys=[generated_by])
