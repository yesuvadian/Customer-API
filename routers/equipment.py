"""
Equipment Asset Register Router
CRUD for equipment units with UEIC auto-generation, linked to OrgDepartment hierarchy.
Enforces org-scoping and module-level RBAC via OrgRolePermission.

ROUTE ORDER RULE (FastAPI matches top-to-bottom):
  All fixed-path routes (no UUID segment) MUST come before /{equipment_id} routes.
  Otherwise FastAPI tries to parse e.g. "manufacturers" as a UUID → 422 error.

  Safe order used here:
    1.  POST   /                          create_equipment
    2.  GET    /                          list_equipment          ← updated with all filters
    3.  GET    /export/csv                export_equipment_csv
    4.  GET    /stats/counts              get_equipment_counts
    5.  GET    /types-by-category/{int}   get_types_by_category_for_type
    6.  GET    /types-by-test-type/{int}  get_types_by_test_type
    7.  GET    /by-ueic/{ueic}            get_equipment_by_ueic
    8.  GET    /manufacturers             get_manufacturers       ← NEW
    9.  GET    /models                    get_models              ← NEW
    10. GET    /substations               get_substations         ← NEW
    11. GET    /divisions                 get_divisions           ← NEW
    12. GET    /circles                   get_circles             ← NEW
    13. GET    /zones                     get_zones               ← NEW
    ── all /{equipment_id} routes below ──
    14. GET    /{equipment_id}
    15. PUT    /{equipment_id}
    16. POST   /{equipment_id}/retire
    17. POST   /{equipment_id}/replace
    18. GET    /{equipment_id}/replacement-report
    19. GET    /{equipment_id}/applicable-tests
    20. GET    /{equipment_id}/history
    21. GET    /{equipment_id}/location-hierarchy
    22. POST   /{equipment_id}/nameplate-files/{field_key}
    23. GET    /{equipment_id}/nameplate-files/{field_key}
"""

import os
import uuid as _uuid
from io import BytesIO
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from auth_utils import get_current_user
from models import Equipment, Module, User
from middleware.org_auth import check_org_permission
from schemas import (
    EquipmentCreate,
    EquipmentUpdate,
    EquipmentResponse,
    EquipmentChainRef,
    EquipmentRetireRequest,
    EquipmentReplaceRequest,
    EquipmentCountResponse,
)
from services.equipment_service import EquipmentService

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "analysis_reports")
os.makedirs(UPLOADS_DIR, exist_ok=True)

NAMEPLATE_FILES_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "nameplate_files")
os.makedirs(NAMEPLATE_FILES_DIR, exist_ok=True)

router = APIRouter(
    prefix="/equipment",
    tags=["equipment"],
    dependencies=[Depends(get_current_user)],
)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL HELPERS  (not routes)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_equipment_module_id(db: Session) -> int:
    """Resolve the Equipment module row; raises 500 if not seeded."""
    mod = db.query(Module).filter_by(path="equipment", is_active=True).first()
    if not mod:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Equipment module not configured. Run seed first.",
        )
    return mod.id


def _require_permission(db: Session, user: User, action: str) -> None:
    """
    Check that *user* has *action* on the Equipment module.
    Org admins bypass all module checks.
    """
    from models import OrgUserRole, OrgRole

    is_org_admin = (
        db.query(OrgUserRole)
        .join(OrgRole)
        .filter(
            OrgUserRole.user_id == user.id,
            OrgRole.is_org_admin == True,
            OrgUserRole.is_active == True,
            OrgRole.is_active == True,
        )
        .first()
    )
    if is_org_admin:
        return

    module_id = _get_equipment_module_id(db)
    if not check_org_permission(user.id, module_id, action, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission '{action}' required on Equipment module",
        )


def _enforce_org_scope(user: User) -> UUID:
    """Return the user's organization_id or raise 403."""
    if not user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization to access equipment",
        )
    return user.organization_id


def _chain_ref(eq_obj) -> dict | None:
    """Lightweight replacement-chain reference dict from an Equipment ORM object."""
    if eq_obj is None:
        return None
    return {
        "id": eq_obj.id,
        "ueic": eq_obj.ueic,
        "status": eq_obj.status.value if eq_obj.status else None,
        "manufacturer": eq_obj.manufacturer,
        "model_number": eq_obj.model_number,
        "commissioned_date": eq_obj.commissioned_date,
        "retired_date": eq_obj.retired_date,
    }


