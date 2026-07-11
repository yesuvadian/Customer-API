import logging
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models import TestingRequest, TestingRequestStatus, TestResult, TestResultImage, CategoryDetails, Recommendation, RecommendationType, TestSession
from utils.common_service import UTCDateTimeMixin

logger = logging.getLogger(__name__)


def _resolve_baseline_result(db, request_id, template_key, current_session, tpl_data):
    """
    Resolve the baseline TestResult for cross-session comparison.

    Reads baseline.strategy from the first enabled cross_session_evaluation field
    in the template. Strategies:
      named_session    — fetch by session_name == baseline.session_name
      previous_session — fetch session_number == current - 1
      first_session    — fetch session_number == 1

    Returns None when:
      - No cross_session_evaluation fields found
      - Current session IS the baseline (skip comparison)
      - No prior result exists yet
    """
    from models import TestResult, TestSession

    # Find the first baseline config from template fields
    baseline_cfg: dict = {}
    for sec in tpl_data.get("sections", []):
        for fld in sec.get("fields", []):
            cs = fld.get("cross_session_evaluation") or {}
            if cs.get("enabled") and cs.get("baseline"):
                baseline_cfg = cs["baseline"]
                break
        if baseline_cfg:
            break

    if not baseline_cfg:
        return None

    strategy = baseline_cfg.get("strategy", "named_session")

    if strategy == "named_session":
        name = baseline_cfg.get("session_name", "")
        if not name or current_session.session_name == name:
            return None
        return (
            db.query(TestResult)
            .join(TestSession, TestResult.test_session_id == TestSession.id)
            .filter(
                TestResult.testing_request_id == request_id,
                TestResult.template_key == template_key,
                TestSession.session_name == name,
            )
            .first()
        )

    elif strategy == "previous_session":
        if not current_session.session_number or current_session.session_number <= 1:
            return None
        return (
            db.query(TestResult)
            .join(TestSession, TestResult.test_session_id == TestSession.id)
            .filter(
                TestResult.testing_request_id == request_id,
                TestResult.template_key == template_key,
                TestSession.session_number == current_session.session_number - 1,
            )
            .first()
        )

    elif strategy == "first_session":
        if current_session.session_number == 1:
            return None
        return (
            db.query(TestResult)
            .join(TestSession, TestResult.test_session_id == TestSession.id)
            .filter(
                TestResult.testing_request_id == request_id,
                TestResult.template_key == template_key,
                TestSession.session_number == 1,
            )
            .first()
        )

    return None


