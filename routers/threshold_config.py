"""
Router: /threshold-config

Admin CRUD for the 4 lookup tables that back the configurable EHS
(Equipment Health Score) computation pipeline (KPTCL spec §12.1):

    /threshold-config/health-bands       -> EquipmentHealthBandThreshold
    /threshold-config/condition-scores   -> ParameterConditionScore
    /threshold-config/status-conditions  -> TestStatusCondition
    /threshold-config/condition-bands    -> EquipmentConditionBandThreshold

These replace the previously hardcoded _RISK_BANDS / _SCORE / _CONDITION
constants in services/analytics_engine.py, and the _condition_from_score
cutoffs in routers/ai_graph.py (see alter_equipment_health_band_threshold.py,
alter_parameter_condition_score.py, alter_test_status_condition.py,
alter_equipment_condition_band_threshold.py for the seed history). Menu-level
visibility is gated by the "Threshold Config" module (see
seed_threshold_config_module.py); this router itself only requires an
authenticated user, same as the other lookup-table CRUD routers (e.g.
equipment_type_kit_mappings.py).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    EquipmentConditionBandThreshold,
    EquipmentHealthBandThreshold,
    ParameterConditionScore,
    TestStatusCondition,
    User,
)

router = APIRouter(
    prefix="/threshold-config",
    tags=["threshold-config"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class HealthBandCreate(BaseModel):
    label: str
    threshold: float
    is_active: bool = True
    notes: Optional[str] = None


class HealthBandUpdate(BaseModel):
    label: Optional[str] = None
    threshold: Optional[float] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class HealthBandResponse(BaseModel):
    id: int
    label: str
    threshold: float
    is_active: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


class ConditionScoreCreate(BaseModel):
    condition: str
    score: float
    is_active: bool = True
    notes: Optional[str] = None


class ConditionScoreUpdate(BaseModel):
    condition: Optional[str] = None
    score: Optional[float] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class ConditionScoreResponse(BaseModel):
    id: int
    condition: str
    score: float
    is_active: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


class StatusConditionCreate(BaseModel):
    status: str
    condition_label: str
    is_active: bool = True
    notes: Optional[str] = None


class StatusConditionUpdate(BaseModel):
    status: Optional[str] = None
    condition_label: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class StatusConditionResponse(BaseModel):
    id: int
    status: str
    condition_label: str
    is_active: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


class ConditionBandCreate(BaseModel):
    label: str
    threshold: float
    is_active: bool = True
    notes: Optional[str] = None


class ConditionBandUpdate(BaseModel):
    label: Optional[str] = None
    threshold: Optional[float] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class ConditionBandResponse(BaseModel):
    id: int
    label: str
    threshold: float
    is_active: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


# ── Health bands ──────────────────────────────────────────────────────────────

@router.get("/health-bands", response_model=List[HealthBandResponse])
def list_health_bands(db: Session = Depends(get_db)):
    return (
        db.query(EquipmentHealthBandThreshold)
        .order_by(EquipmentHealthBandThreshold.threshold.desc())
        .all()
    )


@router.post(
    "/health-bands",
    response_model=HealthBandResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_health_band(
    payload: HealthBandCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.query(EquipmentHealthBandThreshold).filter(
        EquipmentHealthBandThreshold.label == payload.label
    ).first():
        raise HTTPException(status_code=409, detail="A band with this label already exists")

    row = EquipmentHealthBandThreshold(
        label=payload.label,
        threshold=payload.threshold,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/health-bands/{band_id}", response_model=HealthBandResponse)
def update_health_band(
    band_id: int,
    payload: HealthBandUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(EquipmentHealthBandThreshold).filter(
        EquipmentHealthBandThreshold.id == band_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Health band not found")

    data = payload.model_dump(exclude_unset=True)
    if "label" in data and data["label"] != row.label:
        if db.query(EquipmentHealthBandThreshold).filter(
            EquipmentHealthBandThreshold.label == data["label"],
            EquipmentHealthBandThreshold.id != band_id,
        ).first():
            raise HTTPException(status_code=409, detail="A band with this label already exists")
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return row


@router.delete("/health-bands/{band_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_health_band(band_id: int, db: Session = Depends(get_db)):
    row = db.query(EquipmentHealthBandThreshold).filter(
        EquipmentHealthBandThreshold.id == band_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Health band not found")
    db.delete(row)
    db.commit()


# ── Condition scores ──────────────────────────────────────────────────────────

@router.get("/condition-scores", response_model=List[ConditionScoreResponse])
def list_condition_scores(db: Session = Depends(get_db)):
    return db.query(ParameterConditionScore).order_by(ParameterConditionScore.score.desc()).all()


@router.post(
    "/condition-scores",
    response_model=ConditionScoreResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_condition_score(
    payload: ConditionScoreCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.query(ParameterConditionScore).filter(
        ParameterConditionScore.condition == payload.condition
    ).first():
        raise HTTPException(status_code=409, detail="A score for this condition already exists")

    row = ParameterConditionScore(
        condition=payload.condition,
        score=payload.score,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/condition-scores/{score_id}", response_model=ConditionScoreResponse)
def update_condition_score(
    score_id: int,
    payload: ConditionScoreUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ParameterConditionScore).filter(
        ParameterConditionScore.id == score_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Condition score not found")

    data = payload.model_dump(exclude_unset=True)
    if "condition" in data and data["condition"] != row.condition:
        if db.query(ParameterConditionScore).filter(
            ParameterConditionScore.condition == data["condition"],
            ParameterConditionScore.id != score_id,
        ).first():
            raise HTTPException(status_code=409, detail="A score for this condition already exists")
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return row


@router.delete("/condition-scores/{score_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_condition_score(score_id: int, db: Session = Depends(get_db)):
    row = db.query(ParameterConditionScore).filter(
        ParameterConditionScore.id == score_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Condition score not found")
    db.delete(row)
    db.commit()


# ── Status conditions ─────────────────────────────────────────────────────────

@router.get("/status-conditions", response_model=List[StatusConditionResponse])
def list_status_conditions(db: Session = Depends(get_db)):
    return db.query(TestStatusCondition).order_by(TestStatusCondition.id).all()


@router.post(
    "/status-conditions",
    response_model=StatusConditionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_status_condition(
    payload: StatusConditionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.query(TestStatusCondition).filter(
        TestStatusCondition.status == payload.status
    ).first():
        raise HTTPException(status_code=409, detail="A condition for this status already exists")

    row = TestStatusCondition(
        status=payload.status,
        condition_label=payload.condition_label,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/status-conditions/{condition_id}", response_model=StatusConditionResponse)
def update_status_condition(
    condition_id: int,
    payload: StatusConditionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(TestStatusCondition).filter(
        TestStatusCondition.id == condition_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Status condition not found")

    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] != row.status:
        if db.query(TestStatusCondition).filter(
            TestStatusCondition.status == data["status"],
            TestStatusCondition.id != condition_id,
        ).first():
            raise HTTPException(status_code=409, detail="A condition for this status already exists")
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return row


@router.delete("/status-conditions/{condition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_status_condition(condition_id: int, db: Session = Depends(get_db)):
    row = db.query(TestStatusCondition).filter(
        TestStatusCondition.id == condition_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Status condition not found")
    db.delete(row)
    db.commit()


# ── Condition bands (5-tier Excellent/Good/Fair/Poor/Critical scale used by
#    the AI Graph Dashboard - routers/ai_graph.py's _load_condition_bands) ────

@router.get("/condition-bands", response_model=List[ConditionBandResponse])
def list_condition_bands(db: Session = Depends(get_db)):
    return (
        db.query(EquipmentConditionBandThreshold)
        .order_by(EquipmentConditionBandThreshold.threshold.desc())
        .all()
    )


@router.post(
    "/condition-bands",
    response_model=ConditionBandResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_condition_band(
    payload: ConditionBandCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.query(EquipmentConditionBandThreshold).filter(
        EquipmentConditionBandThreshold.label == payload.label
    ).first():
        raise HTTPException(status_code=409, detail="A band with this label already exists")

    row = EquipmentConditionBandThreshold(
        label=payload.label,
        threshold=payload.threshold,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/condition-bands/{band_id}", response_model=ConditionBandResponse)
def update_condition_band(
    band_id: int,
    payload: ConditionBandUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(EquipmentConditionBandThreshold).filter(
        EquipmentConditionBandThreshold.id == band_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Condition band not found")

    data = payload.model_dump(exclude_unset=True)
    if "label" in data and data["label"] != row.label:
        if db.query(EquipmentConditionBandThreshold).filter(
            EquipmentConditionBandThreshold.label == data["label"],
            EquipmentConditionBandThreshold.id != band_id,
        ).first():
            raise HTTPException(status_code=409, detail="A band with this label already exists")
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return row


@router.delete("/condition-bands/{band_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_condition_band(band_id: int, db: Session = Depends(get_db)):
    row = db.query(EquipmentConditionBandThreshold).filter(
        EquipmentConditionBandThreshold.id == band_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Condition band not found")
    db.delete(row)
    db.commit()
