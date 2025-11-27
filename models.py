
from enum import Enum as PyEnum
from sqlalchemy import Enum

import uuid
from sqlalchemy import (
    Column, Float, LargeBinary, Numeric, String, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint, func,Text
)
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import relationship
from database import Base
from utils.common_service import UTCDateTimeMixin
import uuid
from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

#Base = declarative_base()

class AddressTypeEnum(PyEnum):
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

class DocumentTypeEnum(PyEnum):
    PAN = "PAN"
    GST_CERT = "GST_CERT"
    TAN = "TAN"
    CANCELLED_CHEQUE = "CANCELLED_CHEQUE"
    BANK_STATEMENT = "BANK_STATEMENT"
    PASSBOOK = "PASSBOOK"
    ADDRESS_PROOF = "ADDRESS_PROOF"

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

    # ✅ Plan FK
    plan_id = Column(UUID(as_uuid=True), ForeignKey("public.plans.id"), nullable=True)

    # ✅ Relationship: Plan → Users
    plan = relationship(
        "Plan",
        back_populates="users",
        foreign_keys=lambda: [User.plan_id]
    )

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
    pending_kyc = Column(Boolean, default=False)
    document_type = Column(Enum(DocumentTypeEnum, name="bank_document_type_enum"))
    is_verified = Column(Boolean, default=False)
    verified_by = Column(String)
    verified_at = Column(DateTime(timezone=True))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    company_bank_info = relationship(
        "CompanyBankInfo",
        back_populates="documents",
        foreign_keys=[company_bank_info_id]
    )

    
class DocumentTypeEnum(PyEnum):
    CANCELLED_CHEQUE = "CANCELLED_CHEQUE"
    BANK_STATEMENT = "BANK_STATEMENT"
    PASSBOOK = "PASSBOOK"

class CompanyBankInfo(Base):
    __tablename__ = "company_bank_info"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    account_holder_name = Column(String(255), nullable=False)
    bank_name = Column(String(255), nullable=False)
    account_number = Column(String(30), nullable=False)
    ifsc = Column(String(11), nullable=False)
    branch_name = Column(String(255), nullable=True)  # ✅ Added
    account_type = Column(String(20))
    is_primary = Column(Boolean, server_default="false", nullable=False)
    status = Column(Enum(BankStatusEnum), server_default="pending")
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # inside CompanyBankInfo class (after mts)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
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
        foreign_keys=lambda: [CompanyBankDocument.company_bank_info_id]
    )

   

# ------------------------------
# UserRole Model
# ------------------------------
class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "public"}

    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("public.roles.id", ondelete="CASCADE"), primary_key=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
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

    created_by = Column(ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    modified_by = Column(ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_user = relationship("User", foreign_keys=[created_by], lazy="joined")
    modified_user = relationship("User", foreign_keys=[modified_by], lazy="joined")
    role = relationship("Role", back_populates="privileges")
    module = relationship("Module", back_populates="privileges")

    

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

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category = relationship("ProductCategory", back_populates="subcategories")
    created_user = relationship("User", foreign_keys=[created_by])
    modified_user = relationship("User", foreign_keys=[modified_by])
    products = relationship("Product", back_populates="subcategory_obj")


# ------------------------------
# Product Model (Updated)
# ------------------------------
class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    category_id = Column(Integer, ForeignKey("public.product_categories.id", ondelete="SET NULL"))
    subcategory_id = Column(Integer, ForeignKey("public.product_subcategories.id", ondelete="SET NULL"))
    sku = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    is_active = Column(Boolean, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_user = relationship("User", foreign_keys=[created_by])
    modified_user = relationship("User", foreign_keys=[modified_by])
    
    erp_sync_status = Column(String(10), default="pending")     # pending | success | failed
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
    category_obj = relationship("ProductCategory", back_populates="products")
    subcategory_obj = relationship("ProductSubCategory", back_populates="products")
    companies = relationship("CompanyProduct", back_populates="product", cascade="all, delete")


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
    pan = Column(String(10), unique=True, nullable=False)
    gstin = Column(String(15), unique=True)
    tan = Column(String(10), unique=True)
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

    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # inside CompanyBankDocument class (after modified_at)
    erp_sync_status = Column(String(10), default="pending")
    erp_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    erp_error_message = Column(Text, nullable=True)
    erp_external_id = Column(String(255), nullable=True)
    # Relationships
    company_tax_info = relationship("CompanyTaxInfo", back_populates="documents")

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
    category_master_id = Column(Integer, ForeignKey("public.CategoryMaster.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Audit Columns
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ✅ Many-to-One: Detail → Master
    master = relationship(
        "CategoryMaster",
        back_populates="details",
        foreign_keys=[category_master_id]
    )

    # ✅ One-to-Many: Detail → UserDocuments
    user_documents = relationship(
        "UserDocument",
        back_populates="categorydetails",
        cascade="all, delete-orphan",
        foreign_keys="UserDocument.category_detail_id"
    )


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
