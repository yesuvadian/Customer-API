"""
Detailed Project Report (DPR) — capital works / major maintenance project proposal.

This is the entity a DPR RepairWorkflow instance attaches to, via
RepairWorkflow.entity_type='dpr_project' / entity_id=DprProject.id — the same
generic entity_type/entity_id slot RepairWorkflow already exposes for
non-equipment workflows.

The 5-stage approval lifecycle itself (Initiation -> Cost Estimation ->
Technical Review -> Authority Approval -> Execution Tracking) is NOT modeled
here — it lives entirely in the existing RepairWorkflowDefinition /
RepairStageDefinition / RepairStageRole / RepairStageTransition /
RepairStageTemplate tables, seeded by seed_dpr_workflow.py. This table only
holds the DPR's own identity fields (title, proposing dept, etc.) — anything
stage-specific (cost breakdown, technical review checklist, approval
remarks) lives in each stage's OrgTestTemplate-driven form_data instead of as
columns here, same as every other RepairWorkflow-backed process.
"""

from sqlalchemy import Column, String, Text, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from database import Base


class DprProject(Base):
    """A Detailed Project Report — one capital works / major maintenance
    proposal going through the DPR approval workflow."""
    __tablename__ = "dpr_projects"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Human-readable identifier, e.g. "DPR-2026-0001" — generated the same
    # way RepairWorkflowService.generate_workflow_number() builds
    # "RW-REP-<date>-<seq>" (see DprProjectService.generate_project_number).
    project_number = Column(String(50), unique=True, nullable=False, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # What kind of capital works this is (transformer bank replacement,
    # protection system upgrade, civil works, ...) — free text for now;
    # promote to a dropdown-backed lookup table if/when the utility wants a
    # fixed taxonomy.
    project_category = Column(String(100), nullable=True)

    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposing_department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.org_departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Optional link to the substation/equipment this DPR concerns, when
    # applicable (e.g. "replace transformer bank at X substation"). Nullable
    # since some DPRs (civil works, a new substation) have no single
    # equipment to anchor to.
    equipment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.equipment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Denormalized headline numbers, kept in sync from the Cost Estimation /
    # Authority Approval stage form_data by DprProjectService, so lists and
    # dashboards don't need to reach into RepairStageData JSON to sort/filter
    # by cost. The authoritative figures still live in that stage's
    # form_data — these are a read-optimized mirror, not the source of truth.
    estimated_cost = Column(Numeric(14, 2), nullable=True)
    approved_cost = Column(Numeric(14, 2), nullable=True)

    # Mirrors the linked RepairWorkflow's status once that's wired up
    # ("active" | "completed" | "cancelled") — kept here too so project list
    # views don't need to join RepairWorkflow just to filter/sort by status.
    status = Column(String(20), nullable=False, default="active")

    # Set once at creation by DprProjectService.create_project() — the
    # RepairWorkflow instance driving this project's stage lifecycle.
    # Same pattern as TAQCObservation.workflow_id.
    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repair_workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Denormalized from RepairWorkflow.current_stage -> RepairStageDefinition
    # .code after every stage transition (DprProjectService._sync_stage,
    # mirroring AnnualAuditService._sync_stage) — lets list views filter by
    # stage without joining through the workflow tables.
    current_stage_code = Column(String(50), nullable=True, index=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    modified_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    modified_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
