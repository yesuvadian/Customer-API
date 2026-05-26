"""
Admin notification event catalogue management endpoints.

Event Catalogue
  GET    /admin/notifications/events              → list event types
  POST   /admin/notifications/events              → create custom event type
  PUT    /admin/notifications/events/{id}         → update event type
  DELETE /admin/notifications/events/{id}         → deactivate event type
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import NotificationEventCatalogue, User

router = APIRouter(
    prefix="/admin/notifications",
    tags=["admin-notifications"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class EventCatalogueCreate(BaseModel):
    event_type: str
    label: str
    group_name: str
    description: Optional[str] = None
    context_vars: List[str] = []
    default_roles: List[str] = []
    organization_id: Optional[UUID] = None


class EventCatalogueUpdate(BaseModel):
    label: Optional[str] = None
    group_name: Optional[str] = None
    description: Optional[str] = None
    context_vars: Optional[List[str]] = None
    default_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None


class EventCatalogueOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID]
    event_type: str
    label: str
    group_name: str
    description: Optional[str]
    context_vars: list
    default_roles: list
    is_active: bool
    cts: object
    mts: object

    class Config:
        from_attributes = True


# ── Event Catalogue CRUD ──────────────────────────────────────────────────────

@router.get("/events", response_model=List[EventCatalogueOut])
def list_event_types(
    organization_id: Optional[UUID] = None,
    group_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all event types (global + org-specific).

    Returns:
    - Global event types (organization_id = NULL) - available to all orgs
    - Org-specific event types (organization_id = user's org) - custom events

    Org-specific events OVERRIDE global events with the same event_type.
    """
    query = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.is_active.is_(True)
    )

    # If organization_id provided, return global + org-specific
    if organization_id:
        query = query.filter(
            or_(
                NotificationEventCatalogue.organization_id.is_(None),
                NotificationEventCatalogue.organization_id == organization_id
            )
        )
    else:
        # Return only global events
        query = query.filter(NotificationEventCatalogue.organization_id.is_(None))

    # Filter by group if provided
    if group_name:
        query = query.filter(NotificationEventCatalogue.group_name == group_name)

    events = query.order_by(
        NotificationEventCatalogue.group_name,
        NotificationEventCatalogue.label
    ).all()

    # Deduplicate: org-specific overrides global for same event_type
    if organization_id:
        seen = set()
        unique_events = []
        for event in events:
            if event.event_type not in seen:
                seen.add(event.event_type)
                unique_events.append(event)
        return unique_events

    return events


@router.post("/events", response_model=EventCatalogueOut, status_code=status.HTTP_201_CREATED)
def create_event_type(
    data: EventCatalogueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create new custom event type for an organization.

    - organization_id = NULL → Global event (system admin only)
    - organization_id = <uuid> → Org-specific custom event

    Org-specific events can override global events by using the same event_type.
    """
    # Check if event_type already exists for this org
    existing = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.event_type == data.event_type,
        NotificationEventCatalogue.organization_id == data.organization_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Event type '{data.event_type}' already exists for this organization"
        )

    # Validate event_type format (lowercase, underscores only)
    if not data.event_type.replace('_', '').isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event type must contain only letters, numbers, and underscores"
        )

    event = NotificationEventCatalogue(
        event_type=data.event_type,
        label=data.label,
        group_name=data.group_name,
        description=data.description,
        context_vars=data.context_vars,
        default_roles=data.default_roles,
        organization_id=data.organization_id,
        is_active=True
    )

    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.put("/events/{event_id}", response_model=EventCatalogueOut)
def update_event_type(
    event_id: UUID,
    data: EventCatalogueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing event type."""
    event = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event type not found"
        )

    # Update only provided fields
    if data.label is not None:
        event.label = data.label
    if data.group_name is not None:
        event.group_name = data.group_name
    if data.description is not None:
        event.description = data.description
    if data.context_vars is not None:
        event.context_vars = data.context_vars
    if data.default_roles is not None:
        event.default_roles = data.default_roles
    if data.is_active is not None:
        event.is_active = data.is_active

    db.commit()
    db.refresh(event)
    return event


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event_type(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft delete an event type (set is_active = False).

    Note: This will hide the event type from the UI but won't delete
    associated templates. Templates can still fire if called programmatically.
    """
    event = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event type not found"
        )

    # Soft delete
    event.is_active = False
    db.commit()
    return None
