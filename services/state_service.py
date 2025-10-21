from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import State
#from models import State

class StateService:

    @classmethod
    def get_state(cls, db: Session, state_id: int):
        return db.query(State).filter(State.id == state_id).first()

    @classmethod
    def get_states(cls, db: Session, skip: int = 0, limit: int = 100, search: str = None):
        query = db.query(State)
        if search:
            query = query.filter(State.name.ilike(f"%{search}%"))
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_state(cls, db: Session, name: str, country_id: int, code: str | None = None):
        existing = db.query(State).filter(State.name == name, State.country_id == country_id).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State already exists in this country")
        state = State(name=name, code=code, country_id=country_id)
        db.add(state)
        db.commit()
        db.refresh(state)
        return state

    @classmethod
    def update_state(cls, db: Session, state_id: int, updates: dict):
        state = cls.get_state(db, state_id)
        if not state:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="State not found")
        for key, value in updates.items():
            setattr(state, key, value)
        db.commit()
        db.refresh(state)
        return state

    @classmethod
    def delete_state(cls, db: Session, state_id: int):
        state = cls.get_state(db, state_id)
        if state:
            db.delete(state)
            db.commit()
        return state
