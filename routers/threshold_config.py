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
    /threshold-config/calibration-configs -> EquipmentCalibrationConfig, one
                                            row per equipment (lead_days +
                                            is_scheduled), org-scoped via the
                                            equipment it belongs to — unlike
                                            the global lookup tables above.
    /threshold-config/expected-life      -> EquipmentExpectedLife (AI Graph
                                            Dashboard expected service life
                                            per equipment-type keyword)
    /threshold-config/ageing-config      -> AgeingConfig, global singleton
                                            (GET/PUT): default expected life,
                                            life-stage cutoffs, ageing radar
                                            benchmark — see alter_ageing_config.py

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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    AgeingConfig,
    DqiRuleConfig,
    Equipment,
    EquipmentCalibrationConfig,
    EquipmentConditionBandThreshold,
    EquipmentExpectedLife,
    EquipmentHealthBandThreshold,
    FailureCohortThresholdConfig,
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


class FailureCohortThresholdUpdate(BaseModel):
    min_failure_rate: Optional[float] = None
    min_cohort_units: Optional[int] = None
    outlier_z_score: Optional[float] = None


class FailureCohortThresholdResponse(BaseModel):
    min_failure_rate: float
    min_cohort_units: int
    outlier_z_score: float
    # True when this org has its own override row; False means the value
    # shown is the inherited system-wide default -- lets the UI show
    # "(default)" vs "(customized)" without a second round trip.
    is_org_override: bool


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


# ── Failure cohort thresholds ───────────────────────────────────────────────
# Singleton per org, not a list like the tables above -- GET/PUT, not full
# CRUD. See FailureCohortThresholdConfig's own docstring for the
# org-override -> system-default lookup chain.

@router.get("/failure-cohort-thresholds", response_model=FailureCohortThresholdResponse)
def get_failure_cohort_thresholds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_row = (
        db.query(FailureCohortThresholdConfig)
        .filter(FailureCohortThresholdConfig.organization_id == current_user.organization_id)
        .first()
    )
    if org_row:
        return FailureCohortThresholdResponse(
            min_failure_rate=float(org_row.min_failure_rate),
            min_cohort_units=org_row.min_cohort_units,
            outlier_z_score=float(org_row.outlier_z_score),
            is_org_override=True,
        )

    default_row = (
        db.query(FailureCohortThresholdConfig)
        .filter(FailureCohortThresholdConfig.organization_id.is_(None))
        .first()
    )
    if not default_row:
        raise HTTPException(
            status_code=500,
            detail="No system-wide default configured -- run alter_failure_cohort_threshold_config.py",
        )
    return FailureCohortThresholdResponse(
        min_failure_rate=float(default_row.min_failure_rate),
        min_cohort_units=default_row.min_cohort_units,
        outlier_z_score=float(default_row.outlier_z_score),
        is_org_override=False,
    )


