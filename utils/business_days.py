"""
business_days.py
─────────────────
Business-day (Mon–Fri) date math, shared by anything computing "overdue"
that should skip weekends. No holiday calendar exists anywhere in this
schema, so "business day" here means Mon–Fri only — Sat/Sun are excluded,
public holidays are not (there's nothing to look them up against).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

_WEEKEND = (5, 6)  # date.weekday(): Saturday=5, Sunday=6


def business_days_between(start: date, end: date) -> int:
    """
    Signed count of business days between start and end, matching the sign
    convention of (end - start).days: positive if end is after start,
    negative if before, zero if equal.

    The start day itself is never counted (same as plain (end - start).days
    excluding its own start point) — only days strictly between start and
    end, walked one at a time, with weekends skipped.
    """
    if end == start:
        return 0

    forward = end > start
    lo, hi = (start, end) if forward else (end, start)

    total_days = (hi - lo).days
    full_weeks, remainder = divmod(total_days, 7)
    count = full_weeks * 5

    current = lo
    for _ in range(remainder):
        current += timedelta(days=1)
        if current.weekday() not in _WEEKEND:
            count += 1

    return count if forward else -count


def subtract_business_days(d: date, n: int) -> date:
    """Return the date n business days before d, skipping weekends. n <= 0 returns d unchanged."""
    if n <= 0:
        return d
    current = d
    counted = 0
    while counted < n:
        current -= timedelta(days=1)
        if current.weekday() not in _WEEKEND:
            counted += 1
    return current


def add_business_days(d: date, n: int) -> date:
    """Return the date n business days after d, skipping weekends. n <= 0 returns d unchanged."""
    if n <= 0:
        return d
    current = d
    counted = 0
    while counted < n:
        current += timedelta(days=1)
        if current.weekday() not in _WEEKEND:
            counted += 1
    return current


def add_business_hours(start: datetime, hours: float) -> datetime:
    """
    Return the datetime `hours` business-hours after `start`, treating
    Sat/Sun as if the clock stops entirely -- a duration that would run
    into or through a weekend resumes ticking at the following Monday
    00:00 instead of counting weekend time. hours <= 0 returns start
    unchanged. Preserves start's tzinfo (naive in, naive out; aware in,
    aware out).

    Used for SLA/deadline math that must agree with this module's
    day-level functions above: Mon-Fri only, no holiday calendar (there's
    nothing to look one up against in this schema).
    """
    if hours <= 0:
        return start

    remaining = timedelta(hours=hours)
    current = start
    while remaining > timedelta(0):
        if current.weekday() in _WEEKEND:
            current = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=current.tzinfo)
            continue
        next_midnight = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=current.tzinfo)
        today_remaining = next_midnight - current
        if remaining <= today_remaining:
            return current + remaining
        remaining -= today_remaining
        current = next_midnight
    return current