def _to_response(db: Session, eq: Equipment) -> dict:
    """Convert Equipment ORM object to response dict with computed fields."""
    return {
        "id": eq.id,
        "ueic": eq.ueic,
        "organization_id": eq.organization_id,
        "department_id": eq.department_id,
        "equipment_type_id": eq.equipment_type_id,
        "equipment_type_name": eq.equipment_type.name if eq.equipment_type else None,
        "department_name": eq.department.name if eq.department else None,
        "voltage_class": eq.voltage_class,
        "bay_number": eq.bay_number,
        "serial_in_bay": eq.serial_in_bay,
        "nameplate_data": eq.nameplate_data,
        "status": eq.status.value if eq.status else None,
        "replaces_equipment_id": eq.replaces_equipment_id,
        "replaces_equipment": _chain_ref(eq.replaces_equipment),
        "replaced_by_id": eq.replaced_by_id,
        "replaced_by": _chain_ref(
            eq.replaced_by_equipment[0] if eq.replaced_by_equipment else None
        ),
        "replacement_reason_type": eq.replacement_reason_type,
        "commissioned_date": eq.commissioned_date,
        "retired_date": eq.retired_date,
        "retirement_reason": eq.retirement_reason,
        "manufacturer": eq.manufacturer,
        "model_number": eq.model_number,
        "factory_serial_number": eq.factory_serial_number,
        "year_of_manufacture": eq.year_of_manufacture,
        "latitude": eq.latitude,    
        "longitude": eq.longitude,
        "created_by": eq.created_by,
        "modified_by": eq.modified_by,
        "cts": eq.cts,
        "mts": eq.mts,
        "types_by_category": _types_by_category_for_equipment(db, eq),
    }


def _types_by_category_for_equipment(db, eq) -> dict:
    """Return types_by_category for this equipment's type with lifecycle flags."""
    from models import CategoryDetails, OrgTestTemplate

    if not eq.equipment_type_id:
        return {"test": [], "maintenance": [], "inspection": [], "repair_lifecycle": []}

    all_types = (
        db.query(CategoryDetails)
        .filter(
            CategoryDetails.category_master_id == eq.equipment_type_id,
            CategoryDetails.is_active.is_(True),
        )
        .order_by(CategoryDetails.name)
        .all()
    )
    buckets: dict = {"test": [], "maintenance": [], "inspection": [], "repair_lifecycle": []}
    for t in all_types:
        cat = t.category_type or "test"
        bucket = buckets.get(cat, buckets["test"])
        tpl = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.test_type_id == t.id)
            .order_by(OrgTestTemplate.version.desc())
            .first()
        )
        tpl_data = (tpl.template_data or {}) if tpl else {}
        bucket.append(
            {
                "id": t.id,
                "name": t.name,
                "category_type": t.category_type,
                "enable_cumulative": bool(tpl_data.get("enable_cumulative", False)),
                "enable_calibration": bool(tpl_data.get("enable_calibration", False)),
            }
        )
    return buckets


def _get_departments_at_depth(db: Session, org_id, depth: int) -> list:
    """
    Return all departments at a specific tree depth for the given org.
    depth=0 → root (zones), depth=1 → circles, depth=2 → divisions, etc.
    Returns a list of plain dicts: [{"id": ..., "name": ...}, ...]
    """
    from sqlalchemy import text

    sql = text(
        """
        WITH RECURSIVE dept_tree AS (
            SELECT id, name, parent_department_id, 0 AS depth
            FROM org_departments
            WHERE organization_id = :org_id
              AND is_active = true
              AND parent_department_id IS NULL

            UNION ALL

            SELECT d.id, d.name, d.parent_department_id, dt.depth + 1
            FROM org_departments d
            INNER JOIN dept_tree dt ON d.parent_department_id = dt.id
            WHERE d.is_active = true
              AND dt.depth < :max_depth
        )
        SELECT id, name FROM dept_tree WHERE depth = :depth ORDER BY name
        """
    )
    rows = db.execute(
        sql, {"org_id": str(org_id), "depth": depth, "max_depth": depth}
    ).fetchall()
    return [{"id": str(r[0]), "name": r[1]} for r in rows]


