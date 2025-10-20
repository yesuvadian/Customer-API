from datetime import datetime, timezone

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
