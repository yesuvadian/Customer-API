from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from schemas import StateCreate, StateUpdate, StateOut
from services.state_service import StateService

router = APIRouter(prefix="/states", tags=["states"],dependencies=[Depends(get_current_user)])
service = StateService()

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from schemas import StateCreate, StateUpdate, StateOut
from services.state_service import StateService

router = APIRouter(
    prefix="/states",
    tags=["states"],
    dependencies=[Depends(get_current_user)],
)




@router.get("/", response_model=list[StateOut])
def list_states(
    skip: int = 0,
    limit: int = 100,
    search: str | None = Query(None),
    country_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    List states, optionally filtered by `country_id` and/or `search`.
    """
    return service.get_states(
        db, skip=skip, limit=limit, search=search, country_id=country_id
    )


@router.post("/", response_model=StateOut, status_code=status.HTTP_201_CREATED)
def create_state(state: StateCreate, db: Session = Depends(get_db)):
    """
    Create a new state.
    """
    return service.create_state(
        db, name=state.name, country_id=state.country_id, code=state.code
    )


@router.get("/{state_id}", response_model=StateOut)
def get_state(state_id: int, db: Session = Depends(get_db)):
    """
    Retrieve a single state by ID.
    """
    state = service.get_state(db, state_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="State not found"
        )
    return state


@router.put("/{state_id}", response_model=StateOut)
def update_state(state_id: int, updates: StateUpdate, db: Session = Depends(get_db)):
    """
    Update an existing state.
    """
    return service.update_state(db, state_id, updates.dict(exclude_unset=True))


@router.delete("/{state_id}", response_model=StateOut)
def delete_state(state_id: int, db: Session = Depends(get_db)):
    """
    Delete a state.
    """
    return service.delete_state(db, state_id)


@router.post("/", response_model=StateOut)
def create_state(state: StateCreate, db: Session = Depends(get_db)):
    return service.create_state(db, name=state.name, country_id=state.country_id, code=state.code)

@router.get("/{state_id}", response_model=StateOut)
def get_state(state_id: int, db: Session = Depends(get_db)):
    state = service.get_state(db, state_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="State not found")
    return state

@router.put("/{state_id}", response_model=StateOut)
def update_state(state_id: int, updates: StateUpdate, db: Session = Depends(get_db)):
    return service.update_state(db, state_id, updates.dict(exclude_unset=True))

@router.delete("/{state_id}", response_model=StateOut)
def delete_state(state_id: int, db: Session = Depends(get_db)):
    return service.delete_state(db, state_id)
