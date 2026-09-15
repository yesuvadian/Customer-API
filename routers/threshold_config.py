"""
Router: /threshold-config

Admin CRUD for the lookup tables that back the configurable EHS
(Equipment Health Score) computation pipeline (KPTCL spec §12.1), plus the
Data Quality Index rule toggles:

    /threshold-config/health-bands       -> EquipmentHealthBandThreshold
    /threshold-config/condition-scores   -> ParameterConditionScore
    /threshold-config/status-conditions  -> TestStatusCondition
    /threshold-config/condition-bands    -> EquipmentConditionBandThreshold
    /threshold-config/dqi-rules          -> DqiRuleConfig (key constrained to
                                            an allow-list, see DqiRuleCreate)

These replace the previously hardcoded _RISK_BANDS / _SCORE / _CONDITION
constants in services/analytics_engine.py, the _condition_from_score
cutoffs in routers/ai_graph.py, and the hardcoded DQI nameplate-field/
test-history/overdue-test checks in routers/dashboard_kpi.py (see
alter_equipment_health_band_threshold.py, alter_parameter_condition_score.py,
alter_test_status_condition.py, alter_equipment_condition_band_threshold.py,
alter_dqi_rule_config.py for the seed history). Menu-level visibility is
gated by the "Threshold Config" module (see seed_threshold_config_module.py);
this router itself only requires an authenticated user, same as the other
lookup-table CRUD routers (e.g. equipment_type_kit_mappings.py).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    DqiRuleConfig,
    EquipmentConditionBandThreshold,
    EquipmentHealthBandThreshold,
    ParameterConditionScore,
    TestStatusCondition,
    User,
    get_dqi_all_key_labels,
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


# DqiRuleConfig's `key` is still constrained server-side to
# get_dqi_all_key_labels() (models.py, discovered live from the Equipment
# model + the 2 special checks) — dashboard_kpi.py's DQI computation only
# knows how to evaluate exactly those keys — so unlike the 4 tables above,
# create takes a `key` but no arbitrary free-text is accepted for it.
class DqiRuleCreate(BaseModel):
    key: str
    label: Optional[str] = None  # defaults to get_dqi_all_key_labels()[key] if omitted
    is_active: bool = True
    notes: Optional[str] = None
    # None/empty = applies to every equipment type — see DqiRuleConfig's own
    # docstring in models.py for why this scoping exists at all.
    equipment_type_ids: Optional[List[int]] = None


class DqiRuleUpdate(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    equipment_type_ids: Optional[List[int]] = None


class DqiRuleResponse(BaseModel):
    id: int
    key: str
    label: str
    is_active: bool
    notes: Optional[str]
    equipment_type_ids: Optional[List[int]]

    class Config:
        from_attributes = True


class DqiAvailableKeyResponse(BaseModel):
    key: str
    label: str
    in_use: bool


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


# ── DQI rules (Data Quality Index checks — routers/dashboard_kpi.py) ──────────
# `key` is constrained to get_dqi_all_key_labels() (models.py) — see
# DqiRuleCreate's comment above — everything else (toggle/edit label+
# notes/delete) works like the 4 tables above.

@router.get("/dqi-rules", response_model=List[DqiRuleResponse])
def list_dqi_rules(db: Session = Depends(get_db)):
    return db.query(DqiRuleConfig).order_by(DqiRuleConfig.id).all()


@router.get("/dqi-rules/available-keys", response_model=List[DqiAvailableKeyResponse])
def list_dqi_available_keys(db: Session = Depends(get_db)):
    """Every key the DQI computation actually knows how to evaluate, plus
    whether a rule for it already exists — powers the "Add Rule" dropdown
    so the admin picks from real options instead of typing a key that would
    silently never match anything in dashboard_kpi.py.
    """
    used = {row[0] for row in db.query(DqiRuleConfig.key).all()}
    return [
        {"key": k, "label": v, "in_use": k in used}
        for k, v in get_dqi_all_key_labels(db).items()
    ]


@router.post(
    "/dqi-rules",
    response_model=DqiRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dqi_rule(
    payload: DqiRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    available_keys = get_dqi_all_key_labels(db)
    if payload.key not in available_keys:
        raise HTTPException(
            status_code=400,
            detail=f"'{payload.key}' isn't a key the Data Quality computation "
                   f"knows how to evaluate.",
        )
    if db.query(DqiRuleConfig).filter(DqiRuleConfig.key == payload.key).first():
        raise HTTPException(status_code=409, detail="A rule for this key already exists")

    row = DqiRuleConfig(
        key=payload.key,
        label=payload.label or available_keys[payload.key],
        is_active=payload.is_active,
        notes=payload.notes,
        equipment_type_ids=payload.equipment_type_ids or None,
        created_by=current_user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # The .first() check above isn't atomic with this insert — a
        # concurrent request for the same key can still slip past it and
        # hit uq_dqi_rule_key here. Same intended 409 either way, not a 500.
        db.rollback()
        raise HTTPException(status_code=409, detail="A rule for this key already exists")
    db.refresh(row)
    return row


@router.patch("/dqi-rules/{rule_id}", response_model=DqiRuleResponse)
def update_dqi_rule(
    rule_id: int,
    payload: DqiRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(DqiRuleConfig).filter(DqiRuleConfig.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="DQI rule not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return row


@router.delete("/dqi-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dqi_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.query(DqiRuleConfig).filter(DqiRuleConfig.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="DQI rule not found")
    db.delete(row)
    db.commit()
