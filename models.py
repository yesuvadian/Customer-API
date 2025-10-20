
import uuid
from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint, func,Text
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

    # Relationships
    security = relationship("UserSecurity", uselist=False, back_populates="user", cascade="all, delete")
    user_roles = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete",
        foreign_keys="[UserRole.user_id]"  # ⚡ fix ambiguous foreign key
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

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=UTCDateTimeMixin._utc_now)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)

    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    user = relationship("User", back_populates="sessions")

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
