from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import datetime

from database import get_db
from models import User, TestSession, SessionComment
from schemas import SessionCommentCreate, SessionCommentResponse
from auth_utils import get_current_user

router = APIRouter(prefix="/testing_requests/{request_id}/sessions/{session_id}/comments", tags=["Session Comments"])


# ─────────────────────────────────────────────────────────────────────────────
# GET Comments for a Session
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[SessionCommentResponse])
def get_session_comments(
    request_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all comments for a specific session.
    Includes author name and role.
    """
    # Verify session exists
    session = db.query(TestSession).filter(
        TestSession.id == uuid.UUID(session_id),
        TestSession.testing_request_id == uuid.UUID(request_id),
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get comments with author details
    comments = (
        db.query(SessionComment)
        .join(User, SessionComment.author_id == User.id)
        .filter(SessionComment.session_id == uuid.UUID(session_id))
        .order_by(SessionComment.created_at.desc())
        .all()
    )

    # Build response with author details
    result = []
    for comment in comments:
        author = db.query(User).filter(User.id == comment.author_id).first()

        # Get author role name
        author_role = None
        if author and hasattr(author, 'roles') and author.roles:
            author_role = author.roles[0].name if len(author.roles) > 0 else None

        result.append({
            "id": str(comment.id),
            "session_id": str(comment.session_id),
            "comment": comment.comment,
            "author_id": str(comment.author_id),
            "author_name": f"{author.firstname or ''} {author.lastname or ''}".strip() if author else "Unknown",
            "author_role": author_role,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "modified_at": comment.modified_at.isoformat() if comment.modified_at else None,
            "is_edited": comment.modified_at != comment.created_at if comment.modified_at and comment.created_at else False,
        })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# POST Add Comment to Session
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=SessionCommentResponse, status_code=status.HTTP_201_CREATED)
def add_session_comment(
    request_id: str,
    session_id: str,
    payload: SessionCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a comment to a session.
    Typically used by approvers to provide feedback.
    """
    # Verify session exists
    session = db.query(TestSession).filter(
        TestSession.id == uuid.UUID(session_id),
        TestSession.testing_request_id == uuid.UUID(request_id),
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Create comment
    comment = SessionComment(
        id=uuid.uuid4(),
        session_id=uuid.UUID(session_id),
        comment=payload.comment,
        author_id=current_user.id,
        created_at=datetime.utcnow(),
        modified_at=datetime.utcnow(),
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Build response
    author_role = None
    if hasattr(current_user, 'roles') and current_user.roles:
        author_role = current_user.roles[0].name if len(current_user.roles) > 0 else None

    return {
        "id": str(comment.id),
        "session_id": str(comment.session_id),
        "comment": comment.comment,
        "author_id": str(comment.author_id),
        "author_name": f"{current_user.firstname or ''} {current_user.lastname or ''}".strip(),
        "author_role": author_role,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "modified_at": comment.modified_at.isoformat() if comment.modified_at else None,
        "is_edited": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUT Update Comment
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/{comment_id}", response_model=SessionCommentResponse)
def update_session_comment(
    request_id: str,
    session_id: str,
    comment_id: str,
    payload: SessionCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a comment (only by the author).
    """
    comment = db.query(SessionComment).filter(
        SessionComment.id == uuid.UUID(comment_id),
        SessionComment.session_id == uuid.UUID(session_id),
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Only author can update
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this comment")

    comment.comment = payload.comment
    comment.modified_at = datetime.utcnow()

    db.commit()
    db.refresh(comment)

    # Build response
    author_role = None
    if hasattr(current_user, 'roles') and current_user.roles:
        author_role = current_user.roles[0].name if len(current_user.roles) > 0 else None

    return {
        "id": str(comment.id),
        "session_id": str(comment.session_id),
        "comment": comment.comment,
        "author_id": str(comment.author_id),
        "author_name": f"{current_user.firstname or ''} {current_user.lastname or ''}".strip(),
        "author_role": author_role,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "modified_at": comment.modified_at.isoformat() if comment.modified_at else None,
        "is_edited": comment.modified_at != comment.created_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE Remove Comment
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session_comment(
    request_id: str,
    session_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a comment (only by the author or admin).
    """
    comment = db.query(SessionComment).filter(
        SessionComment.id == uuid.UUID(comment_id),
        SessionComment.session_id == uuid.UUID(session_id),
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Only author can delete (or add admin check here)
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this comment")

    db.delete(comment)
    db.commit()

    return None
