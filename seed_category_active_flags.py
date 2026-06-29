"""
Seed script — sync CategoryDetails.is_active from OrgTestTemplate state.

Logic:
  1. For every OrgTestTemplate row that has template_data->>'is_active' = 'false',
     find all CategoryDetails names that map to that template_key via
     TEST_TYPE_TO_TEMPLATE, and set CategoryDetails.is_active = False.
  2. All other CategoryDetails rows (active templates, or ones with no template)
     are left untouched (they default to True from seed_category_details).
  3. Special hard-coded overrides (e.g. "Nameplate") that should always be
     inactive are applied at the end.

Called from seed.py::run_seed() after seed_category_details().
"""

from __future__ import annotations

import logging
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# CategoryDetails names that have no OrgTestTemplate but should be inactive.
ALWAYS_INACTIVE: list[str] = [
    "Nameplate",
]


def sync_category_details_active_flags(session: Session) -> None:
    """
    Sync CategoryDetails.is_active based on OrgTestTemplate.template_data['is_active'].
    Safe to call multiple times (idempotent).
    """
    from models import OrgTestTemplate, CategoryDetails
    from test_templates import TEST_TYPE_TO_TEMPLATE

    # Build reverse map: template_key → list of CategoryDetails names
    key_to_names: dict[str, list[str]] = {}
    for name, key in TEST_TYPE_TO_TEMPLATE.items():
        key_to_names.setdefault(key, []).append(name)

    # Find all templates explicitly marked inactive in their template_data
    all_templates = session.query(OrgTestTemplate).all()

    disabled_names: set[str] = set()
    for tpl in all_templates:
        data = tpl.template_data or {}
        # is_active may be stored as bool or string "false"
        raw = data.get("is_active", True)
        if raw is False or str(raw).lower() == "false":
            names = key_to_names.get(tpl.template_key, [])
            disabled_names.update(names)

    # Add hard-coded always-inactive names
    disabled_names.update(ALWAYS_INACTIVE)

    if not disabled_names:
        log.info("[seed_active_flags] No disabled templates found — nothing to update.")
        return

    # Set CategoryDetails.is_active = False for all matching names
    updated = (
        session.query(CategoryDetails)
        .filter(CategoryDetails.name.in_(disabled_names))
        .update({CategoryDetails.is_active: False}, synchronize_session=False)
    )

    # Ensure everything else is active (re-enable any that were previously disabled
    # but now have an active template)
    enabled_names_from_map = set(TEST_TYPE_TO_TEMPLATE.keys()) - disabled_names
    if enabled_names_from_map:
        session.query(CategoryDetails).filter(
            CategoryDetails.name.in_(enabled_names_from_map)
        ).update({CategoryDetails.is_active: True}, synchronize_session=False)

    session.commit()
    log.info(
        f"[seed_active_flags] Set is_active=False for {updated} CategoryDetails rows: "
        f"{sorted(disabled_names)}"
    )
    print(f"[OK] sync_category_details_active_flags: {updated} rows set inactive.")
