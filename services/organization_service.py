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

            # 2c. Provision TR workflow engine for new org
            self._provision_tr_workflow(org.id)

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
        Clone all active roles (+ module permissions) from the KPTCL template org
        to the new org. Falls back to RoleTemplate provisioning if KPTCL not found.
        """
        from uuid import uuid4
        from models import Organization

        template_org = self.db.query(Organization).filter_by(code="KPTCL").first()
        if template_org:
            source_roles = self.db.query(OrgRole).filter_by(
                organization_id=template_org.id, is_active=True
            ).all()
            new_roles: List[OrgRole] = []
            for src in source_roles:
                existing = self.db.query(OrgRole).filter_by(
                    organization_id=org_id, name=src.name
                ).first()
                if existing:
                    new_roles.append(existing)
                    continue
                role = OrgRole(
                    id=uuid4(),
                    organization_id=org_id,
                    name=src.name,
                    description=src.description,
                    role_type=src.role_type or "default",
                    is_org_admin=src.is_org_admin,
                    is_dept_admin=src.is_dept_admin,
                    is_tester_assignable=getattr(src, "is_tester_assignable", False),
                    is_active=True,
                    cts=self._utc_now(),
                    mts=self._utc_now(),
                )
                self.db.add(role)
                self.db.flush()
                for p in self.db.query(OrgRolePermission).filter_by(org_role_id=src.id).all():
                    self.db.add(OrgRolePermission(
                        id=uuid4(),
                        org_role_id=role.id,
                        module_id=p.module_id,
                        can_view=p.can_view,
                        can_add=p.can_add,
                        can_edit=p.can_edit,
                        can_delete=p.can_delete,
                        can_approve=p.can_approve,
                        can_assign=p.can_assign,
                        can_export=p.can_export,
                        can_import=p.can_import,
                        cts=self._utc_now(),
                        mts=self._utc_now(),
                    ))
                new_roles.append(role)
            self.db.flush()
            print(f"[INFO] Cloned {len(new_roles)} roles from KPTCL → org {org_id}")
            return new_roles

        # Fallback: RoleTemplate-based provisioning
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

    def _provision_tr_workflow(self, org_id: UUID) -> None:
        """
        Provision a generic TR Configurable Workflow for a newly registered org.
        Creates: OrgRoles, TrWfDefinition, TrWfStatus, TrWfStage, TrWfStageRole,
                 TrWfStageTransition, TrWfRoutingDefault.
        Idempotent — safe to call again if provisioning was already done.
        """
        try:
            import uuid as _uuid
            from models import (
                TrWfDefinition, TrWfRoutingDefault, TrWfRoutingRule,
                TrWfStage, TrWfStageRole, TrWfStageTransition, TrWfStatus,
            )

            db = self.db

            def _role(name, description, is_tester_assignable=False):
                r = db.query(OrgRole).filter_by(organization_id=org_id, name=name).first()
                if not r:
                    r = OrgRole(
                        id=_uuid.uuid4(), organization_id=org_id, name=name,
                        description=description, role_type="default",
                        is_org_admin=False, is_dept_admin=False,
                        is_tester_assignable=is_tester_assignable, is_active=True,
                    )
                    db.add(r)
                    db.flush()
                return r

            def _status(wf, code, name, seq, color, approval=False, assignment=False, terminal=False):
                s = db.query(TrWfStatus).filter_by(wf_definition_id=wf.id, status_code=code).first()
                if not s:
                    s = TrWfStatus(
                        id=_uuid.uuid4(), wf_definition_id=wf.id, status_code=code,
                        status_name=name, sequence=seq, color=color,
                        approval_required=approval, assignment_required=assignment,
                        is_terminal=terminal, is_active=True,
                    )
                    db.add(s)
                    db.flush()
                return s

            def _stage(wf, status, name, code, seq, **flags):
                s = db.query(TrWfStage).filter_by(wf_definition_id=wf.id, code=code).first()
                if not s:
                    s = TrWfStage(
                        id=_uuid.uuid4(), wf_definition_id=wf.id, status_id=status.id,
                        name=name, code=code, sequence=seq, weight=10,
                        is_mandatory=True, is_active=True, **flags,
                    )
                    db.add(s)
                    db.flush()
                return s

            def _stage_role(stage, role, can_approve=False, can_assign=False, can_edit=False):
                if not role:
                    return
                exists = db.query(TrWfStageRole).filter_by(stage_id=stage.id, role_id=role.id).first()
                if not exists:
                    db.add(TrWfStageRole(
                        id=_uuid.uuid4(), stage_id=stage.id, role_id=role.id,
                        can_approve=can_approve, can_assign=can_assign, can_edit=can_edit,
                    ))

            def _transition(from_stage, to_stage, action_code,
                            requires_comment=False, is_rejection=False,
                            terminal_status=None, post_action=None):
                exists = db.query(TrWfStageTransition).filter_by(
                    from_stage_id=from_stage.id, action_code=action_code
                ).first()
                if not exists:
                    db.add(TrWfStageTransition(
                        id=_uuid.uuid4(), from_stage_id=from_stage.id,
                        to_stage_id=to_stage.id if to_stage else None,
                        action_code=action_code, requires_comment=requires_comment,
                        is_rejection=is_rejection,
                        terminal_status_id=terminal_status.id if terminal_status else None,
                        post_action=post_action,
                    ))

            from models import Module, OrgRolePermission as OrgRolePerm

            def _grant(role, mod_name, can_view=True, can_add=False, can_edit=False,
                       can_delete=False, can_approve=False, can_assign=False):
                mod = db.query(Module).filter_by(name=mod_name, is_active=True).first()
                if not mod:
                    return
                exists = db.query(OrgRolePerm).filter_by(
                    org_role_id=role.id, module_id=mod.id
                ).first()
                if not exists:
                    db.add(OrgRolePerm(
                        id=_uuid.uuid4(), org_role_id=role.id, module_id=mod.id,
                        can_view=can_view, can_add=can_add, can_edit=can_edit,
                        can_delete=can_delete, can_approve=can_approve, can_assign=can_assign,
                    ))

            # ── Generic roles ─────────────────────────────────────────────────
            role_l2       = _role("L2 Approver",      "Approves and routes test requests at L2")
            role_l3       = _role("L3 Test Assigner",  "Assigns testers at L3 stage")
            role_l4       = _role("L4 Tester",         "Executes tests at L4 stage", is_tester_assignable=True)
            role_reviewer = _role("L3 Reviewer",       "Reviews and approves test results")

            # ── Module permissions ────────────────────────────────────────────
            # L2 Approver: full TR admin access
            _grant(role_l2, "TR Approval Queue",  can_view=True, can_add=True, can_edit=True)
            _grant(role_l2, "TR Result Review",   can_view=True, can_edit=True)
            _grant(role_l2, "TR Workflow Config", can_view=True, can_add=True, can_edit=True)
            _grant(role_l2, "TR Routing Config",  can_view=True, can_add=True, can_edit=True)
            # L3 Test Assigner: approval queue + result review
            _grant(role_l3, "TR Approval Queue",  can_view=True, can_add=True, can_edit=True)
            _grant(role_l3, "TR Result Review",   can_view=True, can_edit=True)
            # L4 Tester: approval queue read + testing module
            _grant(role_l4, "TR Approval Queue",  can_view=True, can_edit=True)
            _grant(role_l4, "Testing",            can_view=True, can_add=True, can_edit=True,
                   can_delete=True, can_approve=True, can_assign=True)
            # L3 Reviewer: approval queue + result review
            _grant(role_reviewer, "TR Approval Queue", can_view=True, can_add=True, can_edit=True)
            _grant(role_reviewer, "TR Result Review",  can_view=True, can_edit=True)
            db.flush()

            # ── Workflow definition ───────────────────────────────────────────
            wf = db.query(TrWfDefinition).filter_by(org_id=org_id, name="Standard Test Workflow").first()
            if not wf:
                wf = TrWfDefinition(
                    id=_uuid.uuid4(), org_id=org_id,
                    name="Standard Test Workflow", request_type="normal",
                    is_default=True, is_active=True,
                    default_l3_role_id=role_l3.id,
                    default_tester_role_id=role_l4.id,
                )
                db.add(wf)
                db.flush()

            # ── Statuses ──────────────────────────────────────────────────────
            st_l2  = _status(wf, "l2_pending_approval",   "Pending L2 Approval",   10, "#F59E0B", approval=True)
            st_l3  = _status(wf, "l3_pending_assignment", "Pending L3 Assignment", 20, "#3B82F6", assignment=True)
            st_l4  = _status(wf, "testing_in_progress",   "Testing In Progress",   30, "#8B5CF6")
            st_rev = _status(wf, "under_l3_review",       "Under L3 Review",       40, "#0891B2", approval=True)
            st_ok  = _status(wf, "wf_completed",          "Workflow Completed",    50, "#10B981", terminal=True)
            st_rej = _status(wf, "wf_rejected",           "Rejected",              60, "#EF4444", terminal=True)
            st_can = _status(wf, "wf_cancelled",          "Cancelled",             70, "#6B7280", terminal=True)

            # ── Stages ────────────────────────────────────────────────────────
            sg_l2  = _stage(wf, st_l2, "L2 Approval & Route",  "l2_approve_route",  1, use_l2_route=True)
            sg_l3  = _stage(wf, st_l3, "L3 Tester Assignment", "l3_assign_tester",  2, is_role_scoped=True)
            sg_l4  = _stage(wf, st_l4, "L4 Test Execution",    "l4_test_execution", 3)
            sg_rev = _stage(wf, st_rev, "L3 Result Review",    "l3_review_result",  4,
                            show_recommendation=True, is_result_stage=True, is_role_scoped=True)

            # ── Stage roles ───────────────────────────────────────────────────
            _stage_role(sg_l2,  role_l2,      can_approve=True)
            _stage_role(sg_l3,  role_l3,      can_assign=True)
            _stage_role(sg_l4,  role_l4,      can_edit=True)
            _stage_role(sg_rev, role_reviewer, can_approve=True)

            # ── Transitions ───────────────────────────────────────────────────
            _transition(sg_l2,  sg_l3,  "approve")
            _transition(sg_l2,  None,   "reject",   requires_comment=True, is_rejection=True, terminal_status=st_rej)
            _transition(sg_l2,  None,   "cancel",   requires_comment=True, terminal_status=st_can)
            _transition(sg_l3,  sg_l4,  "assign")
            _transition(sg_l3,  None,   "cancel",   requires_comment=True, terminal_status=st_can)
            _transition(sg_l4,  sg_rev, "complete")
            _transition(sg_l4,  sg_l3,  "return",   requires_comment=True)
            _transition(sg_rev, None,   "approve",  terminal_status=st_ok, post_action="recommendation_finalize")
            _transition(sg_rev, sg_l4,  "reject",   requires_comment=True, is_rejection=True)
            _transition(sg_rev, None,   "cancel",   requires_comment=True, terminal_status=st_can)

            # ── Standard R&D Workflow (same 4-stage flow, reviewer role) ────────
            wf_rnd = db.query(TrWfDefinition).filter_by(org_id=org_id, name="Standard R&D Workflow").first()
            if not wf_rnd:
                wf_rnd = TrWfDefinition(
                    id=_uuid.uuid4(), org_id=org_id,
                    name="Standard R&D Workflow", request_type=None,
                    is_default=False, is_active=True,
                    default_l3_role_id=role_l3.id,
                    default_tester_role_id=role_l4.id,
                )
                db.add(wf_rnd)
                db.flush()

            rnd_l2  = _status(wf_rnd, "l2_pending_approval",   "Pending L2 Approval",   10, "#F59E0B", approval=True)
            rnd_l3  = _status(wf_rnd, "l3_pending_assignment", "Pending L3 Assignment", 20, "#3B82F6", assignment=True)
            rnd_l4  = _status(wf_rnd, "testing_in_progress",   "Testing In Progress",   30, "#8B5CF6")
            rnd_rev = _status(wf_rnd, "under_l3_review",       "Under L3 Review",       40, "#0891B2", approval=True)
            rnd_ok  = _status(wf_rnd, "wf_completed",          "Workflow Completed",    50, "#10B981", terminal=True)
            rnd_rej = _status(wf_rnd, "wf_rejected",           "Rejected",              60, "#EF4444", terminal=True)
            rnd_can = _status(wf_rnd, "wf_cancelled",          "Cancelled",             70, "#6B7280", terminal=True)

            sg_rnd_l2  = _stage(wf_rnd, rnd_l2,  "L2 Approval & Route",  "l2_approve_route",  1, use_l2_route=True)
            sg_rnd_l3  = _stage(wf_rnd, rnd_l3,  "L3 Tester Assignment", "l3_assign_tester",  2, is_role_scoped=True)
            sg_rnd_l4  = _stage(wf_rnd, rnd_l4,  "L4 Test Execution",    "l4_test_execution", 3)
            sg_rnd_rev = _stage(wf_rnd, rnd_rev,  "L3 Result Review",    "l3_review_result",  4,
                                show_recommendation=True, is_result_stage=True, is_role_scoped=True)

            _stage_role(sg_rnd_l2,  role_l2,       can_approve=True)
            _stage_role(sg_rnd_l3,  role_l3,       can_assign=True)
            _stage_role(sg_rnd_l4,  role_l4,       can_edit=True)
            _stage_role(sg_rnd_rev, role_reviewer,  can_approve=True)

            _transition(sg_rnd_l2,  sg_rnd_l3,  "approve")
            _transition(sg_rnd_l2,  None,        "reject",  requires_comment=True, is_rejection=True, terminal_status=rnd_rej)
            _transition(sg_rnd_l2,  None,        "cancel",  requires_comment=True, terminal_status=rnd_can)
            _transition(sg_rnd_l3,  sg_rnd_l4,  "assign")
            _transition(sg_rnd_l3,  None,        "cancel",  requires_comment=True, terminal_status=rnd_can)
            _transition(sg_rnd_l4,  sg_rnd_rev, "complete")
            _transition(sg_rnd_l4,  sg_rnd_l3,  "return",  requires_comment=True)
            _transition(sg_rnd_rev, None,        "approve", terminal_status=rnd_ok, post_action="recommendation_finalize")
            _transition(sg_rnd_rev, sg_rnd_l4,  "reject",  requires_comment=True, is_rejection=True)
            _transition(sg_rnd_rev, None,        "cancel",  requires_comment=True, terminal_status=rnd_can)

            # ── Failure Registry Workflow (2-stage flow) ──────────────────────
            wf_failure = db.query(TrWfDefinition).filter_by(org_id=org_id, name="Failure Registry Workflow").first()
            if not wf_failure:
                wf_failure = TrWfDefinition(
                    id=_uuid.uuid4(), org_id=org_id,
                    name="Failure Registry Workflow", request_type="failure_registry",
                    is_default=False, is_active=True,
                )
                db.add(wf_failure)
                db.flush()

            fr_l2   = _status(wf_failure, "fr_pending_l2",     "Pending L2 Review",        10, "#F59E0B", approval=True)
            fr_tech = _status(wf_failure, "fr_under_approval",  "Under Technical Approval", 20, "#7C3AED", approval=True)
            fr_done = _status(wf_failure, "fr_approved",        "FR Approved",              30, "#10B981", terminal=True)
            fr_rej  = _status(wf_failure, "fr_rejected",        "FR Rejected",              40, "#EF4444", terminal=True)
            fr_can  = _status(wf_failure, "fr_cancelled",       "FR Cancelled",             50, "#6B7280", terminal=True)

            sg_fr_l2   = _stage(wf_failure, fr_l2,   "L2 Initial Review",  "fr_l2_review",    1)
            sg_fr_tech = _stage(wf_failure, fr_tech,  "Technical Approval", "fr_tech_approve", 2, show_recommendation=True)

            _stage_role(sg_fr_l2,   role_l2, can_approve=True)
            _stage_role(sg_fr_tech, role_l2, can_approve=True)

            _transition(sg_fr_l2,   sg_fr_tech, "approve")
            _transition(sg_fr_l2,   None,       "reject",  requires_comment=True, is_rejection=True, terminal_status=fr_rej)
            _transition(sg_fr_l2,   None,       "cancel",  requires_comment=True, terminal_status=fr_can)
            _transition(sg_fr_tech, None,       "approve", terminal_status=fr_done, post_action="recommendation_finalize")
            _transition(sg_fr_tech, None,       "reject",  requires_comment=True, is_rejection=True, terminal_status=fr_rej)
            _transition(sg_fr_tech, None,       "cancel",  requires_comment=True, terminal_status=fr_can)

            # ── Special Test Workflow (empty — admin configures via UI) ────────
            if not db.query(TrWfDefinition).filter_by(org_id=org_id, name="Special Test Workflow").first():
                db.add(TrWfDefinition(
                    id=_uuid.uuid4(), org_id=org_id,
                    name="Special Test Workflow", request_type="special",
                    is_default=False, is_active=True,
                ))
                db.flush()

            wf_special = db.query(TrWfDefinition).filter_by(org_id=org_id, name="Special Test Workflow").first()

            # ── Document Support Workflow ─────────────────────────────────────
            role_ds_mgr  = _role("Dev Support Manager", "Manages document support requests")
            role_ds_proc = _role("Dev Support",         "Processes document support requests")

            wf_doc = db.query(TrWfDefinition).filter_by(org_id=org_id, name="Document Support Workflow").first()
            if not wf_doc:
                wf_doc = TrWfDefinition(
                    id=_uuid.uuid4(), org_id=org_id,
                    name="Document Support Workflow", request_type="document_support",
                    is_default=False, is_active=True,
                )
                db.add(wf_doc)
                db.flush()

            ds_pending_mgr  = _status(wf_doc, "ds_pending_manager",   "Pending Manager Review", 10, "#7C3AED")
            ds_pending_proc = _status(wf_doc, "ds_pending_processor", "Pending Processor",      20, "#0891B2")
            ds_processing   = _status(wf_doc, "ds_processing",        "Processing",             30, "#EA580C")
            ds_orig_review  = _status(wf_doc, "ds_originator_review", "Originator Review",      40, "#D97706")
            ds_completed    = _status(wf_doc, "ds_completed",         "Completed",              50, "#16A34A", terminal=True)
            ds_cancelled    = _status(wf_doc, "ds_cancelled",         "Cancelled",              60, "#6B7280", terminal=True)
            _status(wf_doc, "ds_rejected", "Rejected", 70, "#DC2626", terminal=True)

            sg_ds_mgr    = _stage(wf_doc, ds_pending_mgr,  "Manager Review",    "ds_manager_review",    10)
            sg_ds_proc   = _stage(wf_doc, ds_pending_proc, "Processor Queue",   "ds_processor_queue",   20)
            sg_ds_work   = _stage(wf_doc, ds_processing,   "Processing",        "ds_processing",        30)
            sg_ds_review = _stage(wf_doc, ds_orig_review,  "Originator Review", "ds_originator_review", 40)

            _stage_role(sg_ds_mgr,  role_ds_mgr,  can_approve=True, can_assign=True)
            _stage_role(sg_ds_proc, role_ds_proc, can_approve=True)
            _stage_role(sg_ds_work, role_ds_proc, can_approve=True, can_edit=True)

            _transition(sg_ds_mgr,    sg_ds_proc,   "assign")
            _transition(sg_ds_mgr,    None,          "reject",   requires_comment=True, is_rejection=True, terminal_status=ds_cancelled)
            _transition(sg_ds_mgr,    None,          "cancel",   is_rejection=True, terminal_status=ds_cancelled)
            _transition(sg_ds_proc,   sg_ds_work,   "assign")
            _transition(sg_ds_proc,   None,          "cancel",   is_rejection=True, terminal_status=ds_cancelled)
            _transition(sg_ds_work,   sg_ds_review, "complete")
            _transition(sg_ds_work,   None,          "cancel",   is_rejection=True, terminal_status=ds_cancelled)
            _transition(sg_ds_review, None,          "accept",   terminal_status=ds_completed)
            _transition(sg_ds_review, sg_ds_work,   "reject",   requires_comment=True, is_rejection=True)

            db.flush()

            # ── Routing default + request_type overrides ──────────────────────
            if not db.query(TrWfRoutingDefault).filter_by(org_id=org_id).first():
                db.add(TrWfRoutingDefault(
                    id=_uuid.uuid4(), org_id=org_id, wf_definition_id=wf.id,
                ))

            for req_type, wf_def in [("failure_registry", wf_failure), ("special", wf_special), ("document_support", wf_doc)]:
                if not db.query(TrWfRoutingRule).filter_by(
                    org_id=org_id, request_type=req_type,
                    equipment_type_id=None, test_type_id=None,
                ).first():
                    db.add(TrWfRoutingRule(
                        id=_uuid.uuid4(), org_id=org_id,
                        wf_definition_id=wf_def.id,
                        request_type=req_type,
                        priority=10, is_active=True,
                    ))

            # ── R&D test type override routing rules ──────────────────────────
            # Route specific test types (tan delta, IR, oil BDV, SFRA, etc.)
            # to L3/L4 roles via Standard Test Workflow at higher priority.
            rd_test_type_ids = [64, 65, 70, 71, 72, 136, 186, 66, 68, 75]
            for tt_id in rd_test_type_ids:
                if not db.query(TrWfRoutingRule).filter_by(
                    org_id=org_id, test_type_id=tt_id,
                ).first():
                    db.add(TrWfRoutingRule(
                        id=_uuid.uuid4(), org_id=org_id,
                        wf_definition_id=wf.id,
                        override_role_id=role_l3.id,
                        override_tester_role_id=role_l4.id,
                        test_type_id=tt_id,
                        priority=20, is_active=True,
                    ))

            db.flush()
            print(f"[INFO] TR workflow provisioned for org {org_id}")

        except Exception as e:
            print(f"[WARN] _provision_tr_workflow failed (non-fatal): {e}")

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
