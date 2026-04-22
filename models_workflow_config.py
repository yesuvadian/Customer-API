"""
Workflow Role Configuration Models
Defines which roles can be assigned to different workflow types based on module permissions
"""

from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, func, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid
from database import Base


class WorkflowRoleConfig(Base):
    """
    Configuration for role assignment in workflows.
    Defines which module permissions are required for a role to be assignable in a workflow.

    Example: For "testing_request" workflow, require roles to have can_add=True
    on module_id=45 (Testing Requests) to be shown as tester options.
    """
    __tablename__ = "workflow_role_configs"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Workflow type (e.g., "testing_request", "inspection_request", "approval_workflow")
    workflow_type = Column(String(100), nullable=False, index=True)

    # Role assignment type (e.g., "tester", "inspector", "reviewer")
    assignment_type = Column(String(100), nullable=False)

    # Module that must have permissions
    module_id = Column(Integer, ForeignKey("public.modules.id", ondelete="CASCADE"), nullable=False)

    # Required permissions on the module
    requires_can_view = Column(Boolean, default=False)
    requires_can_add = Column(Boolean, default=False)
    requires_can_edit = Column(Boolean, default=False)
    requires_can_delete = Column(Boolean, default=False)
    requires_can_approve = Column(Boolean, default=False)
    requires_can_assign = Column(Boolean, default=False)

    # Description
    description = Column(Text)

    # Active flag
    is_active = Column(Boolean, default=True)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    cts = Column(DateTime(timezone=True), server_default=func.now())
    mts = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
