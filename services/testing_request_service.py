from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, text

from models import (
    TestingRequest, TestingRequestStatus, User,
    CategoryMaster, CategoryDetails,
    Organization, OrgDepartment,
    Role, UserRole, TesterLocation,
    OrgRole, OrgUserRole,
    OrgTestTemplate,
)
from utils.common_service import UTCDateTimeMixin, get_dept_subtree_ids, get_user_dept_scope


class TestingRequestService:

    def __init__(self, db: Session):
        self.db = db

    def _generate_request_number(self) -> str:
        today = UTCDateTimeMixin._utc_now().strftime("%Y%m%d")
        count = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.request_number.like(f"TR-{today}-%"))
            .scalar()
        )
        return f"TR-{today}-{(count + 1):04d}"

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
        request_number = self._generate_request_number()
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

    def get_requests(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        originator_id: Optional[UUID] = None,
        tester_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        department_ids: Optional[List[UUID]] = None,  # subtree list (overrides department_id)
        equipment_id: Optional[UUID] = None,
    ) -> List[TestingRequest]:
        query = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.is_schedule_template.is_(False))
        )
        if status_filter:
            query = query.filter(TestingRequest.status == status_filter)
        if category_filter:
            query = query.filter(TestingRequest.request_category == category_filter)
        if originator_id:
            query = query.filter(TestingRequest.originator_id == originator_id)
        if tester_id:
            query = query.filter(TestingRequest.assigned_tester_id == tester_id)
        if organization_id:
            query = query.filter(TestingRequest.organization_id == organization_id)
        if equipment_id:
            query = query.filter(TestingRequest.equipment_id == equipment_id)
        # department_ids (subtree) takes priority over single department_id
        if department_ids is not None:
            query = query.filter(TestingRequest.department_id.in_(department_ids))
        elif department_id:
            query = query.filter(TestingRequest.department_id == department_id)
        return query.order_by(TestingRequest.cts.desc()).offset(skip).limit(limit).all()

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
            query = query.filter(TestingRequest.status == status_filter)
        return query.order_by(TestingRequest.cts.desc()).offset(skip).limit(limit).all()

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

        # Trigger notification
        try:
            from services.notification_service import NotificationService
            ns = NotificationService(self.db)
            ns.notify_request_submitted(request)
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
            query = query.filter(TestingRequest.organization_id == organization_id)
        elif user_id:
            # Fallback for backward compatibility
            query = query.filter(
                or_(
                    TestingRequest.originator_id == user_id,
                    TestingRequest.assigned_tester_id == user_id,
                )
            )
        total = query.count()
        draft = query.filter(TestingRequest.status == TestingRequestStatus.draft).count()
        submitted = query.filter(TestingRequest.status == TestingRequestStatus.submitted).count()
        in_progress = query.filter(
            TestingRequest.status.in_([
                TestingRequestStatus.assigned,
                TestingRequestStatus.accepted,
                TestingRequestStatus.in_progress,
            ])
        ).count()
        under_approval = query.filter(TestingRequest.status == TestingRequestStatus.under_approval).count()
        approved = query.filter(TestingRequest.status == TestingRequestStatus.approved).count()
        rejected = query.filter(TestingRequest.status == TestingRequestStatus.rejected).count()
        completed = query.filter(TestingRequest.status == TestingRequestStatus.completed).count()
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
                {"id": str(o.id), "name": o.name, "code": o.code, "type": "organization"}
                for o in orgs
            ]

        q = self.db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == org_id,
            OrgDepartment.is_active.is_(True),
        )
        q = (
            q.filter(OrgDepartment.parent_department_id.is_(None))
            if parent_id is None
            else q.filter(OrgDepartment.parent_department_id == parent_id)
        )
        depts = q.order_by(OrgDepartment.name).all()
        return [
            {
                "id": str(d.id),
                "name": d.name,
                "code": d.code,
                "parent_department_id": str(d.parent_department_id) if d.parent_department_id else None,
                "has_children": self.db.query(OrgDepartment)
                    .filter(
                        OrgDepartment.parent_department_id == d.id,
                        OrgDepartment.is_active.is_(True),
                    )
                    .count() > 0,
                "type": "department",
            }
            for d in depts
        ]

    def list_equipment_types(self) -> list:
        """Return CategoryMaster rows where description='Testing Equipment'
        with their CategoryDetails grouped by request category."""
        masters = (
            self.db.query(CategoryMaster)
            .filter(
                CategoryMaster.description == "Testing Equipment",
                CategoryMaster.is_active.is_(True),
            )
            .order_by(CategoryMaster.name)
            .all()
        )
        result = []
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
                cat = t.category_type or "test"
                bucket = types_by_category.get(cat, types_by_category["test"])
                # Look up linked OrgTestTemplate to expose lifecycle flags
                tpl = (
                    self.db.query(OrgTestTemplate)
                    .filter(OrgTestTemplate.test_type_id == t.id)
                    .order_by(OrgTestTemplate.version.desc())
                    .first()
                )
                tpl_data = (tpl.template_data or {}) if tpl else {}
                bucket.append({
                    "id": t.id,
                    "name": t.name,
                    "category_type": t.category_type,
                    "enable_cumulative": bool(tpl_data.get("enable_cumulative", False)),
                    "enable_calibration": bool(tpl_data.get("enable_calibration", False)),
                })
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

    def get_user_scope(
        self, user_id: UUID, org_id: Optional[UUID]
    ) -> tuple:
        """Return (is_org_admin: bool, department_id: UUID | None).

        Delegates to the shared get_user_dept_scope() utility in
        utils.common_service so the logic is maintained in one place.
        """
        return get_user_dept_scope(self.db, user_id, org_id)
