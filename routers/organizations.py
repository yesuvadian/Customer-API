"""
Organization management endpoints.
Provides CRUD operations for organizations.
"""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from auth_utils import get_current_user
from middleware.org_auth import require_super_admin, require_org_admin, require_org_member
from models import User, Organization, OrgOnboardingSteps, SystemConfig
from schemas import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationOut,
    OrganizationWithAdmin
)
from services.organization_service import OrganizationService


def _cfg_int(db: Session, key: str, default: int) -> int:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return int(row.value) if row else default


router = APIRouter(
    prefix="/organizations",
    tags=["organizations"]
)


@router.post("/", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    org_data: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Create a new organization.
    Only super admins can create organizations.
    """
    service = OrganizationService(db)
    return service.create_organization(org_data, created_by=current_user.id)


@router.post("/with-admin", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization_with_admin(
    data: OrganizationWithAdmin,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Create a new organization with an admin user.
    Auto-provisions default roles and assigns admin role to the user.
    Only super admins can create organizations.
    """
    service = OrganizationService(db)

    org, admin_user = service.create_organization_with_admin(
        name=data.organization.name,
        code=data.organization.code,
        admin_email=data.admin_email,
        admin_password=data.admin_password,
        admin_firstname=data.admin_firstname,
        admin_lastname=data.admin_lastname,
        admin_phone=data.admin_phone,
        display_name=data.organization.display_name,
        organization_type=data.organization.organization_type,
        industry=data.organization.industry,
        website=data.organization.website,
        primary_email=data.organization.primary_email,
        primary_phone=data.organization.primary_phone,
        plan_id=data.organization.plan_id,
        is_active=data.organization.is_active,
        settings=data.organization.settings or {}
    )

    return org


@router.get("/my-organization", response_model=OrganizationOut)
def get_my_organization(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the current user's organization.
    Returns the organization the user belongs to.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not assigned to any organization"
        )

    service = OrganizationService(db)
    org = service.get_organization(current_user.organization_id)

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return org


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_member)
):
    """
    Get organization by ID.
    Users can only access their own organization unless they're super admin.
    """
    service = OrganizationService(db)
    return service.get_organization(org_id)


@router.get("/", response_model=List[OrganizationOut])
def list_organizations(
    skip: int = 0,
    limit: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List organizations.
    - Super admins: See all organizations
    - Org admins: See only their organization
    """
    service = OrganizationService(db)

    # Check if user is super admin (no organization_id)
    if current_user.organization_id is None:
        # Super admin - return all organizations
        return service.list_organizations(skip=skip, limit=limit, is_active=is_active)
    else:
        # Org admin - return only their organization
        org = service.get_organization(current_user.organization_id)
        if org:
            return [org]
        return []


@router.put("/{org_id}", response_model=OrganizationOut)
def update_organization(
    org_id: UUID,
    org_data: OrganizationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin)
):
    """
    Update organization.
    Only org admins can update their organization.
    """
    service = OrganizationService(db)
    return service.update_organization(org_id, org_data, modified_by=current_user.id)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Soft delete organization.
    Only super admins can delete organizations.
    """
    service = OrganizationService(db)
    service.delete_organization(org_id)
    return None


@router.post("/{org_id}/verify", response_model=OrganizationOut)
def verify_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Verify an organization.
    Only super admins can verify organizations.
    """
    service = OrganizationService(db)
    return service.verify_organization(org_id, verified_by=current_user.id)


@router.get("/code/{code}", response_model=OrganizationOut)
def get_organization_by_code(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Get organization by code.
    Only super admins can search by code.
    """
    service = OrganizationService(db)
    org = service.get_organization_by_code(code)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization with code '{code}' not found"
        )
    return org


# ── Onboarding & Trial Status ────────────────────────────────────────────────

@router.get("/onboarding/status")
def get_onboarding_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=404, detail="No organisation assigned")

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    steps = db.query(OrgOnboardingSteps).filter(
        OrgOnboardingSteps.organization_id == org.id
    ).first()

    steps_data = None
    if steps:
        steps_data = {
            "org_profile": steps.step_org_profile,
            "dept_hierarchy": steps.step_dept_hierarchy,
            "roles_confirmed": steps.step_roles_confirmed,
            "users_invited": steps.step_users_invited,
        }
        all_done = all(steps_data.values())
        if all_done and not org.onboarding_complete:
            org.onboarding_complete = True
            org.onboarding_completed_at = datetime.now(timezone.utc)
            db.commit()

    return {
        "onboarding_complete": org.onboarding_complete,
        "steps": steps_data,
    }


@router.post("/onboarding/step/{step_name}")
def mark_onboarding_step(
    step_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    valid_steps = {"org_profile", "dept_hierarchy", "roles_confirmed", "equip_types", "users_invited"}
    if step_name not in valid_steps:
        raise HTTPException(status_code=400, detail=f"Unknown step '{step_name}'")

    if not current_user.organization_id:
        raise HTTPException(status_code=404, detail="No organisation assigned")

    steps = db.query(OrgOnboardingSteps).filter(
        OrgOnboardingSteps.organization_id == current_user.organization_id
    ).first()

    if not steps:
        steps = OrgOnboardingSteps(organization_id=current_user.organization_id)
        db.add(steps)

    setattr(steps, f"step_{step_name}", True)
    db.commit()
    db.refresh(steps)

    all_done = all([
        steps.step_org_profile,
        steps.step_dept_hierarchy,
        steps.step_roles_confirmed,
        steps.step_users_invited,
    ])
    if all_done:
        org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
        if org and not org.onboarding_complete:
            org.onboarding_complete = True
            org.onboarding_completed_at = datetime.now(timezone.utc)
            db.commit()

    return {"step": step_name, "marked": True, "all_complete": all_done}


@router.post("/onboarding/complete")
def complete_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark onboarding fully complete — called by wizard Finish or Skip."""
    if not current_user.organization_id:
        raise HTTPException(status_code=404, detail="No organisation assigned")

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    if not org.onboarding_complete:
        org.onboarding_complete = True
        org.onboarding_completed_at = datetime.now(timezone.utc)

    # Also mark all steps so the step table is consistent
    steps = db.query(OrgOnboardingSteps).filter(
        OrgOnboardingSteps.organization_id == current_user.organization_id
    ).first()
    if not steps:
        steps = OrgOnboardingSteps(organization_id=current_user.organization_id)
        db.add(steps)
    steps.step_org_profile = True
    steps.step_roles_confirmed = True
    steps.step_dept_hierarchy = True
    steps.step_users_invited = True

    # Provision TR workflow roles and stages before marking complete
    from seed_tr_wf_workflow import seed_tr_wf_workflow
    seed_tr_wf_workflow(db, org=org)

    db.commit()
    return {"onboarding_complete": True}


@router.get("/trial/status")
def get_trial_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=404, detail="No organisation assigned")

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    days_remaining = None
    alert_active = False
    if org.is_trial and org.trial_end_date:
        now = datetime.now(timezone.utc)
        delta = (org.trial_end_date - now).days
        days_remaining = max(0, delta)
        alert_days = _cfg_int(db, "trial_alert_days", 7)
        alert_active = days_remaining <= alert_days

    return {
        "is_trial": org.is_trial,
        "trial_status": org.trial_status,
        "trial_start_date": org.trial_start_date.isoformat() if org.trial_start_date else None,
        "trial_end_date": org.trial_end_date.isoformat() if org.trial_end_date else None,
        "days_remaining": days_remaining,
        "alert_active": alert_active,
    }
