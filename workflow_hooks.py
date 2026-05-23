"""
workflow_hooks.py
─────────────────
Lightweight hook registry for workflow lifecycle events.

Usage
-----
Register a handler (typically in a *_hooks.py module):

    from workflow_hooks import register

    def _on_completed(db, workflow, user_id):
        ...

    register("CALIBRATION", "completed", _on_completed)

Fire hooks from RepairWorkflowService (or any workflow engine):

    from workflow_hooks import fire
    fire(workflow.workflow_code or "", "completed", db, workflow, user_id)

Supported events
----------------
  completed       — workflow reached a terminal stage (no next_stage_id)
  stage_approved  — any non-terminal stage approved (receives current stage_code too)
  stage_rejected  — a stage was rejected

Handlers receive (db, workflow, user_id) and must be idempotent — they may be
called more than once if the workflow engine retries.  Exceptions are caught and
logged; they never block the workflow transition.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# { workflow_code: { event: [handler, ...] } }
_registry: dict[str, dict[str, list[Callable]]] = {}


def register(workflow_code: str, event: str, fn: Callable) -> None:
    """Register a handler for (workflow_code, event)."""
    _registry.setdefault(workflow_code, {}).setdefault(event, []).append(fn)


def fire(
    workflow_code: str,
    event: str,
    db,
    workflow,
    user_id,
    **kwargs,
) -> None:
    """
    Fire all handlers registered for (workflow_code, event).
    Extra kwargs are forwarded to each handler (e.g. stage_code for stage events).
    Never raises — exceptions are caught and logged.
    """
    handlers = _registry.get(workflow_code, {}).get(event, [])
    for fn in handlers:
        try:
            fn(db, workflow, user_id, **kwargs)
        except Exception as exc:
            logger.warning(
                "[WorkflowHook] %s.%s handler %s failed: %s",
                workflow_code, event, fn.__name__, exc,
                exc_info=True,
            )
