
import uuid
from sqlalchemy import (
    Column, LargeBinary, String, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint, func,Text
)
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import relationship
from database import Base
from utils.common_service import UTCDateTimeMixin

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

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"))
    sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete",
        foreign_keys=lambda: [UserSession.user_id]
    )

    # Relationships
    security = relationship("UserSecurity", uselist=False, back_populates="user", cascade="all, delete")
    user_roles = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete",
        foreign_keys="[UserRole.user_id]"  # ⚡ fix ambiguous foreign key
    )
class CompanyTaxDocument(Base):
    __tablename__ = "company_tax_documents"
    __table_args__ = {"schema": "public"}
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_tax_info_id = Column(Integer, ForeignKey("company_tax_info.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    file_type = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    modified_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    #company_tax_info = relationship("CompanyTaxInfo", back_populates="documents")

class State(Base):
    __tablename__ = "states"
    __table_args__ = {"schema": "public"}
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(10))
    country_id = Column(Integer, ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
   
class UserAddress(Base):
    __tablename__ = "user_addresses"
    __table_args__ = (
        UniqueConstraint("user_id", "address_type", "is_primary", name="user_addresses_user_id_address_type_is_primary_key"),
        {"schema": "public"}
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    address_type = Column(String(50), nullable=False)
    is_primary = Column(Boolean, default=False)
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255))
    state_id = Column(Integer, ForeignKey("public.states.id", ondelete="SET NULL"))
    country_id = Column(Integer, ForeignKey("public.countries.id", ondelete="SET NULL"))
    postal_code = Column(String(20))
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)
    mts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])
    modifier = relationship("User", foreign_keys=[modified_by])
    state = relationship("State", foreign_keys=[state_id])
    country = relationship("Country", foreign_keys=[country_id])

    #country = relationship("Country", back_populates="states")
    #company_tax_infos = relationship("CompanyTaxInfo", back_populates="state")
class CompanyTaxInfo(Base):
    __tablename__ = "company_tax_info"
    __table_args__ = {"schema": "public"}
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False)
    pan = Column(String(10), unique=True, nullable=False)
    gstin = Column(String(15), unique=True)
    tan = Column(String(10), unique=True)
    state_id = Column(Integer, ForeignKey("states.id", ondelete="SET NULL"))
    financial_year = Column(String(9))
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"))
    cts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)
    mts = Column(DateTime, default=UTCDateTimeMixin._utc_now, nullable=False)

    #company = relationship("User", back_populates="company_tax_infos", foreign_keys=[company_id])
    #creator = relationship("User", foreign_keys=[created_by])
    #modifier = relationship("User", foreign_keys=[modified_by])
    # CompanyTaxInfo
    #state = relationship("State", back_populates="company_tax_infos", foreign_keys=[state_id])
    #documents = relationship("CompanyTaxDocument", back_populates="company_tax_info", cascade="all, delete")

# ------------------------------
# Country & State Models
# ------------------------------
class Country(Base):
    __tablename__ = "countries"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(10), unique=True)

    

    #states = relationship("State", back_populates="country", cascade="all, delete")
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

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=UTCDateTimeMixin._utc_now)
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
