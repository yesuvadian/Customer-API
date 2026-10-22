"""
Resolved values for the admin-tunable analytics / review-SLA / scheduling /
calibration-interval settings (AnalyticsSettingsConfig, Threshold Config ->
"Analytics & SLA" and "Calibration" tabs). Previously these were .env-only
constants read straight from config.py.

Lookup per setting: the org's own row -> the system-wide default row
(organization_id NULL) -> the config.py/.env constant. A NULL column at any
level falls through to the next one, so a row can override a single value.

Values are cached per organization for CACHE_SECONDS - several callers sit
in hot loops (ParameterAnalyzer runs per reading) - and the Threshold Config
endpoints call invalidate() on every save so an edit applies immediately on
this worker (other workers pick it up within CACHE_SECONDS).

Usage:
    from services.tunable_settings import get_settings
    s = get_settings(db, org_id)
    s["review_sla_hours_alert"]
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import config as _config

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60

# setting key (= AnalyticsSettingsConfig column) -> (config.py / .env name, type)
FIELDS: dict[str, tuple[str, type]] = {
    "analytics_min_trend_points":                 ("ANALYTICS_MIN_TREND_POINTS", int),
    "analytics_stable_fraction":                  ("ANALYTICS_STABLE_FRACTION", float),
    "analytics_min_trend_r_squared":              ("ANALYTICS_MIN_TREND_R_SQUARED", float),
    "analytics_trend_window":                     ("ANALYTICS_TREND_WINDOW", int),
    "analytics_min_watch_history":                ("ANALYTICS_MIN_WATCH_HISTORY", int),
    "analytics_overdue_review_alert_days":        ("ANALYTICS_OVERDUE_REVIEW_ALERT_DAYS", int),
    "analytics_overdue_review_critical_days":     ("ANALYTICS_OVERDUE_REVIEW_CRITICAL_DAYS", int),
    "review_sla_hours_alert":                     ("REVIEW_SLA_HOURS_ALERT", int),
    "review_sla_hours_critical":                  ("REVIEW_SLA_HOURS_CRITICAL", int),
    "schedule_advance_days":                      ("SCHEDULE_ADVANCE_DAYS", int),
    "calibration_interval_min_cycles":            ("CALIBRATION_INTERVAL_MIN_CYCLES", int),
    "calibration_interval_extend_fail_rate_pct":  ("CALIBRATION_INTERVAL_EXTEND_FAIL_RATE_PCT", float),
    "calibration_interval_shorten_fail_rate_pct": ("CALIBRATION_INTERVAL_SHORTEN_FAIL_RATE_PCT", float),
    "calibration_interval_extend_months":         ("CALIBRATION_INTERVAL_EXTEND_MONTHS", int),
    "calibration_interval_shorten_months":        ("CALIBRATION_INTERVAL_SHORTEN_MONTHS", int),
    "calibration_interval_max_months":            ("CALIBRATION_INTERVAL_MAX_MONTHS", int),
    "calibration_interval_min_months":            ("CALIBRATION_INTERVAL_MIN_MONTHS", int),
    # Notifications (notification_service)
    "notif_digest_threshold":                     ("NOTIF_DIGEST_THRESHOLD", int),
    "notif_digest_window_minutes":                ("NOTIF_DIGEST_WINDOW_MINUTES", int),
    "notif_max_retries":                          ("NOTIF_MAX_RETRIES", int),
    "notif_retry_delay_minutes":                  ("NOTIF_RETRY_DELAY_MINUTES", int),
    # Paging
    "tr_page_size":                               ("TR_PAGE_SIZE", int),
    "dashboard_panel_page_size":                  ("DASHBOARD_PANEL_PAGE_SIZE", int),
    # Login & password policy
    "max_login_attempts":                         ("MAX_LOGIN_ATTEMPTS", int),
    "login_lock_duration_min":                    ("LOGIN_LOCK_DURATION_MIN", int),
    "max_otp_attempts":                           ("MAX_OTP_ATTEMPTS", int),
    "otp_lock_duration_min":                      ("OTP_LOCK_DURATION_MIN", int),
    "otp_validity_min":                           ("OTP_VALIDITY_MIN", int),
    "password_history_limit":                     ("PASSWORD_HISTORY_LIMIT", int),
    # One setting for the reset link: the token lifetime AND the expiry the
    # email states (they used to be two unrelated knobs that disagreed).
    "reset_password_link_minutes":                ("RESET_TOKEN_EXPIRE_MINUTES", int),
}

# Last-resort values for settings that aren't config.py constants (read with
# os.getenv + an inline default in the code they came from).
_HARD_DEFAULTS = {
    "NOTIF_DIGEST_THRESHOLD": 10,
    "NOTIF_DIGEST_WINDOW_MINUTES": 5,
    "NOTIF_MAX_RETRIES": 3,
    "NOTIF_RETRY_DELAY_MINUTES": 5,
    "TR_PAGE_SIZE": 20,
    "MAX_OTP_ATTEMPTS": 5,
    "OTP_LOCK_DURATION_MIN": 15,
    "OTP_VALIDITY_MIN": 5,
    "RESET_TOKEN_EXPIRE_MINUTES": 300,
}

_cache: dict[str, tuple[float, dict]] = {}


def env_defaults() -> dict:
    """The config.py/.env value of every setting (the last-resort level)."""
    out = {}
    for key, (const, typ) in FIELDS.items():
        val = getattr(_config, const, None)
        if val is None:
            raw = os.getenv(const)
            val = raw if raw not in (None, "") else _HARD_DEFAULTS.get(const)
        try:
            out[key] = typ(val) if val is not None else None
        except (TypeError, ValueError):
            out[key] = _HARD_DEFAULTS.get(const)
    return out


def _row_values(row) -> dict:
    if row is None:
        return {}
    out = {}
    for key, (_, typ) in FIELDS.items():
        val = getattr(row, key, None)
        if val is not None:
            out[key] = typ(val)
    return out


def default_values(db) -> dict:
    """System-level values: the NULL-org row over the .env constants."""
    from models import AnalyticsSettingsConfig
    base = env_defaults()
    try:
        # SAVEPOINT: if the table isn't migrated yet the failed query only
        # rolls back to here, never the caller's own pending work.
        with db.begin_nested():
            row = (db.query(AnalyticsSettingsConfig)
                   .filter(AnalyticsSettingsConfig.organization_id.is_(None)).first())
        base.update(_row_values(row))
    except Exception:
        # Table not migrated yet (alter_tunable_settings.py not run) - .env only.
        logger.debug("analytics_settings_configs unavailable; using .env", exc_info=True)
    return base


def get_settings(db, org_id: Optional[object] = None) -> dict:
    """Every setting's effective value for org_id (None = system default)."""
    ck = str(org_id) if org_id else "_default"
    hit = _cache.get(ck)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]

    vals = default_values(db)
    if org_id:
        from models import AnalyticsSettingsConfig
        try:
            with db.begin_nested():
                row = (db.query(AnalyticsSettingsConfig)
                       .filter(AnalyticsSettingsConfig.organization_id == org_id).first())
            vals.update(_row_values(row))
        except Exception:
            logger.debug("analytics_settings_configs org lookup failed", exc_info=True)
    _cache[ck] = (time.monotonic(), vals)
    return vals


def max_over_orgs(db, key: str):
    """Largest effective value of `key` across the default and every org
    override - for global queries that must cover every org's window
    (e.g. the daily scheduler's look-ahead), then filter per org."""
    from models import AnalyticsSettingsConfig
    best = get_settings(db, None)[key]
    try:
        col = getattr(AnalyticsSettingsConfig, key)
        with db.begin_nested():
            vals = [v for (v,) in db.query(col).filter(col.isnot(None)).all()]
        for v in vals:
            v = FIELDS[key][1](v)
            if best is None or v > best:
                best = v
    except Exception:
        logger.debug("analytics_settings_configs max lookup failed", exc_info=True)
    return best


def invalidate(org_id: Optional[object] = None) -> None:
    """Drop cached values - all orgs when org_id is None (default changed)."""
    if org_id is None:
        _cache.clear()
    else:
        _cache.pop(str(org_id), None)
