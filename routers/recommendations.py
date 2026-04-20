from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, Recommendation, TestResult
from schemas import RecommendationCreate, RecommendationUpdate, RecommendationResponse
from services.recommendation_service import RecommendationService
from services.recommendation_pdf_service import RecommendationPDFService

router = APIRouter(
    prefix="/recommendations",
    tags=["recommendations"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/", response_model=RecommendationResponse)
def create_recommendation(
    data: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.create_recommendation(
        testing_request_id=data.testing_request_id,
        recommendation_type=data.recommendation_type,
        summary=data.summary,
        submitted_by=current_user.id,
        detailed_notes=data.detailed_notes,
    )


@router.get("/", response_model=List[RecommendationResponse])
def list_recommendations(
    testing_request_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    # Filter by organization to prevent cross-organization data leakage
    organization_id = current_user.organization_id
    return service.get_recommendations(
        testing_request_id=testing_request_id,
        organization_id=organization_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
def get_recommendation(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.get_recommendation(recommendation_id)


@router.get("/{recommendation_id}/detail")
def get_recommendation_detail(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns recommendation + test results (with field_labels) for Flutter detail view."""
    from fastapi import HTTPException
    rec = db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    results = (
        db.query(TestResult)
        .filter(TestResult.testing_request_id == rec.testing_request_id)
        .order_by(TestResult.cts.asc())
        .all()
    )

    def _user_name(user_id):
        if not user_id:
            return None
        from models import User as U
        u = db.query(U).filter(U.id == user_id).first()
        if u:
            return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email
        return str(user_id)

    def _field_labels(template_key):
        labels = {}
        if not template_key:
            return labels
        try:
            from models import OrgTestTemplate
            tmpl = db.query(OrgTestTemplate).filter(OrgTestTemplate.template_key == template_key).first()
            data = tmpl.template_data if tmpl and tmpl.template_data else {}
            if not data:
                from test_templates import get_template_by_key
                data = get_template_by_key(template_key) or {}
            for sec in data.get("sections", []):
                for f in sec.get("fields", []):
                    labels[f["key"]] = f.get("label", f["key"])
        except Exception:
            pass
        return labels

    test_results = []
    for r in results:
        test_results.append({
            "id": str(r.id),
            "test_name": r.test_name,
            "template_key": r.template_key,
            "test_data": r.test_data,
            "field_labels": _field_labels(r.template_key),
            "overall_result": r.overall_result,
            "remarks": r.remarks,
            "tested_by_name": _user_name(r.tested_by),
            "tested_at": r.tested_at.isoformat() if r.tested_at else None,
            "image_count": len(r.images) if r.images else 0,
        })

    return {
        "id": str(rec.id),
        "testing_request_id": str(rec.testing_request_id),
        "recommendation_type": rec.recommendation_type.value if rec.recommendation_type else None,
        "summary": rec.summary,
        "detailed_notes": rec.detailed_notes,
        "approval_status": rec.approval_status,
        "approved_by": str(rec.approved_by) if rec.approved_by else None,
        "approved_by_name": _user_name(rec.approved_by),
        "approved_at": rec.approved_at.isoformat() if rec.approved_at else None,
        "approval_notes": rec.approval_notes,
        "submitted_by": str(rec.submitted_by) if rec.submitted_by else None,
        "submitted_by_name": _user_name(rec.submitted_by),
        "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
        "cts": rec.cts.isoformat() if rec.cts else None,
        "mts": rec.mts.isoformat() if rec.mts else None,
        "replacement_products": rec.replacement_products,
        "test_results": test_results,
    }


@router.put("/{recommendation_id}", response_model=RecommendationResponse)
def update_recommendation(
    recommendation_id: UUID,
    data: RecommendationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecommendationService(db)
    return service.update_recommendation(
        recommendation_id, data.dict(exclude_unset=True), modified_by=current_user.id
    )


@router.get("/{recommendation_id}/pdf")
def download_recommendation_pdf(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and download test report PDF with approval details"""
    # Generate test report PDF with approval information
    pdf_service = RecommendationPDFService(db)
    pdf_buffer = pdf_service.generate_pdf(str(recommendation_id))

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=test_report_{recommendation_id}.pdf"
        }
    )
