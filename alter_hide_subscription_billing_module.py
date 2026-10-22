"""
ALTER: hide all billing UI by switching the "Subscription & Billing" module
off (is_active = false).

This one flag drives every billing screen:
  - sidebar menu entry   - GET /modules/user only returns active modules
  - Role Permission grid - lists active modules only, so it can't be granted
  - Organisation page "Billing" tab, trial/billing banners and the
    /subscription-billing page - GET /public-config returns
    billing_enabled = this module's is_active (routers/public_config.py),
    read by the app at startup (AppConfig.billingEnabled)

Users see the change on their next app load (refresh / log in again). Existing role permission rows are kept untouched, so setting
is_active back to true (--show) restores everything exactly as it was.

seed.py's module list also has is_active False for it, so a re-seed keeps it
hidden.

Safe to run multiple times.

Usage:
    python alter_hide_subscription_billing_module.py           # hide
    python alter_hide_subscription_billing_module.py --show    # show again
"""

from __future__ import annotations

import sys

from database import SessionLocal
from models import Module

MODULE_NAME = "Subscription & Billing"


def main() -> None:
    show = "--show" in sys.argv
    db = SessionLocal()
    try:
        mod = db.query(Module).filter(Module.name == MODULE_NAME).first()
        if not mod:
            print(f'[SKIP] module "{MODULE_NAME}" not found')
            return
        if mod.is_active == show:
            print(f'[OK] "{MODULE_NAME}" already {"visible" if show else "hidden"} (id={mod.id})')
            return
        mod.is_active = show
        db.commit()
        print(f'[OK] "{MODULE_NAME}" is now {"visible" if show else "hidden"} (id={mod.id})')
    finally:
        db.close()


if __name__ == "__main__":
    main()