def _build_threshold_config_html(ev: dict) -> str:
    """
    Build an HTML table from evaluation result fields for use as
    {{alert.thresholdconfig}} in eval_alert / eval_critical email templates.

    Renders only ALERT or CRITICAL fields. Handles two field types:

    Per-session fields (type=number/table):
      Parameter | Measured Value | Status | Normal Range | Alert Range | Critical Range

    Cross-session deviation fields (type=table_aggregate/table_row):
      Parameter | Baseline | Current | Deviation | Status
      (rendered in a separate section with a header)

    Falls back to a plain text summary if no fields are present.
    """
    all_fields = [
        f for f in (ev.get("fields") or [])
        if f.get("status") in ("ALERT", "CRITICAL")
    ]
    if not all_fields:
        return (
            f"<p>Overall result: <strong>{ev.get('overall', '')}</strong>. "
            f"{ev.get('summary', '')}</p>"
        )

    # Discriminate by source marker stamped on every cross-session field
    per_session   = [f for f in all_fields if f.get("source") != "cross_session"]
    cross_session = [f for f in all_fields if f.get("source") == "cross_session"]

    TD  = "style='padding:5px 8px;border:1px solid #ddd;font-size:12px'"
    TH  = "style='padding:5px 8px;border:1px solid #ddd;background:#1E3C72;color:#fff;font-size:12px;text-align:left'"
    TH2 = "style='padding:5px 8px;border:1px solid #ddd;background:#1a3a2a;color:#a5d6a7;font-size:12px;text-align:left'"

    def _fmt(val) -> str:
        return str(round(val, 4)) if isinstance(val, float) else (str(val) if val is not None else "—")

    def _range(lo, hi) -> str:
        if lo is not None and hi is not None:
            return f"{lo} – {hi}"
        if lo is not None:
            return f"≥ {lo}"
        if hi is not None:
            return f"≤ {hi}"
        return "—"

    html = ""

    # ── Per-session threshold table ────────────────────────────────────────────
    if per_session:
        rows = ""
        for f in per_session:
            t = f.get("thresholds") or {}
            status = f.get("status", "")
            sc = "#d32f2f" if status == "CRITICAL" else "#f57c00"
            unit = f.get("unit") or ""
            rows += (
                f"<tr>"
                f"<td {TD}>{f.get('label', f.get('key', ''))}</td>"
                f"<td {TD}><strong>{_fmt(f.get('value'))} {unit}</strong></td>"
                f"<td {TD} style='color:{sc};font-weight:bold'>{status}</td>"
                f"<td {TD}>{_range(t.get('normal_min'), t.get('normal_max'))}</td>"
                f"<td {TD}>{_range(t.get('alert_min'), t.get('alert_max'))}</td>"
                f"<td {TD}>{_range(t.get('critical_below'), t.get('critical_above'))}</td>"
                f"</tr>"
            )
        html += (
            f"<table cellspacing='0' style='border-collapse:collapse;width:100%;margin-top:8px'>"
            f"<tr>"
            f"<th {TH}>Parameter</th><th {TH}>Measured Value</th>"
            f"<th {TH}>Status</th><th {TH}>Normal Range</th>"
            f"<th {TH}>Alert Range</th><th {TH}>Critical Range</th>"
            f"</tr>{rows}</table>"
        )

    # ── Cross-session deviation table ──────────────────────────────────────────
    if cross_session:
        if html:
            html += "<br/>"
        rows = ""
        for f in cross_session:
            status = f.get("status", "")
            sc  = "#d32f2f" if status == "CRITICAL" else "#f57c00"
            dev = _fmt(f.get("deviation"))
            dev_type = "%" if f.get("deviation_type") == "relative_percent" else ""
            sign = "+" if isinstance(f.get("deviation"), (int, float)) and f.get("deviation", 0) > 0 else ""
            rows += (
                f"<tr>"
                f"<td {TD}>{f.get('label', f.get('key', ''))}</td>"
                f"<td {TD}>{_fmt(f.get('baseline_value'))}</td>"
                f"<td {TD}>{_fmt(f.get('current_value'))}</td>"
                f"<td {TD}><strong>{sign}{dev}{dev_type}</strong></td>"
                f"<td {TD} style='color:{sc};font-weight:bold'>{status}</td>"
                f"</tr>"
            )
        html += (
            f"<p style='margin:8px 0 4px;font-size:12px;color:#555'>"
            f"<strong>Cross-Session Comparison (vs FACTORY baseline)</strong></p>"
            f"<table cellspacing='0' style='border-collapse:collapse;width:100%;margin-top:4px'>"
            f"<tr>"
            f"<th {TH2}>Parameter</th><th {TH2}>Baseline</th>"
            f"<th {TH2}>Current</th><th {TH2}>Deviation</th><th {TH2}>Status</th>"
            f"</tr>{rows}</table>"
        )

    return html


def _deduplicated_overall_sections(main_sections: list, overall_sections: list) -> list:
    """
    Return only those sections/fields from overall_sections that don't already
    exist (by field key) in main_sections.  This prevents a double overall_result
    dropdown when the main template already contains that field.
    """
    existing_keys = {
        f.get("key")
        for sec in main_sections
        for f in sec.get("fields", [])
        if f.get("key")
    }
    deduped = []
    for sec in overall_sections:
        filtered_fields = [
            f for f in sec.get("fields", [])
            if f.get("key") not in existing_keys
        ]
        if filtered_fields:
            deduped.append({**sec, "fields": filtered_fields})
    return deduped


