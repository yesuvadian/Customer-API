from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models import TestingRequest, TestingRequestStatus, TestResult, TestResultImage, CategoryDetails, Recommendation, RecommendationType
from utils.common_service import UTCDateTimeMixin


class TestingService:

    def __init__(self, db: Session):
        self.db = db

    def _get_request(self, request_id: UUID) -> TestingRequest:
        request = self.db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
        if not request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")
        return request

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
        if existing_rec:
            existing_rec.recommendation_type = rec_type
            existing_rec.summary = summary
            existing_rec.replacement_products = merged_products
            existing_rec.approval_status = "pending"
            existing_rec.modified_by = tester_id
        else:
            recommendation = Recommendation(
                testing_request_id=request_id,
                organization_id=request.organization_id,  # Auto-populate from testing_request
                recommendation_type=rec_type,
                summary=summary,
                detailed_notes=None,
                replacement_products=merged_products,
                submitted_by=tester_id,
                submitted_at=UTCDateTimeMixin._utc_now(),
                approval_status="pending",
                created_by=tester_id,
            )
            self.db.add(recommendation)

        # Transition directly to under_approval (skips test_submitted)
        request.status = TestingRequestStatus.under_approval
        request.modified_by = tester_id
        self.db.commit()
        self.db.refresh(request)

        # ── Notification: test submitted → notify approvers ───────────────────
        try:
            from services.notification_service import NotificationService
            NotificationService(self.db).notify_test_submitted(request)
        except Exception as _n:
            print(f"[WARN] test_submitted notification failed: {_n}")

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
            # Fallback: static dict (legacy / before provisioning)
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

        # Append overall assessment sections (template-driven)
        try:
            overall = svc.get_overall_assessment(org_id=org_id)
            overall_sections = (overall.template_data or {}).get("sections", [])
            if overall_sections:
                template_data.setdefault("sections", [])
                template_data["sections"].extend(copy.deepcopy(overall_sections))
        except FHE:
            pass  # No overall assessment template yet — skip silently

        return template_data

    def create_structured_result(
        self, request_id: UUID, template_key: str, test_data: dict,
        overall_result: Optional[str], remarks: Optional[str], tester_id: UUID,
        replacement_products: Optional[list] = None,
    ) -> TestResult:
        """Create a structured test result with JSONB data."""
        from test_templates import get_template_by_key
        request = self._get_request(request_id)
        allowed = (
            TestingRequestStatus.in_progress,
            TestingRequestStatus.accepted,
            TestingRequestStatus.test_submitted,
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

        # Upsert: update existing result if same request + template_key, else create
        existing = (
            self.db.query(TestResult)
            .filter(
                TestResult.testing_request_id == request_id,
                TestResult.template_key == template_key,
            )
            .first()
        )

        if existing:
            existing.test_name = test_name
            existing.test_data = test_data
            existing.overall_result = overall_result
            existing.remarks = remarks
            existing.replacement_products = replacement_products
            existing.tested_by = tester_id
            existing.tested_at = UTCDateTimeMixin._utc_now()
            existing.modified_by = tester_id
            result = existing
        else:
            result = TestResult(
                testing_request_id=request_id,
                organization_id=request.organization_id,  # Auto-populate from testing_request
                test_name=test_name,
                template_key=template_key,
                test_data=test_data,
                overall_result=overall_result,
                remarks=remarks,
                replacement_products=replacement_products,
                tested_by=tester_id,
                tested_at=UTCDateTimeMixin._utc_now(),
                created_by=tester_id,
            )
            self.db.add(result)

        # Auto-transition to in_progress if still accepted
        if request.status == TestingRequestStatus.accepted:
            request.status = TestingRequestStatus.in_progress
            request.modified_by = tester_id

        self.db.flush()  # generate result.id before evaluation

        # ── Auto-evaluation ──────────────────────────────────────────────────
        try:
            from services.evaluation_service import EvaluationService
            ev = EvaluationService.run(template_key, test_data, self.db)
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
                    # Tag evaluation_result with revised interval for scheduler
                    ev["revised_interval_days"] = revised
                    result.evaluation_result = ev

            # ── Notification hooks (fire-and-forget; never block save) ────────
            try:
                from services.notification_service import NotificationService
                _nsvc = NotificationService(self.db)
                if ev["overall"] == "CRITICAL":
                    _nsvc.notify_eval_critical(request, result, ev)
                elif ev["overall"] == "ALERT":
                    _nsvc.notify_eval_alert(request, result, ev)
            except Exception as _notif_err:
                print(f"[WARN] Notification hook failed: {_notif_err}")

        except Exception as _eval_err:  # evaluation must never block save
            import traceback
            print(f"[WARN] Evaluation failed for {template_key}: {_eval_err}")
            traceback.print_exc()

        self.db.commit()
        self.db.refresh(result)
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
