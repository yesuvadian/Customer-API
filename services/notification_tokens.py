"""
Notification Recipient Tokens
==============================
Reserved system keywords that can appear inside ``recipient_roles`` /
``recipient_roles_override`` on NotificationTemplate and
NotificationRoutingRule rows.

Format in DB  :  "@token_name"
                 The leading ``@`` distinguishes them from OrgRole UUIDs
                 and role-name strings so no collision is possible.

How they work
-------------
When ``fire()`` resolves recipients it calls
``_resolve_recipients_by_roles()``.  That function now splits the list
into two groups:

  • Strings starting with ``@``  → resolved via this registry from the
                                    source record (TestingRequest, Equipment…)
  • Everything else              → resolved via the existing OrgRole lookup

The resolved User is then injected into the normal per-channel delivery
pipeline — no special-casing in the dispatcher is needed.

Adding a new token
------------------
1.  Add an entry to ``SYSTEM_RECIPIENT_TOKENS`` mapping
    ``"@your_token"`` to the field name on the source record that holds
    a User UUID.
2.  If the field lives on a source_type not yet handled, add a branch in
    ``_resolve_token_user()`` inside ``notification_service.py``.
3.  Re-run the app — no DB migration required.

UI visibility
-------------
``GET /notifications/org-roles`` prepends these tokens at the top of its
response (``is_system_token: true``) so the Flutter Notification Center
shows them as special amber chips above the regular org-role chips.
"""

from typing import Optional

# ── Token → source-record field mapping ───────────────────────────────────────
#
# Key   : the literal string stored in the DB (starts with "@")
# Value : attribute name on the source record that holds a User UUID
#
SYSTEM_RECIPIENT_TOKENS: dict[str, str] = {
    "@assignee":   "assigned_tester_id",  # TestingRequest.assigned_tester_id
    "@owner":      "created_by",           # Any record with a created_by field
    "@requester":  "requested_by",         # Records with a requested_by field
    "@originator": "originator_id",        # TestingRequest.originator_id (submitter)
}

# ── Human-readable labels (shown in the admin UI chip selector) ───────────────
SYSTEM_RECIPIENT_TOKEN_LABELS: dict[str, str] = {
    "@assignee":   "@ Assignee",
    "@owner":      "@ Owner / Creator",
    "@requester":  "@ Requester",
    "@originator": "@ Originator (Submitter)",
}


def is_system_token(value: str) -> bool:
    """Return True if *value* is a recognised system recipient token."""
    return isinstance(value, str) and value in SYSTEM_RECIPIENT_TOKENS


def all_token_entries() -> list[dict]:
    """
    Return a list of dicts in the same shape as ``_get_org_roles()`` output so
    the Flutter UI can render them without special-casing.

    Each entry carries ``is_system_token: True`` so the UI can style them
    differently (amber chips vs the default cyan org-role chips).
    """
    return [
        {
            "id":               token,
            "name":             label,
            "value":            token,
            "label":            label,
            "is_org_admin":     False,
            "is_dept_admin":    False,
            "role_template_id": None,
            "is_system_token":  True,
        }
        for token, label in SYSTEM_RECIPIENT_TOKEN_LABELS.items()
    ]
