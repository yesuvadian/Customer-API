from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, text
from models import TestResult
from datetime import datetime, timedelta

from models import (
    TestingRequest, TestingRequestStatus, User,
    CategoryMaster, CategoryDetails,
    Organization, OrgDepartment,
    Role, UserRole, TesterLocation,
    OrgRole, OrgUserRole,
    OrgTestTemplate,
    Equipment,
    TrWfStageRole,
    TrWfInstance,
    TrWfStatus,
)
from utils.common_service import UTCDateTimeMixin, get_dept_subtree_ids, get_user_dept_scope

# Legacy TestingRequestStatus enum -> display label/color, used to label
# get_breakdown() buckets for requests that never entered the tr_wf_* engine
# (current_status_code is NULL). Mirrors the color choices already used by
# the Flutter _statusColor() switch in testing_requests_screen.dart.
_LEGACY_STATUS_CATALOG = {
    "draft":                  {"label": "Draft",                  "color": "#9CA3AF"},
    "submitted":               {"label": "Submitted",              "color": "#3FA9F5"},
    "pending_approval":        {"label": "Pending Approval",       "color": "#7C3AED"},
    "assigned":                {"label": "Assigned",               "color": "#0891B2"},
    "accepted":                {"label": "Accepted",               "color": "#0F766E"},
    "scheduled":                {"label": "Scheduled",              "color": "#0891B2"},
    "in_progress":              {"label": "In Progress",            "color": "#F59E0B"},
    "test_submitted":           {"label": "Test Submitted",         "color": "#EA580C"},
    "under_approval":           {"label": "Under Approval",         "color": "#7C3AED"},
    "approved":                 {"label": "Approved",               "color": "#16A34A"},
    "rejected":                 {"label": "Rejected",               "color": "#EF4444"},
    "procurement_initiated":    {"label": "Procurement Initiated",  "color": "#38BDF8"},
    "completed":                {"label": "Completed",              "color": "#16A34A"},
    "under_review":             {"label": "Under Review",           "color": "#EA580C"},
    "finance_pending":          {"label": "Finance Pending",        "color": "#38BDF8"},
    "outcome_active":           {"label": "Outcome Active",         "color": "#16A34A"},
    "commissioned":             {"label": "Commissioned",           "color": "#0F766E"},
    "closed":                   {"label": "Closed",                 "color": "#6B7280"},
    "pending_assignment":       {"label": "Pending Assignment",     "color": "#0891B2"},
}


