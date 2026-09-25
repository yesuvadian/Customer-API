"""
Reading naive DB timestamps back as real points in time.

The app writes timestamps as aware UTC (datetime.now(timezone.utc)) into
naive `timestamp without time zone` columns. Postgres converts an aware
value to the *session* time zone before dropping the offset, so what is
stored is session-local wall-clock time (Asia/Calcutta on the current
servers), not UTC. Labelling those values UTC made every stage deadline
5.5h late.

db_naive_to_aware() attaches the session's actual time zone, looked up once
per process with SHOW TimeZone rather than hard-coding +05:30, so the maths
stays right on a server whose Postgres runs in another zone.
"""
import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_session_tz: Optional[tzinfo] = None


def db_session_tz(db: Session) -> tzinfo:
    """The Postgres session time zone that naive timestamps are stored in."""
    global _session_tz
    if _session_tz is None:
        name = db.execute(text("SHOW TimeZone")).scalar()
        try:
            _session_tz = ZoneInfo(name)
        except Exception:
            # Not an IANA name (e.g. a POSIX offset string): fall back to the
            # session's current UTC offset.
            offset = db.execute(text("SELECT EXTRACT(TIMEZONE FROM now())")).scalar()
            _session_tz = timezone(timedelta(seconds=int(offset or 0)))
            logger.warning("DB session TimeZone %r is not an IANA zone; using fixed offset %s", name, _session_tz)
    return _session_tz


def db_naive_to_aware(dt: Optional[datetime], db: Session) -> Optional[datetime]:
    """Attach the DB session time zone to a naive timestamp read from the DB.

    Aware values and None pass through unchanged. The result compares
    correctly with datetime.now(timezone.utc); call .astimezone(timezone.utc)
    when a UTC value is needed for output.
    """
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=db_session_tz(db))
