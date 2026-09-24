"""
CAR Trigger Config API
=========================
Admin CRUD for the rules that decide, per (equipment_type, test_type,
severity), whether a CRITICAL/ALERT evaluation auto-creates a Corrective
Action Request — and if so, which follow-up test/maintenance/inspection/
repair actions get raised automatically (see services/car_service.py,
which reads these rows through _find_trigger_config()/CarTriggerFollowup
at evaluation time). This module is separate from "corrective-action-
requests" (the CAR dashboard itself) — same split as CM Recommendation
Config vs. the CM dashboard.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from auth_utils import get_current_user
from config import CAR_DUE_DAYS_ALERT, CAR_DUE_DAYS_CRITICAL
from database import get_db
from models import CarTriggerConfig, CarTriggerFollowup, CategoryDetails, CategoryMaster, User
from services.category_master_service import CategoryMasterService

router = APIRouter(
    prefix="/car-trigger-config",
    tags=["car-trigger-config"],
    dependencies=[Depends(get_current_user)],
)


def _org_id(current_user) -> Optional[UUID]:
    return current_user.organization_id if isinstance(current_user, User) else current_user.get("organization_id")


def _user_id(current_user) -> Optional[UUID]:
    return current_user.id if isinstance(current_user, User) else current_user.get("id")


def _serialize(config: CarTriggerConfig, db: Session) -> dict:
    equipment_type = db.query(CategoryMaster).filter(CategoryMaster.id == config.equipment_type_id).first()
    test_type = (
        db.query(CategoryDetails).filter(CategoryDetails.id == config.test_type_id).first()
        if config.test_type_id else None
    )
    followups = sorted(config.followups, key=lambda f: f.display_order)
    followup_types = {
        row.id: row
        for row in db.query(CategoryDetails).filter(
            CategoryDetails.id.in_([f.follow_up_test_type_id for f in followups])
        ).all()
    } if followups else {}

    return {
        "id": str(config.id),
        "organization_id": str(config.organization_id) if config.organization_id else None,
        "equipment_type_id": config.equipment_type_id,
        "equipment_type_name": equipment_type.name if equipment_type else None,
        "test_type_id": config.test_type_id,
        "test_type_name": test_type.name if test_type else None,
        "severity": config.severity,
        "car_trigger": config.car_trigger,
        "is_active": config.is_active,
        "display_order": config.display_order,
        "car_due_in_days": config.car_due_in_days,
        # So the UI can show "Default: N days" as a placeholder when this
        # row hasn't overridden it (config.CAR_DUE_DAYS_CRITICAL/ALERT).
        "car_due_in_days_default": CAR_DUE_DAYS_CRITICAL if config.severity == "CRITICAL" else CAR_DUE_DAYS_ALERT,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "modified_at": config.modified_at.isoformat() if config.modified_at else None,
        "followups": [
            {
                "id": str(f.id),
                "follow_up_test_type_id": f.follow_up_test_type_id,
                "follow_up_test_type_name": followup_types.get(f.follow_up_test_type_id).name
                    if followup_types.get(f.follow_up_test_type_id) else None,
                "category_type": followup_types.get(f.follow_up_test_type_id).category_type
                    if followup_types.get(f.follow_up_test_type_id) else None,
                "display_order": f.display_order,
                "due_in_days": f.due_in_days,
                "is_active": f.is_active,
            }
            for f in followups
        ],
    }


@router.get("/equipment-types", summary="Equipment types that have CAR trigger rules configured (or could)")
def list_equipment_types(db: Session = Depends(get_db)):
    # Reuses the same equipment-only CategoryMaster filter as CM Recommendation
    # Config (GET /category_master/masters/equipment) so this screen's card
    # strip lists the same equipment types, not every CategoryMaster row
    # (bank account types, annual audit categories, etc. also live there).
    rows = CategoryMasterService.get_equipment_master_categories(db=db, limit=500, is_active=True)
    return [{"id": r.id, "name": r.name} for r in sorted(rows, key=lambda r: r.name or "")]


@router.get("/test-types", summary="Test/maintenance/inspection/repair types for a given equipment type")
def list_test_types(
    equipment_type_id: int = Query(...),
    category_type: Optional[str] = Query(None, description="test | maintenance | inspection | repair_lifecycle"),
    db: Session = Depends(get_db),
):
    q = db.query(CategoryDetails).filter(
        CategoryDetails.category_master_id == equipment_type_id,
        CategoryDetails.is_active.is_(True),
    )
    if category_type:
        q = q.filter(CategoryDetails.category_type == category_type)
    rows = q.order_by(CategoryDetails.name).all()
    return [{"id": r.id, "name": r.name, "category_type": r.category_type} for r in rows]


@router.get("", summary="List CAR trigger configs (optionally scoped to an equipment type)")
def list_configs(
    equipment_type_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    org_id = _org_id(current_user)
    q = db.query(CarTriggerConfig).options(joinedload(CarTriggerConfig.followups))
    if org_id:
        # SQL's IN() never matches NULL, even when None is in the list -
        # organization_id IS NULL is the global-default row and needs its
        # own explicit OR clause, not .in_([org_id, None]).
        q = q.filter(or_(CarTriggerConfig.organization_id == org_id, CarTriggerConfig.organization_id.is_(None)))
    if equipment_type_id:
        q = q.filter(CarTriggerConfig.equipment_type_id == equipment_type_id)
    configs = q.order_by(CarTriggerConfig.equipment_type_id, CarTriggerConfig.display_order).all()
    return [_serialize(c, db) for c in configs]


@router.get("/{config_id}", summary="Get one CAR trigger config with its follow-ups")
def get_config(config_id: UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    config = (
        db.query(CarTriggerConfig)
        .options(joinedload(CarTriggerConfig.followups))
        .filter(CarTriggerConfig.id == config_id)
        .first()
    )
    if not config:
        raise HTTPException(status_code=404, detail="CAR trigger config not found")
    return _serialize(config, db)


class FollowupInput(BaseModel):
    follow_up_test_type_id: int
    display_order: int = 0
    due_in_days: int = Field(default=7, gt=0)
    is_active: bool = True


class CarTriggerConfigCreate(BaseModel):
    equipment_type_id: int
    test_type_id: Optional[int] = None
    severity: str  # ALERT | CRITICAL
    car_trigger: bool = True
    display_order: int = 0
    car_due_in_days: Optional[int] = Field(default=None, gt=0)
    org_specific: bool = False  # False = global default row (organization_id NULL)
    followups: list[FollowupInput] = []


@router.post("", summary="Create a CAR trigger config rule")
def create_config(
    body: CarTriggerConfigCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if body.severity not in ("ALERT", "CRITICAL"):
        raise HTTPException(status_code=400, detail="severity must be ALERT or CRITICAL")

    org_id = _org_id(current_user) if body.org_specific else None
    existing = db.query(CarTriggerConfig).filter(
        CarTriggerConfig.organization_id == org_id,
        CarTriggerConfig.equipment_type_id == body.equipment_type_id,
        CarTriggerConfig.test_type_id == body.test_type_id,
        CarTriggerConfig.severity == body.severity,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A rule already exists for this equipment type / test type / severity")

    config = CarTriggerConfig(
        organization_id=org_id,
        equipment_type_id=body.equipment_type_id,
        test_type_id=body.test_type_id,
        severity=body.severity,
        car_trigger=body.car_trigger,
        display_order=body.display_order,
        car_due_in_days=body.car_due_in_days,
        created_by=_user_id(current_user),
    )
    db.add(config)
    db.flush()

    for f in body.followups:
        db.add(CarTriggerFollowup(
            car_trigger_config_id=config.id,
            follow_up_test_type_id=f.follow_up_test_type_id,
            display_order=f.display_order,
            due_in_days=f.due_in_days,
            is_active=f.is_active,
        ))

    db.commit()
    db.refresh(config)
    return _serialize(config, db)


class CarTriggerConfigUpdate(BaseModel):
    car_trigger: Optional[bool] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None
    car_due_in_days: Optional[int] = Field(default=None, gt=0)
    followups: Optional[list[FollowupInput]] = None


@router.put("/{config_id}", summary="Update a CAR trigger config rule (and optionally replace its follow-ups)")
def update_config(
    config_id: UUID,
    body: CarTriggerConfigUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    config = db.query(CarTriggerConfig).filter(CarTriggerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="CAR trigger config not found")

    if body.car_trigger is not None:
        config.car_trigger = body.car_trigger
    if body.is_active is not None:
        config.is_active = body.is_active
    if body.display_order is not None:
        config.display_order = body.display_order
    if body.car_due_in_days is not None:
        config.car_due_in_days = body.car_due_in_days

    if body.followups is not None:
        db.query(CarTriggerFollowup).filter(CarTriggerFollowup.car_trigger_config_id == config.id).delete()
        for f in body.followups:
            db.add(CarTriggerFollowup(
                car_trigger_config_id=config.id,
                follow_up_test_type_id=f.follow_up_test_type_id,
                display_order=f.display_order,
                due_in_days=f.due_in_days,
                is_active=f.is_active,
            ))

    db.commit()
    db.refresh(config)
    return _serialize(config, db)


@router.delete("/{config_id}", summary="Deactivate a CAR trigger config rule")
def deactivate_config(config_id: UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    config = db.query(CarTriggerConfig).filter(CarTriggerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="CAR trigger config not found")
    config.is_active = False
    db.commit()
    return {"id": str(config.id), "is_active": False}