class TestingRequestService:

    def __init__(self, db: Session):
        self.db = db

    def _generate_request_number(self, org_id=None, prefix: str = "TR") -> str:
        year = UTCDateTimeMixin._utc_now().strftime("%Y")
        org_prefix = self._get_org_prefix(org_id)
        pattern = f"{prefix}-{org_prefix}-{year}-%"
        # Use MAX of existing suffix instead of COUNT so that manually deleted
        # rows don't cause the next insert to collide on the unique constraint.
        from sqlalchemy import cast, Integer
        rows = (
            self.db.query(TestingRequest.request_number)
            .filter(
                TestingRequest.organization_id == org_id,
                TestingRequest.request_number.like(pattern),
            )
            .all()
        )
        max_seq = 0
        for (rn,) in rows:
            try:
                seq = int(rn.rsplit("-", 1)[-1])
                if seq > max_seq:
                    max_seq = seq
            except (ValueError, AttributeError):
                pass
        return f"{prefix}-{org_prefix}-{year}-{(max_seq + 1):04d}"

    def _get_org_prefix(self, org_id) -> str:
        if not org_id:
            return "XX"
        org = self.db.query(Organization).filter(Organization.id == org_id).first()
        if org and org.code:
            return org.code[:2].upper()
        return "XX"

    def _resolve_is_cumulative(self, test_type_id) -> bool:
        """
        Return True if the template has enable_cumulative=true OR a CUMULATIVE_DIFF rule.
        Checks DB OrgTestTemplate first, then falls back to test_templates.py static dict
        (used by equipment-specific templates like circuit_breaker_operations, oltc_operations).
        """
        if not test_type_id:
            return False

        def _has_cumulative(data: dict) -> bool:
            if data.get("enable_cumulative"):
                return True
            return any(
                (r.get("type") or "").upper() == "CUMULATIVE_DIFF"
                for r in data.get("rules", [])
            )

        tpl = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.test_type_id == test_type_id)
            .order_by(OrgTestTemplate.version.desc())
            .first()
        )
        if tpl and _has_cumulative(tpl.template_data or {}):
            return True

        # Fall back to test_templates.py static dict via test type name
        try:
            from test_templates import TEST_TYPE_TO_TEMPLATE, get_template_by_key
            detail = self.db.query(CategoryDetails).filter(CategoryDetails.id == test_type_id).first()
            if detail:
                tmpl_key = TEST_TYPE_TO_TEMPLATE.get(detail.name)
                if tmpl_key:
                    static_tpl = get_template_by_key(tmpl_key)
                    if static_tpl and _has_cumulative(static_tpl):
                        return True
        except Exception:
            pass

        return False

    def _resolve_is_multi_session(self, test_type_id) -> tuple:
        """
        Return (is_multi_session, total_sessions_planned, session_interval_days)
        from template's supports_multi_session / typical_total_sessions /
        typical_session_interval_days. Same pattern as _resolve_is_cumulative().
        """
        if not test_type_id:
            return False, None, None
        tpl = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.test_type_id == test_type_id)
            .order_by(OrgTestTemplate.version.desc())
            .first()
        )
        if not tpl:
            return False, None, None
        data = tpl.template_data or {}
        if data.get("supports_multi_session") or data.get("multi_session"):
            session_types = data.get("session_types") or []
            # Derive total from session_types length; fall back to explicit value
            total = len(session_types) if session_types else data.get("typical_total_sessions")
            return (
                True,
                total,
                data.get("typical_session_interval_days"),
            )
        return False, None, None

    def _resolve_is_calibration(self, test_type_id) -> bool:
        """
        Return True if the template has enable_calibration=true OR a DATE_ADD rule.
        Covers both legacy flag-based templates and rule-driven templates.
        """
        if not test_type_id:
            return False
        tpl = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.test_type_id == test_type_id)
            .order_by(OrgTestTemplate.version.desc())
            .first()
        )
        if not tpl:
            return False
        data = tpl.template_data or {}
        if data.get("enable_calibration"):
            return True
        return any(
            (r.get("type") or "").upper() == "DATE_ADD"
            for r in data.get("rules", [])
        )

    def create_request(self, data: dict, originator_id: UUID) -> TestingRequest:
        request_number = self._generate_request_number(org_id=data.get("organization_id"))
        test_type_id = data.get("test_type_id")
        is_cumulative = self._resolve_is_cumulative(test_type_id)
        is_calibration = self._resolve_is_calibration(test_type_id)
        _tpl_multi, _tpl_sessions, _tpl_interval = self._resolve_is_multi_session(test_type_id)
        # Template-derived values; explicit payload values override if provided
        _is_multi = data.get("is_multi_session") or _tpl_multi
        _total    = data.get("total_sessions_planned") or _tpl_sessions
        _interval = data.get("session_interval_days") or _tpl_interval
        request = TestingRequest(
            request_number=request_number,
            title=data["title"],
            description=data.get("description"),
            transformer_type=data.get("transformer_type"),
            transformer_rating=data.get("transformer_rating"),
            manufacturer=data.get("manufacturer"),
            serial_number=data.get("serial_number"),
            equipment_type_id=data.get("equipment_type_id"),
            test_type_id=test_type_id,
            equipment_id=data.get("equipment_id"),
            request_category=data.get("request_category", "test"),
            organization_id=data.get("organization_id"),
            department_id=data.get("department_id"),
            zone=data.get("zone"),
            ce_circle=data.get("ce_circle"),
            se_division=data.get("se_division"),
            ee_subdivision=data.get("ee_subdivision"),
            aee_section=data.get("aee_section"),
            ae_je=data.get("ae_je"),
            assigned_tester_id=data.get("assigned_tester_id"),
            priority=data.get("priority", "normal"),
            requested_date=data.get("requested_date"),
            due_date=data.get("due_date"),
            scheduled_start_date=data.get("scheduled_start_date"),
            notes=data.get("notes"),
            status=TestingRequestStatus.draft,
            originator_id=originator_id,
            created_by=originator_id,
            is_multi_session=bool(_is_multi),
            total_sessions_planned=_total,
            session_interval_days=_interval,
            is_cumulative=is_cumulative,
            is_calibration=is_calibration,
            is_schedule_template=data.get("is_schedule_template", False),
            source_schedule_id=data.get("source_schedule_id"),
            surveillance_workflow_id=data.get("surveillance_workflow_id"),
            surveillance_quarter=data.get("surveillance_quarter"),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def get_request(self, request_id: UUID) -> TestingRequest:
        request = self.db.query(TestingRequest).filter(
    TestingRequest.id == request_id,
    TestingRequest.is_schedule_template.is_(False),
).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")
        return request

    @staticmethod
    def _capacity_label(equipment) -> str:
        if not equipment:
            return "Unknown"
        data = equipment.nameplate_data or {}
        value = (
            data.get("rated_mva")
            or data.get("rated_mva_onan")
            or data.get("capacity_mva")
            or data.get("mva_rating")
            or data.get("rated_capacity")
            or data.get("capacity")
            or data.get("kva_rating")
        )
        if value is None or str(value).strip() == "":
            return "Unknown"
        return str(value).strip()

    def _base_request_query(
        self,
        status_filter: Optional[str] = None,
        is_closed: Optional[bool] = None,
        wf_active: Optional[bool] = None,
        category_filter: Optional[str] = None,
        originator_id: Optional[UUID] = None,
        tester_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        department_ids: Optional[List[UUID]] = None,
        equipment_id: Optional[UUID] = None,
        date_from=None,
        date_to=None,
        search: Optional[str] = None,
        voltage_class: Optional[str] = None,
        equipment_type: Optional[str] = None,
        make: Optional[str] = None,
        commissioned_year: Optional[str] = None,
        failure_year: Optional[str] = None,
        capacity_mva: Optional[str] = None,
    ):
        query = (
            self.db.query(TestingRequest)
            .outerjoin(Equipment, TestingRequest.equipment_id == Equipment.id)
            .outerjoin(CategoryMaster, Equipment.equipment_type_id == CategoryMaster.id)
            .filter(TestingRequest.is_schedule_template.is_(False))
        )

        if search:
            term = f"%{search.strip()}%"
            query = query.filter(
                (Equipment.ueic.ilike(term)) |
                (Equipment.bay_number.ilike(term)) |
                (TestingRequest.request_number.ilike(term)) |
                (TestingRequest.title.ilike(term))
            )
                
        if status_filter:
            if status_filter == "open":
                query = query.filter(
                    TestingRequest.status.in_([
                        TestingRequestStatus.draft,
                        TestingRequestStatus.submitted,
                        TestingRequestStatus.assigned,
                        TestingRequestStatus.accepted,
                        TestingRequestStatus.in_progress,
                        TestingRequestStatus.under_approval,
                        TestingRequestStatus.outcome_active,   # <-- add this
                    ])
                )

            elif status_filter in ("closed", "wf_completed"):
                completed_wf_ids = (
                    self.db.query(TRWorkflowInstance.request_id)
                    .filter(TRWorkflowInstance.status == WorkflowInstanceStatus.COMPLETED)
                    .subquery()
                )

                query = query.filter(
                    or_(
                        TestingRequest.status.in_([
                            TestingRequestStatus.closed,
                            TestingRequestStatus.completed,
                            TestingRequestStatus.approved,
                            TestingRequestStatus.rejected,
                        ]),
                        TestingRequest.id.in_(completed_wf_ids),
                    )
                )

            elif status_filter == "rejected":
                query = query.filter(
                    TestingRequest.status == TestingRequestStatus.rejected
                )

            # Direct status codes — either a legacy TestingRequestStatus enum
            # value, or a live tr_wf_* stage code (current_status_code). The
            # two code spaces never overlap, so matching either is safe.
            else:
                statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
                _closed_like = {"completed", "closed", "approved", "rejected"}
                _include_wf = bool(_closed_like.intersection(set(statuses)))

                def _status_conditions(tokens):
                    conds = [TestingRequest.current_status_code.in_(tokens)]
                    enum_vals = []
                    for t in tokens:
                        try:
                            enum_vals.append(TestingRequestStatus(t))
                        except ValueError:
                            pass
                    if enum_vals:
                        conds.append(TestingRequest.status.in_(enum_vals))
                    return or_(*conds)

                if _include_wf:
                    completed_wf_ids = self.db.query(TrWfInstance.testing_request_id).filter(
                        TrWfInstance.status.in_(["completed", "terminated"])
                    ).scalar_subquery()
                    query = query.filter(
                        or_(
                            _status_conditions(statuses),
                            TestingRequest.id.in_(completed_wf_ids),
                        )
                    )
                elif statuses:
                    query = query.filter(_status_conditions(statuses))
        if is_closed is not None:
            _LEGACY_CLOSED_STATUSES = [
                TestingRequestStatus.approved,
                TestingRequestStatus.completed,
                TestingRequestStatus.closed,
                TestingRequestStatus.rejected,
            ]
            wf_done_ids = self.db.query(TrWfInstance.testing_request_id).filter(
                TrWfInstance.status.in_(["completed", "terminated"])
            ).scalar_subquery()
            if is_closed:
                query = query.filter(
                    or_(
                        TestingRequest.status.in_(_LEGACY_CLOSED_STATUSES),
                        TestingRequest.id.in_(wf_done_ids),
                    )
                )
            else:
                query = query.filter(
                    TestingRequest.status.notin_(_LEGACY_CLOSED_STATUSES),
                    TestingRequest.id.notin_(wf_done_ids),
                )

        if wf_active is not None:
            active_wf_ids = self.db.query(TrWfInstance.testing_request_id).filter(
                TrWfInstance.status == "active"
            ).scalar_subquery()
            if wf_active:
                query = query.filter(TestingRequest.id.in_(active_wf_ids))
            else:
                query = query.filter(TestingRequest.id.notin_(active_wf_ids))

        if category_filter:
            query = query.filter(TestingRequest.request_category == category_filter)
        else:
            # Exclude direct submissions (failure_registry, taqc_inspection) from
            # the general TR list — they have their own /direct-submissions endpoint.
            from models import RequestCategory as RC
            query = query.filter(
                TestingRequest.is_direct_submission.is_not(True)
            )
        if originator_id:
            query = query.filter(TestingRequest.originator_id == originator_id)
        if tester_id:
            query = query.filter(TestingRequest.assigned_tester_id == tester_id)
        if organization_id:
            query = query.filter(TestingRequest.organization_id == organization_id)
        if equipment_id:
            query = query.filter(TestingRequest.equipment_id == equipment_id)
        if department_ids is not None:
            query = query.filter(TestingRequest.department_id.in_(department_ids))
        elif department_id:
            query = query.filter(TestingRequest.department_id == department_id)

        if date_from or date_to:

            # All tab -> use tested_at
            if is_closed is None:

                subquery = self.db.query(TestResult.testing_request_id)

                if date_from:
                    subquery = subquery.filter(
                        TestResult.tested_at >= datetime.combine(
                            date_from,
                            datetime.min.time(),
                        )
                    )

                if date_to:
                    subquery = subquery.filter(
                        TestResult.tested_at <
                        datetime.combine(
                            date_to + timedelta(days=1),
                            datetime.min.time(),
                        )
                    )

                query = query.filter(
                    TestingRequest.id.in_(subquery.subquery())
                )

            # Open / Assigned / Overdue -> use CTS
            else:

                if date_from:
                    query = query.filter(
                        TestingRequest.cts >= datetime.combine(
                            date_from,
                            datetime.min.time(),
                        )
                    )

                if date_to:
                    query = query.filter(
                        TestingRequest.cts <
                        datetime.combine(
                            date_to + timedelta(days=1),
                            datetime.min.time(),
                        )
                    )

        if voltage_class:
            if voltage_class == "Unknown":
                query = query.filter(
                    or_(
                        Equipment.voltage_class.is_(None),
                        Equipment.voltage_class == "",
                    )
                )
            else:
                query = query.filter(Equipment.voltage_class == voltage_class)

        if equipment_type:
            if equipment_type == "Unknown":
                query = query.filter(CategoryMaster.name.is_(None))
            else:
                query = query.filter(CategoryMaster.name == equipment_type)

        if make:
            if make == "Unknown":
                query = query.filter(
                    or_(
                        Equipment.manufacturer.is_(None),
                        Equipment.manufacturer == "",
                    )
                )
            else:
                query = query.filter(Equipment.manufacturer == make)

        if commissioned_year:
            if commissioned_year == "Unknown":
                query = query.filter(Equipment.commissioned_date.is_(None))
            else:
                try:
                    query = query.filter(
                        func.extract("year", Equipment.commissioned_date)
                        == int(commissioned_year)
                    )
                except ValueError:
                    query = query.filter(TestingRequest.id.is_(None))

        if failure_year:
            if failure_year == "Unknown":
                query = query.filter(Equipment.retired_date.is_(None))
            else:
                try:
                    query = query.filter(
                        func.extract("year", Equipment.retired_date)
                        == int(failure_year)
                    )
                except ValueError:
                    query = query.filter(TestingRequest.id.is_(None))

        if capacity_mva:
            equipment_rows = (
                self.db.query(Equipment)
                .filter(Equipment.id.isnot(None))
                .all()
            )

            matching_ids = [
                equipment.id
                for equipment in equipment_rows
                if self._capacity_label(equipment) == capacity_mva
            ]

            if matching_ids and capacity_mva == "Unknown":
                query = query.filter(
                    or_(
                        TestingRequest.equipment_id.in_(matching_ids),
                        TestingRequest.equipment_id.is_(None),
                    )
                )
            elif matching_ids:
                query = query.filter(
                    TestingRequest.equipment_id.in_(matching_ids)
                )
            elif capacity_mva == "Unknown":
                query = query.filter(
                    TestingRequest.equipment_id.is_(None)
                )
            else:
                query = query.filter(
                    TestingRequest.id.is_(None)
                )

        return query

    def get_requests(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
        is_closed: Optional[bool] = None,
        wf_active: Optional[bool] = None,
        category_filter: Optional[str] = None,
        originator_id: Optional[UUID] = None,
        tester_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        department_ids: Optional[List[UUID]] = None,  # subtree list (overrides department_id)
        equipment_id: Optional[UUID] = None,
        date_from=None,
        date_to=None,
        search: Optional[str] = None,
        voltage_class: Optional[str] = None,
        equipment_type: Optional[str] = None,
        make: Optional[str] = None,
        commissioned_year: Optional[str] = None,
        failure_year: Optional[str] = None,
        capacity_mva: Optional[str] = None,
    ) -> List[TestingRequest]:
        query = self._base_request_query(
            status_filter=status_filter,
            is_closed=is_closed,
            wf_active=wf_active,
            category_filter=category_filter,
            originator_id=originator_id,
            tester_id=tester_id,
            organization_id=organization_id,
            department_id=department_id,
            department_ids=department_ids,
            equipment_id=equipment_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
            voltage_class=voltage_class,
            equipment_type=equipment_type,
            make=make,
            commissioned_year=commissioned_year,
            failure_year=failure_year,
            capacity_mva=capacity_mva,
        )
        return query.order_by(TestingRequest.cts.desc()).offset(skip).limit(limit).all()

    def count_requests(
        self,
        status_filter: Optional[str] = None,
        is_closed: Optional[bool] = None,
        wf_active: Optional[bool] = None,
        category_filter: Optional[str] = None,
        originator_id: Optional[UUID] = None,
        tester_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        department_ids: Optional[List[UUID]] = None,
        equipment_id: Optional[UUID] = None,
        date_from=None,
        date_to=None,
        search: Optional[str] = None,
        voltage_class: Optional[str] = None,
        equipment_type: Optional[str] = None,
        make: Optional[str] = None,
        commissioned_year: Optional[str] = None,
        failure_year: Optional[str] = None,
        capacity_mva: Optional[str] = None,
        **_ignored,
    ) -> int:
        query = self._base_request_query(
            status_filter=status_filter,
            is_closed=is_closed,
            wf_active=wf_active,
            category_filter=category_filter,
            originator_id=originator_id,
            tester_id=tester_id,
            organization_id=organization_id,
            department_id=department_id,
            department_ids=department_ids,
            equipment_id=equipment_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
            voltage_class=voltage_class,
            equipment_type=equipment_type,
            make=make,
            commissioned_year=commissioned_year,
            failure_year=failure_year,
            capacity_mva=capacity_mva,
        )
        return query.with_entities(func.count(TestingRequest.id)).scalar() or 0

    def get_breakdown(
        self,
        status_filter: Optional[str] = None,
        is_closed: Optional[bool] = None,
        category_filter: Optional[str] = None,
        originator_id: Optional[UUID] = None,
        tester_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        department_ids: Optional[List[UUID]] = None,
        equipment_id: Optional[UUID] = None,
        date_from=None,
        date_to=None,
        search: Optional[str] = None,
    ) -> dict:
        query = self._base_request_query(
            status_filter=status_filter,
            is_closed=is_closed,
            category_filter=category_filter,
            originator_id=originator_id,
            tester_id=tester_id,
            organization_id=organization_id,
            department_id=department_id,
            department_ids=department_ids,
            equipment_id=equipment_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )
        requests = query.all()

        eq_ids = {r.equipment_id for r in requests if r.equipment_id}
        equipment_map = {
            e.id: e
            for e in self.db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all()
        } if eq_ids else {}

        type_ids = {e.equipment_type_id for e in equipment_map.values() if e.equipment_type_id}
        type_map = {
            c.id: c.name
            for c in self.db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
        } if type_ids else {}

        # Workflow status catalog (label/color/sequence per status_code), for
        # requests whose effective status is a tr_wf_* stage rather than the
        # legacy enum. Small table — one query covers every org's definitions.
        wf_status_catalog = {
            s.status_code: {"label": s.status_name, "color": s.color, "sequence": s.sequence}
            for s in self.db.query(TrWfStatus).all()
        }

        by_voltage = {}
        by_type = {}
        by_make = {}
        by_year = {}
        by_failure_year = {}
        by_capacity = {}
        by_status_count = {}
        by_category = {}

        def _inc(bucket: dict, key: str):
            bucket[key] = bucket.get(key, 0) + 1

        for req in requests:
            eq = equipment_map.get(req.equipment_id)
            # Effective status: live tr_wf_* stage code if the request has
            # ever entered the workflow engine, else the legacy enum value.
            # current_status_code is denormalized/kept in sync on every stage
            # transition by TrWorkflowRoutingService.
            effective_status = req.current_status_code or (
                getattr(req.status, "value", str(req.status)) if req.status else "unknown"
            )
            _inc(by_status_count, effective_status)
            _inc(by_category, getattr(req.request_category, "value", str(req.request_category)) if req.request_category else "Unknown")
            _inc(by_voltage, (eq.voltage_class or "").strip() if eq and eq.voltage_class else "Unknown")
            _inc(by_type, type_map.get(eq.equipment_type_id) if eq and eq.equipment_type_id else "Unknown")
            _inc(by_make, (eq.manufacturer or "").strip() if eq and eq.manufacturer else "Unknown")
            _inc(by_year, str(eq.commissioned_date.year) if eq and eq.commissioned_date else "Unknown")
            _inc(by_failure_year, str(eq.retired_date.year) if eq and eq.retired_date else "Unknown")
            _inc(by_capacity, self._capacity_label(eq))

        def _sort_count(d: dict) -> dict:
            return dict(sorted(d.items(), key=lambda item: (-item[1], item[0])))

        def _status_bucket(counts: dict) -> dict:
            """Attach label/color/sequence to each status code, wf catalog
            first (live workflow stage), then legacy catalog, then a
            best-effort fallback — so every code is always labeled."""
            out = {}
            for code, count in counts.items():
                meta = wf_status_catalog.get(code) or _LEGACY_STATUS_CATALOG.get(code)
                if meta:
                    label, color, sequence = meta.get("label", code), meta.get("color"), meta.get("sequence", 999)
                else:
                    label, color, sequence = code.replace("_", " ").title(), None, 999
                out[code] = {"count": count, "label": label, "color": color, "sequence": sequence}
            return dict(sorted(out.items(), key=lambda kv: (kv[1]["sequence"], -kv[1]["count"], kv[0])))

        return {
            "total": len(requests),
            "by_voltage_class": _sort_count(by_voltage),
            "by_type": _sort_count(by_type),
            "by_make": _sort_count(by_make),
            "by_commissioned_year": dict(sorted(by_year.items())),
            "by_failure_year": dict(sorted(by_failure_year.items())),
            "by_capacity_mva": _sort_count(by_capacity),
            "by_status": _status_bucket(by_status_count),
            "by_category": _sort_count(by_category),
        }

    def get_requests_for_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
    ) -> List[TestingRequest]:
        """Return requests where user is originator OR assigned tester."""

        query = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.is_schedule_template.is_(False))
            .filter(
                or_(
                    TestingRequest.originator_id == user_id,
                    TestingRequest.assigned_tester_id == user_id,
                )
            )
        )

        if status_filter:
            if status_filter == "open":
                query = query.filter(
                    TestingRequest.status.in_([
                        TestingRequestStatus.draft,
                        TestingRequestStatus.submitted,
                        TestingRequestStatus.assigned,
                        TestingRequestStatus.accepted,
                        TestingRequestStatus.in_progress,
                        TestingRequestStatus.under_approval,
                        TestingRequestStatus.outcome_active,   # <-- add this
                    ])
                )

            elif status_filter == "closed":
                completed_wf_ids2 = self.db.query(TrWfInstance.testing_request_id).filter(
                    TrWfInstance.status.in_(["completed", "terminated"])
                ).scalar_subquery()
                query = query.filter(
                    or_(
                        TestingRequest.status.in_([
                            TestingRequestStatus.closed,
                            TestingRequestStatus.completed,
                            TestingRequestStatus.approved,
                            TestingRequestStatus.rejected,
                        ]),
                        TestingRequest.id.in_(completed_wf_ids2),
                    )
                )

            elif status_filter == "rejected":
                query = query.filter(
                    TestingRequest.status == TestingRequestStatus.rejected
                )

            else:
                try:
                    query = query.filter(
                        TestingRequest.status == TestingRequestStatus(status_filter)
                    )
                except ValueError:
                    # Unknown status - return no records
                    query = query.filter(False)

        return (
            query.order_by(TestingRequest.cts.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def user_has_tr_wf_approver_role(self, user_id: UUID, organization_id: UUID) -> bool:
        """Return True if the user holds any org role that has can_approve on any TR workflow stage."""
        user_role_ids = [
            r.org_role_id for r in
            self.db.query(OrgUserRole.org_role_id)
            .filter(OrgUserRole.user_id == user_id)
            .all()
        ]
        if not user_role_ids:
            return False
        count = (
            self.db.query(func.count(TrWfStageRole.id))
            .filter(
                TrWfStageRole.role_id.in_(user_role_ids),
                TrWfStageRole.can_approve.is_(True),
            )
            .scalar()
        )
        return (count or 0) > 0

    def update_request(self, request_id: UUID, data: dict, modified_by: UUID) -> TestingRequest:
        request = self.get_request(request_id)
        if request.status != TestingRequestStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft requests can be updated",
            )
        for key, value in data.items():
            if hasattr(request, key) and value is not None:
                setattr(request, key, value)
        request.modified_by = modified_by
        self.db.commit()
        self.db.refresh(request)
        return request

    def delete_request(self, request_id: UUID) -> dict:
        request = self.get_request(request_id)
        if request.status != TestingRequestStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft requests can be deleted",
            )
        self.db.delete(request)
        self.db.commit()
        return {"message": "Testing request deleted successfully"}

    def _user_label(self, user_id) -> str:
        """Resolve a user's friendly display name for notification context."""
        if not user_id:
            return "System"
        u = self.db.query(User).filter(User.id == user_id).first()
        if not u:
            return str(user_id)
        name = " ".join(filter(None, [u.firstname, u.lastname])).strip()
        return name or u.email or str(user_id)

    def submit_request(self, request_id: UUID, modified_by: UUID) -> TestingRequest:
        request = self.get_request(request_id)
        if request.is_schedule_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Template requests cannot be submitted",
            )
        if request.status != TestingRequestStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft requests can be submitted",
            )
        # If tester already assigned during creation, go straight to 'assigned'
        if request.assigned_tester_id:
            request.status = TestingRequestStatus.assigned
            request.assigned_at = UTCDateTimeMixin._utc_now()
        else:
            request.status = TestingRequestStatus.submitted
        request.modified_by = modified_by
        self.db.commit()
        self.db.refresh(request)

        # Instantiate the TR workflow so the L2 approver sees it in their queue
        if request.status == TestingRequestStatus.submitted and not request.wf_instance_id:
            try:
                from services.tr_workflow_routing_service import WorkflowRoutingService
                wf_svc = WorkflowRoutingService(self.db)
                wf_svc.instantiate_workflow(request, performed_by_id=modified_by)
                self.db.commit()
                self.db.refresh(request)
            except Exception as e:
                self.db.rollback()
                import logging
                logging.getLogger(__name__).warning(
                    f"TR workflow instantiation failed for {request.id}: {e}"
                )

        # Trigger notification
        try:
            from services.notification_service import NotificationService
            ns = NotificationService(self.db)
            ns.notify_request_submitted(request)
            # If we jumped straight to 'assigned' (tester was pre-set at creation),
            # also fire the tester-assigned notification.
            if request.status == TestingRequestStatus.assigned:
                ns.notify_tester_assigned(request)
            ns.fire(
                event_type="status_changed",
                context={
                    "request.number": request.request_number or str(request.id),
                    "request.status": request.status.value,
                    "request.title":  getattr(request, "title", "") or "",
                    "status_from":    "draft",
                    "status_to":      request.status.value,
                    "changed_by":     self._user_label(modified_by),
                },
                organization_id=request.organization_id,
                department_id=getattr(request, "department_id", None),
                source_id=request.id,
                source_type="testing_request",
                severity="info",
                workflow_type="testing_request",
                status_from="draft",
                status_to=request.status.value,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Notification failed: {e}")

        return request

    def assign_tester(self, request_id: UUID, tester_id: UUID, assigned_by: UUID) -> TestingRequest:
        request = self.get_request(request_id)
        if request.is_schedule_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Template requests cannot be assigned",
            )
        if request.status != TestingRequestStatus.submitted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only submitted requests can be assigned",
            )
        tester = self.db.query(User).filter(User.id == tester_id).first()
        if not tester:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tester not found")

        request.assigned_tester_id = tester_id
        request.assigned_at = UTCDateTimeMixin._utc_now()
        request.status = TestingRequestStatus.assigned
        request.modified_by = assigned_by
        self.db.commit()
        self.db.refresh(request)

        # Trigger notification
        try:
            from services.notification_service import NotificationService
            ns = NotificationService(self.db)
            ns.notify_tester_assigned(request)
            ns.fire(
                event_type="status_changed",
                context={
                    "request.number": request.request_number or str(request.id),
                    "request.status": request.status.value,
                    "request.title":  getattr(request, "title", "") or "",
                    "status_from":    "submitted",
                    "status_to":      "assigned",
                    "changed_by":     self._user_label(assigned_by),
                },
                organization_id=request.organization_id,
                department_id=getattr(request, "department_id", None),
                source_id=request.id,
                source_type="testing_request",
                severity="info",
                workflow_type="testing_request",
                status_from="submitted",
                status_to="assigned",
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Notification failed: {e}")
        return request

    def get_stats(self, user_id: UUID = None, organization_id: UUID = None) -> dict:
        """Return counts by testing request status."""

        query = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.is_schedule_template.is_(False))
        )

        if organization_id:
            query = query.filter(
                TestingRequest.organization_id == organization_id
            )
        elif user_id:
            query = query.filter(
                or_(
                    TestingRequest.originator_id == user_id,
                    TestingRequest.assigned_tester_id == user_id,
                )
            )

        total = query.count()

        draft = query.filter(
            TestingRequest.status == TestingRequestStatus.draft
        ).count()

        submitted = query.filter(
            TestingRequest.status == TestingRequestStatus.submitted
        ).count()

        in_progress = query.filter(
            TestingRequest.status.in_([
                TestingRequestStatus.assigned,
                TestingRequestStatus.accepted,
                TestingRequestStatus.in_progress,
                TestingRequestStatus.outcome_active,
            ])
        ).count()

        under_approval = query.filter(
            TestingRequest.status == TestingRequestStatus.under_approval
        ).count()

        approved = query.filter(
            TestingRequest.status == TestingRequestStatus.approved
        ).count()

        rejected = query.filter(
            TestingRequest.status == TestingRequestStatus.rejected
        ).count()

        completed = query.filter(
            TestingRequest.status.in_([
                TestingRequestStatus.completed,
                TestingRequestStatus.closed,
            ])
        ).count()

        # Category breakdown
        from models import RequestCategory

        by_category = {}
        for cat in RequestCategory:
            by_category[cat.value] = query.filter(
                TestingRequest.request_category == cat.value
            ).count()

        return {
            "total": total,
            "draft": draft,
            "submitted": submitted,
            "in_progress": in_progress,
            "under_approval": under_approval,
            "approved": approved,
            "rejected": rejected,
            "completed": completed,
            "by_category": by_category,
        }

    # NOTE: Tester workflow transitions (accept, start, submit_results)
    # are in services/testing_service.py, used by routers/testing.py.

    # ── Lookup / dropdown helpers ────────────────────────────────────────────
    # All methods below serve router-level GET endpoints.
    # No DB access belongs in the router; call these methods instead.

    def get_department_hierarchy(
        self,
        org_id: Optional[UUID] = None,
        parent_id: Optional[UUID] = None,
        root_id: Optional[UUID] = None,
        category: Optional[str] = None,
    ) -> list:
        """Return organisations (when org_id is None) or departments.

        Used by Flutter location-picker dropdowns.
        """
        if org_id is None:
            orgs = (
                self.db.query(Organization)
                .filter(Organization.is_active.is_(True))
                .order_by(Organization.name)
                .all()
            )
            return [
                {
                    "id": str(o.id),
                    "name": o.name,
                    "code": o.code,
                    "type": "organization",
                }
                for o in orgs
            ]

        q = self.db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == org_id,
            OrgDepartment.is_active.is_(True),
        )

        if root_id is not None:
            q = q.filter(OrgDepartment.id == root_id)
        elif parent_id is None:
            q = q.filter(OrgDepartment.parent_department_id.is_(None))
        else:
            q = q.filter(OrgDepartment.parent_department_id == parent_id)

        depts = q.order_by(OrgDepartment.name).all()

        from models import TestingRequest
        from sqlalchemy import func
        from utils.common_service import get_dept_subtree_ids

        def _depth(dept) -> int:
            d, n = 0, dept
            while n.parent_department_id is not None:
                parent = (
                    self.db.query(OrgDepartment)
                    .filter(OrgDepartment.id == n.parent_department_id)
                    .first()
                )
                if parent is None:
                    break
                d += 1
                n = parent
            return d

        result = []

        for d in depts:
            subtree_ids = get_dept_subtree_ids(self.db, d.id)

            # Build category filter clause
            from models import RequestCategory as RC
            if category:
                try:
                    _cat_filter = [TestingRequest.request_category == RC(category)]
                except ValueError:
                    _cat_filter = []
            else:
                # Default TR view: exclude direct submissions (FR/TAQC)
                _cat_filter = [TestingRequest.is_direct_submission.is_not(True)]

            # Total requests
            request_count = (
                self.db.query(func.count(TestingRequest.id))
                .filter(
                    TestingRequest.department_id.in_(subtree_ids),
                    TestingRequest.is_schedule_template.is_(False),
                    *_cat_filter,
                )
                .scalar()
            ) or 0

            # Open requests
            open_count = (
                self.db.query(func.count(TestingRequest.id))
                .filter(
                    TestingRequest.department_id.in_(subtree_ids),
                    TestingRequest.is_schedule_template.is_(False),
                    *_cat_filter,
                    TestingRequest.status.in_([
                        TestingRequestStatus.draft,
                        TestingRequestStatus.submitted,
                        TestingRequestStatus.assigned,
                        TestingRequestStatus.accepted,
                        TestingRequestStatus.in_progress,
                        TestingRequestStatus.under_approval,
                        TestingRequestStatus.outcome_active,
                    ]),
                )
                .scalar()
            ) or 0

            # Closed requests
            closed_count = (
                self.db.query(func.count(TestingRequest.id))
                .filter(
                    TestingRequest.department_id.in_(subtree_ids),
                    TestingRequest.is_schedule_template.is_(False),
                    *_cat_filter,
                    TestingRequest.status.in_([
                        TestingRequestStatus.approved,
                        TestingRequestStatus.completed,
                        TestingRequestStatus.closed,
                        TestingRequestStatus.rejected,
                    ]),
                )
                .scalar()
            ) or 0
            result.append({
                "id": str(d.id),
                "name": d.name,
                "code": d.code,
                "request_count": request_count,
                "open_count": open_count,
                "closed_count": closed_count,
                "parent_department_id": (
                    str(d.parent_department_id)
                    if d.parent_department_id
                    else None
                ),
                "has_children": (
                    self.db.query(OrgDepartment)
                    .filter(
                        OrgDepartment.parent_department_id == d.id,
                        OrgDepartment.is_active.is_(True),
                    )
                    .count() > 0
                ),
                "type": "department",
                "depth": _depth(d),
            })

        return result

    # Non-equipment masters — same exclusion list as the Flutter Template Designer.
    _NON_EQUIPMENT_MASTERS = {
        "Annual Audit Categories",
        "Calibration Lifecycle",
        "Cumulative Lifecycle",
        "Repair Lifecycle",
        "Inspection Types",
        "Generic",
    }

    def list_equipment_types(self, org_id=None) -> list:
        """Return active CategoryMaster rows that represent real equipment types,
        grouped by their CategoryDetails request category.

        Inclusion rule: any active master whose name is NOT in the non-equipment
        exclusion list AND that either carries description='Testing Equipment' OR
        has at least one active CategoryDetail — so newly created equipment types
        appear here as soon as they have test/maintenance types defined."""
        masters = (
            self.db.query(CategoryMaster)
            .filter(
                CategoryMaster.is_active.is_(True),
                ~CategoryMaster.name.in_(self._NON_EQUIPMENT_MASTERS),
                # Must have description='Testing Equipment' OR have active details
                (
                    (CategoryMaster.description == "Testing Equipment") |
                    CategoryMaster.id.in_(
                        self.db.query(CategoryDetails.category_master_id)
                        .filter(CategoryDetails.is_active.is_(True))
                        .distinct()
                    )
                ),
            )
            .order_by(CategoryMaster.name)
            .all()
        )
        # Build canonical test_type_id → template map: system templates as base,
        # org templates override where the org has customised them.
        # This is the exact same set the Template Designer renders — single source of truth.
        from services.org_test_template_service import OrgTestTemplateService
        canonical: dict[int, OrgTestTemplate] = (
            OrgTestTemplateService(self.db).canonical_templates_for_org(org_id=org_id)
        )

        result = []
        _CAT_ALIAS = {"repair": "repair_lifecycle"}
        for m in masters:
            all_types = (
                self.db.query(CategoryDetails)
                .filter(
                    CategoryDetails.category_master_id == m.id,
                    CategoryDetails.is_active.is_(True),
                )
                .order_by(CategoryDetails.name)
                .all()
            )
            types_by_category: dict = {
                "test": [], "maintenance": [], "inspection": [], "repair_lifecycle": []
            }
            for t in all_types:
                # Only include if Template Designer has a canonical template for this type
                tpl = canonical.get(t.id)
                if tpl is None:
                    continue
                tpl_data = tpl.template_data or {}
                # Skip if toggled inactive in the Designer
                if tpl_data.get("is_active") is False:
                    continue
                raw_cat = t.category_type or "test"
                cat = _CAT_ALIAS.get(raw_cat, raw_cat)
                bucket = types_by_category.get(cat, types_by_category["test"])
                bucket.append({
                    "id": t.id,
                    "name": t.name,
                    "category_type": t.category_type,
                    "enable_cumulative": bool(tpl_data.get("enable_cumulative", False)),
                    "enable_calibration": bool(tpl_data.get("enable_calibration", False)),
                })
            if any(types_by_category[cat] for cat in types_by_category):
                result.append({
                    "id": m.id,
                    "name": m.name,
                    "tests": types_by_category["test"],    # legacy field
                    "types_by_category": types_by_category,
                })
        return result

    def list_all_test_types(self, category: str = None) -> list:
        """Return all CategoryDetails (test types) across ALL equipment types,
        with lifecycle flags resolved from OrgTestTemplate.

        Optionally filtered by category_type (test / maintenance / inspection /
        repair_lifecycle).  Used by the form when no equipment type is selected.
        """
        query = (
            self.db.query(CategoryDetails, CategoryMaster)
            .join(CategoryMaster, CategoryMaster.id == CategoryDetails.category_master_id)
            .filter(
                CategoryMaster.description == "Testing Equipment",
                CategoryMaster.is_active.is_(True),
                CategoryDetails.is_active.is_(True),
                CategoryDetails.category_type != "nameplate",
            )
        )
        if category:
            query = query.filter(CategoryDetails.category_type == category)
        rows = query.order_by(CategoryMaster.name, CategoryDetails.name).all()

        result = []
        for t, m in rows:
            tpl = (
                self.db.query(OrgTestTemplate)
                .filter(OrgTestTemplate.test_type_id == t.id)
                .order_by(OrgTestTemplate.version.desc())
                .first()
            )
            tpl_data = (tpl.template_data or {}) if tpl else {}
            has_date_add = any(
                (r.get("type") or "").upper() == "DATE_ADD"
                for r in tpl_data.get("rules", [])
            )
            has_cumulative = any(
                (r.get("type") or "").upper() == "CUMULATIVE_DIFF"
                for r in tpl_data.get("rules", [])
            )
            result.append({
                "id": t.id,
                "name": t.name,
                "category_type": t.category_type,
                "equipment_type_id": m.id,
                "equipment_type_name": m.name,
                "enable_cumulative": bool(tpl_data.get("enable_cumulative", False)) or has_cumulative,
                "enable_calibration": bool(tpl_data.get("enable_calibration", False)) or has_date_add,
            })
        return result

    def list_lifecycle_types(self) -> dict:
        """Return calibration and cumulative test types from their dedicated masters.

        Used by the request form to reload the test-type dropdown when a
        lifecycle flag (enable_calibration / enable_cumulative) is detected.
        """
        result: dict = {"calibration": [], "cumulative": []}

        mapping = {
            "Calibration Lifecycle": "calibration",
            "Cumulative Lifecycle":  "cumulative",
        }

        for master_name, bucket_key in mapping.items():
            master = (
                self.db.query(CategoryMaster)
                .filter(CategoryMaster.name == master_name)
                .first()
            )
            if not master:
                continue

            details = (
                self.db.query(CategoryDetails)
                .filter(
                    CategoryDetails.category_master_id == master.id,
                    CategoryDetails.is_active.is_(True),
                )
                .order_by(CategoryDetails.name)
                .all()
            )
            for t in details:
                tpl = (
                    self.db.query(OrgTestTemplate)
                    .filter(OrgTestTemplate.test_type_id == t.id)
                    .order_by(OrgTestTemplate.version.desc())
                    .first()
                )
                tpl_data = (tpl.template_data or {}) if tpl else {}
                result[bucket_key].append({
                    "id": t.id,
                    "name": t.name,
                    "category_type": t.category_type,
                    "enable_calibration": bool(tpl_data.get("enable_calibration", False)),
                    "enable_cumulative":  bool(tpl_data.get("enable_cumulative",  False)),
                })

        return result

    def get_dropdown_values(self, master_desc: str) -> list:
        """Return CategoryDetails for the CategoryMaster identified by description."""
        master = (
            self.db.query(CategoryMaster)
            .filter(
                CategoryMaster.description == master_desc,
                CategoryMaster.is_active.is_(True),
            )
            .first()
        )
        if not master:
            return []
        details = (
            self.db.query(CategoryDetails)
            .filter(
                CategoryDetails.category_master_id == master.id,
                CategoryDetails.is_active.is_(True),
            )
            .order_by(CategoryDetails.id)
            .all()
        )
        return [{"id": d.id, "name": d.name} for d in details]

    def list_testers(
        self,
        zone: Optional[str] = None,
        ce_circle: Optional[str] = None,
        se_division: Optional[str] = None,
        ee_subdivision: Optional[str] = None,
    ) -> list:
        """Return active users with the 'Tester' role, optionally filtered by location."""
        tester_role = self.db.query(Role).filter(Role.name == "Tester").first()
        if not tester_role:
            return []

        has_location_filter = any([zone, ce_circle, se_division, ee_subdivision])

        if has_location_filter:
            q = (
                self.db.query(User, TesterLocation)
                .join(UserRole, UserRole.user_id == User.id)
                .join(TesterLocation, TesterLocation.user_id == User.id)
                .filter(
                    UserRole.role_id == tester_role.id,
                    User.isactive.is_(True),
                    TesterLocation.is_active.is_(True),
                )
            )
            if zone:
                q = q.filter(TesterLocation.zone == zone)
            if ce_circle:
                q = q.filter(TesterLocation.ce_circle == ce_circle)
            if se_division:
                q = q.filter(TesterLocation.se_division == se_division)
            if ee_subdivision:
                q = q.filter(TesterLocation.ee_subdivision == ee_subdivision)

            return [
                {
                    "id": str(u.id),
                    "name": f"{u.firstname} {u.lastname}".strip(),
                    "email": u.email,
                    "zone": tl.zone,
                    "ce_circle": tl.ce_circle,
                    "se_division": tl.se_division,
                    "ee_subdivision": tl.ee_subdivision,
                }
                for u, tl in q.order_by(User.firstname).all()
            ]
        else:
            testers = (
                self.db.query(User)
                .join(UserRole, UserRole.user_id == User.id)
                .filter(UserRole.role_id == tester_role.id, User.isactive.is_(True))
                .order_by(User.firstname)
                .all()
            )
            result = []
            for t in testers:
                loc = (
                    self.db.query(TesterLocation)
                    .filter(TesterLocation.user_id == t.id, TesterLocation.is_active.is_(True))
                    .first()
                )
                result.append({
                    "id": str(t.id),
                    "name": f"{t.firstname} {t.lastname}".strip(),
                    "email": t.email,
                    "zone": loc.zone if loc else None,
                    "ce_circle": loc.ce_circle if loc else None,
                    "se_division": loc.se_division if loc else None,
                    "ee_subdivision": loc.ee_subdivision if loc else None,
                })
            return result

    def get_by_equipment(
        self,
        org_id: UUID,
        department_ids: Optional[List[UUID]] = None,
        request_category: Optional[str] = None,
        is_closed: Optional[bool] = None,
        date_from=None,
        date_to=None,
    ) -> List[dict]:
        """Return testing requests grouped by equipment with alert bar status."""
        from datetime import timezone
        from collections import defaultdict

        today = datetime.now(timezone.utc)
        _CLOSED_STATUSES = {
            TestingRequestStatus.closed,
            TestingRequestStatus.completed,
            TestingRequestStatus.approved,
            TestingRequestStatus.rejected,
        }

        query = (
            self.db.query(TestingRequest)
            .outerjoin(Equipment, TestingRequest.equipment_id == Equipment.id)
            .filter(
                TestingRequest.organization_id == org_id,
                TestingRequest.is_schedule_template.is_(False),
                TestingRequest.equipment_id.isnot(None),
            )
        )
        if department_ids:
            query = query.filter(TestingRequest.department_id.in_(department_ids))
        if request_category:
            from models import RequestCategory as RC
            try:
                query = query.filter(TestingRequest.request_category == RC(request_category))
            except ValueError:
                pass
        if is_closed is not None:
            completed_wf_ids = self.db.query(TrWfInstance.testing_request_id).filter(
                TrWfInstance.status.in_(["completed", "terminated"])
            ).scalar_subquery()
            if is_closed:
                query = query.filter(
                    or_(
                        TestingRequest.status.in_(list(_CLOSED_STATUSES)),
                        TestingRequest.id.in_(completed_wf_ids),
                    )
                )
            else:
                query = query.filter(
                    TestingRequest.status.notin_(list(_CLOSED_STATUSES)),
                    TestingRequest.id.notin_(completed_wf_ids),
                )

        all_reqs = query.order_by(TestingRequest.due_date.asc().nullslast()).all()

        # group by equipment
        groups: dict = defaultdict(list)
        for r in all_reqs:
            groups[r.equipment_id].append(r)

        eq_ids = list(groups.keys())
        equipment_map = {
            e.id: e
            for e in self.db.query(Equipment).filter(Equipment.id.in_(eq_ids)).all()
        }
        type_ids = {e.equipment_type_id for e in equipment_map.values() if e.equipment_type_id}
        type_map = {
            c.id: c.name
            for c in self.db.query(CategoryMaster).filter(CategoryMaster.id.in_(type_ids)).all()
        } if type_ids else {}

        # dept path for all unique dept_ids seen
        dept_ids_seen = {r.department_id for r in all_reqs if r.department_id}
        org_ids_seen  = {r.organization_id for r in all_reqs if r.organization_id}
        from models import OrgDepartment
        all_depts = (
            self.db.query(OrgDepartment)
            .filter(OrgDepartment.organization_id.in_(list(org_ids_seen)))
            .all()
        ) if org_ids_seen else []
        dname_map  = {d.id: d.name for d in all_depts}
        dparent_map = {d.id: d.parent_department_id for d in all_depts if d.parent_department_id}

        def _dept_path(dept_id):
            path, visited, cur = [], set(), dept_id
            while cur and cur not in visited:
                visited.add(cur)
                if cur in dname_map:
                    path.append(dname_map[cur])
                cur = dparent_map.get(cur)
            path.reverse()
            return path

        wf_status_catalog = {
            s.status_code: {"label": s.status_name, "color": s.color}
            for s in self.db.query(TrWfStatus).all()
        }

        def _ticket_dict(r: TestingRequest) -> dict:
            eff = r.current_status_code or (
                getattr(r.status, "value", str(r.status)) if r.status else "unknown"
            )
            meta = wf_status_catalog.get(eff) or _LEGACY_STATUS_CATALOG.get(eff) or {}
            due = None
            if r.due_date:
                due = r.due_date if r.due_date.tzinfo else r.due_date.replace(tzinfo=timezone.utc)
            ref = r.assigned_at or r.requested_date
            if ref and not ref.tzinfo:
                ref = ref.replace(tzinfo=timezone.utc)
            days_in_stage = (today - ref).days if ref else 0
            is_overdue = bool(due and due < today and r.status not in _CLOSED_STATUSES)
            is_stuck   = not is_overdue and days_in_stage > 7
            return {
                "id": str(r.id),
                "request_number": r.request_number,
                "title": r.title,
                "status": eff,
                "status_label": meta.get("label", eff.replace("_", " ").title()),
                "status_color": meta.get("color", "#9CA3AF"),
                "due_date": due.isoformat() if due else None,
                "is_overdue": is_overdue,
                "is_stuck": is_stuck,
                "days_in_stage": days_in_stage,
                "is_closed": r.status in _CLOSED_STATUSES,
            }

        result = []
        for eq_id, reqs in groups.items():
            eq = equipment_map.get(eq_id)
            if not eq:
                continue
            open_tickets = [r for r in reqs if r.status not in _CLOSED_STATUSES]
            closed_count = len(reqs) - len(open_tickets)

            def _due_utc(r):
                if not r.due_date:
                    return None
                return r.due_date if r.due_date.tzinfo else r.due_date.replace(tzinfo=timezone.utc)

            overdue = [r for r in open_tickets if _due_utc(r) and _due_utc(r) < today]
            stuck_list = []
            for r in open_tickets:
                if r in overdue:
                    continue
                ref = r.assigned_at or r.requested_date
                if ref:
                    ref_utc = ref if ref.tzinfo else ref.replace(tzinfo=timezone.utc)
                    if (today - ref_utc).days > 7:
                        stuck_list.append(r)

            bar_status = "overdue" if overdue else ("stuck" if stuck_list else "ok")
            preview = sorted(
                open_tickets,
                key=lambda r: (
                    0 if _due_utc(r) and _due_utc(r) < today else 1,
                    _due_utc(r) or datetime(9999, 1, 1, tzinfo=timezone.utc),
                )
            )[:5]
            dept_id = next((r.department_id for r in reqs), None)
            result.append({
                "equipment_id": str(eq_id),
                "equipment_ueic": eq.ueic,
                "equipment_type_name": type_map.get(eq.equipment_type_id) if eq.equipment_type_id else None,
                "bay_number": eq.bay_number,
                "manufacturer": eq.manufacturer,
                "voltage_class": eq.voltage_class,
                "department_path": _dept_path(dept_id) if dept_id else [],
                "open_count": len(open_tickets),
                "overdue_count": len(overdue),
                "stuck_count": len(stuck_list),
                "closed_count": closed_count,
                "bar_status": bar_status,
                "tickets": [_ticket_dict(r) for r in preview],
            })

        result.sort(key=lambda x: (
            {"overdue": 0, "stuck": 1, "ok": 2}[x["bar_status"]],
            -x["overdue_count"],
        ))
        return result

    def get_user_scope(
        self, user_id: UUID, org_id: Optional[UUID]
    ) -> tuple:
        """Return (is_org_admin: bool, department_id: UUID | None).

        Delegates to the shared get_user_dept_scope() utility in
        utils.common_service so the logic is maintained in one place.
        """
        return get_user_dept_scope(self.db, user_id, org_id)
