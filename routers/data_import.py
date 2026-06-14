"""
Data Import Router — upload PDF/Excel → extract records → review → submit as closed TRs.

Endpoints:
  GET  /data-import/categories              — list categories with test types
  POST /data-import/extract                 — upload file, get extracted records
  POST /data-import/preview-form            — build pre-filled form data for one record
  POST /data-import/submit                  — batch-create TRs from reviewed records
"""

from __future__ import annotations

import traceback
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    CategoryDetails,
    OrgDepartment,
    Organization,
    TestingRequest,
    TestingRequestStatus,
    User,
)
from services.import_extractor_service import (
    IMPORT_CATEGORIES,
    build_form_data,
    extract_records,
    get_template_key,
    get_test_types_for_category,
    resolve_equipment,
)

router = APIRouter(
    prefix="/data-import",
    tags=["data-import"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ExtractedRecord(BaseModel):
    index: int
    report: dict                        # raw extractor output
    serial_number: Optional[str] = None
    test_date: Optional[str] = None
    sub_station: Optional[str] = None
    equipment_found: bool = False
    equipment_id: Optional[str] = None
    equipment_ueic: Optional[str] = None
    form_data: Optional[dict] = None    # pre-built form values
    warnings: List[str] = []


class PreviewFormRequest(BaseModel):
    report: dict
    test_type_name: str
    equipment_id: Optional[UUID] = None


class SubmitRecord(BaseModel):
    report: dict
    form_data: dict
    test_type_name: str
    equipment_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    overall_result: str = "pass"
    remarks: Optional[str] = None


class SubmitRequest(BaseModel):
    records: List[SubmitRecord]
    category: str = "test"


class SubmitResultItem(BaseModel):
    index: int
    success: bool
    tr_id: Optional[str] = None
    request_number: Optional[str] = None
    serial_number: Optional[str] = None
    error: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/categories")
def list_categories(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return all import categories with their available test types."""
    result = []
    for key, cfg in IMPORT_CATEGORIES.items():
        test_types = get_test_types_for_category(key, db)
        result.append({
            "key": key,
            "label": cfg["label"],
            "request_category": cfg["request_category"],
            "test_types": test_types,
        })
    return result


@router.post("/extract", status_code=status.HTTP_200_OK)
async def extract_file(
    file: UploadFile = File(...),
    test_type_name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a PDF or Excel file and extract all records from it.

    Returns a list of ExtractedRecord objects — one per report found in the file.
    Each record includes the raw report dict, auto-matched equipment info,
    pre-built form_data, and any extraction warnings.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    records_raw, global_warnings = extract_records(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        test_type_name=test_type_name,
    )

    if global_warnings and not records_raw:
        raise HTTPException(status_code=422, detail="; ".join(global_warnings))

    results: list[dict] = []
    for idx, report in enumerate(records_raw):
        serial = report.get("serial_number") or ""
        rec_warnings: list[str] = list(global_warnings)

        eq = resolve_equipment(serial or None, None, db)
        eq_found = eq is not None

        if serial and not eq_found:
            rec_warnings.append(
                f"Equipment with serial '{serial}' not found in asset register. "
                "Please select equipment manually before submitting."
            )

        # Build form_data using the template builder (mirrors seed scripts)
        try:
            form_data = build_form_data(report, test_type_name, eq)
        except Exception:
            form_data = report
            rec_warnings.append("Form template could not be applied — raw values shown.")

        results.append(
            ExtractedRecord(
                index=idx,
                report=report,
                serial_number=serial or None,
                test_date=report.get("test_date") or None,
                sub_station=report.get("sub_station") or None,
                equipment_found=eq_found,
                equipment_id=str(eq.id) if eq else None,
                equipment_ueic=eq.ueic if eq else None,
                form_data=form_data,
                warnings=rec_warnings,
            ).model_dump()
        )

    return {
        "total": len(results),
        "filename": file.filename,
        "test_type_name": test_type_name,
        "records": results,
    }


@router.post("/preview-form")
def preview_form(
    body: PreviewFormRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Build (or rebuild) the pre-filled form_data for a single report dict."""
    eq = None
    if body.equipment_id:
        from models import Equipment
        eq = db.query(Equipment).filter(Equipment.id == body.equipment_id).first()
        if not eq:
            raise HTTPException(status_code=404, detail="Equipment not found.")

    if not eq:
        serial = body.report.get("serial_number")
        eq = resolve_equipment(serial, None, db)

    try:
        form_data = build_form_data(body.report, body.test_type_name, eq)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Form build failed: {e}")

    template_key = get_template_key(body.test_type_name)
    equipment_info = None
    if eq:
        dept = getattr(eq, "department", None)
        equipment_info = {
            "id": str(eq.id),
            "ueic": eq.ueic,
            "serial_number": eq.factory_serial_number,
            "manufacturer": getattr(eq, "manufacturer", None),
            "department_id": str(dept.id) if dept else None,
            "department_name": dept.name if dept else None,
            "organization_id": str(eq.organization_id) if eq.organization_id else None,
        }

    return {
        "form_data": form_data,
        "template_key": template_key,
        "equipment_info": equipment_info,
    }


@router.post("/submit")
def submit_import(
    body: SubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Batch-submit reviewed import records as closed TestingRequests.

    Each record goes through the full TR lifecycle:
      draft → in_progress → test result created → recommendation → closed

    Failures on individual records are isolated and reported; other records continue.
    """
    from services.testing_request_service import TestingRequestService
    from services.testing_service import TestingService
    from services.recommendation_service import RecommendationService

    tr_svc = TestingRequestService(db)
    tst_svc = TestingService(db)
    rec_svc = RecommendationService(db)

    results: list[dict] = []

    for idx, rec in enumerate(body.records):
        serial = rec.report.get("serial_number", "").strip()
        test_date_str = rec.report.get("test_date")
        sub_station = rec.report.get("sub_station", "")

        try:
            # ── Resolve equipment ────────────────────────────────────────────
            eq = resolve_equipment(serial or None, rec.equipment_id, db)
            if not eq:
                results.append(SubmitResultItem(
                    index=idx, success=False, serial_number=serial,
                    error=f"Equipment '{serial}' not found. Assign equipment_id manually."
                ).model_dump())
                continue

            # ── Resolve test type ────────────────────────────────────────────
            test_type = db.query(CategoryDetails).filter(
                CategoryDetails.name == rec.test_type_name
            ).first()
            if not test_type:
                results.append(SubmitResultItem(
                    index=idx, success=False, serial_number=serial,
                    error=f"Test type '{rec.test_type_name}' not found in database."
                ).model_dump())
                continue

            template_key = get_template_key(rec.test_type_name)
            if not template_key:
                results.append(SubmitResultItem(
                    index=idx, success=False, serial_number=serial,
                    error=f"No template mapped for test type '{rec.test_type_name}'."
                ).model_dump())
                continue

            # ── Resolve org / department ─────────────────────────────────────
            org_id = rec.organization_id or eq.organization_id
            dept_id = rec.department_id
            if not dept_id and eq.department:
                dept_id = eq.department.id

            if not org_id:
                org = db.query(Organization).first()
                org_id = org.id if org else None

            # ── Parse test date ───────────────────────────────────────────────
            from datetime import datetime, timezone
            tested_at = None
            if test_date_str:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y"):
                    try:
                        tested_at = datetime.strptime(test_date_str, fmt).replace(
                            tzinfo=timezone.utc
                        )
                        break
                    except ValueError:
                        continue
            if not tested_at:
                tested_at = datetime.now(timezone.utc)

            # ── Idempotency check ─────────────────────────────────────────────
            import_tag = f"IMP-{tested_at.strftime('%Y%m%d')}-{serial}-{template_key[:8].upper()}"
            existing = (
                db.query(TestingRequest)
                .filter(TestingRequest.notes.contains(import_tag))
                .first()
            )
            if existing:
                results.append(SubmitResultItem(
                    index=idx, success=True,
                    tr_id=str(existing.id),
                    request_number=existing.request_number,
                    serial_number=serial,
                    error="Already imported (skipped duplicate).",
                ).model_dump())
                continue

            # ── Rebuild form_data if caller didn't provide it ────────────────
            form_data = rec.form_data
            if not form_data:
                form_data = build_form_data(rec.report, rec.test_type_name, eq)

            remarks = rec.remarks or f"Imported from file. Sub-station: {sub_station}."

            # ── Create TR (draft) ────────────────────────────────────────────
            tr = tr_svc.create_request(
                data={
                    "title": (
                        f"{rec.test_type_name} — "
                        f"{eq.factory_serial_number or eq.ueic}"
                        f" ({tested_at.strftime('%Y-%m-%d')})"
                    ),
                    "description": f"Imported from file. Serial: {serial}. Sub-station: {sub_station}.",
                    "equipment_id": eq.id,
                    "equipment_type_id": eq.equipment_type_id,
                    "test_type_id": test_type.id,
                    "organization_id": org_id,
                    "department_id": dept_id,
                    "assigned_tester_id": current_user.id,
                    "requested_date": tested_at,
                    "scheduled_start_date": tested_at,
                    "request_category": body.category,
                    "notes": f"[{import_tag}] Data import by {current_user.email}.",
                },
                originator_id=current_user.id,
            )

            # ── Advance to in_progress ────────────────────────────────────────
            tr.status = TestingRequestStatus.in_progress
            tr.completed_at = tested_at
            db.flush()

            # ── Create test result ────────────────────────────────────────────
            from sqlalchemy.exc import InvalidRequestError
            try:
                tst_svc.create_structured_result(
                    request_id=tr.id,
                    template_key=template_key,
                    test_data=form_data,
                    overall_result=rec.overall_result,
                    remarks=remarks,
                    tester_id=current_user.id,
                )
            except InvalidRequestError:
                db.expire_all()

            # Backdate test result to historical date
            from sqlalchemy import text
            db.execute(
                text(
                    "UPDATE public.test_results "
                    "SET tested_at = :d WHERE testing_request_id = :rid"
                ),
                {"d": tested_at, "rid": tr.id},
            )
            db.flush()

            # ── Create recommendation ─────────────────────────────────────────
            recommendation = rec_svc.create_recommendation(
                testing_request_id=tr.id,
                recommendation_type=rec.overall_result,
                summary=f"{rec.overall_result.capitalize()} — {remarks}",
                submitted_by=current_user.id,
                next_action="none",
            )

            # ── Close TR ──────────────────────────────────────────────────────
            tr.status = TestingRequestStatus.closed
            recommendation.approval_status = "approved"
            recommendation.approved_by = current_user.id
            recommendation.approved_at = tested_at
            db.commit()

            results.append(SubmitResultItem(
                index=idx,
                success=True,
                tr_id=str(tr.id),
                request_number=tr.request_number,
                serial_number=serial,
            ).model_dump())

        except Exception as exc:
            db.rollback()
            results.append(SubmitResultItem(
                index=idx,
                success=False,
                serial_number=serial,
                error=str(exc),
            ).model_dump())

    total_ok = sum(1 for r in results if r["success"])
    return {
        "submitted": len(body.records),
        "created": total_ok,
        "failed": len(body.records) - total_ok,
        "results": results,
    }