def _resolve_nameplate_file_field(db: Session, equipment: Equipment, field_key: str) -> dict:
    """
    Look up the template for this equipment type and return the field definition
    for field_key. Raises 404 if the field doesn't exist or isn't type='file'.
    """
    from models import CategoryDetails, OrgTestTemplate

    detail = (
        db.query(CategoryDetails)
        .filter(
            CategoryDetails.category_master_id == equipment.equipment_type_id,
            CategoryDetails.category_type == "nameplate",
        )
        .first()
    )
    if not detail:
        raise HTTPException(
            status_code=404,
            detail="No nameplate template found for this equipment type.",
        )

    tmpl = (
        db.query(OrgTestTemplate)
        .filter(
            OrgTestTemplate.test_type_id == detail.id,
            OrgTestTemplate.org_id == equipment.organization_id,
        )
        .first()
    ) or (
        db.query(OrgTestTemplate)
        .filter(
            OrgTestTemplate.test_type_id == detail.id,
            OrgTestTemplate.org_id == None,  # noqa: E711
        )
        .first()
    )
    if not tmpl:
        raise HTTPException(status_code=404, detail="Nameplate template not provisioned.")

    for section in (tmpl.template_data or {}).get("sections", []):
        for field in section.get("fields", []):
            if field.get("key") == field_key:
                if field.get("type") != "file":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Field '{field_key}' is not a file-upload field in the template.",
                    )
                return field

    raise HTTPException(
        status_code=404,
        detail=f"Field '{field_key}' not found in nameplate template.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ① STATIC ROUTES — no UUID path segment  (MUST be above /{equipment_id})
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. CREATE ────────────────────────────────────────────────────────────────
@router.post("/", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
def create_equipment(
    data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new equipment unit. UEIC is auto-generated."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_add")

    if data.organization_id and data.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create equipment in another organization",
        )

    equipment = EquipmentService.create_equipment(
        db=db,
        organization_id=org_id,
        department_id=data.department_id,
        equipment_type_id=data.equipment_type_id,
        voltage_class=data.voltage_class,
        bay_number=data.bay_number,
        nameplate_data=data.nameplate_data,
        commissioned_date=data.commissioned_date,
        manufacturer=data.manufacturer,
        model_number=data.model_number,
        factory_serial_number=data.factory_serial_number,
        year_of_manufacture=data.year_of_manufacture,
        latitude=data.latitude,    
        longitude=data.longitude,  
        created_by=current_user.id,
    )
    db.commit()
    db.refresh(equipment)

    try:
        from services.test_request_schedule_service import TestRequestScheduleService
        TestRequestScheduleService.instantiate_equipment_schedules(db, equipment, current_user.id)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[WARN] instantiate_equipment_schedules failed: {exc}")

    try:
        from services.notification_service import NotificationService
        commissioned_by = (
            f"{current_user.firstname or ''} {current_user.lastname or ''}".strip()
            or current_user.email
        )
        NotificationService(db).notify_equipment_registered(
            equipment,
            commissioned_by=commissioned_by,
            organization_id=org_id,
            department_id=equipment.department_id,
        )
    except Exception as _n:
        print(f"[WARN] equipment_registered notification failed: {_n}")

    return _to_response(db, equipment)


# ── 2. LIST (with ALL filters) ────────────────────────────────────────────────
# ── 2. LIST (with ALL filters) ────────────────────────────────────────────────
@router.get("/", response_model=List[EquipmentResponse])
def list_equipment(
    # Basic filters
    department_id: Optional[UUID] = None,
    equipment_type_id: Optional[int] = None,
    status: Optional[str] = None,
    voltage_class: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model_number: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    # Area filters
    tlss_division: Optional[str] = None,
    wm_circle: Optional[str] = None,
    transmission_zone: Optional[str] = None,
    substation_ids: Optional[str] = None,
    # Year filters
    commission_year: Optional[int] = None,
    commission_year_from: Optional[int] = None,
    commission_year_to: Optional[int] = None,
    failure_year: Optional[int] = None,
    failure_year_from: Optional[int] = None,
    failure_year_to: Optional[int] = None,
    replacement_year: Optional[int] = None,
    replacement_year_from: Optional[int] = None,
    replacement_year_to: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List equipment with optional filters. Scoped to user's organization."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    # ← Only pass what EquipmentService.list_equipment currently supports.
    # The new filter params (model_number, tlss_division, etc.) are accepted
    # by the route but ignored until equipment_service.py is also updated.
    items = EquipmentService.list_equipment(
        db=db,
        organization_id=org_id,
        department_id=department_id,
        equipment_type_id=equipment_type_id,
        status=status,
        voltage_class=voltage_class,
        manufacturer=manufacturer,
        model_number=model_number,
        substation_ids=substation_ids,
        tlss_division=tlss_division,
        wm_circle=wm_circle,
        transmission_zone=transmission_zone,
        search=search,
        skip=skip,
        limit=limit,
        commission_year=commission_year,
        commission_year_from=commission_year_from,
        commission_year_to=commission_year_to,
        failure_year=failure_year,
        failure_year_from=failure_year_from,
        failure_year_to=failure_year_to,
        replacement_year=replacement_year,
        replacement_year_from=replacement_year_from,
        replacement_year_to=replacement_year_to,
    )
    return [_to_response(db, eq) for eq in items]


# ── 3. EXPORT CSV ─────────────────────────────────────────────────────────────
@router.get("/export/csv")
def export_equipment_csv(
    department_id: Optional[UUID] = None,
    equipment_type_id: Optional[int] = None,
    status: Optional[str] = None,
    voltage_class: Optional[str] = None,
    manufacturer: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export equipment list as UTF-8 CSV."""
    import csv
    import io
    from datetime import datetime

    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_export")

    items = EquipmentService.list_equipment(
        db=db,
        organization_id=org_id,
        department_id=department_id,
        equipment_type_id=equipment_type_id,
        status=status,
        voltage_class=voltage_class,
        manufacturer=manufacturer,
        search=search,
        skip=0,
        limit=10_000,
    )

    columns = [
        ("UEIC",                    lambda eq: eq.ueic or ""),
        ("Equipment Type",          lambda eq: eq.equipment_type.name if eq.equipment_type else ""),
        ("Department",              lambda eq: eq.department.name if eq.department else ""),
        ("Status",                  lambda eq: eq.status.value if eq.status else ""),
        ("Voltage Class (kV)",      lambda eq: eq.voltage_class or ""),
        ("Bay Number",              lambda eq: eq.bay_number or ""),
        ("Manufacturer",            lambda eq: eq.manufacturer or ""),
        ("Model Number",            lambda eq: eq.model_number or ""),
        ("Factory Serial Number",   lambda eq: eq.factory_serial_number or ""),
        ("Year of Manufacture",     lambda eq: str(eq.year_of_manufacture) if eq.year_of_manufacture else ""),
        ("Commissioned Date",       lambda eq: str(eq.commissioned_date).split("T")[0] if eq.commissioned_date else ""),
        ("Retired Date",            lambda eq: str(eq.retired_date).split("T")[0] if eq.retired_date else ""),
        ("Retirement Reason",       lambda eq: eq.retirement_reason or ""),
        ("Created",                 lambda eq: str(eq.cts).split("T")[0] if eq.cts else ""),
        ("Last Modified",           lambda eq: str(eq.mts).split("T")[0] if eq.mts else ""),
    ]

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([col[0] for col in columns])
    for eq in items:
        writer.writerow([col[1](eq) for col in columns])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM so Excel opens correctly
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"equipment_export_{timestamp}.csv"

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 4. STATS / COUNTS ─────────────────────────────────────────────────────────
@router.get("/stats/counts", response_model=EquipmentCountResponse)
def get_equipment_counts(
    department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Equipment counts by status — scoped to user's organization."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")
    return EquipmentService.get_equipment_count(db, org_id, department_id)


# ── 5. TYPES BY CATEGORY (by equipment_type_id int) ──────────────────────────
@router.get("/types-by-category/{equipment_type_id}")
def get_types_by_category_for_type(
    equipment_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return types_by_category for a CategoryMaster (equipment type) ID."""

    class _FakeEq:
        pass

    fake = _FakeEq()
    fake.equipment_type_id = equipment_type_id
    return _types_by_category_for_equipment(db, fake)


# ── 6. TYPES BY TEST-TYPE (by test_type_id int) ───────────────────────────────
@router.get("/types-by-test-type/{test_type_id}")
def get_types_by_test_type(
    test_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return types_by_category for the equipment category that owns test_type_id."""
    from models import CategoryDetails

    detail = db.query(CategoryDetails).filter(CategoryDetails.id == test_type_id).first()
    if not detail or not detail.category_master_id:
        return {"test": [], "maintenance": [], "inspection": [], "repair_lifecycle": []}

    class _FakeEq:
        pass

    fake = _FakeEq()
    fake.equipment_type_id = detail.category_master_id
    return _types_by_category_for_equipment(db, fake)


# ── 7. GET BY UEIC ────────────────────────────────────────────────────────────
@router.get("/by-ueic/{ueic}", response_model=EquipmentResponse)
def get_equipment_by_ueic(
    ueic: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment_by_ueic(db, ueic)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    if equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    return _to_response(db, equipment)


# ── 8. MANUFACTURERS (filter-data) ────────────────────────────────────────────
@router.get("/manufacturers")
def get_manufacturers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return distinct manufacturer names present in the org's equipment."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    from sqlalchemy import distinct

    rows = (
        db.query(distinct(Equipment.manufacturer))
        .filter(
            Equipment.organization_id == org_id,
            Equipment.manufacturer.isnot(None),
            Equipment.manufacturer != "",
        )
        .order_by(Equipment.manufacturer)
        .all()
    )
    return [{"id": r[0], "name": r[0]} for r in rows]


# ── 9. MODELS (filter-data) ───────────────────────────────────────────────────
@router.get("/models")
def get_models(
    manufacturer: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return distinct model numbers, optionally filtered by manufacturer."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    from sqlalchemy import distinct

    query = db.query(distinct(Equipment.model_number)).filter(
        Equipment.organization_id == org_id,
        Equipment.model_number.isnot(None),
        Equipment.model_number != "",
    )
    if manufacturer:
        query = query.filter(Equipment.manufacturer.ilike(f"%{manufacturer}%"))
    rows = query.order_by(Equipment.model_number).all()
    return [{"model_number": r[0]} for r in rows]


# ── 10. SUBSTATIONS (filter-data) ─────────────────────────────────────────────
@router.get("/substations")
def get_substations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return leaf departments (substations) for the org."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    from sqlalchemy import text

    sql = text(
        """
        WITH RECURSIVE dept_tree AS (
            SELECT id, name, code, parent_department_id, 0 AS depth
            FROM org_departments
            WHERE organization_id = :org_id
              AND is_active = true
              AND parent_department_id IS NULL

            UNION ALL

            SELECT d.id, d.name, d.code, d.parent_department_id, dt.depth + 1
            FROM org_departments d
            INNER JOIN dept_tree dt ON d.parent_department_id = dt.id
            WHERE d.is_active = true
        ),
        leaf_depts AS (
            SELECT dt.id, dt.name, dt.code
            FROM dept_tree dt
            WHERE NOT EXISTS (
                SELECT 1 FROM org_departments child
                WHERE child.parent_department_id = dt.id
                  AND child.is_active = true
            )
        )
        SELECT id, name, code FROM leaf_depts ORDER BY name
        """
    )
    rows = db.execute(sql, {"org_id": str(org_id)}).fetchall()
    return [{"id": str(r[0]), "name": r[1], "code": r[2]} for r in rows]


# ── 11. DIVISIONS (filter-data) ───────────────────────────────────────────────
@router.get("/divisions")
def get_divisions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return depth-2 departments (TLSS Divisions)."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")
    return _get_departments_at_depth(db, org_id, depth=2)


# ── 12. CIRCLES (filter-data) ─────────────────────────────────────────────────
@router.get("/circles")
def get_circles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return depth-1 departments (W&M Circles)."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")
    return _get_departments_at_depth(db, org_id, depth=1)


# ── 13. ZONES (filter-data) ───────────────────────────────────────────────────
@router.get("/zones")
def get_zones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return depth-0 departments (Transmission Zones / root)."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")
    return _get_departments_at_depth(db, org_id, depth=0)


# ═══════════════════════════════════════════════════════════════════════════════
# ② DYNAMIC ROUTES — all contain /{equipment_id: UUID}  (always LAST)
# ═══════════════════════════════════════════════════════════════════════════════

# ── 14. GET SINGLE ────────────────────────────────────────────────────────────
@router.get("/{equipment_id}", response_model=EquipmentResponse)
def get_equipment(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    if equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    return _to_response(db, equipment)


# ── 15. UPDATE ────────────────────────────────────────────────────────────────
@router.put("/{equipment_id}", response_model=EquipmentResponse)
def update_equipment(
    equipment_id: UUID,
    data: EquipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_edit")

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    equipment = EquipmentService.update_equipment(
        db=db,
        equipment_id=equipment_id,
        modified_by=current_user.id,
        **data.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(equipment)
    return _to_response(db, equipment)


# ── 16. RETIRE ────────────────────────────────────────────────────────────────
@router.post("/{equipment_id}/retire", response_model=EquipmentResponse)
def retire_equipment(
    equipment_id: UUID,
    data: EquipmentRetireRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retire equipment (soft-delete). UEIC and historical data remain."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_edit")

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    equipment = EquipmentService.retire_equipment(
        db=db,
        equipment_id=equipment_id,
        reason=data.reason,
        modified_by=current_user.id,
    )
    db.commit()
    db.refresh(equipment)

    try:
        from services.notification_service import NotificationService
        retired_by = (
            f"{current_user.firstname or ''} {current_user.lastname or ''}".strip()
            or current_user.email
        )
        NotificationService(db).notify_equipment_retired(
            equipment,
            retired_by=retired_by,
            reason=data.reason or "",
            organization_id=org_id,
            department_id=equipment.department_id,
        )
    except Exception as _n:
        print(f"[WARN] equipment_retired notification failed: {_n}")

    return _to_response(db, equipment)


# ── 17. REPLACE ───────────────────────────────────────────────────────────────
@router.post("/{equipment_id}/replace", status_code=status.HTTP_201_CREATED)
async def replace_equipment(
    equipment_id: UUID,
    reason: str = Form(..., description="Reason for replacement"),
    reason_type: str = Form(
        "other",
        description="'recommendation_compliance' or 'other'",
    ),
    recommendation_id: Optional[str] = Form(None),
    nameplate_data: Optional[str] = Form(None, description="JSON-encoded nameplate fields"),
    manufacturer: Optional[str] = Form(None),
    model_number: Optional[str] = Form(None),
    factory_serial_number: Optional[str] = Form(None),
    year_of_manufacture: Optional[int] = Form(None),
    commissioned_date: Optional[str] = Form(None, description="ISO date string"),
    analysis_report: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retire old equipment and register a replacement.
    reason_type='other' → analysis_report PDF is mandatory.
    reason_type='recommendation_compliance' → recommendation_id is mandatory.
    """
    import json
    from datetime import datetime as _dt

    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_add")

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    if reason_type == "other" and analysis_report is None:
        raise HTTPException(
            status_code=400,
            detail="An analysis report PDF is required when replacement reason is not linked to a recommendation.",
        )
    if reason_type == "recommendation_compliance" and not recommendation_id:
        raise HTTPException(
            status_code=400,
            detail="recommendation_id is required when reason_type is 'recommendation_compliance'.",
        )

    report_path: Optional[str] = None
    if analysis_report is not None:
        file_ext = os.path.splitext(analysis_report.filename or "report.pdf")[1] or ".pdf"
        safe_name = f"{_uuid.uuid4()}{file_ext}"
        dest = os.path.join(UPLOADS_DIR, safe_name)
        content = await analysis_report.read()
        with open(dest, "wb") as f:
            f.write(content)
        report_path = f"uploads/analysis_reports/{safe_name}"

    parsed_nameplate: Optional[dict] = None
    if nameplate_data:
        try:
            parsed_nameplate = json.loads(nameplate_data)
        except Exception:
            raise HTTPException(status_code=400, detail="nameplate_data must be valid JSON.")

    parsed_date = None
    if commissioned_date:
        try:
            parsed_date = _dt.fromisoformat(commissioned_date)
        except Exception:
            raise HTTPException(status_code=400, detail="commissioned_date must be a valid ISO date.")

    rec_uuid: Optional[UUID] = None
    if recommendation_id:
        try:
            rec_uuid = UUID(recommendation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="recommendation_id must be a valid UUID.")

    old, new = EquipmentService.replace_equipment(
        db=db,
        old_equipment_id=equipment_id,
        reason=reason,
        created_by=current_user.id,
        reason_type=reason_type,
        recommendation_id=rec_uuid,
        analysis_report_path=report_path,
        nameplate_data=parsed_nameplate,
        commissioned_date=parsed_date,
        manufacturer=manufacturer,
        model_number=model_number,
        factory_serial_number=factory_serial_number,
        year_of_manufacture=year_of_manufacture,
    )
    db.commit()
    db.refresh(old)
    db.refresh(new)

    try:
        from services.notification_service import NotificationService
        eq_type_name = (
            existing.equipment_type.name
            if existing.equipment_type
            else str(existing.equipment_type_id)
        )
        dept_name = existing.department.name if existing.department else "-"
        NotificationService(db).fire(
            event_type="equipment_replacement",
            context={
                "old_ueic":       old.ueic,
                "new_ueic":       new.ueic,
                "equipment_type": eq_type_name,
                "department":     dept_name,
                "reason_type":    reason_type,
                "reason":         reason,
                "replaced_by":    f"{current_user.firstname} {current_user.lastname}",
                "replaced_on":    old.retired_date.strftime("%d/%m/%Y") if old.retired_date else "-",
            },
            organization_id=org_id,
            source_id=new.id,
            source_type="equipment",
            severity="info",
        )
    except Exception:
        pass

    report_url = f"/equipment/{new.id}/replacement-report"
    return {
        "retired_equipment": _to_response(db, old),
        "new_equipment":     _to_response(db, new),
        "report_url":        report_url,
    }


# ── 18. REPLACEMENT REPORT PDF ────────────────────────────────────────────────
@router.get("/{equipment_id}/replacement-report")
def download_replacement_report(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    new_eq = EquipmentService.get_equipment(db, equipment_id)
    if not new_eq or new_eq.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")
    if not new_eq.replaces_equipment_id:
        raise HTTPException(
            status_code=400,
            detail="This equipment is not a replacement unit. No replacement report available.",
        )

    from services.equipment_replacement_pdf_service import EquipmentReplacementPDFService

    try:
        buf: BytesIO = EquipmentReplacementPDFService(db).generate_pdf(
            old_equipment_id=new_eq.replaces_equipment_id,
            new_equipment_id=new_eq.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    filename = f"Replacement_Report_{new_eq.ueic}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 19. APPLICABLE TESTS ──────────────────────────────────────────────────────
@router.get("/{equipment_id}/applicable-tests")
def get_applicable_tests(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test types applicable to this equipment's type."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    existing = EquipmentService.get_equipment(db, equipment_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    tests = EquipmentService.get_applicable_tests(db, equipment_id)

    from models import OrgTestTemplate

    def _template_flags(test_type_id: int) -> dict:
        tpl = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.test_type_id == test_type_id)
            .order_by(OrgTestTemplate.version.desc())
            .first()
        )
        data = (tpl.template_data or {}) if tpl else {}
        return {
            "enable_cumulative": bool(data.get("enable_cumulative", False)),
            "enable_calibration": bool(data.get("enable_calibration", False)),
        }

    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category_type": t.category_type,
            "is_active": t.is_active,
            **_template_flags(t.id),
        }
        for t in tests
    ]


# ── 20. HISTORY ───────────────────────────────────────────────────────────────
@router.get("/{equipment_id}/history")
def get_equipment_history(
    equipment_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Testing and failure history for one equipment unit."""
    from models import TestingRequest
    from sqlalchemy.orm import joinedload

    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment or equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    rows = (
        db.query(TestingRequest)
        .options(
            joinedload(TestingRequest.originator),
            joinedload(TestingRequest.test_results),
        )
        .filter(TestingRequest.equipment_id == equipment_id)
        .order_by(TestingRequest.cts.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    def _fmt(r):
        result = r.test_results[0] if r.test_results else None
        originator = r.originator
        return {
            "id": str(r.id),
            "request_number": r.request_number,
            "title": r.title,
            "request_category": r.request_category.value if r.request_category else None,
            "status": r.status.value if r.status else None,
            "priority": r.priority,
            "is_direct_submission": r.is_direct_submission,
            "overall_result": result.overall_result if result else None,
            "submitted_by": (
                f"{originator.firstname or ''} {originator.lastname or ''}".strip()
                if originator
                else None
            ),
            "cts": r.cts.isoformat() if r.cts else None,
        }

    return {
        "equipment_id": str(equipment_id),
        "ueic": equipment.ueic,
        "total": len(rows),
        "records": [_fmt(r) for r in rows],
    }


# ── 21. LOCATION HIERARCHY ────────────────────────────────────────────────────
@router.get("/{equipment_id}/location-hierarchy")
def get_equipment_location_hierarchy(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full department hierarchy for an equipment's location."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    if equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found")

    ancestry = EquipmentService._get_department_ancestry_names(db, equipment.department_id)
    return {
        "equipment_id": str(equipment.id),
        "ueic": equipment.ueic,
        "department_id": str(equipment.department_id),
        "department_name": equipment.department.name if equipment.department else None,
        "hierarchy": ancestry,
    }


# ── 22. UPLOAD NAMEPLATE FILE ─────────────────────────────────────────────────
@router.post("/{equipment_id}/nameplate-files/{field_key}", status_code=200)
async def upload_nameplate_file(
    equipment_id: UUID,
    field_key: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a file for a 'file'-type field in the nameplate template."""
    from datetime import datetime as _dt

    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_edit")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment or equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found.")

    field_def = _resolve_nameplate_file_field(db, equipment, field_key)

    accepted = set(field_def.get("accept", ["image/jpeg", "application/pdf"]))
    content_type = file.content_type or ""
    if content_type not in accepted:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{content_type}' not allowed. Accepted: {sorted(accepted)}",
        )

    max_bytes = field_def.get("max_size_kb", 10240) * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {field_def.get('max_size_kb', 10240)} KB.",
        )

    eq_dir = os.path.join(NAMEPLATE_FILES_DIR, str(equipment_id))
    os.makedirs(eq_dir, exist_ok=True)

    ext = os.path.splitext(file.filename or "upload")[1] or (
        ".jpg" if "jpeg" in content_type else ".pdf"
    )
    stored_name = f"{field_key}_{_uuid.uuid4()}{ext}"
    dest = os.path.join(eq_dir, stored_name)
    with open(dest, "wb") as fh:
        fh.write(content)

    relative_path = f"uploads/nameplate_files/{equipment_id}/{stored_name}"

    nameplate = dict(equipment.nameplate_data or {})
    nameplate[field_key] = {
        "original_filename": file.filename,
        "path": relative_path,
        "size_bytes": len(content),
        "mime_type": content_type,
        "uploaded_at": _dt.utcnow().isoformat(),
        "uploaded_by": str(current_user.id),
    }

    from sqlalchemy.orm.attributes import flag_modified

    equipment.nameplate_data = nameplate
    flag_modified(equipment, "nameplate_data")
    equipment.modified_by = current_user.id
    db.commit()

    return {
        "field_key": field_key,
        "original_filename": file.filename,
        "path": relative_path,
        "size_bytes": len(content),
        "mime_type": content_type,
    }


# ── 23. DOWNLOAD NAMEPLATE FILE ───────────────────────────────────────────────
@router.get("/{equipment_id}/nameplate-files/{field_key}")
def download_nameplate_file(
    equipment_id: UUID,
    field_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve the uploaded file for a nameplate field."""
    org_id = _enforce_org_scope(current_user)
    _require_permission(db, current_user, "can_view")

    equipment = EquipmentService.get_equipment(db, equipment_id)
    if not equipment or equipment.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Equipment not found.")

    nameplate = equipment.nameplate_data or {}
    file_meta = nameplate.get(field_key)
    if not isinstance(file_meta, dict) or "path" not in file_meta:
        raise HTTPException(
            status_code=404,
            detail=f"No file uploaded for field '{field_key}'.",
        )

    abs_path = os.path.join(os.path.dirname(__file__), "..", file_meta["path"])
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="File not found on server.")

    import mimetypes

    def _stream():
        with open(abs_path, "rb") as fh:
            yield from iter(lambda: fh.read(65536), b"")

    mime = (
        file_meta.get("mime_type")
        or mimetypes.guess_type(abs_path)[0]
        or "application/octet-stream"
    )
    filename = file_meta.get("original_filename", os.path.basename(abs_path))
    return StreamingResponse(
        _stream(),
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )