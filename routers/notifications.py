"""
User-facing notification endpoints.

GET  /notifications              → list in-app notifications (paginated)
GET  /notifications/unread-count → unread badge count
PUT  /notifications/{id}/read   → mark one as read
PUT  /notifications/read-all    → mark all as read
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, UserNotification

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class UserNotificationOut(BaseModel):
    id: UUID
    event_type: str
    title: str
    body: str
    severity: Optional[str] = None
    source_id: Optional[UUID] = None
    source_type: Optional[str] = None
    is_read: bool
    read_at: Optional[object] = None
    cts: object

    class Config:
        from_attributes = True


class UnreadCountOut(BaseModel):
    count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[UserNotificationOut])
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's in-app notifications, newest first."""
    q = (
        db.query(UserNotification)
        .filter(UserNotification.user_id == current_user.id)
    )
    if unread_only:
        q = q.filter(UserNotification.is_read.is_(False))
    return q.order_by(UserNotification.cts.desc()).offset(skip).limit(limit).all()


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return number of unread in-app notifications for the bell badge."""
    count = (
        db.query(UserNotification)
        .filter(
            UserNotification.user_id == current_user.id,
            UserNotification.is_read.is_(False),
        )
        .count()
    )
    return {"count": count}


@router.put("/{notification_id}/read", response_model=UserNotificationOut)
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    from datetime import datetime, timezone
    from fastapi import HTTPException, status

    notif = (
        db.query(UserNotification)
        .filter(
            UserNotification.id == notification_id,
            UserNotification.user_id == current_user.id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    notif.is_read = True
    notif.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(notif)
    return notif


@router.put("/read-all", response_model=UnreadCountOut)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    from datetime import datetime, timezone
    from sqlalchemy import update

    now = datetime.now(timezone.utc)
    db.query(UserNotification).filter(
        UserNotification.user_id == current_user.id,
        UserNotification.is_read.is_(False),
    ).update({"is_read": True, "read_at": now})
    db.commit()
    return {"count": 0}
