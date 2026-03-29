from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import (
    TestingRequestResponse,
    TestResultResponse,
    TestResultStructuredCreate,
    TestResultStructuredResponse,
    TestResultImageResponse,
    SubmitTestResultsBody,
)
from services.testing_service import TestingService

router = APIRouter(
    prefix="/testing",
    tags=["testing"],
    dependencies=[Depends(get_current_user)],
)


def _enrich(req):
    """Attach computed display names to ORM object for tester workflow."""
    req.equipment_type_name = req.equipment_type.name if req.equipment_type else None
    req.equipment_name = req.equipment_type.name if req.equipment_type else None  # Alias for Flutter
    req.test_type_name = req.test_type.name if req.test_type else None
    req.department_name = req.department.name if req.department else None
    if req.originator:
        req.originator_name = f"{req.originator.firstname or ''} {req.originator.lastname or ''}".strip() or req.originator.email
        req.requester_email = req.originator.email  # For Flutter UI
    else:
        req.originator_name = None
        req.requester_email = None
    if req.assigned_tester:
        req.assigned_tester_name = f"{req.assigned_tester.firstname or ''} {req.assigned_tester.lastname or ''}".strip() or req.assigned_tester.email
    else:
        req.assigned_tester_name = None
    return req


@router.get("/my-assignments", response_model=List[TestingRequestResponse])
def get_my_assignments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    assignments = service.get_my_assignments(tester_id=current_user.id, skip=skip, limit=limit)
    return [_enrich(req) for req in assignments]


@router.put("/{request_id}/accept", response_model=TestingRequestResponse)
def accept_assignment(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    req = service.accept_assignment(request_id, tester_id=current_user.id)
    return _enrich(req)


@router.put("/{request_id}/start", response_model=TestingRequestResponse)
def start_testing(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    req = service.start_testing(request_id, tester_id=current_user.id)
    return _enrich(req)


@router.get("/{request_id}/results")
def get_test_results(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    results = service.get_test_results(request_id)
    # Build response with image metadata for each result
    response = []
    for r in results:
        imgs = [
            TestResultImageResponse(
                id=img.id,
                file_name=img.file_name,
                file_type=img.file_type,
                file_size=img.file_size,
                caption=img.caption,
                download_url=f"/testing/results/images/{img.id}",
                cts=img.cts,
            )
            for img in (r.images or [])
        ]
        resp = TestResultResponse(
            id=r.id,
            testing_request_id=r.testing_request_id,
            test_name=r.test_name,
            test_category=r.test_category,
            result_value=r.result_value,
            result_unit=r.result_unit,
            pass_fail=r.pass_fail,
            remarks=r.remarks,
            file_name=r.file_name,
            file_type=r.file_type,
            file_size=r.file_size,
            template_key=r.template_key,
            test_data=r.test_data,
            overall_result=r.overall_result,
            replacement_products=r.replacement_products,
            tested_by=r.tested_by,
            tested_at=r.tested_at,
            image_count=len(imgs),
            images=imgs,
            cts=r.cts,
            mts=r.mts,
        )
        response.append(resp)
    return response


@router.put("/{request_id}/submit_results", response_model=TestingRequestResponse)
def submit_test_results(
    request_id: UUID,
    body: Optional[SubmitTestResultsBody] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    req = service.submit_test_results(
        request_id,
        tester_id=current_user.id,
        replacement_products=body.replacement_products if body else None,
    )
    return _enrich(req)


# ─── Template & Structured Results ──────────────────────────

@router.get("/templates/by-key/{template_key}")
def get_test_template_by_key(
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the dynamic form template looked up by template key (for requests without a test_type_id)."""
    from services.org_test_template_service import OrgTestTemplateService
    import copy
    svc = OrgTestTemplateService(db)
    tmpl = svc.get_by_template_key(template_key)
    data = copy.deepcopy(tmpl.template_data or {})
    if "key" not in data:
        data["key"] = tmpl.template_key
    # Append Overall Assessment sections
    try:
        overall = svc.get_overall_assessment(org_id=tmpl.org_id)
        overall_sections = (overall.template_data or {}).get("sections", [])
        data.setdefault("sections", [])
        data["sections"].extend(copy.deepcopy(overall_sections))
    except Exception:
        pass
    return data


@router.get("/templates/{test_type_id}")
def get_test_template(
    test_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the dynamic form template for a test type."""
    service = TestingService(db)
    return service.get_template(test_type_id)


@router.post("/{request_id}/results/structured", response_model=TestResultStructuredResponse)
def create_structured_result(
    request_id: UUID,
    data: TestResultStructuredCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit structured test results with JSONB data."""
    service = TestingService(db)
    result = service.create_structured_result(
        request_id=request_id,
        template_key=data.template_key,
        test_data=data.test_data,
        overall_result=data.overall_result,
        remarks=data.remarks,
        tester_id=current_user.id,
        replacement_products=data.replacement_products,
    )
    # Build response with images list
    return _build_structured_response(result)


@router.post("/results/{result_id}/images", response_model=List[TestResultImageResponse])
def upload_result_images(
    result_id: UUID,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload multiple images for a test result."""
    service = TestingService(db)
    images = service.upload_result_images(result_id, files, tester_id=current_user.id)
    return [
        TestResultImageResponse(
            id=img.id,
            file_name=img.file_name,
            file_type=img.file_type,
            file_size=img.file_size,
            caption=img.caption,
            download_url=f"/testing/results/images/{img.id}",
            cts=img.cts,
        )
        for img in images
    ]


@router.get("/results/images/{image_id}")
def download_result_image(
    image_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a single test result image."""
    service = TestingService(db)
    img = service.get_result_image(image_id)
    return Response(
        content=img.file_data,
        media_type=img.file_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{img.file_name}"'},
    )


def _build_structured_response(result) -> TestResultStructuredResponse:
    """Build a structured response with image metadata."""
    images = [
        TestResultImageResponse(
            id=img.id,
            file_name=img.file_name,
            file_type=img.file_type,
            file_size=img.file_size,
            caption=img.caption,
            download_url=f"/testing/results/images/{img.id}",
            cts=img.cts,
        )
        for img in (result.images or [])
    ]
    return TestResultStructuredResponse(
        id=result.id,
        testing_request_id=result.testing_request_id,
        test_name=result.test_name,
        template_key=result.template_key,
        test_data=result.test_data,
        overall_result=result.overall_result,
        remarks=result.remarks,
        replacement_products=result.replacement_products,
        tested_by=result.tested_by,
        tested_at=result.tested_at,
        images=images,
        cts=result.cts,
        mts=result.mts,
    )
