"""
test_schedule_dashboard_service.py
────────────────────────────────────
Compliance matrix for the Test Schedule Dashboard tab.

Returns per-equipment × per-test-type next-due/overdue data in one
efficient batch (no N+1 queries).

Health Index formula (computed, not stored):
    100 - (15 × overdue) - (8 × due_imminent ≤15d) - (3 × due_soon ≤30d)
    clamped 0–100
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    CategoryDetails,
    CategoryMaster,
    Equipment,
    OrgDepartment,
    TestingRequest,
    TestRequestSchedule,
)


# ─────────────────────────────────────────────────────────────────
# Status thresholds (days until due)
# ─────────────────────────────────────────────────────────────────
_OVERDUE_THRESHOLD    = 0    # <= 0  → overdue   (red)
_IMMINENT_THRESHOLD   = 15   # 1–15  → due_imminent (orange)
_SOON_THRESHOLD       = 30   # 16–30 → due_soon  (amber)
                             # >30   → ok        (green)

_STATUS_PRIORITY = {
    "overdue":      4,
    "due_imminent": 3,
    "due_soon":     2,
    "ok":           1,
    "na":           0,
}

_OVERALL_LABEL = {
    "overdue":      "OVERDUE",
    "due_imminent": "ALERT",
    "due_soon":     "DUE",
    "ok":           "OK",
    "na":           "OK",
}


def _cell_status(days: Optional[int]) -> str:
    if days is None:
        return "na"
    if days <= _OVERDUE_THRESHOLD:
        return "overdue"
    if days <= _IMMINENT_THRESHOLD:
        return "due_imminent"
    if days <= _SOON_THRESHOLD:
        return "due_soon"
    return "ok"


def _health_index(cells: dict) -> int:
    overdue  = sum(1 for c in cells.values() if c["status"] == "overdue")
    imminent = sum(1 for c in cells.values() if c["status"] == "due_imminent")
    soon     = sum(1 for c in cells.values() if c["status"] == "due_soon")
    score = 100 - (15 * overdue) - (8 * imminent) - (3 * soon)
    return max(0, min(100, score))


class TestScheduleDashboardService:

    def __init__(self, db: Session):
        self.db  = db
        self._today = date.today()

    # ─────────────────────────────────────────────────────────────
    # Public — compliance matrix
    # ─────────────────────────────────────────────────────────────

    def get_compliance_matrix(
        self,
        org_id: UUID,
        equipment_type_name: Optional[str] = None,
        voltage_class: Optional[str] = None,
        department_id: Optional[UUID] = None,
        search: Optional[str] = None,
    ) -> dict:
        """
        Returns:
            columns  — ordered list of test-type names that have schedules
            kpis     — 5 headline numbers
            rows     — one row per equipment with per-test-type cells
        """

        # 1. Equipment type master (only if specific type requested)
        master = None
        if equipment_type_name:
            master = (
                self.db.query(CategoryMaster)
                .filter_by(name=equipment_type_name, is_active=True)
                .first()
            )
            if not master:
                return {"columns": [], "kpis": self._empty_kpis(), "rows": []}

        # 2. Equipment list
        eq_q = (
            self.db.query(Equipment)
            .filter(
                Equipment.organization_id == org_id,
                Equipment.status == "active",
            )
        )
        # Filter by equipment type only if specific type requested
        if master:
            eq_q = eq_q.filter(Equipment.equipment_type_id == master.id)
        if voltage_class:
            eq_q = eq_q.filter(Equipment.voltage_class == voltage_class)
        if department_id:
            dept_ids = self._dept_subtree(department_id)
            eq_q = eq_q.filter(Equipment.department_id.in_(dept_ids))
        if search:
            eq_q = eq_q.filter(Equipment.ueic.ilike(f"%{search}%"))

        equipments = eq_q.order_by(Equipment.ueic).all()
        if not equipments:
            return {"columns": [], "kpis": self._empty_kpis(), "rows": []}

        eq_ids = [e.id for e in equipments]

        # 2b. Equipment type name map
        type_ids = list({e.equipment_type_id for e in equipments if e.equipment_type_id})
        type_name_map: dict = {}
        if type_ids:
            type_rows = self.db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
            type_name_map = {r.id: r.name for r in type_rows}

        # 3. All operational schedules for these equipment
        schedules = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.equipment_id.in_(eq_ids),
                TestRequestSchedule.is_active == True,
                TestRequestSchedule.is_deleted == False,
            )
            .all()
        )

        # Index: equipment_id → {test_type_id → schedule}
        sched_idx: dict[UUID, dict[int, TestRequestSchedule]] = {}
        # Index: equipment_id → list of frequency values
        freq_idx: dict[UUID, list[str]] = {}
        test_type_ids_ordered: list[int] = []
        _seen_tt: set[int] = set()
        for s in schedules:
            sched_idx.setdefault(s.equipment_id, {})[s.test_type_id] = s
            if s.frequency:
                freq_idx.setdefault(s.equipment_id, []).append(s.frequency.value)
            if s.test_type_id not in _seen_tt:
                test_type_ids_ordered.append(s.test_type_id)
                _seen_tt.add(s.test_type_id)

        if not test_type_ids_ordered:
            return {"columns": [], "kpis": self._empty_kpis(), "rows": []}

        # 4. Test type names (preserve seed insertion order)
        test_types = (
            self.db.query(CategoryDetails)
            .filter(CategoryDetails.id.in_(test_type_ids_ordered))
            .all()
        )
        tt_map: dict[int, CategoryDetails] = {t.id: t for t in test_types}
        columns = [
            {"id": tid, "name": tt_map[tid].name}
            for tid in test_type_ids_ordered
            if tid in tt_map
        ]

        # 5. Batch: last completed TestingRequest per (equipment_id, test_type_id)
        last_completed = self._batch_last_completed(eq_ids, test_type_ids_ordered)

        # 6. Build rows — only equipment that have at least one schedule
        rows = []
        for eq in equipments:
            eq_scheds = sched_idx.get(eq.id, {})
            if not eq_scheds:
                continue
            cells: dict[str, dict] = {}
            worst_status = "na"

            for col in columns:
                tid = col["id"]
                sched = eq_scheds.get(tid)
                if sched is None:
                    cells[str(tid)] = {
                        "next_due": None,
                        "days_until_due": None,
                        "last_tested": None,
                        "status": "na",
                    }
                    continue

                next_run = sched.next_run_date
                if next_run:
                    next_date = next_run.date() if isinstance(next_run, datetime) else next_run
                    days = (next_date - self._today).days
                else:
                    next_date = None
                    days = None

                last_key = (eq.id, tid)
                last_dt: Optional[datetime] = last_completed.get(last_key)
                last_tested_str = last_dt.date().isoformat() if last_dt else None

                status = _cell_status(days)
                if _STATUS_PRIORITY[status] > _STATUS_PRIORITY[worst_status]:
                    worst_status = status

                cells[str(tid)] = {
                    "next_due":      next_date.isoformat() if next_date else None,
                    "days_until_due": days,
                    "last_tested":   last_tested_str,
                    "status":        status,
                    "frequency":     sched.frequency.value if sched.frequency else None,
                }

            health = _health_index(cells)
            # Dominant frequency: most common among this equipment's schedules
            freqs = freq_idx.get(eq.id, [])
            dominant_freq = max(set(freqs), key=freqs.count) if freqs else None
            rows.append({
                "equipment_id":       str(eq.id),
                "ueic":               eq.ueic,
                "voltage_class":      eq.voltage_class,
                "manufacturer":       eq.manufacturer,
                "year_of_manufacture":eq.year_of_manufacture,
                "model_number":       eq.model_number,
                "overall_status":     _OVERALL_LABEL[worst_status],
                "health_index":       health,
                "cells":              cells,
                "equipment_type_name": type_name_map.get(eq.equipment_type_id, "Unknown") if eq.equipment_type_id else "Unknown",
                "dominant_frequency":  dominant_freq,
            })

        # 7. KPIs
        kpis = self._compute_kpis(rows, columns)

        return {"columns": columns, "kpis": kpis, "rows": rows}

    # ─────────────────────────────────────────────────────────────
    # Public — equipment detail (upcoming + recent)
    # ─────────────────────────────────────────────────────────────

    def get_equipment_detail(self, equipment_id: UUID, org_id: UUID) -> dict:
        """
        Returns upcoming scheduled tests (next 60 days) and
        the 10 most recent completed test requests for the equipment.
        """
        eq = (
            self.db.query(Equipment)
            .filter(Equipment.id == equipment_id, Equipment.organization_id == org_id)
            .first()
        )
        if not eq:
            return {}

        today = self._today
        cutoff = today + timedelta(days=60)

        schedules = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.equipment_id == equipment_id,
                TestRequestSchedule.is_active == True,
                TestRequestSchedule.is_deleted == False,
            )
            .all()
        )

        tt_ids = [s.test_type_id for s in schedules if s.test_type_id]
        tt_map: dict[int, CategoryDetails] = {}
        if tt_ids:
            rows = self.db.query(CategoryDetails).filter(CategoryDetails.id.in_(tt_ids)).all()
            tt_map = {r.id: r for r in rows}

        upcoming = []
        for s in schedules:
            next_run = s.next_run_date
            if not next_run:
                continue
            next_date = next_run.date() if isinstance(next_run, datetime) else next_run
            days = (next_date - today).days
            tt = tt_map.get(s.test_type_id)
            status = _cell_status(days)

            # include overdue and within 60-day window
            if days <= 60:
                upcoming.append({
                    "schedule_id":  str(s.id),
                    "test_type_id": s.test_type_id,
                    "test_name":    tt.name if tt else "Unknown",
                    "next_due":     next_date.isoformat(),
                    "days_until_due": days,
                    "status":       status,
                    "frequency":    s.frequency.value if s.frequency else None,
                    "is_overdue":   days <= 0,
                    "overdue_by":   abs(days) if days <= 0 else None,
                })

        upcoming.sort(key=lambda x: x["days_until_due"])

        # Recent completed requests
        recent = (
            self.db.query(TestingRequest)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.status == "completed",
            )
            .order_by(TestingRequest.completed_at.desc())
            .limit(10)
            .all()
        )

        recent_list = []
        for r in recent:
            tt = tt_map.get(r.test_type_id) if r.test_type_id else None
            recent_list.append({
                "request_id":     str(r.id),
                "request_number": r.request_number,
                "test_name":      tt.name if tt else (r.title or "Unknown"),
                "completed_at":   r.completed_at.date().isoformat() if r.completed_at else None,
                "priority":       r.priority,
            })

        # Health summary
        all_scheds = schedules
        cells_for_health: dict[str, dict] = {}
        for s in all_scheds:
            next_run = s.next_run_date
            if next_run:
                nd = next_run.date() if isinstance(next_run, datetime) else next_run
                days = (nd - today).days
            else:
                days = None
            cells_for_health[str(s.test_type_id)] = {"status": _cell_status(days)}

        health = _health_index(cells_for_health)
        overdue_count  = sum(1 for c in cells_for_health.values() if c["status"] == "overdue")
        imminent_count = sum(1 for c in cells_for_health.values() if c["status"] == "due_imminent")

        if overdue_count > 0:
            health_status = "ALERT"
        elif imminent_count > 0:
            health_status = "DUE"
        else:
            health_status = "OK"

        return {
            "equipment_id":       str(eq.id),
            "ueic":               eq.ueic,
            "voltage_class":      eq.voltage_class,
            "manufacturer":       eq.manufacturer,
            "year_of_manufacture":eq.year_of_manufacture,
            "upcoming_tests":     upcoming,
            "recent_results":     recent_list,
            "health_summary": {
                "health_index":   health,
                "status":         health_status,
                "overdue_count":  overdue_count,
                "imminent_count": imminent_count,
                "total_schedules": len(schedules),
            },
        }

    # ─────────────────────────────────────────────────────────────
    # Public — filter options
    # ─────────────────────────────────────────────────────────────

    def get_filter_options(self, org_id: UUID) -> dict:
        """
        Returns equipment types, voltage classes, and departments with
        equipment/schedule counts — drives the compliance tab filter UI.
        """
        # Equipment types that have active equipment in this org
        eq_types = (
            self.db.query(CategoryMaster)
            .join(Equipment, Equipment.equipment_type_id == CategoryMaster.id)
            .filter(Equipment.organization_id == org_id, Equipment.status == "active")
            .distinct()
            .order_by(CategoryMaster.name)
            .all()
        )

        # Equipment count per equipment type
        type_count_rows = (
            self.db.query(Equipment.equipment_type_id, func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id, Equipment.status == "active")
            .group_by(Equipment.equipment_type_id)
            .all()
        )
        type_counts = {row[0]: row[1] for row in type_count_rows}

        # Voltage classes present for this org
        vc_rows = (
            self.db.query(Equipment.voltage_class)
            .filter(
                Equipment.organization_id == org_id,
                Equipment.status == "active",
                Equipment.voltage_class.isnot(None),
            )
            .distinct()
            .order_by(Equipment.voltage_class)
            .all()
        )

        # Departments (leaf substations) for this org
        depts = (
            self.db.query(OrgDepartment)
            .filter(OrgDepartment.organization_id == org_id, OrgDepartment.is_active == True)
            .order_by(OrgDepartment.name)
            .all()
        )

        # Equipment count per department (direct + descendants via subtree)
        dept_eq_counts: dict = {}
        eq_dept_rows = (
            self.db.query(Equipment.department_id, func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id, Equipment.status == "active",
                    Equipment.department_id.isnot(None))
            .group_by(Equipment.department_id)
            .all()
        )
        for dept_id, cnt in eq_dept_rows:
            dept_eq_counts[dept_id] = cnt

        # Schedule count per department — org-level (equipment_id IS NULL)
        dept_sched_counts: dict = {}
        sched_dept_rows = (
            self.db.query(TestRequestSchedule.department_id, func.count(TestRequestSchedule.id))
            .filter(
                TestRequestSchedule.organization_id == org_id,
                TestRequestSchedule.equipment_id.is_(None),
                TestRequestSchedule.is_active == True,
                TestRequestSchedule.is_deleted == False,
                TestRequestSchedule.department_id.isnot(None),
            )
            .group_by(TestRequestSchedule.department_id)
            .all()
        )
        for dept_id, cnt in sched_dept_rows:
            dept_sched_counts[dept_id] = cnt

        # Schedule count per department — equipment-linked (via equipment.department_id)
        eq_sched_dept_rows = (
            self.db.query(Equipment.department_id, func.count(TestRequestSchedule.id))
            .join(TestRequestSchedule, TestRequestSchedule.equipment_id == Equipment.id)
            .filter(
                TestRequestSchedule.organization_id == org_id,
                TestRequestSchedule.is_active == True,
                TestRequestSchedule.is_deleted == False,
                Equipment.department_id.isnot(None),
            )
            .group_by(Equipment.department_id)
            .all()
        )
        for dept_id, cnt in eq_sched_dept_rows:
            dept_sched_counts[dept_id] = dept_sched_counts.get(dept_id, 0) + cnt

        # Build parent lookup {str(id): str(parent_id)}
        parent_map: dict = {}
        for d in depts:
            if d.parent_department_id:
                parent_map[str(d.id)] = str(d.parent_department_id)

        # Propagate schedule counts up to all ancestors (string-keyed)
        str_sched_counts = {str(k): v for k, v in dept_sched_counts.items()}
        for dept_id_str, cnt in list(str_sched_counts.items()):
            pid = parent_map.get(dept_id_str)
            while pid:
                str_sched_counts[pid] = str_sched_counts.get(pid, 0) + cnt
                pid = parent_map.get(pid)
        dept_sched_counts = str_sched_counts

        # Only include departments that have equipment OR org-level schedules
        dept_list = []
        for d in depts:
            eq_cnt    = dept_eq_counts.get(d.id, 0)
            sched_cnt = dept_sched_counts.get(str(d.id), 0)
            if sched_cnt > 0:
                parent_id_str = parent_map.get(str(d.id))
                dept_list.append({
                    "id":              str(d.id),
                    "name":            d.name,
                    "equipment_count": eq_cnt,
                    "schedule_count":  sched_cnt,
                    "parent_id":       parent_id_str,
                    "parent_name":     None,
                })

        # Sort departments by equipment count descending
        dept_list.sort(key=lambda x: x["equipment_count"], reverse=True)

        return {
            "equipment_types": [
                {"id": str(e.id), "name": e.name, "equipment_count": type_counts.get(e.id, 0)}
                for e in eq_types
            ],
            "voltage_classes": [r[0] for r in vc_rows if r[0]],
            "departments":     dept_list,
        }

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _batch_last_completed(
        self, eq_ids: list, tt_ids: list
    ) -> dict[tuple, datetime]:
        """
        One query → dict[(equipment_id, test_type_id)] = completed_at
        """
        rows = (
            self.db.query(
                TestingRequest.equipment_id,
                TestingRequest.test_type_id,
                func.max(TestingRequest.completed_at).label("last_completed"),
            )
            .filter(
                TestingRequest.equipment_id.in_(eq_ids),
                TestingRequest.test_type_id.in_(tt_ids),
                TestingRequest.status == "completed",
            )
            .group_by(TestingRequest.equipment_id, TestingRequest.test_type_id)
            .all()
        )
        return {(r.equipment_id, r.test_type_id): r.last_completed for r in rows}

    def _dept_subtree(self, dept_id: UUID) -> list[UUID]:
        """
        Return dept_id + ALL descendant department IDs at any depth.
        Uses iterative BFS — safe for the 6-level KPTCL hierarchy
        (Zone → Circle → Division → SubDiv → Section → Substation).
        """
        visited: list[UUID] = []
        queue: list[UUID] = [dept_id]
        while queue:
            current_batch = queue[:]
            queue = []
            visited.extend(current_batch)
            children = (
                self.db.query(OrgDepartment.id)
                .filter(OrgDepartment.parent_department_id.in_(current_batch))
                .all()
            )
            for (child_id,) in children:
                if child_id not in visited:
                    queue.append(child_id)
        return visited

    def _compute_kpis(self, rows: list, columns: list) -> dict:
        today = self._today
        month_start = today.replace(day=1)

        total            = len(rows)
        overdue          = 0
        due_30           = 0
        critical_alert   = 0
        completed_month  = 0

        for row in rows:
            status = row["overall_status"]
            if status == "OVERDUE":
                overdue += 1
                critical_alert += 1
            elif status == "ALERT":
                critical_alert += 1
            if status in ("DUE", "ALERT", "OVERDUE"):
                due_30 += 1

        # Completed this month: count completed TestingRequests across all equipment
        # We can't do it cheaply here without an extra query; use due_30 proxy for now
        # (callers can override with a real count from a separate query if needed)
        completed_month = 0  # populated by router via separate query

        pct = lambda n: f"{round(n / total * 100, 1)}%" if total else "0%"

        return {
            "total_transformers":  total,
            "tests_due_30_days":   due_30,
            "tests_due_pct":       pct(due_30),
            "overdue_tests":       overdue,
            "overdue_pct":         pct(overdue),
            "critical_alert":      critical_alert,
            "critical_pct":        pct(critical_alert),
            "completed_this_month": completed_month,
            "completed_pct":       "—",
        }

    def _empty_kpis(self) -> dict:
        return {
            "total_transformers": 0,
            "tests_due_30_days": 0, "tests_due_pct": "0%",
            "overdue_tests": 0, "overdue_pct": "0%",
            "critical_alert": 0, "critical_pct": "0%",
            "completed_this_month": 0, "completed_pct": "—",
        }

    # ─────────────────────────────────────────────────────────────
    # Public — org-level schedules (equipment_id = NULL)
    # ─────────────────────────────────────────────────────────────

    def get_org_schedules(
        self,
        org_id: UUID,
        department_id: Optional[UUID] = None,
    ) -> dict:
        """
        Returns active schedules that are not linked to a specific equipment
        (equipment_id IS NULL). These are org-level / site-level schedules
        such as TA&QC Inspection.
        """
        q = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.organization_id == org_id,
                TestRequestSchedule.equipment_id.is_(None),
                TestRequestSchedule.is_active.is_(True),
                TestRequestSchedule.is_deleted.is_(False),
            )
        )
        if department_id:
            q = q.filter(TestRequestSchedule.department_id == department_id)

        schedules = q.order_by(TestRequestSchedule.next_run_date).all()

        # Load test type names
        tt_ids = list({s.test_type_id for s in schedules if s.test_type_id})
        tt_map: dict[int, CategoryDetails] = {}
        if tt_ids:
            tt_map = {
                r.id: r
                for r in self.db.query(CategoryDetails)
                .filter(CategoryDetails.id.in_(tt_ids))
                .all()
            }

        # Load department names
        dept_ids = list({s.department_id for s in schedules if s.department_id})
        dept_map: dict = {}
        if dept_ids:
            dept_map = {
                d.id: d
                for d in self.db.query(OrgDepartment)
                .filter(OrgDepartment.id.in_(dept_ids))
                .all()
            }

        items = []
        for s in schedules:
            next_run = s.next_run_date
            if next_run:
                next_date = next_run.date() if isinstance(next_run, datetime) else next_run
                days = (next_date - self._today).days
            else:
                next_date = None
                days = None

            status = _cell_status(days)
            tt   = tt_map.get(s.test_type_id)
            dept = dept_map.get(s.department_id) if s.department_id else None

            items.append({
                "schedule_id":      str(s.id),
                "title":            s.title,
                "test_type":        tt.name if tt else None,
                "department":       dept.name if dept else None,
                "frequency":        s.frequency.value if s.frequency else None,
                "next_due":         next_date.isoformat() if next_date else None,
                "days_until_due":   days,
                "status":           status,
                "request_category": s.request_category.value if s.request_category else None,
            })

        return {"items": items, "total": len(items)}
