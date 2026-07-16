"""
Router: /org-test-templates

Endpoints for managing per-org test templates (designer CRUD + provisioning).
Protected by auth; privilege-check is handled by auth_privilege middleware
against the "CM/PM Master Template" module.
"""
import io
import uuid as _uuid
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import OrgTestTemplate, User
from schemas import OrgTestTemplateCreate, OrgTestTemplateResponse, OrgTestTemplateUpdate
from services.org_test_template_service import OrgTestTemplateService, active_template_filter

router = APIRouter(
    prefix="/org-test-templates",
    tags=["org-test-templates"],
    dependencies=[Depends(get_current_user)],
)

# Separate router for browser-accessible endpoints (auth via query token)
browser_router = APIRouter(
    prefix="/org-test-templates",
    tags=["org-test-templates"],
)


# ─── List ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[OrgTestTemplateResponse])
def list_templates(
    org_id: Optional[UUID] = Query(None, description="Filter by org; omit for global defaults"),
    active_only: bool = Query(False, description="When true, exclude disabled templates"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgTestTemplateService(db)
    return svc.list_templates(org_id=org_id, active_only=active_only)


# ─── Overall Assessment (global appended section) ────────────────────────────

@router.get("/overall-assessment", response_model=OrgTestTemplateResponse)
def get_overall_assessment(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the overall assessment template (org-specific → global fallback)."""
    svc = OrgTestTemplateService(db)
    return svc.get_overall_assessment(org_id=org_id)


@router.post("/overall-assessment/provision", status_code=200)
def provision_overall_assessment(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Seed or update the global overall assessment template."""
    svc = OrgTestTemplateService(db)
    inserted = svc.provision_overall_assessment()
    return {"inserted": inserted, "message": "Provisioned" if inserted else "Updated"}


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


# ─── By request category ─────────────────────────────────────────────────────

@router.get("/by-request-category/{request_category}", response_model=OrgTestTemplateResponse)
def get_by_request_category(
    request_category: str,
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the best-match template for a given request_category
    (maintenance | inspection | repair_lifecycle).
    Prefers org-specific row; falls back to global default.
    Uses REQUEST_CATEGORY_TO_TEMPLATE from test_templates.py.
    """
    from test_templates import REQUEST_CATEGORY_TO_TEMPLATE
    template_key = REQUEST_CATEGORY_TO_TEMPLATE.get(request_category)
    if not template_key:
        raise HTTPException(
            status_code=404,
            detail=f"No default template mapped for request_category='{request_category}'",
        )
    svc = OrgTestTemplateService(db)
    # Try org-specific first, then global
    if org_id:
        tmpl = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.org_id == org_id, OrgTestTemplate.template_key == template_key,
                    active_template_filter())
            .first()
        )
        if tmpl:
            return tmpl
    tmpl = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.org_id == None, OrgTestTemplate.template_key == template_key,  # noqa: E711
                active_template_filter())
        .first()
    )
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_key}' not found or is disabled")
    return tmpl


# ─── Template for equipment type + category (used by PM/maintenance/inspection TRs) ──

@router.get("/for-equipment/{equipment_type_id}/category/{category_type}")
def get_for_equipment_category(
    equipment_type_id: int,
    category_type: str,
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the canonical template for a given equipment type + category type.
    Respects org override: org template wins over global.
    Used when a TR has no specific test_type_id (e.g. PM workflow).
    """
    from models import CategoryDetails
    from services.org_test_template_service import OrgTestTemplateService

    canonical = OrgTestTemplateService(db).canonical_templates_for_org(org_id=org_id)

    # Find the first CategoryDetail for this equipment + category that has a template
    detail = (
        db.query(CategoryDetails)
        .filter(
            CategoryDetails.category_master_id == equipment_type_id,
            CategoryDetails.category_type == category_type,
            CategoryDetails.is_active == True,
        )
        .order_by(CategoryDetails.id)
        .all()
    )
    for d in detail:
        tpl = canonical.get(d.id)
        if tpl:
            return tpl

    raise HTTPException(
        status_code=404,
        detail=f"No template found for equipment_type_id={equipment_type_id}, category_type={category_type}",
    )


# ─── List by category_type (e.g., "nameplate") ───────────────────────────────

@router.get("/by-category-type/{category_type}")
def list_by_category_type(
    category_type: str,
    org_id: Optional[UUID] = Query(None, description="Org UUID; omit for global defaults"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all templates whose linked CategoryDetails has the given category_type.
    Use category_type='nameplate' to list all 19 nameplate field-entry templates.
    Falls back to globals when org_id is not supplied.
    """
    from models import CategoryDetails as CD

    q = (
        db.query(OrgTestTemplate)
        .join(CD, CD.id == OrgTestTemplate.test_type_id)
        .filter(CD.category_type == category_type, active_template_filter())
    )
    if org_id:
        q = q.filter(OrgTestTemplate.org_id == org_id)
    else:
        q = q.filter(OrgTestTemplate.org_id == None)  # noqa: E711

    results = q.order_by(OrgTestTemplate.template_key).all()

    # Return lightweight list (key, name, equipment_type, section count)
    return [
        {
            "id": str(t.id),
            "template_key": t.template_key,
            "test_type_id": t.test_type_id,
            "name": t.template_data.get("name", t.template_key),
            "equipment_type": t.template_data.get("equipment_type"),
            "template_type": t.template_data.get("template_type"),
            "section_count": len(t.template_data.get("sections", [])),
            "is_system": t.is_system,
            "version": t.version,
        }
        for t in results
    ]


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


# ─── New test type + org template (atomic) ────────────────────────────────────

class _NewTypeRequest(BaseModel):
    equipment_master_id: int
    category_type: str          # test | maintenance | inspection | repair
    template_key: str
    template_data: dict
    org_id: Optional[UUID] = None

    class Config:
        extra = "forbid"


@router.post("/new-type", response_model=OrgTestTemplateResponse, status_code=201)
def create_new_type_template(
    body: _NewTypeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a brand-new test type (CategoryDetail) for an equipment master
    and immediately link it to a new org-specific OrgTestTemplate.
    """
    from models import CategoryDetails, CategoryMaster
    from services.org_test_template_service import OrgTestTemplateService

    # Validate equipment master exists
    master = db.query(CategoryMaster).filter(CategoryMaster.id == body.equipment_master_id).first()
    if not master:
        raise HTTPException(status_code=404, detail="Equipment master not found")

    valid_types = {"test", "maintenance", "inspection", "repair"}
    if body.category_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"category_type must be one of {valid_types}")

    type_name = body.template_data.get("name", "").strip()
    if not type_name:
        raise HTTPException(status_code=400, detail="template_data.name is required")

    # Create CategoryDetail (the new test type)
    detail = CategoryDetails(
        category_master_id=body.equipment_master_id,
        name=type_name,
        category_type=body.category_type,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(detail)
    db.flush()  # get detail.id

    # Create org-specific OrgTestTemplate linked to the new type
    org_id = body.org_id or current_user.organization_id
    svc = OrgTestTemplateService(db)
    tpl = svc.create_template(
        template_key=body.template_key,
        template_data=body.template_data,
        test_type_id=detail.id,
        org_id=org_id,
        created_by=current_user.id,
    )
    db.commit()
    return tpl


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


# ─── Enable / disable ────────────────────────────────────────────────────────

@router.patch("/{template_id}/active", response_model=OrgTestTemplateResponse)
def set_template_active(
    template_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle is_active on OrgTestTemplate and sync CategoryDetails.is_active by name."""
    from fastapi import HTTPException
    from models import CategoryDetails
    from test_templates import TEST_TYPE_TO_TEMPLATE

    tpl = db.query(OrgTestTemplate).filter(OrgTestTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    is_active = bool(body.get("is_active", True))

    # 1. Update OrgTestTemplate.template_data['is_active']
    data = dict(tpl.template_data or {})
    data["is_active"] = is_active
    tpl.template_data = data

    # 2. Sync CategoryDetails.is_active for all rows matching this template key
    #    Build reverse map: template_key -> list of CategoryDetails names
    template_key = tpl.template_key
    matching_names = [name for name, key in TEST_TYPE_TO_TEMPLATE.items() if key == template_key]
    if matching_names:
        db.query(CategoryDetails).filter(
            CategoryDetails.name.in_(matching_names)
        ).update({CategoryDetails.is_active: is_active}, synchronize_session=False)

    db.commit()
    db.refresh(tpl)
    return tpl


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


# ─── Preview (HTML) ──────────────────────────────────────────────────────────

def _auth_from_query_token(token: str, db: Session) -> User:
    """Verify a raw JWT token passed as a query param (for browser URL access)."""
    import os
    import jwt as pyjwt
    from models import User as UserModel
    SECRET_KEY = os.getenv("SECRET_KEY", "change_this_secret")
    ALGORITHM = "HS256"
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = _uuid.UUID(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@browser_router.get("/{template_id}/preview", response_class=HTMLResponse)
def preview_template(
    template_id: UUID,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """Render the template as a styled HTML form (browser-friendly preview)."""
    _auth_from_query_token(token, db)
    svc = OrgTestTemplateService(db)
    tmpl = svc.get_by_id(template_id)
    data = tmpl.template_data or {}
    name = data.get("name", tmpl.template_key or "Template")
    import copy
    sections = copy.deepcopy(data.get("sections", []))

    # Append Overall Assessment sections
    try:
        overall = svc.get_overall_assessment(org_id=tmpl.org_id)
        overall_sections = (overall.template_data or {}).get("sections", [])
        sections.extend(copy.deepcopy(overall_sections))
    except Exception:
        pass

    def _to_html_date(val: str) -> str:
        """Convert DD-MM-YYYY or DD/MM/YYYY → YYYY-MM-DD for <input type=date>."""
        if not val:
            return ""
        for sep in ("-", "/"):
            parts = val.split(sep)
            if len(parts) == 3:
                d, m, y = parts
                if len(y) == 4:          # DD-MM-YYYY
                    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                if len(d) == 4:          # YYYY-MM-DD already
                    return val
        return val

    def field_html(f: dict) -> str:
        ftype = f.get("type", "text")
        label = f.get("label", f.get("key", ""))
        unit = f.get("unit", "") or ""
        default = str(f.get("default", "") or "")
        required = f.get("required", False)
        read_only = f.get("read_only", False)
        opts = f.get("options", [])
        cols = f.get("columns", [])
        default_rows = f.get("default_rows", [])

        req_badge = '<span class="req">*</span>' if required else ""
        ro_badge = '<span class="ro">🔒 Read-only</span>' if read_only else ""
        unit_txt = f' <span class="unit">{unit}</span>' if unit else ""
        ro_class = ' ro-field' if read_only else ""
        ro_attr = 'readonly' if read_only else ""

        # Checkbox gets its own full-row container (no outer label wrapper)
        if ftype == "checkbox":
            checked = "checked" if default.lower() in ("true", "1", "yes") else ""
            disabled = "disabled" if read_only else ""
            cb_on = default.lower() in ("true", "1", "yes")

            bg = "rgba(63,169,245,0.12)" if cb_on else "rgba(255,255,255,0.04)"
            border_col = "rgba(63,169,245,0.5)" if cb_on else "rgba(255,255,255,0.12)"

            # ✅ FIX: move HTML outside f-string expressions
            req_html = '<span style="color:#f55;margin-left:3px;">*</span>' if required else ''
            ro_html = '<span style="color:#ffb347;font-size:10px;margin-left:6px;">&nbsp;🔒</span>' if read_only else ''

            text_color = "#e0e6f0" if cb_on else "#aac0d5"

            return (
                f'<div class="field cb-field" style="grid-column:1/-1;'
                f'background:{bg};border:1px solid {border_col};border-radius:10px;'
                f'padding:10px 14px;display:flex;align-items:center;gap:10px;">'
                f'<input type="checkbox" {checked} {disabled} style="width:18px;height:18px;accent-color:#3fa9f5;">'
                f'<span style="color:{text_color};font-size:13px;">'
                f'{label}{req_html}{ro_html}'
                f'</span></div>'
            )
        html = f'<div class="field{ro_class}"><label>{label}{req_badge}{ro_badge}</label>'

        if ftype == "textarea":
            html += f'<textarea rows="3" {ro_attr}>{default}</textarea>'
        elif ftype == "dropdown":
            disabled = "disabled" if read_only else ""
            html += f'<select {disabled}>'
            html += '<option value="">-- Select --</option>'
            for o in opts:
                html += f'<option>{o}</option>'
            html += "</select>"
        elif ftype == "boolean":
            checked = "checked" if default.lower() in ("true", "1", "yes") else ""
            disabled = "disabled" if read_only else ""
            html += f'<label class="toggle"><input type="checkbox" {checked} {disabled}><span class="slider"></span></label>'
        elif ftype == "date":
            html_date = _to_html_date(default)
            html += f'<input type="date" value="{html_date}" {ro_attr}>'
        elif ftype == "number":
            html += f'<input type="number" value="{default}" placeholder="0" {ro_attr}>{unit_txt}'
        elif ftype == "table":
            html += '<div class="tbl-wrap"><table><thead><tr>'
            for c in cols:
                html += f'<th>{c.get("label", c.get("key", ""))}</th>'
            html += "</tr></thead><tbody>"
            for row in default_rows:
                html += "<tr>"
                for c in cols:
                    cell_val = row.get(c.get("key", ""), "")
                    html += f'<td><input type="text" value="{cell_val}" {ro_attr}></td>'
                html += "</tr>"
            if not default_rows:
                html += '<tr>' + ''.join(f'<td><input type="text"></td>' for _ in cols) + '</tr>'
            html += "</tbody></table></div>"
        elif ftype == "file":
            accept_types = f.get("accept", ["image/jpeg", "application/pdf"])
            accept_str = ",".join(accept_types)
            max_kb = f.get("max_size_kb", 10240)
            accepted_label = ", ".join(
                t.replace("image/", "").replace("application/", "").upper()
                for t in accept_types
            )
            html += (
                f'<div style="border:1px dashed rgba(63,169,245,0.4);border-radius:8px;'
                f'padding:10px;text-align:center;color:#3fa9f5aa;font-size:12px;">'
                f'<div style="font-size:20px;margin-bottom:4px;">📎</div>'
                f'<div>{accepted_label} &nbsp;·&nbsp; max {max_kb // 1024} MB</div>'
                f'<input type="file" accept="{accept_str}" style="display:none">'
                f'</div>'
            )
        else:
            html += f'<input type="text" value="{default}" placeholder="{label}" {"readonly" if read_only else ""}>{unit_txt}'

        html += "</div>"
        return html

    sections_html = ""
    for sec in sections:
        title = sec.get("title", "Section")
        fields_html = "".join(field_html(f) for f in sec.get("fields", []))
        sections_html += f"""
        <div class="section">
          <div class="sec-title">{title}</div>
          <div class="fields">{fields_html}</div>
        </div>"""

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} — Preview</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: #EFF4FF;
      color: #0F172A;
      min-height: 100vh;
      padding: 32px 16px;
    }}
    .container {{ max-width: 820px; margin: 0 auto; }}
    .page-header {{
      background: #0F2B6B;
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 24px;
      display: flex; align-items: center; gap: 14px;
    }}
    .page-header-icon {{
      width: 42px; height: 42px; background: rgba(255,255,255,0.15);
      border-radius: 10px; display: flex; align-items: center; justify-content: center;
      font-size: 20px; flex-shrink: 0;
    }}
    h1 {{
      font-size: 20px; font-weight: 700; color: #FFFFFF;
      margin-bottom: 2px;
    }}
    .subtitle {{
      font-size: 11px; color: rgba(255,255,255,0.6);
      text-transform: uppercase; letter-spacing: 1px;
    }}
    .section {{
      background: #FFFFFF;
      border: 1px solid #CBD5E1;
      border-radius: 12px;
      margin-bottom: 16px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(15,43,107,0.06);
    }}
    .sec-title {{
      padding: 11px 18px;
      font-size: 12px; font-weight: 700;
      background: #0F2B6B;
      border-bottom: 1px solid #CBD5E1;
      color: #FFFFFF;
      text-transform: uppercase; letter-spacing: 0.8px;
      display: flex; align-items: center; gap: 8px;
    }}
    .sec-title::before {{
      content: ''; display: inline-block;
      width: 3px; height: 14px;
      background: #1A56DB; border-radius: 2px;
    }}
    .fields {{ padding: 16px 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .field {{ display: flex; flex-direction: column; gap: 5px; }}
    .field.ro-field {{
      background: #FFF7ED;
      border: 1px solid #FED7AA;
      border-radius: 8px;
      padding: 8px 10px;
    }}
    label {{
      font-size: 11.5px; color: #64748B;
      display: flex; align-items: center; gap: 6px;
      font-weight: 500;
    }}
    .req {{ color: #DC2626; font-size: 14px; }}
    .ro {{ color: #D97706; font-size: 10px; background: #FEF3C7;
           padding: 1px 6px; border-radius: 4px; font-weight: 600; }}
    .unit {{ color: #94A3B8; font-size: 11px; }}
    input[type=text], input[type=number], input[type=date], select, textarea {{
      background: #F8FAFC;
      border: 1px solid #CBD5E1;
      border-radius: 8px;
      color: #0F172A;
      padding: 8px 10px;
      font-size: 13px;
      width: 100%;
      outline: none;
      transition: border-color 0.15s;
    }}
    input:focus, select:focus, textarea:focus {{
      border-color: #1A56DB;
      box-shadow: 0 0 0 3px rgba(26,86,219,0.12);
    }}
    input[readonly], textarea[readonly] {{
      color: #D97706;
      background: #FFFBEB;
      border-color: #FDE68A;
      cursor: default;
    }}
    select option {{ background: #FFFFFF; color: #0F172A; }}
    .toggle {{ display: inline-flex; align-items: center; cursor: pointer; }}
    .toggle input {{ display: none; }}
    .slider {{
      width: 42px; height: 22px; background: #CBD5E1; border-radius: 11px;
      position: relative; transition: background 0.2s;
    }}
    .slider::after {{
      content: ''; position: absolute; top: 3px; left: 3px;
      width: 16px; height: 16px; border-radius: 50%;
      background: #fff; transition: left 0.2s;
      box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }}
    .toggle input:checked + .slider {{ background: #1A56DB; }}
    .toggle input:checked + .slider::after {{ left: 23px; }}
    .tbl-wrap {{ overflow-x: auto; grid-column: 1 / -1; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{
      padding: 8px 10px;
      border: 1px solid #E2E8F0;
      text-align: left;
    }}
    th {{ background: #EFF4FF; color: #0F2B6B; font-weight: 700; font-size: 11px;
          text-transform: uppercase; letter-spacing: 0.5px; }}
    td input {{ background: transparent; border: none; color: #0F172A; width: 100%; outline: none; }}
    .preview-badge {{
      text-align: center; margin-top: 32px;
      color: #94A3B8; font-size: 11px; letter-spacing: 1px;
      padding: 8px;
      border: 1px dashed #CBD5E1;
      border-radius: 8px;
      background: #fff;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="page-header">
      <div class="page-header-icon">📋</div>
      <div>
        <h1>{name}</h1>
        <div class="subtitle">Template Preview &nbsp;·&nbsp; Read-only</div>
      </div>
    </div>
    {sections_html}
    <div class="preview-badge">PREVIEW ONLY — NOT A LIVE FORM</div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_page)


# ─── PDF ─────────────────────────────────────────────────────────────────────

@browser_router.get("/{template_id}/pdf")
def pdf_template(
    template_id: UUID,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """Generate and stream a PDF rendering of the template."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    )

    _auth_from_query_token(token, db)
    svc = OrgTestTemplateService(db)
    tmpl = svc.get_by_id(template_id)
    data = tmpl.template_data or {}
    name = data.get("name", tmpl.template_key or "Template")
    import copy
    sections = copy.deepcopy(data.get("sections", []))

    # Append Overall Assessment sections
    try:
        overall = svc.get_overall_assessment(org_id=tmpl.org_id)
        overall_sections = (overall.template_data or {}).get("sections", [])
        sections.extend(copy.deepcopy(overall_sections))
    except Exception:
        pass

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    # ── Nexus palette ────────────────────────────────────────────────────────
    NAVY        = colors.HexColor("#0F2B6B")   # headings / section bg
    BLUE        = colors.HexColor("#1A56DB")   # accent line / title
    PANEL_BG    = colors.HexColor("#EFF4FF")   # alternate row tint
    ICON_BG     = colors.HexColor("#DBEAFE")   # label cell bg
    BORDER_CLR  = colors.HexColor("#CBD5E1")   # grid lines
    TEXT_PRI    = colors.HexColor("#1E293B")   # body text
    TEXT_SEC    = colors.HexColor("#64748B")   # label text
    WHITE       = colors.white
    ORANGE      = colors.HexColor("#D97706")   # read-only hint
    SEC_FG      = WHITE                         # section header foreground

    title_style = ParagraphStyle("title", fontSize=18, textColor=NAVY,
                                  fontName="Helvetica-Bold", spaceAfter=2)
    sub_style   = ParagraphStyle("sub",   fontSize=8,  textColor=TEXT_SEC,
                                  fontName="Helvetica", spaceAfter=14, leading=12)
    sec_style   = ParagraphStyle("sec",   fontSize=9,  textColor=SEC_FG,
                                  fontName="Helvetica-Bold", spaceBefore=0, spaceAfter=0,
                                  leftIndent=6)
    label_style = ParagraphStyle("lbl",   fontSize=8,  textColor=TEXT_SEC,
                                  fontName="Helvetica", leftIndent=4)
    value_style = ParagraphStyle("val",   fontSize=10, textColor=TEXT_PRI,
                                  fontName="Helvetica", leftIndent=4)
    ro_style    = ParagraphStyle("ro",    fontSize=10, textColor=ORANGE,
                                  fontName="Helvetica-Oblique", leftIndent=4)

    story = [
        Paragraph(name, title_style),
        Paragraph("Test Template  ·  Read-only Preview", sub_style),
        HRFlowable(width="100%", color=BLUE, thickness=1.2, spaceAfter=12),
    ]

    for sec in sections:
        # ── Section header row (navy band) ───────────────────────────────────
        sec_title = Paragraph(sec.get("title", "Section").upper(), sec_style)
        hdr_table = Table([[sec_title]], colWidths=[doc.width])
        hdr_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]))
        story.append(hdr_table)

        fields = sec.get("fields", [])
        cells = []
        for f in fields:
            label = f.get("label", f.get("key", ""))
            ftype = f.get("type", "text")
            default = str(f.get("default", "") or "")
            unit = f.get("unit", "") or ""
            read_only = f.get("read_only", False)
            required = f.get("required", False)
            opts = f.get("options", [])

            req_mark = " *" if required else ""
            lbl_para = Paragraph(f"{label}{req_mark}", label_style)

            if ftype in ("boolean", "checkbox"):
                val_text = "☑  Yes / Done" if default.lower() in ("true", "1", "yes") else "☐  No / Pending"
            elif ftype == "dropdown":
                val_text = f"[{' / '.join(opts[:4])}{'...' if len(opts) > 4 else ''}]" if opts else "[Dropdown]"
            elif ftype == "table":
                cols = f.get("columns", [])
                val_text = "Table: " + ", ".join(c.get("label", c.get("key", "")) for c in cols)
            elif ftype == "file":
                accept_types = f.get("accept", ["image/jpeg", "application/pdf"])
                accepted_label = " / ".join(
                    t.replace("image/", "").replace("application/", "").upper()
                    for t in accept_types
                )
                max_kb = f.get("max_size_kb", 10240)
                val_text = f"[File Upload — {accepted_label}, max {max_kb // 1024} MB]"
            else:
                disp = f"{default} {unit}".strip() if default else f"___"
                val_text = disp

            val_para = Paragraph(val_text, ro_style if read_only else value_style)
            cells.append([lbl_para, val_para])

        # Pair into 2 columns
        rows = []
        for i in range(0, len(cells), 2):
            left  = cells[i]
            right = cells[i + 1] if i + 1 < len(cells) else [Paragraph("", label_style), Spacer(1, 1)]
            rows.append([left[0], left[1], right[0], right[1]])

        if rows:
            col_w = doc.width / 4
            tbl = Table(rows, colWidths=[col_w * 0.7, col_w * 1.3, col_w * 0.7, col_w * 1.3])
            ts = TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("GRID",          (0, 0), (-1, -1), 0.4, BORDER_CLR),
                # alternate row shading
                *[("BACKGROUND", (0, r), (-1, r), PANEL_BG if r % 2 == 0 else WHITE)
                  for r in range(len(rows))],
            ])
            tbl.setStyle(ts)
            story.append(tbl)
        story.append(Spacer(1, 10))

    doc.build(story)
    buf.seek(0)
    safe_name = name.replace(" ", "_").replace("/", "-")
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
    )
