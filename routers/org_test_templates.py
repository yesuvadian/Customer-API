"""
Router: /org-test-templates

Endpoints for managing per-org test templates (designer CRUD + provisioning).
Protected by auth; privilege-check is handled by auth_privilege middleware
against the "Test Template Management" module.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import OrgTestTemplate, User
from schemas import OrgTestTemplateCreate, OrgTestTemplateResponse, OrgTestTemplateUpdate
from services.org_test_template_service import OrgTestTemplateService

router = APIRouter(
    prefix="/org-test-templates",
    tags=["org-test-templates"],
    dependencies=[Depends(get_current_user)],
)


# ─── List ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[OrgTestTemplateResponse])
def list_templates(
    org_id: Optional[UUID] = Query(None, description="Filter by org; omit for global defaults"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgTestTemplateService(db)
    return svc.list_templates(org_id=org_id)


# ─── Fetch for tester form (by test_type_id, best-match) ─────────────────────

@router.get("/by-test-type/{test_type_id}", response_model=OrgTestTemplateResponse)
def get_by_test_type(
    test_type_id: int,
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the template for a given test_type_id.
    Prefers org-specific row; falls back to global default.
    """
    svc = OrgTestTemplateService(db)
    return svc.get_for_test_type(test_type_id=test_type_id, org_id=org_id)


# ─── Single ──────────────────────────────────────────────────────────────────

@router.get("/{template_id}", response_model=OrgTestTemplateResponse)
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgTestTemplateService(db)
    return svc.get_by_id(template_id)


# ─── Create ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=OrgTestTemplateResponse, status_code=201)
def create_template(
    body: OrgTestTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgTestTemplateService(db)
    return svc.create_template(
        template_key=body.template_key,
        template_data=body.template_data,
        test_type_id=body.test_type_id,
        org_id=body.org_id,
        created_by=current_user.id,
    )


# ─── Update (designer save) ───────────────────────────────────────────────────

@router.put("/{template_id}", response_model=OrgTestTemplateResponse)
def update_template(
    template_id: UUID,
    body: OrgTestTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgTestTemplateService(db)
    return svc.update_template(
        template_id=template_id,
        template_data=body.template_data,
        modified_by=current_user.id,
    )


# ─── Reset to global default ─────────────────────────────────────────────────

@router.post("/{template_id}/reset", response_model=OrgTestTemplateResponse)
def reset_to_global(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset an org-specific template back to the global default."""
    svc = OrgTestTemplateService(db)
    return svc.reset_to_global(template_id=template_id, modified_by=current_user.id)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgTestTemplateService(db)
    svc.delete_template(template_id)


# ─── Provisioning ────────────────────────────────────────────────────────────

@router.post("/provision/global", status_code=200)
def provision_global(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Seed global default templates from static test_templates.py dict."""
    svc = OrgTestTemplateService(db)
    count = svc.provision_global_defaults()
    return {"inserted": count, "message": f"Provisioned {count} global templates"}


@router.post("/provision/org/{org_id}", status_code=200)
def provision_for_org(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clone all global defaults for a specific org."""
    svc = OrgTestTemplateService(db)
    count = svc.provision_for_org(org_id=org_id, created_by=current_user.id)
    return {"inserted": count, "message": f"Provisioned {count} templates for org {org_id}"}
