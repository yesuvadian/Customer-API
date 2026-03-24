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
        rec_type = self._derive_recommendation_type(results)
        summary = self._build_recommendation_summary(request, results, rec_type)

        # Check for existing recommendation (re-submission from test_submitted)
        existing_rec = (
            self.db.query(Recommendation)
            .filter(Recommendation.testing_request_id == request_id)
            .first()
        )
        if existing_rec:
            existing_rec.recommendation_type = rec_type
            existing_rec.summary = summary
            existing_rec.replacement_products = replacement_products
            existing_rec.approval_status = "pending"
            existing_rec.modified_by = tester_id
        else:
            recommendation = Recommendation(
                testing_request_id=request_id,
                organization_id=request.organization_id,  # Auto-populate from testing_request
                recommendation_type=rec_type,
                summary=summary,
                detailed_notes=None,
                replacement_products=replacement_products,
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
        return request

    @staticmethod
    def _derive_recommendation_type(results: list) -> RecommendationType:
        """Derive recommendation type from overall_result of test results."""
        overall_results = [
            (r.overall_result or "").lower().strip()
            for r in results if r.overall_result
        ]
        if not overall_results:
            return RecommendationType.conditional

        if all(r == "pass" for r in overall_results):
            return RecommendationType.pass_test
        elif any(r == "fail" for r in overall_results):
            return RecommendationType.fail
        else:
            return RecommendationType.conditional

    @staticmethod
    def _build_recommendation_summary(request, results: list, rec_type: RecommendationType) -> str:
        """Build a human-readable recommendation summary."""
        test_names = [r.test_name or r.template_key or "Test" for r in results]
        tests_str = ", ".join(test_names)
        title = request.title or request.request_number
        type_label = rec_type.value.upper()
        return f"[{type_label}] {title} — {len(results)} test(s): {tests_str}"

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

    def get_template(self, test_type_id: int) -> dict:
        """Look up the form template for a given test type ID."""
        from test_templates import get_template_for_test_type
        detail = self.db.query(CategoryDetails).filter(CategoryDetails.id == test_type_id).first()
        if not detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test type not found")
        template = get_template_for_test_type(detail.name)
        if not template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"No template defined for test type: {detail.name}")
        return template

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
        test_name = template["name"] if template else template_key

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
