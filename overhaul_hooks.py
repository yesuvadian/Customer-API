"""
overhaul_hooks.py
─────────────────
Registers lifecycle hooks for the OVERHAUL repair workflow.

Imported once at app startup (main.py) — the import is the registration.

Hooks
-----
  completed  — OVERHAUL workflow completed (terminal):
               • close the associated OverhaulRecommendation
               • reset cumulative counter to zero (optional, per business rules)
"""

from __future__ import annotations

import logging
from uuid import UUID

from workflow_hooks import register

logger = logging.getLogger(__name__)

OVERHAUL_WORKFLOW_CODE = "OVERHAUL"


# ─────────────────────────────────────────────────────────────────────────────
# Hook: workflow completed
# ─────────────────────────────────────────────────────────────────────────────

def _on_overhaul_completed(db, workflow, user_id, **_kwargs) -> None:
    """
    Called when the OVERHAUL workflow reaches its terminal state.
    1. Close the associated OverhaulRecommendation (set status to CLOSED)
    2. This allows a new overhaul workflow to be triggered if threshold is crossed again
    """
    from models import OverhaulRecommendation
    from datetime import datetime, timezone

    if not workflow.equipment_id:
        return

    # Find the open recommendation for this equipment and workflow
    rec = (
        db.query(OverhaulRecommendation)
        .filter(
            OverhaulRecommendation.workflow_id == workflow.id,
            OverhaulRecommendation.status == "OPEN",
        )
        .first()
    )

    if rec:
        rec.status = "CLOSED"
        rec.closed_at = datetime.now(timezone.utc)
        db.flush()
        logger.info(
            "[OverhaulHook] OverhaulRecommendation %s closed after workflow %s completed",
            rec.id, workflow.id,
        )
    else:
        logger.warning(
            "[OverhaulHook] No open OverhaulRecommendation found for workflow %s",
            workflow.id,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registration — runs on import
# ─────────────────────────────────────────────────────────────────────────────

register(OVERHAUL_WORKFLOW_CODE, "completed", _on_overhaul_completed)

logger.info("[OverhaulHook] registered OVERHAUL.completed hook")
