"""
test_schedule_dashboard.py
──────────────────────────
Read-only endpoints for the Test Schedule Compliance tab.

All routes require authentication (JWT).
Org-scoping is enforced: every query is filtered to the caller's org_id.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.test_schedule_dashboard_service import TestScheduleDashboardService

router = APIRouter(
    prefix="/test-schedule",
    tags=["test-schedule-dashboard"],
    dependencies=[Depends(get_current_user)],
)


# ─────────────────────────────────────────────────────────────────
# Filter options  (populates the dropdown menus)
# ─────────────────────────────────────────────────────────────────

@router.get("/filter-options")
def filter_options(
    org_id: UUID = Query(...),
    db: Session = Depends(get_db),
):
    """
    Returns equipment types, voltage classes, and departments
    available for the given organisation — used to populate the
    Compliance tab filter dropdowns.
    """
    return TestScheduleDashboardService(db).get_filter_options(org_id)


# ─────────────────────────────────────────────────────────────────
# Compliance matrix
# ─────────────────────────────────────────────────────────────────

@router.get("/compliance")
def compliance_matrix(
    org_id: UUID = Query(...),
    equipment_type: str = Query("Power Transformer"),
    voltage_class: Optional[str] = Query(None),
    department_id: Optional[UUID] = Query(None),
    search: Optional[str] = Query(None, description="Filter by UEIC (partial match)"),
    db: Session = Depends(get_db),
):
    """
    Compliance matrix for the Test Schedule dashboard tab.

    Returns:
    - `columns`  — ordered list of test-type dicts {id, name}
    - `kpis`     — 5 headline KPI numbers
    - `rows`     — one row per equipment with `cells` keyed by test_type_id

    Cell status values:
      ok | due_soon (≤30d) | due_imminent (≤15d) | overdue (≤0d) | na (no schedule)
    """
    try:
        return TestScheduleDashboardService(db).get_compliance_matrix(
            org_id=org_id,
            equipment_type_name=equipment_type,
            voltage_class=voltage_class or None,
            department_id=department_id,
            search=search or None,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


# ─────────────────────────────────────────────────────────────────
# Equipment detail
# ─────────────────────────────────────────────────────────────────

@router.get("/compliance/equipment/{equipment_id}")
def equipment_detail(
    equipment_id: UUID,
    org_id: UUID = Query(...),
    db: Session = Depends(get_db),
):
    """
    Upcoming tests (next 60 days) and recent completed results
    for a single equipment — shown in the detail panel when a
    row is tapped in the compliance matrix.
    """
    result = TestScheduleDashboardService(db).get_equipment_detail(
        equipment_id=equipment_id,
        org_id=org_id,
    )
    if not result:
        raise HTTPException(404, "Equipment not found.")
    return result
