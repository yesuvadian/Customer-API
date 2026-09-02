"""
category_labels.py
───────────────────
Single source of truth for RequestCategory display labels and colors (test,
maintenance, inspection, repair_lifecycle, failure_registry, taqc_inspection).

Each class property is a LabelPair — it carries both the underlying key
(the DB/enum value) and the display value together, instead of relying on
the Python attribute name to stand in for the key. A call site that
genuinely needs a different value for the same key (e.g. the notification
routing UI preferring "Repair Cycle" over "Repair") subclasses
RequestCategoryLabels and overrides just that one property — the divergence
stays explicit and in one place instead of being copy-pasted into a fresh
dict at each call site.

When these labels move to a DB-backed lookup, only this file changes —
call sites keep using RequestCategoryLabels.get() / .as_dict().
"""

from __future__ import annotations


class LabelPair:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value


class LabelPairRegistry:
    """Shared as_dict()/get() lookup behaviour for any class whose properties
    are LabelPairs. Kept separate from RequestCategoryLabels so unrelated
    LabelPair registries (e.g. RequestCategoryColors) don't have to inherit
    RequestCategoryLabels' own key/value pairs just to reuse this logic."""

    @classmethod
    def as_dict(cls) -> dict[str, str]:
        """key -> value for every LabelPair on this class (inherited included), for
        call sites that need a plain dict (e.g. dict.get() with a fallback)."""
        pairs: dict[str, str] = {}
        for klass in reversed(cls.__mro__):
            for v in vars(klass).values():
                if isinstance(v, LabelPair):
                    pairs[v.key] = v.value
        return pairs

    @classmethod
    def get(cls, key: str | None, default: str | None = None) -> str:
        if not key:
            return default if default is not None else ""
        pairs = cls.as_dict()
        if key in pairs:
            return pairs[key]
        return default if default is not None else key.replace("_", " ").title()


class RequestCategoryLabels(LabelPairRegistry):
    TEST = LabelPair("test", "Test")
    MAINTENANCE = LabelPair("maintenance", "Maintenance")
    INSPECTION = LabelPair("inspection", "Inspection")
    REPAIR_LIFECYCLE = LabelPair("repair_lifecycle", "Repair")
    FAILURE_REGISTRY = LabelPair("failure_registry", "FR")
    TAQC_INSPECTION = LabelPair("taqc_inspection", "TA&QC")


class NotificationRoutingCategoryLabels(RequestCategoryLabels):
    """Notification routing-rule dropdown — overrides repair_lifecycle to
    'Repair Cycle', and adds 'nameplate' which isn't a RequestCategory value
    but appears as a CategoryDetails.category_type in this context."""

    REPAIR_LIFECYCLE = LabelPair("repair_lifecycle", "Repair Cycle")
    NAMEPLATE = LabelPair("nameplate", "Nameplate")


class RequestCategoryFullLabels(RequestCategoryLabels):
    """Full (non-abbreviated) names for failure_registry/taqc_inspection — used
    for KPI tiles, notification context payloads, and report titles where the
    short chip labels ("FR"/"TA&QC") would read as too terse. Not normalized
    against the short labels — both forms are legitimately used in different
    places, so this is kept as its own explicit override rather than merged."""

    FAILURE_REGISTRY = LabelPair("failure_registry", "Failure Registry")
    TAQC_INSPECTION = LabelPair("taqc_inspection", "TA&QC Inspection")


class RequestCategoryColors(LabelPairRegistry):
    """Canonical hex color per category_type, for UI chips/legends/timelines.
    Sourced from testing_requests_screen.dart's palette (the primary list
    view) — other frontend files previously disagreed with each other and
    with this (e.g. taqc_inspection was orange in one screen, light blue in
    another); this is now the single source those screens read from."""

    TEST = LabelPair("test", "#3FA9F5")
    MAINTENANCE = LabelPair("maintenance", "#EA580C")
    INSPECTION = LabelPair("inspection", "#0F766E")
    REPAIR_LIFECYCLE = LabelPair("repair_lifecycle", "#2563EB")
    FAILURE_REGISTRY = LabelPair("failure_registry", "#EF5350")
    TAQC_INSPECTION = LabelPair("taqc_inspection", "#40C4FF")


# ── Test-evaluation status labels and colors ──────────────────────────────────