@router.put("/failure-cohort-thresholds", response_model=FailureCohortThresholdResponse)
def update_failure_cohort_thresholds(
    payload: FailureCohortThresholdUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates this org's own override row on first edit (get-or-create) --
    every org starts on the inherited system-wide default and only
    diverges once an admin here actually changes something."""
    row = (
        db.query(FailureCohortThresholdConfig)
        .filter(FailureCohortThresholdConfig.organization_id == current_user.organization_id)
        .first()
    )
    if not row:
        default_row = (
            db.query(FailureCohortThresholdConfig)
            .filter(FailureCohortThresholdConfig.organization_id.is_(None))
            .first()
        )
        row = FailureCohortThresholdConfig(
            organization_id=current_user.organization_id,
            min_failure_rate=default_row.min_failure_rate if default_row else 1.0,
            min_cohort_units=default_row.min_cohort_units if default_row else 4,
            outlier_z_score=default_row.outlier_z_score if default_row else 3.0,
        )
        db.add(row)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return FailureCohortThresholdResponse(
        min_failure_rate=float(row.min_failure_rate),
        min_cohort_units=row.min_cohort_units,
        outlier_z_score=float(row.outlier_z_score),
        is_org_override=True,
    )


@router.delete("/failure-cohort-thresholds", status_code=status.HTTP_204_NO_CONTENT)
def reset_failure_cohort_thresholds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Removes this org's override row so it falls back to the system-wide
    default again -- a no-op (not a 404) if there was no override to begin
    with, since "already at default" is the same end state either way."""
    row = (
        db.query(FailureCohortThresholdConfig)
        .filter(FailureCohortThresholdConfig.organization_id == current_user.organization_id)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()


@router.delete("/dqi-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dqi_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.query(DqiRuleConfig).filter(DqiRuleConfig.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="DQI rule not found")
    db.delete(row)
    db.commit()


# ── Calibration configs ─────────────────────────────────────────────────────
# EquipmentCalibrationConfig is per-EQUIPMENT (unique on equipment_id), not a
# label-keyed lookup table like the sections above — so it's addressed by
# equipment_id, and a PUT does the create-or-update ("upsert") a singleton
# config naturally calls for, rather than separate POST/PATCH-by-row-id.
# Org-scoped via the equipment it belongs to (every other section in this
# file is a global, org-agnostic table — this is the one exception).

class CalibrationConfigUpsert(BaseModel):
    lead_days: int = 30
    is_scheduled: bool = True


class CalibrationConfigResponse(BaseModel):
    id: Optional[UUID] = None
    equipment_id: UUID
    equipment_label: str
    lead_days: int
    is_scheduled: bool
    # None when no explicit override row exists yet — the effective
    # lead_days/is_scheduled above are still the real values (defaults),
    # this just tells the UI whether there's a row here to edit/delete.
    has_override: bool


def _calibration_org_id(current_user: User) -> UUID:
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization to access calibration configs",
        )
    return current_user.organization_id


@router.get("/calibration-configs", response_model=List[CalibrationConfigResponse])
def list_calibration_configs(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A triage queue of equipment whose LATEST calibration result is Fail
    (CalibrationService.get_calibration_status(...)["state"] ==
    "CRITICAL"), not a config screen for every calibration-tracked piece
    of equipment. Deliberately does NOT filter on
    EquipmentCalibrationConfig.is_scheduled — confirmed live that flag
    drifts out of sync with the actual latest result (its own update path,
    evaluate_calibration()/_handle_fail(), is invoked fire-and-forget from
    testing_service.py wrapped in a bare try/except that swallows any
    error, so a failed write there leaves is_scheduled=True even though
    the equipment is genuinely still failing). get_calibration_status()
    recomputes "state" straight from the latest TestResult every call, so
    it can't drift the way a separately-persisted flag can: the row
    appears the moment a result comes back Fail and disappears the moment
    a later result comes back Pass, regardless of is_scheduled's state.

    Equipment never appears here until it fails once — lead_days for
    equipment that hasn't failed yet isn't editable from this screen.
    """
    from models import TestingRequest
    from services.calibration_service import CalibrationService

    org_id = _calibration_org_id(current_user)
    q = (
        db.query(Equipment)
        .filter(
            Equipment.organization_id == org_id,
            Equipment.id.in_(
                db.query(TestingRequest.equipment_id).filter(
                    TestingRequest.organization_id == org_id,
                    TestingRequest.is_calibration.is_(True),
                    TestingRequest.equipment_id.isnot(None),
                ).distinct()
            ),
        )
    )
    if search:
        q = q.filter(Equipment.ueic.ilike(f"%{search}%"))
    equipment_rows = q.order_by(Equipment.ueic.asc()).all()

    svc = CalibrationService(db)
    configs_by_equipment = {
        c.equipment_id: c
        for c in db.query(EquipmentCalibrationConfig)
        .filter(EquipmentCalibrationConfig.equipment_id.in_([e.id for e in equipment_rows]))
        .all()
    }

    out = []
    for eq in equipment_rows:
        status = svc.get_calibration_status(eq.id)
        if status["state"] != "CRITICAL":
            continue
        cfg = configs_by_equipment.get(eq.id)
        out.append(CalibrationConfigResponse(
            id=cfg.id if cfg else None,
            equipment_id=eq.id,
            equipment_label=eq.ueic,
            lead_days=cfg.lead_days if cfg else 30,
            is_scheduled=cfg.is_scheduled if cfg else True,
            has_override=cfg is not None,
        ))

    return out[offset:offset + limit]


@router.put("/calibration-configs/{equipment_id}", response_model=CalibrationConfigResponse)
def upsert_calibration_config(
    equipment_id: UUID,
    payload: CalibrationConfigUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _calibration_org_id(current_user)
    equipment = (
        db.query(Equipment)
        .filter(Equipment.id == equipment_id, Equipment.organization_id == org_id)
        .first()
    )
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    if payload.lead_days < 0:
        raise HTTPException(status_code=422, detail="lead_days cannot be negative")

    cfg = (
        db.query(EquipmentCalibrationConfig)
        .filter(EquipmentCalibrationConfig.equipment_id == equipment_id)
        .first()
    )
    if cfg:
        cfg.lead_days = payload.lead_days
        cfg.is_scheduled = payload.is_scheduled
    else:
        cfg = EquipmentCalibrationConfig(
            equipment_id=equipment_id,
            lead_days=payload.lead_days,
            is_scheduled=payload.is_scheduled,
            created_by=current_user.id,
        )
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return CalibrationConfigResponse(
        id=cfg.id,
        equipment_id=equipment.id,
        equipment_label=equipment.ueic,
        lead_days=cfg.lead_days,
        is_scheduled=cfg.is_scheduled,
        has_override=True,
    )


@router.delete("/calibration-configs/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calibration_config(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Removes the explicit override row so this equipment falls back to
    the system default (lead_days=30, is_scheduled=True) again — a no-op
    (not a 404) if there was no override to begin with, matching
    reset_failure_cohort_thresholds' own "already at default" reasoning."""
    org_id = _calibration_org_id(current_user)
    cfg = (
        db.query(EquipmentCalibrationConfig)
        .join(Equipment, Equipment.id == EquipmentCalibrationConfig.equipment_id)
        .filter(
            EquipmentCalibrationConfig.equipment_id == equipment_id,
            Equipment.organization_id == org_id,
        )
        .first()
    )
    if cfg:
        db.delete(cfg)
        db.commit()


# ── Expected life + ageing settings (AI Graph Dashboard — routers/ai_graph.py's
#    _load_expected_life / _load_ageing_config) ───────────────────────────────
# Replace the previously hardcoded _TYPE_LIFE / _DEFAULT_LIFE, the /grouped
# life-stage cutoffs and the /ageing radar benchmark. Both tables are global
# (not org-scoped), like the band/score tables above. Created + seeded by
# alter_ageing_config.py; until it's run these endpoints answer 503 with that
# hint (ai_graph.py itself keeps working on its hardcoded fallbacks meanwhile).

_AGEING_SETUP_HINT = (
    "Ageing configuration tables don't exist yet -- run alter_ageing_config.py"
)

# Same values alter_ageing_config.py seeds / ai_graph.py falls back to.
_AGEING_DEFAULTS = dict(
    default_expected_life_years=30.0,
    life_stage_mid=0.5,
    life_stage_near_end=0.8,
    life_stage_overdue=1.0,
    benchmark_aging_rate=30.0,
    benchmark_volatility=25.0,
    benchmark_life_left_risk=35.0,
    benchmark_thermal_stress=25.0,
    benchmark_load_factor=30.0,
)
_BENCHMARK_FIELDS = (
    "benchmark_aging_rate", "benchmark_volatility", "benchmark_life_left_risk",
    "benchmark_thermal_stress", "benchmark_load_factor",
)


def _ageing_table_missing(db: Session) -> HTTPException:
    db.rollback()
    return HTTPException(status_code=503, detail=_AGEING_SETUP_HINT)


class ExpectedLifeCreate(BaseModel):
    match_pattern: str
    expected_life_years: float
    sort_order: int = 0
    is_active: bool = True
    notes: Optional[str] = None


class ExpectedLifeUpdate(BaseModel):
    match_pattern: Optional[str] = None
    expected_life_years: Optional[float] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class ExpectedLifeResponse(BaseModel):
    id: int
    match_pattern: str
    expected_life_years: float
    sort_order: int
    is_active: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


class AgeingConfigUpdate(BaseModel):
    default_expected_life_years: Optional[float] = None
    life_stage_mid: Optional[float] = None
    life_stage_near_end: Optional[float] = None
    life_stage_overdue: Optional[float] = None
    benchmark_aging_rate: Optional[float] = None
    benchmark_volatility: Optional[float] = None
    benchmark_life_left_risk: Optional[float] = None
    benchmark_thermal_stress: Optional[float] = None
    benchmark_load_factor: Optional[float] = None
    notes: Optional[str] = None


class AgeingConfigResponse(BaseModel):
    default_expected_life_years: float
    life_stage_mid: float
    life_stage_near_end: float
    life_stage_overdue: float
    benchmark_aging_rate: float
    benchmark_volatility: float
    benchmark_life_left_risk: float
    benchmark_thermal_stress: float
    benchmark_load_factor: float
    notes: Optional[str] = None
    # False = no row saved yet; the values shown are the built-in defaults
    # ai_graph.py is currently using (same idea as is_org_override above).
    is_configured: bool


def _validate_life_years(v: float, what: str = "Expected life") -> None:
    if not (0 < v <= 1000):
        raise HTTPException(
            status_code=422,
            detail=f"{what} must be greater than 0 (and at most 1000 years)",
        )


def _clean_pattern(v: Optional[str]) -> str:
    v = (v or "").strip()
    if not v:
        raise HTTPException(status_code=422, detail="Match pattern is required")
    if len(v) > 100:
        raise HTTPException(status_code=422, detail="Match pattern must be at most 100 characters")
    return v


def _pattern_taken(db: Session, pattern: str, exclude_id: Optional[int] = None) -> bool:
    # Case-insensitive, since matching against the equipment type name is.
    q = db.query(EquipmentExpectedLife).filter(
        func.lower(EquipmentExpectedLife.match_pattern) == pattern.lower()
    )
    if exclude_id is not None:
        q = q.filter(EquipmentExpectedLife.id != exclude_id)
    return q.first() is not None


@router.get("/expected-life", response_model=List[ExpectedLifeResponse])
def list_expected_life(db: Session = Depends(get_db)):
    """Rules in match order — the first active rule whose pattern is a
    substring of the equipment type name wins (see ai_graph._expected_life)."""
    try:
        return (
            db.query(EquipmentExpectedLife)
            .order_by(EquipmentExpectedLife.sort_order.asc(), EquipmentExpectedLife.id.asc())
            .all()
        )
    except ProgrammingError:
        raise _ageing_table_missing(db)


@router.post(
    "/expected-life",
    response_model=ExpectedLifeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_expected_life(
    payload: ExpectedLifeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pattern = _clean_pattern(payload.match_pattern)
    _validate_life_years(payload.expected_life_years)
    try:
        taken = _pattern_taken(db, pattern)
    except ProgrammingError:
        raise _ageing_table_missing(db)
    if taken:
        raise HTTPException(status_code=409, detail="A rule with this match pattern already exists")

    row = EquipmentExpectedLife(
        match_pattern=pattern,
        expected_life_years=payload.expected_life_years,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Same race as create_dqi_rule: the .first() check isn't atomic.
        db.rollback()
        raise HTTPException(status_code=409, detail="A rule with this match pattern already exists")
    db.refresh(row)
    return row


# PATCH like the other tables' row updates; PUT accepted too (same partial
# semantics) for callers that prefer it.
@router.api_route(
    "/expected-life/{rule_id}",
    methods=["PUT", "PATCH"],
    response_model=ExpectedLifeResponse,
)
def update_expected_life(
    rule_id: int,
    payload: ExpectedLifeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        row = db.query(EquipmentExpectedLife).filter(EquipmentExpectedLife.id == rule_id).first()
    except ProgrammingError:
        raise _ageing_table_missing(db)
    if not row:
        raise HTTPException(status_code=404, detail="Expected life rule not found")

    data = payload.model_dump(exclude_unset=True)
    if "match_pattern" in data:
        data["match_pattern"] = _clean_pattern(data["match_pattern"])
        if _pattern_taken(db, data["match_pattern"], exclude_id=rule_id):
            raise HTTPException(status_code=409, detail="A rule with this match pattern already exists")
    if "expected_life_years" in data:
        if data["expected_life_years"] is None:
            raise HTTPException(status_code=422, detail="Expected life is required")
        _validate_life_years(data["expected_life_years"])
    for nn in ("sort_order", "is_active"):
        if nn in data and data[nn] is None:
            data.pop(nn)
    for field, value in data.items():
        setattr(row, field, value)
    row.modified_by = current_user.id

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A rule with this match pattern already exists")
    db.refresh(row)
    return row


@router.delete("/expected-life/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expected_life(rule_id: int, db: Session = Depends(get_db)):
    try:
        row = db.query(EquipmentExpectedLife).filter(EquipmentExpectedLife.id == rule_id).first()
    except ProgrammingError:
        raise _ageing_table_missing(db)
    if not row:
        raise HTTPException(status_code=404, detail="Expected life rule not found")
    db.delete(row)
    db.commit()


def _ageing_response(row: Optional[AgeingConfig]) -> AgeingConfigResponse:
    if row is None:
        return AgeingConfigResponse(**_AGEING_DEFAULTS, notes=None, is_configured=False)
    return AgeingConfigResponse(
        **{k: float(getattr(row, k)) for k in _AGEING_DEFAULTS},
        notes=row.notes,
        is_configured=True,
    )


@router.get("/ageing-config", response_model=AgeingConfigResponse)
def get_ageing_config(db: Session = Depends(get_db)):
    try:
        row = db.query(AgeingConfig).order_by(AgeingConfig.id.asc()).first()
    except ProgrammingError:
        raise _ageing_table_missing(db)
    return _ageing_response(row)


@router.put("/ageing-config", response_model=AgeingConfigResponse)
def update_ageing_config(
    payload: AgeingConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partial update of the single global row (created on first save from
    the built-in defaults — get-or-create, like update_failure_cohort_thresholds).
    Validated on the MERGED values, so e.g. raising only near_end above the
    stored overdue cutoff is rejected."""
    try:
        row = db.query(AgeingConfig).order_by(AgeingConfig.id.asc()).first()
    except ProgrammingError:
        raise _ageing_table_missing(db)

    current = (
        {k: float(getattr(row, k)) for k in _AGEING_DEFAULTS} if row else dict(_AGEING_DEFAULTS)
    )
    data = payload.model_dump(exclude_unset=True)
    notes_set = "notes" in data
    notes = data.pop("notes", None)
    for k, v in data.items():
        if v is None:
            raise HTTPException(status_code=422, detail=f"{k} cannot be empty")
    merged = {**current, **data}

    _validate_life_years(merged["default_expected_life_years"], "Default expected life")
    # Columns are Numeric(6,3): validate the values as they'll be stored,
    # or e.g. 0.7999 < 0.8 passes and then both save as 0.800.
    for _k in ("life_stage_mid", "life_stage_near_end", "life_stage_overdue"):
        merged[_k] = round(float(merged[_k]), 3)
        if _k in data:
            data[_k] = merged[_k]
    mid = merged["life_stage_mid"]
    near_end = merged["life_stage_near_end"]
    overdue = merged["life_stage_overdue"]
    if not (0 < mid < near_end <= overdue):
        raise HTTPException(
            status_code=422,
            detail="Life-stage cutoffs must satisfy 0 < Mid-life < Near end <= Overdue",
        )
    if overdue > 10:
        raise HTTPException(
            status_code=422,
            detail="Overdue cutoff must be at most 10 (1000% of expected life)",
        )
    for k in _BENCHMARK_FIELDS:
        if not (0 <= merged[k] <= 100):
            raise HTTPException(
                status_code=422, detail="Radar benchmark values must be between 0 and 100")

    if row is None:
        row = AgeingConfig(created_by=current_user.id)
        db.add(row)
    for k, v in merged.items():
        setattr(row, k, v)
    if notes_set:
        row.notes = notes
    row.modified_by = current_user.id

    db.commit()
    db.refresh(row)
    return _ageing_response(row)