class TestingService:

    def __init__(self, db: Session):
        self.db = db

    def _get_request(self, request_id: UUID) -> TestingRequest:
        request = self.db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")
        return request

    def _user_label(self, user_id) -> str:
        """Resolve a user's friendly display name for notification context."""
        from models import User
        if not user_id:
            return "System"
        u = self.db.query(User).filter(User.id == user_id).first()
        if not u:
            return str(user_id)
        name = " ".join(filter(None, [u.firstname, u.lastname])).strip()
        return name or u.email or str(user_id)

    def _fire_status_changed(self, request, status_from: str, status_to: str, user_id) -> None:
        """Emit the status_changed notification event for a lifecycle transition.
        Fire-and-forget — never blocks the transaction."""
        try:
            from services.notification_service import NotificationService
            NotificationService(self.db).fire(
                event_type="status_changed",
                context={
                    "request.number": request.request_number or str(request.id),
                    "request.status": status_to,
                    "request.title":  getattr(request, "title", "") or "",
                    "status_from":    status_from,
                    "status_to":      status_to,
                    "changed_by":     self._user_label(user_id),
                },
                organization_id=request.organization_id,
                department_id=getattr(request, "department_id", None),
                source_id=request.id,
                source_type="testing_request",
                severity="info",
                workflow_type="testing_request",
                status_from=status_from,
                status_to=status_to,
            )
        except Exception as _e:
            logger.warning(f"status_changed notification failed: {_e}")

    def accept_assignment(self, request_id: UUID, tester_id: UUID) -> TestingRequest:
        request = self._get_request(request_id)
        if request.status != TestingRequestStatus.assigned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only assigned requests can be accepted",
            )
        if str(request.assigned_tester_id) != str(tester_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the assigned tester can accept this request",
            )
        request.status = TestingRequestStatus.accepted
        request.accepted_at = UTCDateTimeMixin._utc_now()
        request.modified_by = tester_id
        self.db.commit()
        self.db.refresh(request)
        self._fire_status_changed(request, "assigned", "accepted", tester_id)
        return request

    def start_testing(self, request_id: UUID, tester_id: UUID) -> TestingRequest:
        request = self._get_request(request_id)
        if request.status != TestingRequestStatus.accepted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only accepted requests can be started",
            )
        if str(request.assigned_tester_id) != str(tester_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the assigned tester can start testing",
            )
        request.status = TestingRequestStatus.in_progress
        request.modified_by = tester_id
        self.db.commit()
        self.db.refresh(request)
        self._fire_status_changed(request, "accepted", "in_progress", tester_id)
        return request

    # NOTE: Old upload_test_result (multipart form) removed.
    # Use create_structured_result() for JSONB-based submissions.

    def get_test_results(self, request_id: UUID) -> List[TestResult]:
        return (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == request_id)
            .order_by(TestResult.cts.asc())
            .all()
        )

    def submit_test_results(self, request_id: UUID, tester_id: UUID, replacement_products=None) -> TestingRequest:
        request = self._get_request(request_id)
        _prev_status = request.status.value

        from models import RequestCategory as _RC
        _is_fr = request.request_category == _RC.failure_registry

        if not _is_fr:
            if request.status not in (TestingRequestStatus.in_progress, TestingRequestStatus.test_submitted):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only in-progress or test_submitted requests can have results submitted",
                )
            if str(request.assigned_tester_id) != str(tester_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the assigned tester can submit results",
                )

        results = self.get_test_results(request_id)
        if not results:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one test result must be uploaded before submitting",
            )

        # --- Auto-create or update Recommendation from test results ---
        # Prefer evaluation_result if any result has CRITICAL/ALERT evaluation
        rec_type, summary, suggested_prods = self._derive_recommendation_from_results(request, results)
        # Merge caller-supplied replacement_products with auto-suggested ones
        merged_products = replacement_products or suggested_prods or None

        # Check for existing recommendation (re-submission from test_submitted)
        existing_rec = (
            self.db.query(Recommendation)
            .filter(Recommendation.testing_request_id == request_id)
            .first()
        )
        rec_obj = None
        if existing_rec:
            existing_rec.recommendation_type = rec_type
            existing_rec.summary = summary
            existing_rec.replacement_products = merged_products
            existing_rec.approval_status = "pending"
            existing_rec.modified_by = tester_id
            rec_obj = existing_rec
        else:
            rec_obj = Recommendation(
                testing_request_id=request_id,
                organization_id=request.organization_id,
                recommendation_type=rec_type,
                summary=summary,
                detailed_notes=None,
                replacement_products=merged_products,
                submitted_by=tester_id,
                submitted_at=UTCDateTimeMixin._utc_now(),
                approval_status="pending",
                created_by=tester_id,
            )
            self.db.add(rec_obj)

        # ── FR: check if current WF stage has only terminal transitions ──────────
        # If every transition out of the current stage is terminal (no next stage),
        # auto-complete the request now instead of parking it in under_approval.
        if _is_fr and request.wf_instance_id:
            from models import TrWfInstance, TrWfStage, TrWfStageTransition, TrWfStatus as _TrWfStatus
            instance = self.db.query(TrWfInstance).filter(
                TrWfInstance.id == request.wf_instance_id
            ).first()
            _auto_closed = False
            if instance and instance.current_stage_id:
                transitions = self.db.query(TrWfStageTransition).filter(
                    TrWfStageTransition.from_stage_id == instance.current_stage_id
                ).all()
                all_terminal = transitions and all(t.to_stage_id is None for t in transitions)
                if all_terminal:
                    # Find the "complete" (non-rejection, non-cancel) terminal transition
                    complete_t = next(
                        (t for t in transitions
                         if not t.is_rejection and t.action_code not in ('reject', 'cancel')),
                        transitions[0],  # fallback to first if no clear complete action
                    )
                    # Apply terminal WF status
                    _term_code = None
                    if complete_t.terminal_status_id:
                        term_status = self.db.query(_TrWfStatus).filter(
                            _TrWfStatus.id == complete_t.terminal_status_id
                        ).first()
                        if term_status:
                            _term_code = term_status.status_code
                    if not _term_code:
                        # Fallback: last status in the WF definition by sequence
                        _last_s = (
                            self.db.query(_TrWfStatus)
                            .filter(_TrWfStatus.wf_definition_id == instance.wf_definition_id)
                            .order_by(_TrWfStatus.sequence.desc())
                            .first()
                        )
                        if _last_s:
                            _term_code = _last_s.status_code
                    if _term_code:
                        request.current_status_code = _term_code
                        instance.current_status_code = _term_code
                        instance.current_stage_id = None
                        instance.status = "completed"
                    # Auto-approve the recommendation and dispatch
                    self.db.flush()
                    rec_obj.approval_status = "approved"
                    rec_obj.approved_by = tester_id
                    rec_obj.approved_at = UTCDateTimeMixin._utc_now()
                    self.db.flush()
                    from services.workflow_dispatch_service import WorkflowDispatchService
                    WorkflowDispatchService(self.db).dispatch(request, rec_obj, tester_id)
                    _auto_closed = True

            if not _auto_closed:
                request.status = TestingRequestStatus.under_approval
        elif not _is_fr:
            # Multi-session check: only transition to under_approval if all sessions complete
            if request.is_multi_session and request.total_sessions_planned:
                completed_sessions = self.db.query(TestSession).filter(
                    TestSession.testing_request_id == request_id,
                    TestSession.status == "completed"
                ).count()
                if completed_sessions >= request.total_sessions_planned:
                    request.status = TestingRequestStatus.under_approval
                else:
                    request.status = TestingRequestStatus.in_progress
            else:
                request.status = TestingRequestStatus.under_approval

        request.modified_by = tester_id
        self.db.commit()
        self.db.refresh(request)

        # Notify on the lifecycle status change (e.g. in_progress → under_approval)
        if request.status.value != _prev_status:
            self._fire_status_changed(request, _prev_status, request.status.value, tester_id)

        # ── Surveillance tracking: update if this is a surveillance test ──────
        if request.surveillance_workflow_id:
            try:
                from services.surveillance_tracking_service import SurveillanceTrackingService

                # Get result status from latest test result
                latest_result = results[-1] if results else None
                result_status = latest_result.overall_result if latest_result else None
                tested_at = latest_result.tested_at if latest_result else None

                SurveillanceTrackingService(self.db).update_test_result(
                    testing_request_id=request_id,
                    test_status='completed',
                    result_status=result_status,
                    tested_at=tested_at
                )
            except Exception as _surv:
                logger.warning("[TestingService] Surveillance tracking update failed: %s", _surv)

        return request

    @staticmethod
    def _derive_recommendation_from_results(
        request, results: list
    ) -> tuple:
        """
        Derive (recommendation_type, summary, suggested_products) from results.

        Priority:
          1. If any evaluation_result.overall == CRITICAL → fail + auto-summary
          2. If any evaluation_result.overall == ALERT   → conditional + auto-summary
          3. Fall back to overall_result strings (pass/fail/conditional)
        """
        from services.evaluation_service import EvaluationService

        # ── Evaluation-based derivation ──────────────────────────────────────
        critical_results = [r for r in results if (r.evaluation_result or {}).get("overall") == "CRITICAL"]
        alert_results    = [r for r in results if (r.evaluation_result or {}).get("overall") == "ALERT"]
        title = getattr(request, "title", "") or getattr(request, "request_number", "") or ""

        if critical_results:
            # Merge summaries from all CRITICAL results
            summaries: list[str] = []
            products: list = []
            for r in critical_results:
                ev = r.evaluation_result or {}
                txt = EvaluationService.build_remedial_summary(ev, title)
                if txt:
                    summaries.append(txt)
                products.extend(EvaluationService.collect_suggested_products(ev))
            # Deduplicate products by item_name
            seen, uniq = set(), []
            for p in products:
                k = p.get("item_name", str(p))
                if k not in seen:
                    seen.add(k)
                    uniq.append(p)
            full_summary = " | ".join(summaries) if summaries else f"[CRITICAL] {title}"
            return RecommendationType.fail, full_summary, uniq or None

        if alert_results:
            summaries = []
            for r in alert_results:
                ev = r.evaluation_result or {}
                txt = EvaluationService.build_remedial_summary(ev, title)
                if txt:
                    summaries.append(txt)
            full_summary = " | ".join(summaries) if summaries else f"[ALERT] {title}"
            return RecommendationType.conditional, full_summary, None

        # ── Fallback: use tester-entered overall_result strings ──────────────
        overall_results = [
            (r.overall_result or "").lower().strip()
            for r in results if r.overall_result
        ]
        if not overall_results:
            rec_type = RecommendationType.conditional
        elif all(r == "pass" for r in overall_results):
            rec_type = RecommendationType.pass_test
        elif any(r == "fail" for r in overall_results):
            rec_type = RecommendationType.fail
        else:
            rec_type = RecommendationType.conditional

        test_names = [r.test_name or r.template_key or "Test" for r in results]
        summary = f"[{rec_type.value.upper()}] {title} — {len(results)} test(s): {', '.join(test_names)}"
        return rec_type, summary, None

    def get_my_assignments(self, tester_id: UUID, skip: int = 0, limit: int = 100) -> List[TestingRequest]:
        return (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.equipment_type),
                joinedload(TestingRequest.test_type),
                joinedload(TestingRequest.department),
                joinedload(TestingRequest.originator),
                joinedload(TestingRequest.organization),
            )
            .filter(TestingRequest.assigned_tester_id == tester_id)
            .order_by(TestingRequest.cts.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    # ─── Template & Structured Results ──────────────────────

    def get_template(self, test_type_id: int, org_id=None) -> dict:
        """
        Return the form template for a test type.
        Prefers OrgTestTemplate row (org-specific > global default).
        Falls back to the static test_templates.py dict for backwards-compat.
        """
        detail = self.db.query(CategoryDetails).filter(CategoryDetails.id == test_type_id).first()
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test type not found")

        # Database-backed template (org-specific or global default)
        from services.org_test_template_service import OrgTestTemplateService
        from fastapi import HTTPException as FHE
        import copy
        svc = OrgTestTemplateService(self.db)
        _org_tmpl = None
        try:
            _org_tmpl = svc.get_for_test_type(test_type_id=test_type_id, org_id=org_id)
            template_data = copy.deepcopy(_org_tmpl.template_data)
        except FHE:
            # Fallback 1: another template for the same equipment type + category.
            # Only for maintenance/inspection/repair — NOT for 'test', where each
            # test type has its own specific template and a sibling would be wrong.
            if detail.category_master_id and detail.category_type and detail.category_type != "test":
                sibling_ids = [
                    row.id
                    for row in self.db.query(CategoryDetails).filter(
                        CategoryDetails.category_master_id == detail.category_master_id,
                        CategoryDetails.category_type == detail.category_type,
                        CategoryDetails.is_active.is_(True),
                        CategoryDetails.id != test_type_id,
                    ).all()
                ]
                _org_tmpl = None
                for sid in sibling_ids:
                    try:
                        _org_tmpl = svc.get_for_test_type(test_type_id=sid, org_id=org_id)
                        break
                    except FHE:
                        continue
                if _org_tmpl:
                    template_data = copy.deepcopy(_org_tmpl.template_data)
                else:
                    # Fallback 2: static dict (legacy / before provisioning)
                    from test_templates import get_template_for_test_type
                    template_data = get_template_for_test_type(detail.name)
                    if not template_data:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No template defined for test type: {detail.name}",
                        )
            else:
                # Fallback 2: static dict (legacy / before provisioning)
                from test_templates import get_template_for_test_type
                template_data = get_template_for_test_type(detail.name)
                if not template_data:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No template defined for test type: {detail.name}",
                    )

        # Inject template_key so the frontend can use it for result submission
        if _org_tmpl and "key" not in template_data:
            template_data["key"] = _org_tmpl.template_key

        # Normalise field types so the result form understands them:
        #   toggle  → boolean  (designer calls it toggle; form renders boolean)
        #   columns: List[str] → List[{key, label, type}]  (designer saves str list)
        for section in template_data.get("sections", []):
            for field in section.get("fields", []):
                if field.get("type") == "toggle":
                    field["type"] = "boolean"
                if field.get("type") == "table":
                    cols = field.get("columns", [])
                    if cols and isinstance(cols[0], str):
                        field["columns"] = [
                            {
                                "key": c.lower().replace(" ", "_"),
                                "label": c,
                                "type": "text",
                            }
                            for c in cols
                        ]

        # Append overall assessment sections (template-driven), skipping fields
        # whose key already exists in the main template to avoid duplicates
        # (e.g. overall_result appears in both static templates and overall_assessment).
        try:
            overall = svc.get_overall_assessment(org_id=org_id)
            overall_sections = (overall.template_data or {}).get("sections", [])
            if overall_sections:
                template_data.setdefault("sections", [])
                template_data["sections"].extend(
                    _deduplicated_overall_sections(template_data["sections"], copy.deepcopy(overall_sections))
                )
        except FHE:
            pass  # No overall assessment template yet — skip silently

        return template_data

    def create_structured_result(
        self, request_id: UUID, template_key: str, test_data: dict,
        overall_result: Optional[str], remarks: Optional[str], tester_id: UUID,
        replacement_products: Optional[list] = None,
        test_session_id: Optional[UUID] = None,
        testing_kit_id: Optional[UUID] = None,
        finalize: bool = True,
    ) -> TestResult:
        """Create a structured test result with JSONB data."""
        from test_templates import get_template_by_key
        request = self._get_request(request_id)
        # FR records have their own status lifecycle — skip TR status gate entirely.
        from models import RequestCategory as _RC
        _is_fr = request.request_category == _RC.failure_registry

        if not _is_fr:
            if request.wf_instance_id:
                # Workflow-driven TR: derive allowed statuses from the WF definition.
                # Any status that belongs to a non-terminal, non-approval, non-assignment
                # stage is an execution stage where results can be submitted.
                from models import TrWfInstance, TrWfStatus as _TrWfStatus
                instance = self.db.query(TrWfInstance).filter(
                    TrWfInstance.id == request.wf_instance_id
                ).first()
                wf_execution_codes: set[str] = set()
                if instance:
                    rows = self.db.query(_TrWfStatus).filter(
                        _TrWfStatus.wf_definition_id == instance.wf_definition_id,
                        _TrWfStatus.is_terminal.is_(False),
                        _TrWfStatus.approval_required.is_(False),
                        _TrWfStatus.assignment_required.is_(False),
                        _TrWfStatus.is_active.is_(True),
                    ).all()
                    wf_execution_codes = {r.status_code for r in rows}
                if request.current_status_code not in wf_execution_codes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Test results cannot be submitted at this workflow stage",
                    )
            else:
                # Legacy TR without a workflow instance — use the fixed status list.
                allowed = (
                    TestingRequestStatus.in_progress,
                    TestingRequestStatus.accepted,
                    TestingRequestStatus.test_submitted,
                    TestingRequestStatus.pending_assignment,
                    TestingRequestStatus.scheduled,
                )
                if request.status not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Test results can only be saved for accepted, in-progress, or test_submitted requests",
                    )

        template = get_template_by_key(template_key)
        if template:
            test_name = template["name"]
        else:
            # Try org template (created via Template Designer)
            try:
                from services.org_test_template_service import OrgTestTemplateService as _OTSvc
                _otsvc = _OTSvc(self.db)
                _ot = _otsvc.get_by_template_key(template_key)
                test_name = (_ot.template_data or {}).get("name") or template_key
            except Exception:
                test_name = template_key

        # Upsert: update existing result if same request + template_key + session, else create
        # For multi-session: look up by session_id if provided
        # For legacy single-session: look up by request_id + template_key + session_id=NULL
        existing = (
            self.db.query(TestResult)
            .filter(
                TestResult.testing_request_id == request_id,
                TestResult.template_key == template_key,
                TestResult.test_session_id == test_session_id,  # Match session (NULL for legacy)
            )
            .first()
        )

        if existing:
            existing.test_name = test_name
            existing.test_data = test_data
            existing.overall_result = overall_result
            existing.remarks = remarks
            existing.replacement_products = replacement_products
            existing.test_session_id = test_session_id  # Update session link
            if testing_kit_id is not None:
                existing.testing_kit_id = testing_kit_id
            existing.tested_by = tester_id
            existing.tested_at = UTCDateTimeMixin._utc_now()
            existing.modified_by = tester_id
            result = existing
        else:
            result = TestResult(
                testing_request_id=request_id,
                test_session_id=test_session_id,  # Link to session
                organization_id=request.organization_id,  # Auto-populate from testing_request
                test_name=test_name,
                template_key=template_key,
                test_data=test_data,
                overall_result=overall_result,
                remarks=remarks,
                replacement_products=replacement_products,
                testing_kit_id=testing_kit_id,
                tested_by=tester_id,
                tested_at=UTCDateTimeMixin._utc_now(),
                created_by=tester_id,
            )
            self.db.add(result)

        # Auto-transition to in_progress if still accepted/pending_assignment/scheduled
        if request.status in (
            TestingRequestStatus.accepted,
            TestingRequestStatus.pending_assignment,
            TestingRequestStatus.scheduled,
        ):
            request.status = TestingRequestStatus.in_progress
            request.modified_by = tester_id

        self.db.flush()  # generate result.id before evaluation

        # ── Auto-evaluation (skipped for draft saves) ────────────────────────
        if not finalize:
            self.db.commit()
            self.db.refresh(result)
            return result

        try:
            from services.evaluation_service import EvaluationService
            ev = EvaluationService.run(template_key, test_data, self.db, org_id=request.organization_id)
            result.evaluation_result = ev

            # CRITICAL → override overall_result + pre-fill remedial recommendation
            if ev["overall"] == "CRITICAL":
                result.overall_result = "fail"
                remedial = EvaluationService.build_remedial_summary(
                    ev, request_title=getattr(request, "title", "") or ""
                )
                if remedial:
                    result.remarks = (result.remarks or "") + (
                        f"\n[AUTO-EVAL] {remedial}" if result.remarks else f"[AUTO-EVAL] {remedial}"
                    )
                # Pre-fill suggested_products on result (tester can review/edit before submit)
                suggested = EvaluationService.collect_suggested_products(ev)
                if suggested and not result.replacement_products:
                    result.replacement_products = suggested

            # ALERT → store revised_interval on result for scheduler
            elif ev["overall"] == "ALERT":
                revised = EvaluationService.get_min_revised_interval(ev)
                if revised is not None:
                    ev["revised_interval_days"] = revised
                    result.evaluation_result = ev

            # ── Cross-session comparison (generic — driven by enable_cross_session flag) ──
            try:
                if test_session_id:
                    from models import TestSession as _TS
                    _session = self.db.query(_TS).filter(_TS.id == test_session_id).first()
                    if _session:
                        _tpl_data = EvaluationService.get_template_data(
                            template_key, self.db, org_id=request.organization_id
                        )
                        if _tpl_data and _tpl_data.get("enable_cross_session"):
                            _baseline_result = _resolve_baseline_result(
                                self.db, request_id, template_key, _session, _tpl_data
                            )
                            if _baseline_result and _baseline_result.test_data:
                                _cross_ev = EvaluationService.evaluate_cross_session(
                                    _tpl_data,
                                    _baseline_result.test_data,
                                    test_data,
                                )
                                if _cross_ev["fields"]:
                                    ev["fields"].extend(_cross_ev["fields"])
                                    ev["cross_session_comparison"] = _cross_ev
                                    from services.evaluation_service import _STATUS_RANK as _sr
                                    if _sr.get(_cross_ev["overall"], 0) > _sr.get(ev["overall"], 0):
                                        ev["overall"] = _cross_ev["overall"]
                                    # Sync overall_result with escalated severity
                                    if ev["overall"] == "CRITICAL" and result.overall_result != "fail":
                                        result.overall_result = "fail"
                                    elif ev["overall"] == "ALERT" and result.overall_result not in ("fail", "conditional"):
                                        result.overall_result = "conditional"
                                    result.evaluation_result = ev
            except Exception as _cs_err:
                logger.warning(f"Cross-session comparison failed: {_cs_err}")

            # ── Notification hooks (fire-and-forget; never block save) ────────
            try:
                from services.notification_service import NotificationService
                overall_threshold = ev.get("overall", "NORMAL")
                if overall_threshold in ("ALERT", "CRITICAL"):
                    _event_map = {"ALERT": "eval_alert", "CRITICAL": "eval_critical"}
                    _tester_name = getattr(getattr(request, "tester", None), "full_name", None) or "Unknown"
                    _eq_ueic = (
                        getattr(getattr(request, "equipment", None), "ueic", "") or
                        getattr(request, "equipment_name", "") or ""
                    )
                    NotificationService(self.db).fire(
                        event_type=_event_map[overall_threshold],
                        context={
                            "request.number":        request.request_number or "",
                            "equipment.ueic":        _eq_ueic,
                            "eval.test_type":        result.test_name or test_name or template_key or "",
                            "eval.overall":          overall_threshold,
                            "result_summary":        ev.get("summary") or ev.get("finding") or "",
                            "result_threshold":      overall_threshold,
                            "tester_name":           _tester_name,
                            "eval.evaluated_at":     str(result.tested_at or result.cts or "")[:19],
                            "alert.thresholdconfig": _build_threshold_config_html(ev),
                            "revised_interval":      (
                                f"{ev['revised_interval_days']} days"
                                if ev.get("revised_interval_days") is not None else "—"
                            ),
                        },
                        organization_id=request.organization_id,
                        department_id=getattr(request, "department_id", None),
                        source_id=result.id,
                        source_type="test_result",
                        severity="critical" if overall_threshold == "CRITICAL" else "alert",
                        workflow_type="testing_request",
                        equipment_type=getattr(getattr(request, "equipment_type", None), "name", None),
                        test_type=(request.request_category.value if request.request_category else None),
                        activity_type=result.test_name,
                    )
            except Exception as _notif_err:
                logger.warning(f"Notification event emission failed: {_notif_err}")

        except Exception as _eval_err:  # evaluation must never block save
            import traceback
            logger.error(f"[EVAL_FAIL] template={template_key} org={request.organization_id} err={_eval_err}\n{traceback.format_exc()}")
            print(f"[WARN] Evaluation failed for {template_key}: {_eval_err}")
            traceback.print_exc()

        # ── Analytics Engine (fire-and-forget; never block save) ─────────────
        try:
            self.db.flush()  # ensure result.id is persisted before analytics read it
            from services.analytics_engine import AnalyticsEngine
            AnalyticsEngine(self.db).run_for_test(result.id)
        except Exception as _analytics_err:
            logger.warning(f"Analytics engine failed for result {result.id}: {_analytics_err}")

        # ── Mark linked session as completed ──────────────────────────────────
        # Sessions are pre-generated by the auto-generate flow.
        # When a result is submitted for a specific session, mark that session
        # as completed. Never create new sessions here.
        if test_session_id:
            try:
                _linked_session = self.db.query(TestSession).filter(
                    TestSession.id == test_session_id
                ).first()
                if _linked_session and _linked_session.status != "completed":
                    _linked_session.status = "completed"
                    _linked_session.modified_by = tester_id
            except Exception as _sess_err:
                print(f"[WARN] Session status update failed: {_sess_err}")

        self.db.commit()
        self.db.refresh(result)

        # ── Calibration DATE_ADD evaluation (fire-and-forget; never blocks save) ─
        # Fires for any template whose rules list contains a DATE_ADD rule.
        # Reads calibration_date + validity_months from test_data, computes
        # next_due, updates equipment calibration status, and triggers repair
        # workflow if result == Fail.
        if getattr(request, 'equipment_id', None) and result.template_key:
            try:
                from test_templates import get_template_by_key as _get_tmpl_cal
                _tmpl_cal = _get_tmpl_cal(result.template_key)
                if _tmpl_cal is None:
                    from services.org_test_template_service import OrgTestTemplateService as _OTS_CAL
                    try:
                        _ot_cal = _OTS_CAL(self.db).get_by_template_key(result.template_key)
                        _tmpl_cal = _ot_cal.template_data if _ot_cal else None
                    except Exception:
                        _tmpl_cal = None

                _has_date_add = any(
                    (r.get("type") or "").upper() == "DATE_ADD"
                    for r in (_tmpl_cal or {}).get("rules", [])
                )

                if _has_date_add:
                    from services.calibration_service import CalibrationService
                    CalibrationService(self.db).evaluate_calibration(
                        equipment_id=request.equipment_id,
                        user_id=tester_id,
                    )
                    print(
                        f"[CALIBRATION] DATE_ADD evaluated — equipment={request.equipment_id} "
                        f"template={result.template_key}"
                    )
            except Exception as _cal_err:
                import traceback
                print(f"[WARN] Calibration DATE_ADD evaluation failed: {_cal_err}")
                traceback.print_exc()

        # ── Cumulative overhaul evaluation (fire-and-forget; never blocks save) ─
        # Fires for any template whose rules list contains a CUMULATIVE_DIFF rule.
        # Covers all cumulative test types (OLTC ops count, CB ops count, etc.)
        # generically — no hardcoded is_cumulative flag needed.
        # Idempotent: evaluate_overhaul_trigger() only creates a new ticket when
        # cumulative >= threshold AND no open recommendation already exists.
        if getattr(request, 'equipment_id', None) and result.template_key:
            try:
                from test_templates import get_template_by_key as _get_tmpl_c
                _tmpl_c = _get_tmpl_c(result.template_key)
                if _tmpl_c is None:
                    from services.org_test_template_service import OrgTestTemplateService as _OTS_C
                    try:
                        _ot_c = _OTS_C(self.db).get_by_template_key(result.template_key)
                        _tmpl_c = _ot_c.template_data if _ot_c else None
                    except Exception:
                        _tmpl_c = None

                _has_cumulative = any(
                    (r.get("type") or "").upper() == "CUMULATIVE_DIFF"
                    for r in (_tmpl_c or {}).get("rules", [])
                )

                if _has_cumulative:
                    from services.cumulative_service import CumulativeService
                    from sqlalchemy.orm.attributes import flag_modified
                    _csvc = CumulativeService(self.db)
                    lifecycle = _csvc.evaluate_overhaul_trigger(
                        equipment_id=request.equipment_id,
                        user_id=tester_id,
                    )
                    merged = {**(result.evaluation_result or {}), "cumulative_lifecycle": lifecycle}
                    result.evaluation_result = merged
                    flag_modified(result, "evaluation_result")
                    self.db.commit()
                    self.db.refresh(result)
                    print(
                        f"[CUMULATIVE] equipment={request.equipment_id} "
                        f"template={result.template_key} "
                        f"cumulative={lifecycle.get('cumulative_value')} "
                        f"threshold={lifecycle.get('threshold_value')} "
                        f"status={lifecycle.get('status')}"
                    )
            except Exception as _cum_err:
                import traceback
                print(f"[WARN] Cumulative evaluation failed: {_cum_err}")
                traceback.print_exc()

        return result

    def upload_result_images(self, result_id: UUID, files: list, tester_id: UUID) -> List[TestResultImage]:
        """Upload multiple images for a test result."""
        result = self.db.query(TestResult).filter(TestResult.id == result_id).first()
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test result not found")

        images = []
        for i, file in enumerate(files):
            file_data = file.file.read()
            img = TestResultImage(
                test_result_id=result_id,
                file_name=file.filename,
                file_type=file.content_type,
                file_size=len(file_data),
                file_data=file_data,
                sort_order=i,
                created_by=tester_id,
            )
            self.db.add(img)
            images.append(img)

        self.db.commit()
        for img in images:
            self.db.refresh(img)
        return images

    def get_result_image(self, image_id: UUID) -> TestResultImage:
        """Get a single image by ID."""
        img = self.db.query(TestResultImage).filter(TestResultImage.id == image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        return img
