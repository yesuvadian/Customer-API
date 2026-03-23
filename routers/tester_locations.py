from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import TesterLocation, User, Role, UserRole

router = APIRouter(
    prefix="/tester_locations",
    tags=["tester_locations"],
    dependencies=[Depends(get_current_user)],
)


# ─── LIST all tester-location mappings ────────────────────
@router.get("/")
def list_tester_locations(
    zone: Optional[str] = None,
    ce_circle: Optional[str] = None,
    se_division: Optional[str] = None,
    ee_subdivision: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(TesterLocation, User)
        .join(User, User.id == TesterLocation.user_id)
        .filter(TesterLocation.is_active == True)
    )
    if zone:
        query = query.filter(TesterLocation.zone == zone)
    if ce_circle:
        query = query.filter(TesterLocation.ce_circle == ce_circle)
    if se_division:
        query = query.filter(TesterLocation.se_division == se_division)
    if ee_subdivision:
        query = query.filter(TesterLocation.ee_subdivision == ee_subdivision)

    results = query.order_by(User.firstname).all()
    return [
        {
            "id": tl.id,
            "user_id": str(tl.user_id),
            "user_name": f"{u.firstname} {u.lastname}".strip(),
            "user_email": u.email,
            "zone": tl.zone,
            "ce_circle": tl.ce_circle,
            "se_division": tl.se_division,
            "ee_subdivision": tl.ee_subdivision,
            "is_active": tl.is_active,
        }
        for tl, u in results
    ]


# ─── GET users with Tester role (for the user dropdown) ──
@router.get("/available_testers")
def available_testers(db: Session = Depends(get_db)):
    """Returns users who have the Tester role (for the 'user' dropdown in the mapping form)."""
    tester_role = db.query(Role).filter(Role.name == "Tester").first()
    if not tester_role:
        return []

    testers = (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id)
        .filter(UserRole.role_id == tester_role.id, User.isactive == True)
        .order_by(User.firstname)
        .all()
    )
    return [
        {
            "id": str(t.id),
            "name": f"{t.firstname} {t.lastname}".strip(),
            "email": t.email,
        }
        for t in testers
    ]


# ─── CREATE a new mapping ────────────────────────────────
@router.post("/")
def create_tester_location(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    # Make sure the user exists and has Tester role
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    mapping = TesterLocation(
        user_id=user_id,
        zone=data.get("zone"),
        ce_circle=data.get("ce_circle"),
        se_division=data.get("se_division"),
        ee_subdivision=data.get("ee_subdivision"),
        is_active=True,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    return {
        "id": mapping.id,
        "user_id": str(mapping.user_id),
        "user_name": f"{user.firstname} {user.lastname}".strip(),
        "user_email": user.email,
        "zone": mapping.zone,
        "ce_circle": mapping.ce_circle,
        "se_division": mapping.se_division,
        "ee_subdivision": mapping.ee_subdivision,
        "is_active": mapping.is_active,
    }


# ─── UPDATE ──────────────────────────────────────────────
@router.put("/{mapping_id}")
def update_tester_location(
    mapping_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mapping = db.query(TesterLocation).filter(TesterLocation.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    for field in ["zone", "ce_circle", "se_division", "ee_subdivision", "is_active"]:
        if field in data:
            setattr(mapping, field, data[field])

    db.commit()
    db.refresh(mapping)

    user = db.query(User).filter(User.id == mapping.user_id).first()
    return {
        "id": mapping.id,
        "user_id": str(mapping.user_id),
        "user_name": f"{user.firstname} {user.lastname}".strip() if user else "",
        "user_email": user.email if user else "",
        "zone": mapping.zone,
        "ce_circle": mapping.ce_circle,
        "se_division": mapping.se_division,
        "ee_subdivision": mapping.ee_subdivision,
        "is_active": mapping.is_active,
    }


# ─── DELETE ──────────────────────────────────────────────
@router.delete("/{mapping_id}")
def delete_tester_location(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mapping = db.query(TesterLocation).filter(TesterLocation.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    db.delete(mapping)
    db.commit()
    return {"message": "Tester location mapping deleted successfully"}