class TestEvaluationStatusLabels(LabelPairRegistry):
    """Human-readable label per test-evaluation overall status — the
    NORMAL/ALERT/CRITICAL vocabulary services/evaluation_service.py's
    evaluate() computes onto TestResult.evaluation_result['overall']."""
    NORMAL   = LabelPair("NORMAL",   "Normal")
    ALERT    = LabelPair("ALERT",    "Alert")
    CRITICAL = LabelPair("CRITICAL", "Critical")


class TestEvaluationStatusColors(LabelPairRegistry):
    """Canonical hex color per test-evaluation overall status. Sourced from
    analytics_dashboard_page.dart's _StatusBadge palette — other frontend
    files (e.g. base_role_dashboard.dart's flagged-equipment badge) had
    independently invented a different CRITICAL/ALERT pair with no NORMAL
    color at all; this is now the single source those should read from."""
    NORMAL   = LabelPair("NORMAL",   "#16A34A")
    ALERT    = LabelPair("ALERT",    "#D97706")
    CRITICAL = LabelPair("CRITICAL", "#DC2626")


# ── Billing status labels, colors, and icons ──────────────────────────────────

class BillingStatusLabels(LabelPairRegistry):
    """Human-readable label per billing subscription status."""
    ACTIVE          = LabelPair("active",          "Active")
    EXPIRED         = LabelPair("expired",         "Expired")
    PENDING_PAYMENT = LabelPair("pending_payment", "Pending Payment")
    TRIAL           = LabelPair("trial",           "Trial")
    TRIAL_EXPIRED   = LabelPair("trial_expired",   "Trial Expired")


class BillingStatusColors(LabelPairRegistry):
    """Canonical hex color per billing status — served via API so Flutter
    never hardcodes color logic."""
    ACTIVE          = LabelPair("active",          "#16A34A")   # green-600
    EXPIRED         = LabelPair("expired",         "#DC2626")   # red-600
    PENDING_PAYMENT = LabelPair("pending_payment", "#94A3B8")   # slate-400
    TRIAL           = LabelPair("trial",           "#D97706")   # amber-600
    TRIAL_EXPIRED   = LabelPair("trial_expired",   "#DC2626")   # red-600


class BillingStatusIcons(LabelPairRegistry):
    """Material icon name per billing status for Flutter Icon() widget."""
    ACTIVE          = LabelPair("active",          "check_circle_outline")
    EXPIRED         = LabelPair("expired",         "cancel_outlined")
    PENDING_PAYMENT = LabelPair("pending_payment", "schedule")
    TRIAL           = LabelPair("trial",           "hourglass_top")
    TRIAL_EXPIRED   = LabelPair("trial_expired",   "hourglass_disabled")


class BillingOrderStatusLabels(LabelPairRegistry):
    """Human-readable label per billing order status."""
    PENDING   = LabelPair("pending",   "Pending")
    PAID      = LabelPair("paid",      "Paid")
    FAILED    = LabelPair("failed",    "Failed")
    CANCELLED = LabelPair("cancelled", "Cancelled")


class BillingOrderStatusColors(LabelPairRegistry):
    """Canonical hex color per billing order status."""
    PENDING   = LabelPair("pending",   "#D97706")   # amber-600
    PAID      = LabelPair("paid",      "#16A34A")   # green-600
    FAILED    = LabelPair("failed",    "#DC2626")   # red-600
    CANCELLED = LabelPair("cancelled", "#94A3B8")   # slate-400


# ── TR workflow outcome colors ────────────────────────────────────────────────

class TrWfOutcomeColors(LabelPairRegistry):
    """Canonical hex color per terminal/non-terminal TR workflow OUTCOME —
    rejected, cancelled, or returned (sent back a stage without closing).
    Sourced from wf_timeline_sheet.dart's flowchart palette (the original
    place these three were ever colored) and tr_kanban_board.dart's matching
    Rejected/Cancelled columns — this is now the single source those, and
    every other view (e.g. the Overview Dashboard's Rejected/Cancelled
    card), should read the color from, rather than each deciding it
    independently in Flutter."""
    REJECTED  = LabelPair("rejected",  "#EF5350")
    CANCELLED = LabelPair("cancelled", "#FB8C00")
    RETURNED  = LabelPair("returned",  "#7C3AED")
