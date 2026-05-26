from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import text


# ─────────────────────────────────────────────────────────────────────────────
# Department hierarchy helpers — shared across all services / routers
# ─────────────────────────────────────────────────────────────────────────────

def get_dept_subtree_ids(db: Session, dept_id: UUID) -> List[UUID]:
    """Return dept_id plus all its recursive child department IDs.

    Uses a PostgreSQL recursive CTE to walk the org_departments tree.
    Allows zone/circle-level users to see data from all child departments.
    """
    result = db.execute(text("""
        WITH RECURSIVE dept_tree AS (
            SELECT id FROM public.org_departments WHERE id = :root_id AND is_active = true
            UNION ALL
            SELECT d.id
            FROM   public.org_departments d
            JOIN   dept_tree dt ON d.parent_department_id = dt.id
            WHERE  d.is_active = true
        )
        SELECT id FROM dept_tree
    """), {"root_id": str(dept_id)})
    return [row[0] for row in result.fetchall()]


def get_user_dept_scope(db: Session, user_id: UUID, org_id: Optional[UUID]) -> Tuple[bool, Optional[UUID]]:
    """Return (is_org_admin, department_id).

    Shared by all services/routers that need to scope queries to a user's
    department hierarchy.

    Priority:
      1. If the user holds an org-admin role → (True, None)  [no dept restriction]
      2. OrgUserRole.department_id  (role scoped to a specific department)
      3. User.department_id         (user's primary department)
      4. (False, None)              [no dept restriction found]
    """
    from models import OrgRole, OrgUserRole, User

    # Check for org-admin role
    is_org_admin = (
        db.query(OrgRole)
        .join(OrgUserRole, OrgUserRole.org_role_id == OrgRole.id)
        .filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active.is_(True),
            OrgRole.is_org_admin.is_(True),
        )
        .first()
    ) is not None

    if is_org_admin:
        return True, None

    # Priority 1: role scoped to a specific department
    user_dept_role = (
        db.query(OrgUserRole)
        .filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active.is_(True),
            OrgUserRole.department_id.isnot(None),
        )
        .first()
    )
    if user_dept_role and user_dept_role.department_id:
        return False, user_dept_role.department_id

    # Priority 2: user's primary department
    user = db.query(User).filter(User.id == user_id).first()
    dept_id = user.department_id if user else None
    return False, dept_id


class UTCDateTimeMixin:
    """Provides reusable UTC datetime utilities."""

    @staticmethod
    def _utc_now() -> datetime:
        """Return the current UTC time as an aware datetime."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _make_aware(dt: datetime) -> datetime:
        """Convert a naive datetime to UTC-aware. Returns None if dt is None."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
