"""
Analytics API Router
====================

Drill-down chain:

  Zone / Circle / Division analytics
    GET /analytics/departments/{id}                    ← node KPIs
    GET /analytics/departments/{id}/tree               ← node + one level of child nodes
    GET /analytics/departments/{id}/equipment          ← every equipment in this dept (with scores)

  Equipment analytics
    GET /analytics/equipment/{id}                      ← aggregated health
    GET /analytics/equipment/{id}/tests                ← test history (all templates, latest-first)
    GET /analytics/equipment/{id}/parameters           ← latest param analytics (all templates)
    GET /analytics/equipment/{id}/parameters/{key}/history
                                                       ← time-series of one parameter across all tests

  Test-result analytics
    GET  /analytics/test-results/{id}                  ← test-level scores + findings
    GET  /analytics/test-results/{id}/raw              ← test-level scores + actual test_data JSONB

  Trigger / recompute
    POST /analytics/test-results/{id}/run
    POST /analytics/equipment/{id}/run
"""

import uuid
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, func
from sqlalchemy.orm import Session, joinedload

from database import get_vendor_db
from auth_utils import get_current_user
from models import (
    CategoryMaster,
    Equipment,
    EquipmentAnalytics,
    HierarchyAnalytics,
    OrgDepartment,
    ParameterAnalytics,
    TestAnalytics,
    TestResult,
    TestingRequest,
)
from services.analytics_engine import AnalyticsEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard summary endpoint (consumed by the AI Analytics Dashboard UI)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", summary="AI Analytics Dashboard summary")
def get_analytics_dashboard(
    department_id: Optional[uuid.UUID] = Query(None),
    date_from:     Optional[date]      = Query(None, description="Filter completed_at >= this date (YYYY-MM-DD)"),
    date_to:       Optional[date]      = Query(None, description="Filter completed_at <= this date (YYYY-MM-DD)"),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns a single payload for the AI Analytics Dashboard:

      - kpi_summary        : totals by risk level
      - hierarchy_node     : analytics for the selected department (or None)
      - top_critical       : up to 10 equipment with the lowest health scores
      - recent_anomalies   : up to 20 latest parameter anomalies
      - health_distribution: equipment count per risk band
      - department_scores  : one-level child breakdown (for drill-down)
    """
    # ── 1. Resolve equipment IDs in scope ────────────────────────────────────
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    eq_query = db.query(EquipmentAnalytics)
    if dept_ids:
        eq_query = eq_query.filter(EquipmentAnalytics.department_id.in_(dept_ids))
    all_ea: list[EquipmentAnalytics] = eq_query.all()

    # ── 2. KPI summary ───────────────────────────────────────────────────────
    risk_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
    for ea in all_ea:
        risk_counts[ea.risk_level or "Unknown"] = risk_counts.get(ea.risk_level or "Unknown", 0) + 1

    total = len(all_ea)
    avg_score = round(
        sum(float(ea.health_score) for ea in all_ea if ea.health_score is not None) / total, 1
    ) if total else None

    # Total completed/closed tests across all scoped equipment
    all_eq_ids = [ea.equipment_id for ea in all_ea if ea.equipment_id]
    _TERMINAL_STATUSES_KPI = ("completed", "closed")
    total_tests_q = (
        db.query(func.count(TestingRequest.id))
        .filter(
            TestingRequest.equipment_id.in_(all_eq_ids),
            TestingRequest.status.in_(_TERMINAL_STATUSES_KPI),
        )
    ) if all_eq_ids else None
    if total_tests_q is not None:
        total_tests_q = _apply_completed_at_filter(total_tests_q, date_from, date_to)
    total_tests = (total_tests_q.scalar() or 0) if total_tests_q is not None else 0

    # ── 3. Hierarchy node ───────────────────────────────────────────────────
    ha_node = None
    dept_obj = None
    if department_id:
        ha_node = db.query(HierarchyAnalytics).filter(
            HierarchyAnalytics.department_id == department_id
        ).first()
        dept_obj = db.get(OrgDepartment, department_id)

    # ── 4. Top critical equipment (only equipment with at least 1 test) ─────
    _TERMINAL_STATUSES = ("completed", "closed")

    # Count tests for ALL scoped equipment first so we can filter before limiting
    if all_eq_ids:
        tc_q = (
            db.query(TestingRequest.equipment_id, func.count(TestingRequest.id))
            .filter(
                TestingRequest.equipment_id.in_(all_eq_ids),
                TestingRequest.status.in_(_TERMINAL_STATUSES),
            )
        )
        tc_q = _apply_completed_at_filter(tc_q, date_from, date_to)
        test_count_rows = tc_q.group_by(TestingRequest.equipment_id).all()
        test_count_map: dict = {row[0]: row[1] for row in test_count_rows}
    else:
        test_count_map = {}

    critical_ea = sorted(
        [ea for ea in all_ea if ea.health_score is not None
         and test_count_map.get(ea.equipment_id, 0) > 0],
        key=lambda e: e.health_score,
    )[:10]

    eq_ids = [ea.equipment_id for ea in critical_ea]
    eq_map = {e.id: e for e in db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all()}

    type_ids = list({e.equipment_type_id for e in eq_map.values() if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    }

    dept_ids_for_names = list({ea.department_id for ea in critical_ea if ea.department_id})
    dept_name_map = {
        d.id: d.name
        for d in db.query(OrgDepartment).filter(OrgDepartment.id.in_(dept_ids_for_names)).all()
    }

    top_critical = [
        {
            "equipment_id":     str(ea.equipment_id),
            "ueic":             eq_map[ea.equipment_id].ueic if ea.equipment_id in eq_map else None,
            "equipment_type":   type_map.get(eq_map[ea.equipment_id].equipment_type_id) if ea.equipment_id in eq_map else None,
            "department":       dept_name_map.get(ea.department_id),
            "department_id":    str(ea.department_id) if ea.department_id else None,
            "health_score":     float(ea.health_score),
            "risk_level":       ea.risk_level,
            "condition_summary":ea.condition_summary,
            "parameters_at_risk":ea.parameters_at_risk,
            "last_test_date":   ea.last_test_date.isoformat() if ea.last_test_date else None,
            "test_count":       test_count_map.get(ea.equipment_id, 0),
            "links": {
                "analytics":  f"/analytics/equipment/{ea.equipment_id}",
                "tests":      f"/analytics/equipment/{ea.equipment_id}/tests",
                "parameters": f"/analytics/equipment/{ea.equipment_id}/parameters",
            },
        }
        for ea in critical_ea
        if ea.equipment_id in eq_map
    ]

    # ── 5. Recent anomalies ──────────────────────────────────────────────────
    anom_query = (
        db.query(ParameterAnalytics)
        .filter(ParameterAnalytics.is_anomaly == True)  # noqa: E712
        .order_by(ParameterAnalytics.calculated_at.desc())
    )
    if dept_ids:
        anom_query = anom_query.filter(ParameterAnalytics.equipment_id.in_(
            [ea.equipment_id for ea in all_ea]
        ))
    recent_anomalies_rows = anom_query.limit(20).all()

    anom_eq_ids = list({r.equipment_id for r in recent_anomalies_rows})
    anom_eq_map = {e.id: e for e in db.query(Equipment).filter(Equipment.id.in_(anom_eq_ids)).all()}

    recent_anomalies = [
        {
            "equipment_id":   str(r.equipment_id),
            "ueic":           anom_eq_map[r.equipment_id].ueic if r.equipment_id in anom_eq_map else None,
            "template_key":   r.template_key,
            "parameter_key":  r.parameter_key,
            "parameter_label":r.parameter_label,
            "value":          float(r.current_value) if r.current_value is not None else None,
            "unit":           r.unit,
            "anomaly_type":   r.anomaly_type,
            "anomaly_detail": r.anomaly_detail,
            "condition":      r.condition,
            "detected_at":    r.calculated_at.isoformat() if r.calculated_at else None,
            "links": {
                "equipment":    f"/analytics/equipment/{r.equipment_id}",
                "parameter_history": (
                    f"/analytics/equipment/{r.equipment_id}"
                    f"/parameters/{r.parameter_key}/history"
                    f"?template_key={r.template_key}"
                ),
            },
        }
        for r in recent_anomalies_rows
    ]

    # ── 6. One-level child department scores (for drill-down picker) ─────────
    child_ha_rows = (
        db.query(HierarchyAnalytics)
        .filter(HierarchyAnalytics.parent_department_id == department_id)
        .all()
    ) if department_id else []

    child_dept_ids = [c.department_id for c in child_ha_rows]
    child_dept_map = {
        d.id: d.name
        for d in db.query(OrgDepartment).filter(OrgDepartment.id.in_(child_dept_ids)).all()
    }

    department_scores = [
        {
            "department_id":  str(c.department_id),
            "department_name":child_dept_map.get(c.department_id),
            "level_type":     c.level_type,
            "health_score":   float(c.health_score) if c.health_score is not None else None,
            "risk_level":     c.risk_level,
            "equipment_count":c.equipment_count,
            "links": {
                "analytics": f"/analytics/departments/{c.department_id}",
                "equipment": f"/analytics/departments/{c.department_id}/equipment",
            },
        }
        for c in child_ha_rows
    ]

    return {
        "department_id":   str(department_id) if department_id else None,
        "department_name": dept_obj.name if dept_obj else None,
        "kpi_summary": {
            "total_equipment": total,
            "avg_health_score": avg_score,
            "total_tests":   total_tests,
            "critical":  risk_counts["Critical"],
            "high":      risk_counts["High"],
            "medium":    risk_counts["Medium"],
            "low":       risk_counts["Low"],
        },
        "hierarchy_node":    _serialize_hierarchy_analytics(ha_node, dept_obj) if ha_node else None,
        "top_critical":      top_critical,
        "recent_anomalies":  recent_anomalies,
        "department_scores": department_scores,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Trigger endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/test-results/{test_result_id}/run", summary="Run analytics for a test result")
def run_test_analytics(
    test_result_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    from models import TestResult as _TR
    from services.evaluation_service import EvaluationService

    # Re-evaluate the stored test_data so stale evaluation_result rows (e.g.
    # fields=[]) are refreshed before analytics runs.
    tr = db.get(_TR, test_result_id)
    if not tr:
        raise HTTPException(status_code=404, detail="Test result not found")

    template_data = EvaluationService.get_template_data(
        tr.template_key, db, org_id=tr.organization_id
    )
    if template_data:
        fresh_eval = EvaluationService.evaluate_test_data(template_data, tr.test_data or {})
        tr.evaluation_result = fresh_eval
        db.flush()

    engine = AnalyticsEngine(db)
    ta = engine.run_for_test(test_result_id)
    if not ta:
        raise HTTPException(status_code=404, detail="Test result not found or template missing")
    db.commit()
    return {
        "status":         "ok",
        "test_result_id": str(test_result_id),
        "health_score":   float(ta.health_score) if ta.health_score is not None else None,
        "risk_level":     ta.risk_level,
        "condition":      ta.condition_summary,
        "eval_fields":    len(tr.evaluation_result.get("fields", [])) if tr.evaluation_result else 0,
    }


@router.post("/equipment/{equipment_id}/run", summary="Re-run equipment analytics")
def run_equipment_analytics(
    equipment_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    engine = AnalyticsEngine(db)
    ea = engine.run_for_equipment(equipment_id)
    if not ea:
        raise HTTPException(status_code=404, detail="Equipment not found or no test analytics available")
    db.commit()
    return {
        "status":        "ok",
        "equipment_id":  str(equipment_id),
        "health_score":  float(ea.health_score) if ea.health_score is not None else None,
        "risk_level":    ea.risk_level,
    }


@router.post("/recompute-all", summary="Recompute analytics for every test result (admin)")
def recompute_all_analytics(
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """Re-runs score_test + equipment aggregation for every TestResult in the DB.
    Use after changing the scoring formula to backfill historical scores."""
    from models import TestResult
    results = db.query(TestResult).all()
    engine  = AnalyticsEngine(db)
    done, failed = 0, 0
    for tr in results:
        try:
            engine.run_for_test(tr.id)
            done += 1
        except Exception as exc:
            failed += 1
            logger.warning("recompute_all: failed for %s: %s", tr.id, exc)
    db.commit()
    return {"status": "ok", "recomputed": done, "failed": failed}


@router.get("/dashboard/equipment", summary="Paginated equipment list for dashboard")
def get_dashboard_equipment(
    department_id: Optional[uuid.UUID] = Query(None),
    page:          int                 = Query(1, ge=1),
    page_size:     int                 = Query(20, ge=1, le=100),
    search:        Optional[str]       = Query(None, description="Filter by UEIC (partial match)"),
    date_from:     Optional[date]      = Query(None),
    date_to:       Optional[date]      = Query(None),
    db:            Session             = Depends(get_vendor_db),
    user:          dict                = Depends(get_current_user),
):
    """
    Returns all equipment in scope (worst health first), paginated.
    Equipment with no analytics appear at the end with null scores.
    """
    dept_ids = _collect_department_ids(department_id, db) if department_id else None

    # All equipment in scope
    eq_q = db.query(Equipment)
    if dept_ids:
        eq_q = eq_q.filter(Equipment.department_id.in_(dept_ids))
    if search:
        eq_q = eq_q.filter(Equipment.ueic.ilike(f"%{search}%"))
    all_eq: list[Equipment] = eq_q.all()

    eq_ids = [e.id for e in all_eq]

    # Analytics map
    ea_rows = db.query(EquipmentAnalytics).filter(
        EquipmentAnalytics.equipment_id.in_(eq_ids)
    ).all()
    ea_map = {r.equipment_id: r for r in ea_rows}

    # Type names
    type_ids = list({e.equipment_type_id for e in all_eq if e.equipment_type_id})
    type_map = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    }

    # Department names
    dept_ids_for_names = list({e.department_id for e in all_eq if e.department_id})
    dept_name_map = {
        d.id: d.name
        for d in db.query(OrgDepartment).filter(OrgDepartment.id.in_(dept_ids_for_names)).all()
    }

    # Test counts (respects date filter)
    tc_q = (
        db.query(TestingRequest.equipment_id, func.count(TestingRequest.id))
        .filter(
            TestingRequest.equipment_id.in_(eq_ids),
            TestingRequest.status.in_(("completed", "closed")),
        )
    )
    tc_q = _apply_completed_at_filter(tc_q, date_from, date_to)
    test_count_map = {row[0]: row[1] for row in tc_q.group_by(TestingRequest.equipment_id).all()}

    def _sort_key(eq: Equipment):
        ea = ea_map.get(eq.id)
        if ea and ea.health_score is not None:
            return (0, float(ea.health_score))   # tested: sort ascending (worst first)
        return (1, 0.0)                           # untested: at the end

    sorted_eq = sorted(all_eq, key=_sort_key)
    total = len(sorted_eq)
    start = (page - 1) * page_size
    page_eq = sorted_eq[start: start + page_size]

    items = []
    for eq in page_eq:
        ea = ea_map.get(eq.id)
        items.append({
            "equipment_id":      str(eq.id),
            "ueic":              eq.ueic,
            "equipment_type":    type_map.get(eq.equipment_type_id),
            "department":        dept_name_map.get(eq.department_id),
            "department_id":     str(eq.department_id) if eq.department_id else None,
            "health_score":      float(ea.health_score) if ea and ea.health_score is not None else None,
            "risk_level":        ea.risk_level if ea else "Unknown",
            "parameters_at_risk":ea.parameters_at_risk if ea else 0,
            "test_count":        test_count_map.get(eq.id, 0),
            "tested":            ea is not None,
        })

    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  start + page_size < total,
        "items":     items,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchy drill-down
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/departments/{department_id}", summary="Hierarchy analytics for a department node")
def get_department_analytics(
    department_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    row = (
        db.query(HierarchyAnalytics)
        .filter(HierarchyAnalytics.department_id == department_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No hierarchy analytics for this department")
    dept = db.get(OrgDepartment, department_id)
    return _serialize_hierarchy_analytics(row, dept)


@router.get("/departments/{department_id}/tree", summary="Node + one level of children")
def get_department_tree(
    department_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    root     = db.query(HierarchyAnalytics).filter(HierarchyAnalytics.department_id == department_id).first()
    root_dept = db.get(OrgDepartment, department_id)

    child_rows = (
        db.query(HierarchyAnalytics)
        .filter(HierarchyAnalytics.parent_department_id == department_id)
        .all()
    )
    child_depts = {
        str(d.id): d
        for d in db.query(OrgDepartment)
        .filter(OrgDepartment.parent_department_id == department_id)
        .all()
    }

    return {
        "node":     _serialize_hierarchy_analytics(root, root_dept) if root else None,
        "children": [
            _serialize_hierarchy_analytics(c, child_depts.get(str(c.department_id)))
            for c in child_rows
        ],
    }


@router.get(
    "/departments/{department_id}/equipment",
    summary="All equipment in a department with their analytics scores",
)
def get_department_equipment(
    department_id: uuid.UUID,
    include_sub_departments: bool = Query(
        False,
        description="If true, include equipment from all nested child departments",
    ),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns every Equipment record in this department (and optionally all child
    departments) joined with its EquipmentAnalytics row (if computed).

    Each item in the response carries:
      - equipment_id   — use to call GET /analytics/equipment/{equipment_id}
      - ueic           — human-readable asset code
      - equipment_type — category name
      - health_score, risk_level, condition_summary from EquipmentAnalytics
      - links.analytics, links.tests, links.parameters
    """
    dept_ids = _collect_department_ids(department_id, db) if include_sub_departments else {department_id}

    equipment_rows = (
        db.query(Equipment)
        .filter(Equipment.department_id.in_(dept_ids), Equipment.status != "retired")
        .all()
    )

    # Bulk-fetch analytics for all equipment found
    eq_ids = [e.id for e in equipment_rows]
    analytics_map: dict[uuid.UUID, EquipmentAnalytics] = {
        ea.equipment_id: ea
        for ea in db.query(EquipmentAnalytics).filter(EquipmentAnalytics.equipment_id.in_(eq_ids)).all()
    }

    # Bulk-fetch category names
    type_ids  = list({e.equipment_type_id for e in equipment_rows if e.equipment_type_id})
    type_map  = {
        c.id: c.name
        for c in db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
    }

    return [
        _serialize_equipment_summary(e, analytics_map.get(e.id), type_map)
        for e in equipment_rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Equipment drill-down
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/equipment/{equipment_id}", summary="Aggregated health analytics for one equipment")
def get_equipment_analytics(
    equipment_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    ea  = db.query(EquipmentAnalytics).filter(EquipmentAnalytics.equipment_id == equipment_id).first()
    if not ea:
        raise HTTPException(status_code=404, detail="No analytics available for this equipment")
    eq  = db.get(Equipment, equipment_id)
    return _serialize_equipment_analytics(ea, eq)


@router.get(
    "/equipment/{equipment_id}/tests",
    summary="Test history for equipment — each test result linked to its analytics",
)
def get_equipment_test_history(
    equipment_id: uuid.UUID,
    template_key: Optional[str] = Query(None, description="Filter to one test type"),
    limit:        int           = Query(50, ge=1, le=200),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns every TestAnalytics row for this equipment, latest-first.
    Each item includes:
      - test_result_id     → call GET /analytics/test-results/{id} for full analytics
      - testing_request_id → call GET /testing-requests/{id} for the request record
      - template_key, tested_at, health_score, risk_level, critical_findings
      - links.analytics, links.raw
    """
    q = (
        db.query(TestAnalytics)
        .filter(TestAnalytics.equipment_id == equipment_id)
        .order_by(TestAnalytics.calculated_at.desc())
    )
    if template_key:
        q = q.filter(TestAnalytics.template_key == template_key)
    rows = q.limit(limit).all()

    # Bulk-fetch tested_at from TestResult
    result_ids = [r.test_result_id for r in rows]
    tested_at_map = {
        r.id: r.tested_at or r.cts
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }

    return [_serialize_test_history_item(r, tested_at_map.get(r.test_result_id)) for r in rows]


@router.get(
    "/equipment/{equipment_id}/parameters",
    summary="Latest parameter analytics for all tracked parameters on an equipment",
)
def get_parameter_analytics(
    equipment_id: uuid.UUID,
    template_key: Optional[str] = Query(None),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    q = db.query(ParameterAnalytics).filter(ParameterAnalytics.equipment_id == equipment_id)
    if template_key:
        q = q.filter(ParameterAnalytics.template_key == template_key)
    rows = q.order_by(ParameterAnalytics.calculated_at.desc()).all()
    result_ids = [r.test_result_id for r in rows]
    tested_at_map = {
        r.id: (r.tested_at or r.cts)
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }
    return [_serialize_parameter_analytics(r, tested_at_map.get(r.test_result_id)) for r in rows]


@router.get(
    "/equipment/{equipment_id}/parameters/{parameter_key}/history",
    summary="Time-series history of one parameter across all test runs",
)
def get_parameter_history(
    equipment_id:  uuid.UUID,
    parameter_key: str,
    template_key:  Optional[str] = Query(None),
    limit:         int           = Query(50, ge=1, le=500),
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns chronological readings for a single parameter, including the raw
    measured value, the test_result_id and testing_request_id so the caller
    can navigate to the actual stored result.

    Each item:
      {
        "tested_at":          "2024-03-15T09:30:00Z",
        "value":              42.5,
        "unit":               "MOhm",
        "condition":          "Good",
        "status":             "NORMAL",
        "score":              100,
        "is_anomaly":         false,
        "test_result_id":     "...",
        "testing_request_id": "...",
        "links": {
          "test_result":         "/analytics/test-results/{id}",
          "raw_data":            "/analytics/test-results/{id}/raw",
          "testing_request":     "/testing-requests/{id}"
        }
      }
    """
    q = (
        db.query(ParameterAnalytics)
        .filter(
            ParameterAnalytics.equipment_id  == equipment_id,
            ParameterAnalytics.parameter_key == parameter_key,
        )
        .order_by(ParameterAnalytics.calculated_at.asc())
    )
    if template_key:
        q = q.filter(ParameterAnalytics.template_key == template_key)
    rows = q.limit(limit).all()

    # Bulk-fetch tested_at + testing_request_id from TestResult
    result_ids = [r.test_result_id for r in rows]
    results_map = {
        r.id: r
        for r in db.query(TestResult).filter(TestResult.id.in_(result_ids)).all()
    }

    return [
        _serialize_parameter_history_point(row, results_map.get(row.test_result_id))
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Test-result drill-down
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/test-results/{test_result_id}", summary="Test-level analytics")
def get_test_analytics(
    test_result_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    row = db.query(TestAnalytics).filter(TestAnalytics.test_result_id == test_result_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Analytics not yet computed for this test result")
    tr = db.get(TestResult, test_result_id)
    return _serialize_test_analytics(row, tr)


@router.get(
    "/test-results/{test_result_id}/raw",
    summary="Test-level analytics + the actual stored test_data JSONB",
)
def get_test_analytics_with_raw(
    test_result_id: uuid.UUID,
    db:   Session = Depends(get_vendor_db),
    user: dict    = Depends(get_current_user),
):
    """
    Returns the full analytics alongside the raw `test_data` JSONB that was
    recorded by the tester, plus the per-field `evaluation_result`.
    This is the terminal drill-down: the user sees both the computed insights
    and the underlying measurements side-by-side.
    """
    row = db.query(TestAnalytics).filter(TestAnalytics.test_result_id == test_result_id).first()
    tr  = db.get(TestResult, test_result_id)

    if not tr:
        raise HTTPException(status_code=404, detail="Test result not found")

    req = db.get(TestingRequest, tr.testing_request_id) if tr.testing_request_id else None
    eq  = db.get(Equipment, req.equipment_id) if req and req.equipment_id else None

    analytics = _serialize_test_analytics(row, tr) if row else None

    return {
        "analytics":        analytics,
        "test_result": {
            "id":                  str(tr.id),
            "testing_request_id":  str(tr.testing_request_id) if tr.testing_request_id else None,
            "test_name":           tr.test_name,
            "test_category":       tr.test_category,
            "template_key":        tr.template_key,
            "overall_result":      tr.overall_result,
            "tested_at":           tr.tested_at.isoformat() if tr.tested_at else None,
            "test_data":           tr.test_data or {},
            "evaluation_result":   tr.evaluation_result or {},
            "remarks":             tr.remarks,
        },
        "equipment": _serialize_equipment_brief(eq) if eq else None,
        "testing_request": {
            "id":             str(req.id),
            "request_number": req.request_number,
            "title":          getattr(req, "title", None),
            "status":         req.status.value if req.status else None,
        } if req else None,
        "links": {
            "equipment_analytics": f"/analytics/equipment/{eq.id}" if eq else None,
            "equipment_tests":     f"/analytics/equipment/{eq.id}/tests" if eq else None,
            "parameter_analytics": f"/analytics/equipment/{eq.id}/parameters?template_key={tr.template_key}" if eq and tr.template_key else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _apply_completed_at_filter(q, date_from: Optional[date], date_to: Optional[date]):
    """Filter a TestingRequest query by completed_at range (both bounds optional)."""
    if date_from:
        q = q.filter(TestingRequest.completed_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(TestingRequest.completed_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return q


def _collect_department_ids(root_id: uuid.UUID, db: Session) -> set:
    """BFS to collect root + all descendant department IDs."""
    visited: set = set()
    queue = [root_id]
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        children = (
            db.query(OrgDepartment.id)
            .filter(OrgDepartment.parent_department_id == current)
            .all()
        )
        queue.extend(child_id for (child_id,) in children)
    return visited


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_hierarchy_analytics(row: HierarchyAnalytics, dept: Optional[OrgDepartment] = None) -> dict:
    return {
        "id":                    str(row.id),
        "department_id":         str(row.department_id),
        "department_name":       dept.name if dept else None,
        "department_code":       dept.code if dept else None,
        "parent_department_id":  str(row.parent_department_id) if row.parent_department_id else None,
        "level_type":            row.level_type,
        "health_score":          float(row.health_score) if row.health_score is not None else None,
        "risk_level":            row.risk_level,
        "equipment_count":       row.equipment_count,
        "equipment_critical":    row.equipment_critical,
        "equipment_high":        row.equipment_high,
        "equipment_medium":      row.equipment_medium,
        "equipment_low":         row.equipment_low,
        "child_count":           row.child_count,
        "child_breakdown":       row.child_breakdown or {},
        "calculated_at":         row.calculated_at.isoformat() if row.calculated_at else None,
        "links": {
            "self":      f"/analytics/departments/{row.department_id}",
            "tree":      f"/analytics/departments/{row.department_id}/tree",
            "equipment": f"/analytics/departments/{row.department_id}/equipment",
        },
    }


def _serialize_equipment_summary(
    eq: Equipment,
    ea: Optional[EquipmentAnalytics],
    type_map: dict,
) -> dict:
    return {
        "equipment_id":      str(eq.id),
        "ueic":              eq.ueic,
        "manufacturer":      eq.manufacturer,
        "model_number":      eq.model_number,
        "equipment_type":    type_map.get(eq.equipment_type_id),
        "department_id":     str(eq.department_id) if eq.department_id else None,
        "commissioned_date": eq.commissioned_date.isoformat() if eq.commissioned_date else None,
        "status":            eq.status.value if eq.status else None,
        # analytics (None if not yet computed)
        "health_score":      float(ea.health_score)      if ea and ea.health_score      is not None else None,
        "risk_level":        ea.risk_level                if ea else None,
        "condition_summary": ea.condition_summary         if ea else None,
        "last_test_date":    ea.last_test_date.isoformat() if ea and ea.last_test_date  else None,
        "parameters_at_risk":ea.parameters_at_risk        if ea else None,
        "test_types_assessed":ea.test_types_assessed      if ea else None,
        "analytics_computed":ea is not None,
        "links": {
            "analytics":   f"/analytics/equipment/{eq.id}",
            "tests":       f"/analytics/equipment/{eq.id}/tests",
            "parameters":  f"/analytics/equipment/{eq.id}/parameters",
        },
    }


def _serialize_equipment_analytics(ea: EquipmentAnalytics, eq: Optional[Equipment] = None) -> dict:
    return {
        "id":                   str(ea.id),
        "equipment_id":         str(ea.equipment_id),
        "ueic":                 eq.ueic          if eq else None,
        "manufacturer":         eq.manufacturer  if eq else None,
        "model_number":         eq.model_number  if eq else None,
        "department_id":        str(ea.department_id) if ea.department_id else None,
        "health_score":         float(ea.health_score) if ea.health_score is not None else None,
        "risk_level":           ea.risk_level,
        "condition_summary":    ea.condition_summary,
        "test_type_scores":     ea.test_type_scores     or {},
        "critical_findings":    ea.critical_findings    or [],
        "parameters_at_risk":   ea.parameters_at_risk,
        "test_types_assessed":  ea.test_types_assessed,
        "last_test_date":       ea.last_test_date.isoformat() if ea.last_test_date else None,
        "calculated_at":        ea.calculated_at.isoformat()  if ea.calculated_at  else None,
        "links": {
            "tests":      f"/analytics/equipment/{ea.equipment_id}/tests",
            "parameters": f"/analytics/equipment/{ea.equipment_id}/parameters",
            "department": f"/analytics/departments/{ea.department_id}" if ea.department_id else None,
        },
    }


def _serialize_equipment_brief(eq: Equipment) -> dict:
    return {
        "equipment_id":     str(eq.id),
        "ueic":             eq.ueic,
        "manufacturer":     eq.manufacturer,
        "model_number":     eq.model_number,
        "department_id":    str(eq.department_id) if eq.department_id else None,
        "status":           eq.status.value if eq.status else None,
    }


def _serialize_test_analytics(row: TestAnalytics, tr: Optional[TestResult] = None) -> dict:
    return {
        "id":                str(row.id),
        "test_result_id":    str(row.test_result_id),
        "testing_request_id":str(row.testing_request_id) if row.testing_request_id else None,
        "equipment_id":      str(row.equipment_id),
        "template_key":      row.template_key,
        "test_name":         tr.test_name      if tr else None,
        "test_category":     tr.test_category  if tr else None,
        "tested_at":         (tr.tested_at or tr.cts).isoformat() if tr and (tr.tested_at or tr.cts) else None,
        "overall_result":    tr.overall_result if tr else None,
        "health_score":      float(row.health_score) if row.health_score is not None else None,
        "risk_level":        row.risk_level,
        "condition_summary": row.condition_summary,
        "trend_summary":     row.trend_summary,
        "critical_findings": row.critical_findings or [],
        "recommendations":   row.recommendations  or [],
        "parameter_count":   row.parameter_count,
        "evaluated_count":   row.evaluated_count,
        "calculated_at":     row.calculated_at.isoformat() if row.calculated_at else None,
        "links": {
            "self":            f"/analytics/test-results/{row.test_result_id}",
            "raw":             f"/analytics/test-results/{row.test_result_id}/raw",
            "equipment":       f"/analytics/equipment/{row.equipment_id}",
            "parameters":      f"/analytics/equipment/{row.equipment_id}/parameters?template_key={row.template_key}",
            "testing_request": f"/testing-requests/{row.testing_request_id}" if row.testing_request_id else None,
        },
    }


def _serialize_test_history_item(row: TestAnalytics, tested_at) -> dict:
    return {
        "test_result_id":    str(row.test_result_id),
        "testing_request_id":str(row.testing_request_id) if row.testing_request_id else None,
        "template_key":      row.template_key,
        "tested_at":         tested_at.isoformat() if tested_at else None,
        "health_score":      float(row.health_score) if row.health_score is not None else None,
        "risk_level":        row.risk_level,
        "condition_summary": row.condition_summary,
        "critical_findings": row.critical_findings or [],
        "evaluated_count":   row.evaluated_count,
        "links": {
            "analytics":       f"/analytics/test-results/{row.test_result_id}",
            "raw":             f"/analytics/test-results/{row.test_result_id}/raw",
            "testing_request": f"/testing-requests/{row.testing_request_id}" if row.testing_request_id else None,
        },
    }


def _serialize_parameter_analytics(row: ParameterAnalytics, tested_at=None) -> dict:
    return {
        "last_tested_at": tested_at.isoformat() if tested_at else None,
        "id":                   str(row.id),
        "equipment_id":         str(row.equipment_id),
        "test_result_id":       str(row.test_result_id),
        "template_key":         row.template_key,
        "parameter_key":        row.parameter_key,
        "parameter_label":      row.parameter_label,
        "parameter_type":       row.parameter_type,
        "current_value":        float(row.current_value)     if row.current_value     is not None else None,
        "unit":                 row.unit,
        "condition":            row.condition,
        "status":               row.status,
        "score":                float(row.score)             if row.score             is not None else None,
        "trend":                row.trend,
        "trend_slope":          float(row.trend_slope)       if row.trend_slope       is not None else None,
        "trend_r_squared":      float(row.trend_r_squared)   if row.trend_r_squared   is not None else None,
        "history_count":        row.history_count,
        "annual_change":        float(row.annual_change)     if row.annual_change     is not None else None,
        "pct_change_annual":    float(row.pct_change_annual) if row.pct_change_annual is not None else None,
        "breach_threshold":     float(row.breach_threshold)  if row.breach_threshold  is not None else None,
        "breach_predicted_at":  row.breach_predicted_at.isoformat() if row.breach_predicted_at else None,
        "days_to_breach":       row.days_to_breach,
        "is_anomaly":           row.is_anomaly,
        "anomaly_type":         row.anomaly_type,
        "anomaly_detail":       row.anomaly_detail,
        "calculated_at":        row.calculated_at.isoformat() if row.calculated_at else None,
        "links": {
            "test_result":   f"/analytics/test-results/{row.test_result_id}",
            "raw_data":      f"/analytics/test-results/{row.test_result_id}/raw",
            "history":       f"/analytics/equipment/{row.equipment_id}/parameters/{row.parameter_key}/history?template_key={row.template_key}",
        },
    }


def _serialize_parameter_history_point(row: ParameterAnalytics, tr: Optional[TestResult]) -> dict:
    tested_at = None
    if tr:
        dt = tr.tested_at or tr.cts
        tested_at = dt.isoformat() if dt else None

    return {
        "tested_at":          tested_at,
        "value":              float(row.current_value)  if row.current_value  is not None else None,
        "unit":               row.unit,
        "condition":          row.condition,
        "status":             row.status,
        "score":              float(row.score)          if row.score          is not None else None,
        "is_anomaly":         row.is_anomaly,
        "anomaly_type":       row.anomaly_type,
        "test_result_id":     str(row.test_result_id),
        "testing_request_id": str(tr.testing_request_id) if tr and tr.testing_request_id else None,
        "links": {
            "test_result":     f"/analytics/test-results/{row.test_result_id}",
            "raw_data":        f"/analytics/test-results/{row.test_result_id}/raw",
            "testing_request": f"/testing-requests/{tr.testing_request_id}" if tr and tr.testing_request_id else None,
        },
    }
